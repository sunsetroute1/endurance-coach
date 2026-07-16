"""Tests for domain Pydantic models."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from endurance_coach.domain.enums import (
    DataProviderType,
    InjuryRiskLevel,
    MetricFamily,
    ResourceType,
)
from endurance_coach.domain.models import (
    CoachResponse,
    InjuryRiskAssessment,
    LoadMetrics,
    MetricSnapshot,
    MetricValue,
    NormalizedActivity,
    RawPayload,
)


def test_raw_payload_is_frozen() -> None:
    payload = RawPayload(
        user_id=uuid4(),
        provider=DataProviderType.GARMIN,
        resource_type=ResourceType.SLEEP,
        provider_record_id="sleep-1",
        payload={"score": 85},
        content_hash="hash",
        fetched_at=datetime.now(UTC),
    )
    with pytest.raises(ValidationError):
        payload.content_hash = "changed"  # type: ignore[misc]


def test_normalized_activity_fields() -> None:
    activity = NormalizedActivity(
        user_id=uuid4(),
        provider=DataProviderType.GARMIN,
        provider_record_id="act-1",
        name="Easy Run",
        activity_type="running",
        started_at=datetime.now(UTC),
        duration_seconds=3600,
        source_payload_id=uuid4(),
    )
    assert activity.distance_meters is None


def test_load_metrics() -> None:
    metrics = LoadMetrics(
        ctl=65.0,
        atl=72.0,
        tsb=-7.0,
        acwr=1.1,
        weekly_load=450.0,
        monotony=1.4,
        strain=630.0,
    )
    assert metrics.tsb == metrics.ctl - metrics.atl


def test_metric_snapshot() -> None:
    user_id = uuid4()
    snapshot = MetricSnapshot(
        user_id=user_id,
        family=MetricFamily.LOAD,
        as_of=datetime.now(UTC),
        metrics=(
            MetricValue(key="ctl", value=65.0, unit="tss", computed_at=datetime.now(UTC)),
        ),
    )
    assert snapshot.metrics[0].key == "ctl"


def test_injury_risk_assessment() -> None:
    assessment = InjuryRiskAssessment(
        level=InjuryRiskLevel.MODERATE,
        score=0.55,
        factors=("acwr_elevated", "monotony_high"),
    )
    assert len(assessment.factors) == 2


def test_coach_response_confidence_bounds() -> None:
    with pytest.raises(ValidationError):
        CoachResponse(
            explanation="test",
            recommendations=(),
            metrics_used=(),
            confidence=1.5,
        )
