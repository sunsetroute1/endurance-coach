"""Tests for Strava activity normalizer."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from endurance_coach.domain.enums import DataProviderType, ResourceType
from endurance_coach.domain.models import RawPayload
from endurance_coach.processor.providers.strava.normalizers import StravaActivityNormalizer
from tests.fixtures.strava_payloads import STRAVA_ACTIVITY_PAYLOAD


@pytest.mark.asyncio
async def test_strava_activity_normalizer() -> None:
    payload = RawPayload(
        id=uuid4(),
        user_id=uuid4(),
        provider=DataProviderType.STRAVA,
        resource_type=ResourceType.ACTIVITIES,
        provider_record_id="123456789",
        payload=STRAVA_ACTIVITY_PAYLOAD,
        content_hash="hash",
        fetched_at=datetime.now(UTC),
    )

    activity = await StravaActivityNormalizer().normalize(payload)

    assert activity.name == "Morning Run"
    assert activity.activity_type == "Run"
    assert activity.duration_seconds == 3600
    assert activity.distance_meters == 10000.0
    assert activity.avg_heart_rate == 145
    assert activity.training_load == 82.0
