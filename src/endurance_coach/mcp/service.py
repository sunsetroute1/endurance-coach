"""MCP tool implementations — read normalized data and computed metrics only."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any
from uuid import UUID

from zoneinfo import ZoneInfo

from endurance_coach.analytics.engine import DefaultMetricEngine
from endurance_coach.analytics.math import compute_hrv_deviation_pct
from endurance_coach.analytics.repositories import AnalyticsDataRepository
from endurance_coach.analytics.trail_efforts import (
    VALID_RANK_BY,
    is_trail_activity,
    rank_trail_efforts,
)
from endurance_coach.analytics.math import CTL_TIME_CONSTANT
from endurance_coach.analytics.weekly import (
    build_weekly_aggregate_row,
    group_by_week,
    iter_week_starts,
    resolve_week_window,
    week_end,
)
from endurance_coach.coach.service import DefaultCoachService
from endurance_coach.db.models import ActivityRecord
from endurance_coach.domain.enums import MetricFamily
from endurance_coach.garmin.activity_detail import DetailedActivityService
from endurance_coach.garmin.daily_readiness import (
    DailyGarminReadinessService,
    MorningReadinessIncompleteError,
)
from endurance_coach.garmin.daily_recap import DailyRecapService
from endurance_coach.timezone_util import today_local
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
        app_timezone: str = "America/Denver",
        lap_fetcher: Any | None = None,
    ) -> None:
        self._data_repo = data_repo
        self._metric_engine = metric_engine
        self._coach_service = coach_service
        self._app_timezone = app_timezone
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
            return serialize(activity, payload=payload if include_metrics else None)

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
        record = await self._data_repo.get_sleep_for_date(user_id, as_of)
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

        activities = await self._data_repo.get_activities_between(user_id, range_start, range_end)
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
        )

        activity_groups = group_by_week(activities, lambda record: record.started_at.date())
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

        activities = await self._data_repo.get_activities_between(user_id, range_start, as_of)
        efforts = rank_trail_efforts(
            activities,
            rank_by=normalized_rank,  # type: ignore[arg-type]
            limit=top_n,
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
            "total_trail_activities": sum(1 for activity in activities if is_trail_activity(activity)),
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

    async def get_daily_garmin_readiness(
        self,
        user_id: UUID,
        target_date: date | None = None,
    ) -> dict[str, object]:
        service = DailyGarminReadinessService(self._data_repo)
        try:
            response = await service.get_daily_readiness(
                user_id,
                timezone=self._app_timezone,
                target_date=target_date,
                require_complete=True,
            )
            return response.model_dump()
        except MorningReadinessIncompleteError as exc:
            return exc.status.model_dump(mode="json")

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
