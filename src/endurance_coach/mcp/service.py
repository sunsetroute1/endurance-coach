"""MCP tool implementations — read normalized data and computed metrics only."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any
from uuid import UUID

from endurance_coach.analytics.engine import DefaultMetricEngine
from endurance_coach.analytics.math import compute_hrv_deviation_pct
from endurance_coach.analytics.repositories import AnalyticsDataRepository
from endurance_coach.coach.service import DefaultCoachService
from endurance_coach.domain.enums import MetricFamily
from endurance_coach.garmin.activity_detail import DetailedActivityService
from endurance_coach.garmin.daily_readiness import (
    DailyGarminReadinessService,
    MorningReadinessIncompleteError,
)
from endurance_coach.timezone_util import today_local
from endurance_coach.mcp.serializers import (
    activity_to_dict,
    coach_response_to_dict,
    hrv_to_dict,
    injury_risk_factors_from_snapshot,
    injury_risk_level_from_snapshot,
    readiness_to_dict,
    sleep_to_dict,
    snapshot_metrics,
    snapshot_to_dict,
)


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
    ) -> dict[str, object]:
        since = today_local(self._app_timezone) - timedelta(days=max(days, 1))
        activities = await self._data_repo.get_activities_since(user_id, since)
        return {
            "days": days,
            "count": len(activities),
            "activities": [activity_to_dict(activity) for activity in activities],
        }

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
    ) -> dict[str, object]:
        as_of = today_local(self._app_timezone)
        records = await self._data_repo.get_hrv_in_window(user_id, as_of, window_days=days)
        latest = records[-1] if records else None
        deviation = None
        if latest is not None:
            deviation = compute_hrv_deviation_pct(latest.hrv_ms, latest.baseline_ms)

        return {
            "days": days,
            "latest": hrv_to_dict(latest) if latest else None,
            "hrv_deviation_pct": deviation,
            "readings": [hrv_to_dict(record) for record in records],
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

    async def get_detailed_activity(
        self,
        user_id: UUID,
        *,
        target_date: date | None = None,
        activity_id: str | None = None,
    ) -> dict[str, object]:
        service = DetailedActivityService(
            self._data_repo,
            timezone=self._app_timezone,
            lap_fetcher=self._lap_fetcher,
        )
        response = await service.get_detailed_activity(
            user_id,
            target_date=target_date,
            activity_id=activity_id,
        )
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
