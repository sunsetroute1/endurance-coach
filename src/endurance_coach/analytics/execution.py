"""Execution metrics — HR drift and aerobic decoupling from activity splits."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from endurance_coach.analytics.math import compute_aerobic_decoupling_pct, compute_hr_drift_pct
from endurance_coach.analytics.repositories import AnalyticsDataRepository
from endurance_coach.domain.enums import MetricFamily
from endurance_coach.domain.models import MetricSnapshot, MetricValue


def _half_split_hr(payload: dict[str, Any]) -> tuple[float | None, float | None]:
    detail = payload.get("detail", {})
    if not isinstance(detail, dict):
        return None, None

    splits = detail.get("splitSummaries") or detail.get("lapDTOs") or []
    if not isinstance(splits, list) or len(splits) < 2:
        return None, None

    midpoint = len(splits) // 2
    first_half = splits[:midpoint]
    second_half = splits[midpoint:]

    def avg_hr(parts: list[dict[str, Any]]) -> float | None:
        values = [
            float(part.get("averageHR") or part.get("avgHr") or 0)
            for part in parts
            if isinstance(part, dict)
        ]
        values = [v for v in values if v > 0]
        return sum(values) / len(values) if values else None

    return avg_hr(first_half), avg_hr(second_half)


class ExecutionMetricsCalculator:
    family = MetricFamily.EXECUTION
    metric_keys = ("hr_drift_pct", "aerobic_decoupling_pct")

    def __init__(self, data_repo: AnalyticsDataRepository) -> None:
        self._data_repo = data_repo

    async def compute(self, user_id: UUID, as_of: datetime) -> MetricSnapshot:
        activities = await self._data_repo.get_recent_activities(user_id, limit=5)
        drift_values: list[float] = []
        decoupling_values: list[float] = []

        for activity in activities:
            payload = await self._data_repo.get_activity_payload(activity.source_payload_id)
            if not payload:
                continue
            early_hr, late_hr = _half_split_hr(payload)
            if early_hr is None or late_hr is None:
                continue
            drift_values.append(compute_hr_drift_pct(early_hr, late_hr))
            decoupling_values.append(compute_aerobic_decoupling_pct(early_hr, late_hr))

        avg_drift = sum(drift_values) / len(drift_values) if drift_values else 0.0
        avg_decoupling = (
            sum(decoupling_values) / len(decoupling_values) if decoupling_values else 0.0
        )

        metrics = (
            MetricValue(key="hr_drift_pct", value=avg_drift, unit="percent", computed_at=as_of),
            MetricValue(
                key="aerobic_decoupling_pct",
                value=avg_decoupling,
                unit="percent",
                computed_at=as_of,
            ),
        )
        return MetricSnapshot(
            user_id=user_id,
            family=self.family,
            as_of=as_of,
            metrics=metrics,
        )
