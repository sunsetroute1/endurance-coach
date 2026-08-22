"""Tests for Samsung Health normalizers."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from endurance_coach.domain.enums import DataProviderType, ResourceType
from endurance_coach.domain.models import RawPayload
from endurance_coach.processor.providers.samsung.normalizers import (
    SamsungActivityNormalizer,
    SamsungSleepNormalizer,
    SamsungStepsNormalizer,
)


def _payload(resource_type: ResourceType, provider_record_id: str, body: dict) -> RawPayload:
    return RawPayload(
        id=uuid4(),
        user_id=uuid4(),
        provider=DataProviderType.SAMSUNG_HEALTH,
        resource_type=resource_type,
        provider_record_id=provider_record_id,
        payload=body,
        content_hash="test-hash",
        fetched_at=datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_samsung_sleep_normalizer() -> None:
    normalizer = SamsungSleepNormalizer()
    payload = _payload(
        ResourceType.SLEEP,
        "2026-07-16",
        {
            "sleep_date": "2026-07-16",
            "total_sleep_seconds": 27900,
            "deep_sleep_seconds": 5400,
            "sleep_score": 84,
        },
    )
    sleep = await normalizer.normalize(payload)
    assert sleep.total_sleep_seconds == 27900
    assert sleep.sleep_score == 84


@pytest.mark.asyncio
async def test_samsung_steps_normalizer() -> None:
    normalizer = SamsungStepsNormalizer()
    payload = _payload(
        ResourceType.STEPS,
        "2026-07-16",
        {"date": "2026-07-16", "total_steps": 9124, "distance_meters": 7012.5},
    )
    steps = await normalizer.normalize(payload)
    assert steps.total_steps == 9124
    assert steps.distance_meters == 7012.5


@pytest.mark.asyncio
async def test_samsung_activity_normalizer() -> None:
    normalizer = SamsungActivityNormalizer()
    payload = _payload(
        ResourceType.ACTIVITIES,
        "exercise-101",
        {
            "name": "Trail Run",
            "activity_type": "running",
            "start_time": "2026-07-14T07:30:00-06:00",
            "duration_seconds": 3720,
            "distance_meters": 10250,
            "avg_heart_rate": 142,
        },
    )
    activity = await normalizer.normalize(payload)
    assert activity.name == "Trail Run"
    assert activity.duration_seconds == 3720
    assert activity.avg_heart_rate == 142
