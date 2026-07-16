"""Tests for metric engine orchestration."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from endurance_coach.analytics.engine import DefaultMetricEngine
from endurance_coach.domain.enums import MetricFamily
from endurance_coach.domain.models import MetricSnapshot, MetricValue


class StubCalculator:
    def __init__(self, family: MetricFamily) -> None:
        self.family = family

    async def compute(self, user_id, as_of):
        return MetricSnapshot(
            user_id=user_id,
            family=self.family,
            as_of=as_of,
            metrics=(MetricValue(key="test", value=1.0, unit="x", computed_at=as_of),),
        )


class StubDataRepo:
    def __init__(self) -> None:
        self.saved: list[MetricSnapshot] = []

    async def save_snapshot(self, snapshot: MetricSnapshot):
        self.saved.append(snapshot)
        return snapshot

    async def get_latest_snapshot(self, user_id, family):
        for snapshot in reversed(self.saved):
            if snapshot.family == family:
                return snapshot
        return None


@pytest.mark.asyncio
async def test_metric_engine_compute_all() -> None:
    repo = StubDataRepo()
    engine = DefaultMetricEngine(repo)  # type: ignore[arg-type]
    engine._calculators = (
        StubCalculator(MetricFamily.LOAD),
        StubCalculator(MetricFamily.RECOVERY),
    )

    user_id = uuid4()
    snapshots = await engine.compute_all(user_id, datetime.now(UTC))

    assert len(snapshots) == 2
    assert len(repo.saved) == 2


@pytest.mark.asyncio
async def test_metric_engine_get_latest() -> None:
    repo = StubDataRepo()
    engine = DefaultMetricEngine(repo)  # type: ignore[arg-type]
    user_id = uuid4()
    now = datetime.now(UTC)

    snapshot = MetricSnapshot(
        user_id=user_id,
        family=MetricFamily.LOAD,
        as_of=now,
        metrics=(MetricValue(key="ctl", value=65.0, unit="load", computed_at=now),),
    )
    await repo.save_snapshot(snapshot)

    latest = await engine.get_latest_snapshot(user_id, MetricFamily.LOAD)
    assert latest is not None
    assert latest.metrics[0].key == "ctl"
