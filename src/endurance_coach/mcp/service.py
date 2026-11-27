"""MCP tool implementations — read normalized data and computed metrics only."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from endurance_coach.analytics.engine import DefaultMetricEngine
from endurance_coach.analytics.math import CTL_TIME_CONSTANT, compute_hrv_deviation_pct
from endurance_coach.analytics.repositories import AnalyticsDataRepository
from endurance_coach.analytics.trail_efforts import (
    VALID_RANK_BY,
    is_trail_activity,
    rank_trail_efforts,
)
from endurance_coach.analytics.weekly import (
    build_weekly_aggregate_row,
    group_by_week,
    iter_week_starts,
    resolve_week_window,
    week_end,
)
from endurance_coach.coach.service import DefaultCoachService
from endurance_coach.collector.providers.garmin.activity_detail_sync import (
    SqlActivityDetailStore,
    sample_to_dict,
)
from endurance_coach.db.models import ActivityRecord
from endurance_coach.domain.enums import MetricFamily, ResourceType
from endurance_coach.garmin.activity_detail import DetailedActivityService
from endurance_coach.garmin.activity_efficiency import (
    analyze_activity_samples,
    compare_activity_analyses,
)
from endurance_coach.garmin.activity_series import decimate_samples
from endurance_coach.garmin.daily_readiness import DailyGarminReadinessService
from endurance_coach.garmin.training_plan import project_training_plan
from endurance_coach.garmin.daily_recap import DailyRecapService
from endurance_coach.garmin.data_quality import build_data_quality
from endurance_coach.garmin.longitudinal import build_longitudinal_report
from endurance_coach.garmin.performance_metrics import (
    RESOURCE_TYPES,
    project_performance_records,
)
from endurance_coach.garmin.performance_trends import (
    TREND_WINDOWS,
    build_performance_trends,
    metric_points,
)
from endurance_coach.garmin.sleep_selection import sleep_record_for_local_date
from endurance_coach.mcp.serializers import (
    activity_to_dict,
    activity_to_summary_dict,
    coach_response_to_dict,
    hrv_to_dict,
    injury_risk_factors_from_snapshot,
    injury_risk_level_from_snapshot,
    readiness_to_dict,
    sleep_to_dict,
    snapshot_metrics,
    snapshot_to_dict,
)
from endurance_coach.timezone_util import format_local, server_timezone_name, today_local

MAX_ACTIVITY_LIMIT_FULL = 100
MAX_ACTIVITY_LIMIT_SUMMARY = 500


def _clamp_activity_page(*, start: int, limit: int, summary_only: bool) -> tuple[int, int]:
    offset = max(start, 0)
    cap = MAX_ACTIVITY_LIMIT_SUMMARY if summary_only else MAX_ACTIVITY_LIMIT_FULL
    page_size = max(min(limit, cap), 1)
    return offset, page_size


class CoachMCPService:
    """Coaching-oriented MCP tools backed by normalized records and metric snapshots."""

    def __init__(
        self,
        data_repo: AnalyticsDataRepository,
        metric_engine: DefaultMetricEngine,
        coach_service: DefaultCoachService,
        *,
        app_timezone: str | None = None,
        lap_fetcher: Any | None = None,
    ) -> None:
        self._data_repo = data_repo
        self._metric_engine = metric_engine
        self._coach_service = coach_service
        self._app_timezone = app_timezone or server_timezone_name()
        self._lap_fetcher = lap_fetcher

    async def get_recent_activities(
        self,
        user_id: UUID,
        days: int = 7,
        *,
        start: int = 0,
        limit: int = 50,
        activitytype: str | None = None,
        summary_only: bool = True,
        include_metrics: bool = True,
    ) -> dict[str, object]:
        since = today_local(self._app_timezone) - timedelta(days=max(days, 1))
        today = today_local(self._app_timezone)
        offset, page_size = _clamp_activity_page(
            start=start,
            limit=limit,
            summary_only=summary_only,
        )
        max_limit = MAX_ACTIVITY_LIMIT_SUMMARY if summary_only else MAX_ACTIVITY_LIMIT_FULL
        activities, total = await self._data_repo.list_activities(
            user_id,
            since=since,
            activity_type=activitytype,
            start=offset,
            limit=page_size,
            max_limit=max_limit,
            timezone=self._app_timezone,
        )
        returned = len(activities)

        app_tz = ZoneInfo(self._app_timezone)
        today_candidates, _ = await self._data_repo.list_activities(
            user_id,
            since=today - timedelta(days=1),
            activity_type=activitytype,
            start=0,
            limit=50,
            max_limit=50,
            timezone=self._app_timezone,
        )
        activities_today = [
            activity
            for activity in today_candidates
            if activity.started_at.astimezone(app_tz).date() == today
        ]

        all_for_metrics = {activity.id: activity for activity in activities + activities_today}
        payloads_by_id = await self._load_activity_payloads(
            list(all_for_metrics.values()),
            include_metrics=include_metrics,
        )

        serialize = activity_to_summary_dict if summary_only else activity_to_dict

        def serialize_activity(activity: ActivityRecord) -> dict[str, object]:
            payload = payloads_by_id.get(activity.source_payload_id)
            return serialize(
                activity,
                payload=payload if include_metrics else None,
                timezone=self._app_timezone,
            )

        return {
            "mode": "summary" if summary_only else "full",
            "timezone": self._app_timezone,
            "as_of_date": today.isoformat(),
            "days": days,
            "start": offset,
            "limit": page_size,
            "activitytype": activitytype,
            "summary_only": summary_only,
            "include_metrics": include_metrics,
            "total": total,
            "count": returned,
            "has_more": offset + returned < total,
            "activities_today_count": len(activities_today),
            "activities_today": [serialize_activity(activity) for activity in activities_today],
            "activities": [serialize_activity(activity) for activity in activities],
        }

    async def _load_activity_payloads(
        self,
        activities: list[Any],
        *,
        include_metrics: bool,
    ) -> dict[Any, dict]:
        if not include_metrics or not activities:
            return {}
        payload_ids = list({activity.source_payload_id for activity in activities})
        return await self._data_repo.get_raw_payloads_by_ids(payload_ids)

    async def get_sleep_summary(
        self,
        user_id: UUID,
        target_date: date | None = None,
    ) -> dict[str, object]:
        as_of = target_date or today_local(self._app_timezone)
        record = await sleep_record_for_local_date(self._data_repo, user_id, as_of)
        sleep_by_date = await self._data_repo.get_sleep_by_date(user_id, as_of, window_days=7)
        recovery = await self._metric_engine.get_latest_snapshot(user_id, MetricFamily.RECOVERY)
        sleep_debt = snapshot_metrics(recovery).get("sleep_debt_hours", {}).get("value")

        return {
            "date": as_of.isoformat(),
            "sleep": sleep_to_dict(record) if record else None,
            "recent_nights": [
                {"date": day.isoformat(), "total_sleep_seconds": seconds}
                for day, seconds in sorted(sleep_by_date.items())
            ],
            "sleep_debt_hours": sleep_debt,
        }

    async def get_hrv_trend(
        self,
        user_id: UUID,
        days: int = 14,
        *,
        rollup: str = "daily",
    ) -> dict[str, object]:
        as_of = today_local(self._app_timezone)
        records = await self._data_repo.get_hrv_in_window(user_id, as_of, window_days=days)
        latest = records[-1] if records else None
        deviation = None
        if latest is not None:
            deviation = compute_hrv_deviation_pct(latest.hrv_ms, latest.baseline_ms)

        if rollup == "weekly":
            grouped = group_by_week(records, lambda record: record.recorded_at.date())
            week_starts = iter_week_starts(as_of, weeks=max((days + 6) // 7, 1))
            readings = [
                {
                    "week_start": week_start.isoformat(),
                    "week_end": week_end(week_start).isoformat(),
                    "readings": len(grouped.get(week_start, [])),
                    "avg_ms": round(
                        sum(record.hrv_ms for record in grouped.get(week_start, []))
                        / len(grouped[week_start]),
                        1,
                    )
                    if grouped.get(week_start)
                    else None,
                }
                for week_start in week_starts
            ]
        else:
            readings = [hrv_to_dict(record) for record in records]

        return {
            "days": days,
            "rollup": rollup,
            "latest": hrv_to_dict(latest) if latest else None,
            "hrv_deviation_pct": deviation,
            "readings": readings,
        }

    async def get_weekly_aggregates(
        self,
        user_id: UUID,
        weeks: int = 12,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> dict[str, object]:
        as_of = end_date or today_local(self._app_timezone)
        if start_date is not None and start_date > as_of:
            start_date, as_of = as_of, start_date

        week_starts, range_start, range_end, week_count = resolve_week_window(
            end_date=as_of,
            weeks=weeks,
            start_date=start_date,
        )

        activities = await self._data_repo.get_activities_between(
            user_id,
            range_start,
            range_end,
            timezone=self._app_timezone,
        )
        hrv = await self._data_repo.get_hrv_between(user_id, range_start, range_end)
        sleep = await self._data_repo.get_sleep_records_in_window(user_id, range_start, range_end)
        steps = await self._data_repo.get_steps_in_window(user_id, range_start, range_end)
        stress = await self._data_repo.get_stress_in_window(user_id, range_start, range_end)
        body_battery = await self._data_repo.get_body_battery_in_window(
            user_id,
            range_start,
            range_end,
        )
        readiness = await self._data_repo.get_readiness_in_window(user_id, range_start, range_end)
        load_history_days = (range_end - range_start).days + CTL_TIME_CONSTANT + 1
        daily_loads = await self._data_repo.get_daily_activity_loads(
            user_id,
            range_end,
            history_days=load_history_days,
            timezone=self._app_timezone,
        )

        activity_groups = group_by_week(
            activities,
            lambda record: self._local_day(record.started_at),
        )
        hrv_groups = group_by_week(hrv, lambda record: record.recorded_at.date())
        sleep_groups = group_by_week(sleep, lambda record: record.sleep_date)
        steps_groups = group_by_week(steps, lambda record: record.step_date)
        stress_groups = group_by_week(stress, lambda record: record.recorded_at.date())
        battery_groups = group_by_week(body_battery, lambda record: record.recorded_at.date())
        readiness_groups = group_by_week(readiness, lambda record: record.recorded_at.date())

        aggregates = [
            build_weekly_aggregate_row(
                week_start,
                activities=activity_groups.get(week_start, []),
                hrv=hrv_groups.get(week_start, []),
                sleep=sleep_groups.get(week_start, []),
                steps=steps_groups.get(week_start, []),
                stress=stress_groups.get(week_start, []),
                body_battery=battery_groups.get(week_start, []),
                readiness=readiness_groups.get(week_start, []),
                daily_loads=daily_loads,
            )
            for week_start in week_starts
        ]

        return {
            "rollup": "mon_sun",
            "weeks": week_count,
            "range_start": range_start.isoformat(),
            "range_end": range_end.isoformat(),
            "aggregates": aggregates,
        }

    async def get_top_trail_efforts(
        self,
        user_id: UUID,
        *,
        days: int = 90,
        start_date: date | None = None,
        end_date: date | None = None,
        limit: int = 10,
        rank_by: str = "vert_duration",
    ) -> dict[str, object]:
        as_of = end_date or today_local(self._app_timezone)
        range_start = start_date or (as_of - timedelta(days=max(days, 1)))
        if range_start > as_of:
            range_start, as_of = as_of, range_start

        normalized_rank = rank_by if rank_by in VALID_RANK_BY else "vert_duration"
        top_n = max(min(limit, 50), 1)

        activities = await self._data_repo.get_activities_between(
            user_id,
            range_start,
            as_of,
            timezone=self._app_timezone,
        )
        efforts = rank_trail_efforts(
            activities,
            rank_by=normalized_rank,  # type: ignore[arg-type]
            limit=top_n,
            timezone=self._app_timezone,
        )

        return {
            "rank_by": normalized_rank,
            "ranking_notes": {
                "vert_duration": "elevation_m / duration_h (m/h)",
                "training_load": "Garmin activity training load (higher = harder)",
                "pace_terrain": "vert_m_per_km * (600 / pace_sec_per_km); rewards steep + fast",
            },
            "start_date": range_start.isoformat(),
            "end_date": as_of.isoformat(),
            "limit": top_n,
            "total_trail_activities": sum(
                1 for activity in activities if is_trail_activity(activity)
            ),
            "count": len(efforts),
            "efforts": efforts,
        }

    async def get_training_readiness(
        self,
        user_id: UUID,
        target_date: date | None = None,
    ) -> dict[str, object]:
        as_of = target_date or today_local(self._app_timezone)
        readiness = await self._data_repo.get_latest_readiness(user_id, as_of)
        return {
            "date": as_of.isoformat(),
            "readiness": readiness_to_dict(readiness) if readiness else None,
        }

    async def get_running_training_plan(self, user_id: UUID) -> dict[str, object]:
        rows = await self._data_repo.list_latest_raw_payloads_by_type(
            user_id,
            ResourceType.TRAINING_PLAN.value,
        )
        plans: list[dict[str, object]] = []
        seen: set[object] = set()
        for row in rows:
            projected = project_training_plan(row.payload)
            plan_id = projected.get("training_plan_id")
            if plan_id in seen:
                continue
            seen.add(plan_id)
            plans.append(projected)
        return {"plans": plans}

    async def get_recovery_state(self, user_id: UUID) -> dict[str, object]:
        recovery = await self._metric_engine.get_latest_snapshot(user_id, MetricFamily.RECOVERY)
        recovery_metrics = snapshot_metrics(recovery)
        return {
            "snapshot": snapshot_to_dict(recovery),
            "recovery_score": recovery_metrics.get("recovery_score", {}).get("value"),
            "fatigue_score": recovery_metrics.get("fatigue_score", {}).get("value"),
            "sleep_debt_hours": recovery_metrics.get("sleep_debt_hours", {}).get("value"),
            "hrv_deviation_pct": recovery_metrics.get("hrv_deviation_pct", {}).get("value"),
        }

    async def get_weekly_load(self, user_id: UUID) -> dict[str, object]:
        load = await self._metric_engine.get_latest_snapshot(user_id, MetricFamily.LOAD)
        metrics = snapshot_metrics(load)
        return {
            "snapshot": snapshot_to_dict(load),
            "ctl": metrics.get("ctl", {}).get("value"),
            "atl": metrics.get("atl", {}).get("value"),
            "tsb": metrics.get("tsb", {}).get("value"),
            "acwr": metrics.get("acwr", {}).get("value"),
            "weekly_load": metrics.get("weekly_load", {}).get("value"),
            "weekly_load_progression": metrics.get("weekly_load_progression", {}).get("value"),
            "monotony": metrics.get("monotony", {}).get("value"),
            "strain": metrics.get("strain", {}).get("value"),
        }

    async def get_injury_risk(self, user_id: UUID) -> dict[str, object]:
        risk = await self._metric_engine.get_latest_snapshot(user_id, MetricFamily.RISK)
        metrics = snapshot_metrics(risk)
        return {
            "snapshot": snapshot_to_dict(risk),
            "level": injury_risk_level_from_snapshot(risk),
            "score": metrics.get("injury_risk_score", {}).get("value"),
            "factors": list(injury_risk_factors_from_snapshot(risk)),
        }

    async def get_garmin_performance(
        self,
        user_id: UUID,
        *,
        days: int = 28,
    ) -> dict[str, object]:
        end = today_local(self._app_timezone)
        start = end - timedelta(days=days - 1)
        rows = await self._data_repo.list_recent_garmin_raw(user_id, RESOURCE_TYPES)
        return project_performance_records(rows, start=start, end=end)

    async def get_garmin_performance_trends(
        self,
        user_id: UUID,
        *,
        window_days: int = 28,
    ) -> dict[str, object]:
        if window_days not in TREND_WINDOWS:
            raise ValueError(f"window_days must be one of {TREND_WINDOWS}")
        end = today_local(self._app_timezone)
        history_start = date(2015, 1, 1)
        wide_start = history_start - timedelta(days=1)
        wide_end = end + timedelta(days=1)
        rows = await self._data_repo.list_recent_garmin_raw(
            user_id,
            RESOURCE_TYPES,
            limit=20000,
        )
        projected = project_performance_records(rows, start=history_start, end=end)
        metrics = projected["metrics"]
        activity_rows = await self._data_repo.list_activity_trend_points(
            user_id,
            history_start,
            end,
            timezone=self._app_timezone,
            provider="garmin",
        )
        activities = [
            self._activity_trend_row(row)
            for row in activity_rows
            if isinstance(row.get("started_at"), datetime)
        ]
        hrv_rows = await self._data_repo.get_hrv_between(user_id, wide_start, wide_end)
        hrv_points: list[tuple[date, float]] = []
        resting_from_hrv: list[tuple[date, float]] = []
        for row in hrv_rows:
            if row.provider != "garmin":
                continue
            day = self._local_day(row.recorded_at)
            if not history_start <= day <= end:
                continue
            hrv_points.append((day, float(row.hrv_ms)))
            if row.resting_heart_rate is not None:
                resting_from_hrv.append((day, float(row.resting_heart_rate)))
        heart_rate_series = metric_points(metrics.get("heart_rate"), "restingHR")
        if heart_rate_series:
            resting = heart_rate_series
            resting_note = "Stored daily heart-rate history."
        else:
            resting = resting_from_hrv
            resting_note = (
                "Stored resting heart rate from HRV records. "
                "A separate daily heart-rate series is not in the database yet."
            )
        sleep_rows = await self._data_repo.get_sleep_records_in_window(
            user_id, history_start, end
        )
        sleep_points = [
            (row.sleep_date, float(row.total_sleep_seconds))
            for row in sleep_rows
            if row.provider == "garmin"
        ]
        battery_rows = await self._data_repo.get_body_battery_in_window(
            user_id, wide_start, wide_end
        )
        battery_points = [
            (day, float(row.level))
            for row in battery_rows
            if row.provider == "garmin"
            and history_start <= (day := self._local_day(row.recorded_at)) <= end
        ]
        report = build_performance_trends(
            end=end,
            window_days=window_days,
            performance_metrics=metrics,
            hrv=hrv_points,
            resting_hr=resting,
            sleep_seconds=sleep_points,
            body_battery=battery_points,
            activities=activities,
        )
        resting_trend = report["recovery"]["resting_heart_rate_bpm"]
        if isinstance(resting_trend, dict):
            resting_trend["note"] = resting_note
        mountain = report.get("mountain_running")
        if isinstance(mountain, dict):
            mountain["detail_streams"] = await self._detail_stream_summary(
                user_id,
                end=end,
                window_days=window_days,
            )
        return report

    async def get_garmin_data_quality(self, user_id: UUID) -> dict[str, object]:
        series = await self._data_repo.garmin_metric_days(user_id)
        kept = [
            item
            for item in series
            if item["metric"] != "activities" and (item["days"] or item["metric"] in {
                "hill_score",
                "running_economy",
                "stamina_curve",
                "power_curve",
                "vo2_max",
                "lactate_threshold",
            })
        ]
        activities = await self._data_repo.garmin_activity_completeness(user_id)
        hrv = await self._data_repo.garmin_hrv_integrity(user_id, self._app_timezone)
        last_sync = await self._data_repo.latest_garmin_sync(user_id)
        return build_data_quality(
            series=kept,
            activities=activities,
            hrv=hrv,
            last_sync=last_sync,
        )

    async def get_garmin_activity_details(
        self,
        user_id: UUID,
        provider_activity_id: str,
    ) -> dict[str, object]:
        store = SqlActivityDetailStore(self._data_repo.session)
        found = await store.collection_row(user_id, provider_activity_id)
        if found is None or found[0].status != "collected":
            status = found[0].status if found is not None else "not_collected"
            return {
                "provider_activity_id": provider_activity_id,
                "status": status,
                "samples": [],
                "note": (
                    "No collected chart is stored for this activity. "
                    "Missing samples are not invented."
                ),
            }
        collection, activity = found
        rows = await store.samples(activity.id)
        parsed = [sample_to_dict(row) for row in rows]
        reduced = decimate_samples(parsed)
        for sample in reduced["samples"]:
            recorded = sample.get("recorded_at")
            if isinstance(recorded, datetime):
                sample["recorded_at"] = format_local(recorded, self._app_timezone)
            elif isinstance(recorded, str):
                sample["recorded_at"] = format_local(
                    datetime.fromisoformat(recorded),
                    self._app_timezone,
                )
        return {
            "provider_activity_id": provider_activity_id,
            "status": "collected",
            "started_at": format_local(activity.started_at, self._app_timezone),
            "distance_meters": activity.distance_meters,
            "elevation_gain_meters": activity.elevation_gain_meters,
            "duration_seconds": activity.duration_seconds,
            "sample_count": collection.sample_count,
            "median_interval_seconds": collection.median_interval_seconds,
            "metric_keys": collection.metric_keys,
            "factors_applied": False,
            **reduced,
        }

    async def get_garmin_activity_efficiency(
        self,
        user_id: UUID,
        provider_activity_id: str,
    ) -> dict[str, object]:
        parsed, activity = await self._detail_samples(user_id, provider_activity_id)
        if activity is None:
            return {
                "provider_activity_id": provider_activity_id,
                "available": False,
                "note": "No collected chart is stored for this activity.",
            }
        return {
            "provider_activity_id": provider_activity_id,
            "available": True,
            "distance_meters": activity.distance_meters,
            "elevation_gain_meters": activity.elevation_gain_meters,
            "duration_seconds": activity.duration_seconds,
            "analysis": analyze_activity_samples(parsed),
        }

    async def get_garmin_activity_comparison(
        self,
        user_id: UUID,
        provider_activity_id: str,
    ) -> dict[str, object]:
        target_samples, target = await self._detail_samples(user_id, provider_activity_id)
        if target is None:
            return {
                "provider_activity_id": provider_activity_id,
                "available": False,
                "note": "No collected chart is stored for this activity.",
            }
        store = SqlActivityDetailStore(self._data_repo.session)
        others = []
        for activity in await store.collected_activities(user_id, limit=80):
            if activity.provider_record_id == provider_activity_id:
                continue
            rows = await store.samples(activity.id)
            others.append(_comparison_row(activity, [sample_to_dict(row) for row in rows]))
        return {
            "provider_activity_id": provider_activity_id,
            "available": True,
            **compare_activity_analyses(_comparison_row(target, target_samples), others),
        }

    async def get_garmin_activity_backfill_status(self, user_id: UUID) -> dict[str, object]:
        store = SqlActivityDetailStore(self._data_repo.session)
        return await store.backfill_status(user_id)

    async def get_garmin_activity_longitudinal(self, user_id: UUID) -> dict[str, object]:
        store = SqlActivityDetailStore(self._data_repo.session)
        rows = []
        for collection, activity in await store.list_collections(user_id):
            samples: list[dict[str, Any]] = []
            if collection.status == "collected":
                stored = await store.samples(activity.id)
                samples = [sample_to_dict(row) for row in stored]
            rows.append(
                {
                    "provider_activity_id": activity.provider_record_id,
                    "local_day": self._local_day(activity.started_at),
                    "status": collection.status,
                    "distance_meters": activity.distance_meters,
                    "elevation_gain_meters": activity.elevation_gain_meters,
                    "duration_seconds": activity.duration_seconds,
                    "median_interval_seconds": collection.median_interval_seconds,
                    "samples": samples,
                }
            )
        return build_longitudinal_report(rows)

    async def _detail_samples(
        self,
        user_id: UUID,
        provider_activity_id: str,
    ) -> tuple[list[dict[str, Any]], ActivityRecord | None]:
        store = SqlActivityDetailStore(self._data_repo.session)
        found = await store.collection_row(user_id, provider_activity_id)
        if found is None or found[0].status != "collected":
            return [], None
        rows = await store.samples(found[1].id)
        return [sample_to_dict(row) for row in rows], found[1]

    async def _detail_stream_summary(
        self,
        user_id: UUID,
        *,
        end: date,
        window_days: int,
    ) -> dict[str, object]:
        start = end - timedelta(days=window_days - 1)
        store = SqlActivityDetailStore(self._data_repo.session)
        in_window = []
        for activity in await store.collected_activities(user_id, limit=80):
            if start <= self._local_day(activity.started_at) <= end:
                in_window.append(activity)
        if not in_window:
            return {
                "available": False,
                "activities": 0,
                "note": (
                    "No collected activity-detail charts fall in this window. "
                    "Actual pace is not used as grade-adjusted pace."
                ),
            }
        summaries = []
        for activity in in_window:
            rows = await store.samples(activity.id)
            analysis = analyze_activity_samples([sample_to_dict(row) for row in rows])
            drift = analysis["cardiovascular_drift"]
            potential = analysis["stamina"]["potential"]
            summaries.append(
                {
                    "provider_activity_id": activity.provider_record_id,
                    "drift_available": drift.get("available"),
                    "drift_reason": drift.get("reason"),
                    "selection": drift.get("selection"),
                    "heart_rate_change_bpm": drift.get("heart_rate_change_bpm")
                    if drift.get("available")
                    else None,
                    "power_faded": analysis["power_fade"].get("faded"),
                    "grade_adjusted_speed_available": drift["grade_adjusted_speed"].get(
                        "available"
                    ),
                    "potential_stamina_depletion": potential.get("depletion")
                    if isinstance(potential, dict)
                    else None,
                }
            )
        return {
            "available": True,
            "activities": len(summaries),
            "activities_detail": summaries,
            "note": (
                "Stream metrics are calculated from stored charts. "
                "Actual pace is not grade-adjusted pace."
            ),
        }

    def _local_day(self, moment: datetime) -> date:
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=UTC)
        return moment.astimezone(ZoneInfo(self._app_timezone)).date()

    def _activity_trend_row(self, row: dict[str, object]) -> dict[str, object]:
        started = row["started_at"]
        assert isinstance(started, datetime)
        return {
            "day": self._local_day(started),
            "activity_type": row.get("activity_type"),
            "duration_seconds": row.get("duration_seconds"),
            "distance_meters": row.get("distance_meters"),
            "avg_heart_rate": row.get("avg_heart_rate"),
            "pace_sec_per_km": row.get("avg_pace_sec_per_km"),
            "elevation_meters": row.get("elevation_gain_meters"),
            "training_load": row.get("training_load"),
            "grade_adjusted_speed_mps": row.get("grade_adjusted_speed_mps"),
            "stamina_begin": row.get("stamina_begin"),
            "stamina_end": row.get("stamina_end"),
        }

    async def get_daily_garmin_readiness(
        self,
        user_id: UUID,
        target_date: date | None = None,
    ) -> dict[str, object]:
        service = DailyGarminReadinessService(self._data_repo)
        response = await service.get_daily_readiness(
            user_id,
            timezone=self._app_timezone,
            target_date=target_date,
            require_complete=False,
        )
        return response.model_dump(mode="json")

    async def get_daily_recap(
        self,
        user_id: UUID,
        target_date: date | None = None,
    ) -> dict[str, object]:
        service = DailyRecapService(self._data_repo, timezone=self._app_timezone)
        response = await service.get_daily_recap(user_id, target_date=target_date)
        return response.model_dump()

    async def get_detailed_activity(
        self,
        user_id: UUID,
        *,
        target_date: date | None = None,
        activity_id: str | None = None,
    ) -> dict[str, object]:
        from fastapi import HTTPException

        service = DetailedActivityService(
            self._data_repo,
            timezone=self._app_timezone,
            lap_fetcher=self._lap_fetcher,
        )
        try:
            response = await service.get_detailed_activity(
                user_id,
                target_date=target_date,
                activity_id=activity_id,
            )
        except HTTPException as exc:
            raise ValueError(
                f"{exc.detail}. Pass `id` or `provider_activity_id` from "
                "get_recent_activities, or omit activity_id for the most recent activity."
            ) from exc
        return response.model_dump()

    async def generate_daily_training_plan(self, user_id: UUID) -> dict[str, object]:
        response = await self._coach_service.generate_daily_training_plan(user_id)
        return coach_response_to_dict(response)

    async def explain_today(self, user_id: UUID) -> dict[str, object]:
        response = await self._coach_service.explain_today(user_id)
        return coach_response_to_dict(response)

    async def summarize_last_week(self, user_id: UUID) -> dict[str, object]:
        response = await self._coach_service.summarize_last_week(user_id)
        return coach_response_to_dict(response)


def _comparison_row(activity: ActivityRecord, samples: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "provider_activity_id": activity.provider_record_id,
        "distance_meters": activity.distance_meters,
        "elevation_gain_meters": activity.elevation_gain_meters,
        "duration_seconds": activity.duration_seconds,
        "analysis": analyze_activity_samples(samples),
    }
