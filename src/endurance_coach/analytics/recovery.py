"""Recovery metrics — sleep debt, recovery score, fatigue score."""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from endurance_coach.analytics.load import LoadMetricsCalculator
from endurance_coach.analytics.math import (
    compute_fatigue_score,
    compute_hrv_deviation_pct,
    compute_recovery_score,
    compute_sleep_debt_hours,
)
from endurance_coach.analytics.repositories import AnalyticsDataRepository
from endurance_coach.domain.enums import MetricFamily
from endurance_coach.domain.models import MetricSnapshot, MetricValue, RecoveryMetrics


class RecoveryMetricsCalculator:
    family = MetricFamily.RECOVERY
    metric_keys = ("recovery_score", "fatigue_score", "sleep_debt_hours", "hrv_deviation_pct")

    def __init__(
        self,
        data_repo: AnalyticsDataRepository,
        load_calculator: LoadMetricsCalculator,
    ) -> None:
        self._data_repo = data_repo
        self._load_calculator = load_calculator

    async def compute_recovery_metrics(self, user_id: UUID, as_of: date) -> RecoveryMetrics:
        sleep_by_date = await self._data_repo.get_sleep_by_date(user_id, as_of)
        sleep_debt_hours = compute_sleep_debt_hours(sleep_by_date, as_of)

        hrv = await self._data_repo.get_latest_hrv(user_id, as_of)
        hrv_deviation = 0.0
        if hrv is not None:
            hrv_deviation = compute_hrv_deviation_pct(hrv.hrv_ms, hrv.baseline_ms)

        readiness = await self._data_repo.get_latest_readiness(user_id, as_of)
        sleep_score = await self._data_repo.get_latest_sleep_score(user_id, as_of)

        recovery_score = compute_recovery_score(
            readiness_score=float(readiness.readiness_score) if readiness else None,
            sleep_score=float(sleep_score) if sleep_score is not None else None,
            hrv_deviation_pct=hrv_deviation,
        )

        load_metrics = await self._load_calculator.compute_load_metrics(user_id, as_of)
        fatigue_score = compute_fatigue_score(
            tsb=load_metrics.tsb,
            sleep_debt_hours=sleep_debt_hours,
            hrv_deviation_pct=hrv_deviation,
        )

        return RecoveryMetrics(
            recovery_score=recovery_score,
            fatigue_score=fatigue_score,
            sleep_debt_hours=sleep_debt_hours,
            hrv_deviation_pct=hrv_deviation,
        )

    async def compute(self, user_id: UUID, as_of: datetime) -> MetricSnapshot:
        metrics_data = await self.compute_recovery_metrics(user_id, as_of.date())
        metrics = (
            MetricValue(
                key="recovery_score",
                value=metrics_data.recovery_score,
                unit="score",
                computed_at=as_of,
            ),
            MetricValue(
                key="fatigue_score",
                value=metrics_data.fatigue_score,
                unit="score",
                computed_at=as_of,
            ),
            MetricValue(
                key="sleep_debt_hours",
                value=metrics_data.sleep_debt_hours,
                unit="hours",
                computed_at=as_of,
            ),
            MetricValue(
                key="hrv_deviation_pct",
                value=metrics_data.hrv_deviation_pct,
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
