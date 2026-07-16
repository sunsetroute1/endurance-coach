"""Metric engine — orchestrates calculators and persists snapshots."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from endurance_coach.analytics.execution import ExecutionMetricsCalculator
from endurance_coach.analytics.load import LoadMetricsCalculator
from endurance_coach.analytics.recovery import RecoveryMetricsCalculator
from endurance_coach.analytics.repositories import AnalyticsDataRepository
from endurance_coach.analytics.risk import InjuryRiskCalculator
from endurance_coach.domain.enums import MetricFamily
from endurance_coach.domain.models import MetricSnapshot


class DefaultMetricEngine:
    def __init__(self, data_repo: AnalyticsDataRepository) -> None:
        self._data_repo = data_repo
        self._load = LoadMetricsCalculator(data_repo)
        self._recovery = RecoveryMetricsCalculator(data_repo, self._load)
        self._risk = InjuryRiskCalculator(data_repo, self._load)
        self._execution = ExecutionMetricsCalculator(data_repo)
        self._calculators = (self._load, self._recovery, self._risk, self._execution)

    async def compute_all(
        self,
        user_id: UUID,
        as_of: datetime | None = None,
    ) -> list[MetricSnapshot]:
        target = as_of or datetime.now(UTC)
        snapshots: list[MetricSnapshot] = []
        for calculator in self._calculators:
            snapshot = await calculator.compute(user_id, target)
            await self._data_repo.save_snapshot(snapshot)
            snapshots.append(snapshot)
        return snapshots

    async def get_latest_snapshot(
        self,
        user_id: UUID,
        family: MetricFamily,
    ) -> MetricSnapshot | None:
        return await self._data_repo.get_latest_snapshot(user_id, family)
