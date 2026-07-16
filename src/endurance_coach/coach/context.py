"""Read-only context assembly for coach graph nodes."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from endurance_coach.analytics.engine import DefaultMetricEngine
from endurance_coach.analytics.math import compute_hrv_deviation_pct
from endurance_coach.analytics.repositories import AnalyticsDataRepository
from endurance_coach.domain.enums import MetricFamily
from endurance_coach.domain.models import MetricSnapshot


class DefaultCoachContextFetcher:
    def __init__(
        self,
        data_repo: AnalyticsDataRepository,
        metric_engine: DefaultMetricEngine,
    ) -> None:
        self._data_repo = data_repo
        self._metric_engine = metric_engine

    async def fetch_metric_snapshots(
        self,
        user_id: UUID,
        as_of: date,
    ) -> tuple[MetricSnapshot, ...]:
        snapshots: list[MetricSnapshot] = []
        for family in (
            MetricFamily.LOAD,
            MetricFamily.RECOVERY,
            MetricFamily.RISK,
            MetricFamily.EXECUTION,
        ):
            snapshot = await self._metric_engine.get_latest_snapshot(user_id, family)
            if snapshot is not None:
                snapshots.append(snapshot)
        return tuple(snapshots)

    async def fetch_activity_summary(
        self,
        user_id: UUID,
        *,
        window_days: int = 7,
    ) -> dict[str, object]:
        week_end = datetime.now(UTC).date()
        week_start = week_end - timedelta(days=window_days - 1)
        activities = await self._data_repo.get_activities_since(user_id, week_start)
        total_duration = sum(activity.duration_seconds for activity in activities)

        sleep_by_date = await self._data_repo.get_sleep_by_date(
            user_id,
            week_end,
            window_days=window_days,
        )
        avg_sleep_hours = None
        if sleep_by_date:
            avg_sleep_hours = sum(sleep_by_date.values()) / len(sleep_by_date) / 3600

        hrv_records = await self._data_repo.get_hrv_in_window(
            user_id,
            week_end,
            window_days=window_days,
        )
        hrv_trend_pct = None
        if hrv_records:
            latest = hrv_records[-1]
            hrv_trend_pct = compute_hrv_deviation_pct(latest.hrv_ms, latest.baseline_ms)

        return {
            "week_start": week_start.isoformat(),
            "week_end": week_end.isoformat(),
            "activity_count": len(activities),
            "total_duration_seconds": total_duration,
            "avg_sleep_hours": avg_sleep_hours,
            "hrv_trend_pct": hrv_trend_pct,
        }
