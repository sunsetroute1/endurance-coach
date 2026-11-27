"""Injury risk assessment from load and recovery signals."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from endurance_coach.analytics.load import LoadMetricsCalculator
from endurance_coach.analytics.math import assess_injury_risk, compute_weekly_load_progression
from endurance_coach.analytics.repositories import AnalyticsDataRepository
from endurance_coach.domain.enums import InjuryRiskLevel, MetricFamily
from endurance_coach.domain.models import InjuryRiskAssessment, MetricSnapshot, MetricValue
from endurance_coach.timezone_util import calendar_date


class InjuryRiskCalculator:
    family = MetricFamily.RISK
    metric_keys = ("injury_risk_score", "injury_risk_level", "injury_risk_factors")

    def __init__(
        self,
        data_repo: AnalyticsDataRepository,
        load_calculator: LoadMetricsCalculator,
    ) -> None:
        self._data_repo = data_repo
        self._load_calculator = load_calculator

    async def compute_injury_risk(
        self,
        user_id: UUID,
        as_of: datetime,
    ) -> InjuryRiskAssessment:
        as_of_date = calendar_date(as_of)
        loads = await self._load_calculator.compute_load_metrics(user_id, as_of_date)
        daily_loads = await self._data_repo.get_daily_activity_loads(user_id, as_of_date)
        progression = compute_weekly_load_progression(daily_loads, as_of_date)

        score, factors = assess_injury_risk(
            acwr=loads.acwr,
            monotony=loads.monotony,
            weekly_load_progression=progression,
            tsb=loads.tsb,
        )

        if score >= 75:
            level = InjuryRiskLevel.CRITICAL
        elif score >= 50:
            level = InjuryRiskLevel.HIGH
        elif score >= 25:
            level = InjuryRiskLevel.MODERATE
        else:
            level = InjuryRiskLevel.LOW

        return InjuryRiskAssessment(level=level, score=score, factors=factors)

    async def compute(self, user_id: UUID, as_of: datetime) -> MetricSnapshot:
        assessment = await self.compute_injury_risk(user_id, as_of)
        metrics = (
            MetricValue(
                key="injury_risk_score",
                value=assessment.score,
                unit="score",
                computed_at=as_of,
            ),
            MetricValue(
                key="injury_risk_level",
                value=float(
                    ["low", "moderate", "high", "critical"].index(assessment.level.value)
                ),
                unit="level",
                computed_at=as_of,
            ),
            MetricValue(
                key="injury_risk_factors",
                value=float(len(assessment.factors)),
                unit=";".join(assessment.factors),
                computed_at=as_of,
            ),
        )
        return MetricSnapshot(
            user_id=user_id,
            family=self.family,
            as_of=as_of,
            metrics=metrics,
        )
