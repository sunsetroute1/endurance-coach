"""Load metrics calculator — CTL, ATL, TSB, ACWR, monotony, weekly progression."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from uuid import UUID

from endurance_coach.analytics.math import (
    compute_acwr,
    compute_ctl_atl,
    compute_monotony_strain,
    compute_tsb,
    compute_weekly_load_progression,
)
from endurance_coach.analytics.repositories import AnalyticsDataRepository
from endurance_coach.domain.enums import MetricFamily
from endurance_coach.domain.models import LoadMetrics, MetricSnapshot, MetricValue


class LoadMetricsCalculator:
    family = MetricFamily.LOAD
    metric_keys = (
        "ctl",
        "atl",
        "tsb",
        "acwr",
        "weekly_load",
        "monotony",
        "strain",
        "weekly_load_progression",
    )

    def __init__(self, data_repo: AnalyticsDataRepository) -> None:
        self._data_repo = data_repo

    async def compute_load_metrics(self, user_id: UUID, as_of: date) -> LoadMetrics:
        daily_loads = await self._data_repo.get_daily_activity_loads(user_id, as_of)
        ctl, atl = compute_ctl_atl(daily_loads, as_of)
        tsb = compute_tsb(ctl, atl)
        acwr = compute_acwr(atl, ctl)
        monotony, strain = compute_monotony_strain(daily_loads, as_of)
        weekly_load = sum(
            daily_loads.get(as_of - timedelta(days=offset), 0.0) for offset in range(7)
        )
        return LoadMetrics(
            ctl=ctl,
            atl=atl,
            tsb=tsb,
            acwr=acwr,
            weekly_load=weekly_load,
            monotony=monotony,
            strain=strain,
        )

    async def compute(self, user_id: UUID, as_of: datetime) -> MetricSnapshot:
        as_of_date = as_of.date()
        loads = await self.compute_load_metrics(user_id, as_of_date)
        progression = compute_weekly_load_progression(
            await self._data_repo.get_daily_activity_loads(user_id, as_of_date),
            as_of_date,
        )

        metrics = (
            MetricValue(key="ctl", value=loads.ctl, unit="load", computed_at=as_of),
            MetricValue(key="atl", value=loads.atl, unit="load", computed_at=as_of),
            MetricValue(key="tsb", value=loads.tsb, unit="load", computed_at=as_of),
            MetricValue(key="acwr", value=loads.acwr, unit="ratio", computed_at=as_of),
            MetricValue(key="weekly_load", value=loads.weekly_load, unit="load", computed_at=as_of),
            MetricValue(key="monotony", value=loads.monotony, unit="ratio", computed_at=as_of),
            MetricValue(key="strain", value=loads.strain, unit="load", computed_at=as_of),
            MetricValue(
                key="weekly_load_progression",
                value=progression,
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
