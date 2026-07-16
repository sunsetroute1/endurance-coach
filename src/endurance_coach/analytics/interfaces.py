"""Calculator interfaces for deterministic metric computation."""

from __future__ import annotations

from datetime import date, datetime
from typing import Protocol
from uuid import UUID

from endurance_coach.domain.enums import MetricFamily
from endurance_coach.domain.models import (
    InjuryRiskAssessment,
    LoadMetrics,
    MetricSnapshot,
    RecoveryMetrics,
)


class MetricCalculator(Protocol):
    """Single metric or metric-family calculator."""

    @property
    def family(self) -> MetricFamily: ...

    @property
    def metric_keys(self) -> tuple[str, ...]: ...

    async def compute(
        self,
        user_id: UUID,
        as_of: datetime,
    ) -> MetricSnapshot: ...


class LoadCalculator(Protocol):
    async def compute_ctl_atl_tsb(
        self,
        user_id: UUID,
        as_of: date,
    ) -> LoadMetrics: ...

    async def compute_acwr(
        self,
        user_id: UUID,
        as_of: date,
    ) -> float: ...

    async def compute_trimp(
        self,
        user_id: UUID,
        activity_date: date,
    ) -> float: ...

    async def compute_monotony(
        self,
        user_id: UUID,
        as_of: date,
        window_days: int = 7,
    ) -> float: ...

    async def compute_weekly_load_progression(
        self,
        user_id: UUID,
        as_of: date,
    ) -> float: ...


class ExecutionCalculator(Protocol):
    async def compute_hr_drift(
        self,
        user_id: UUID,
        activity_id: UUID,
    ) -> float: ...

    async def compute_pace_hr_decoupling(
        self,
        user_id: UUID,
        activity_id: UUID,
    ) -> float: ...


class RecoveryCalculator(Protocol):
    async def compute_sleep_debt(
        self,
        user_id: UUID,
        as_of: date,
        window_days: int = 14,
    ) -> float: ...

    async def compute_recovery_score(
        self,
        user_id: UUID,
        as_of: date,
    ) -> RecoveryMetrics: ...

    async def compute_fatigue_score(
        self,
        user_id: UUID,
        as_of: date,
    ) -> float: ...


class RiskCalculator(Protocol):
    async def compute_injury_risk(
        self,
        user_id: UUID,
        as_of: date,
    ) -> InjuryRiskAssessment: ...


class MetricEngine(Protocol):
    """Orchestrates all calculators and persists snapshots."""

    async def compute_all(
        self,
        user_id: UUID,
        as_of: datetime | None = None,
    ) -> list[MetricSnapshot]: ...

    async def get_latest_snapshot(
        self,
        user_id: UUID,
        family: MetricFamily,
    ) -> MetricSnapshot | None: ...
