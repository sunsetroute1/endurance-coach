"""Tests for Garmin normalizers."""

import pytest
from tests.fixtures.garmin_payloads import (
    activity_payload,
    body_battery_payload,
    hrv_payload,
    readiness_payload,
    sleep_payload,
    steps_payload,
    stress_payload,
)

from endurance_coach.processor.providers.garmin.normalizers import (
    GarminActivityNormalizer,
    GarminBodyBatteryNormalizer,
    GarminHRVNormalizer,
    GarminReadinessNormalizer,
    GarminSleepNormalizer,
    GarminStepsNormalizer,
    GarminStressNormalizer,
)


@pytest.mark.asyncio
async def test_normalize_activity() -> None:
    normalizer = GarminActivityNormalizer()
    result = await normalizer.normalize(activity_payload())

    assert result.name == "Treadmill Running"
    assert result.activity_type == "treadmill_running"
    assert result.duration_seconds == 3000
    assert result.distance_meters == 8170.6
    assert result.avg_heart_rate == 123
    assert result.training_load == 32.0


@pytest.mark.asyncio
async def test_extract_running_dynamics() -> None:
    normalizer = GarminActivityNormalizer()
    payload = activity_payload()
    dynamics = normalizer.extract_running_dynamics(payload, activity_id=__import__("uuid").uuid4())

    assert dynamics is not None
    assert dynamics.avg_cadence == 153.0
    assert dynamics.avg_vertical_oscillation_mm == 8.2


@pytest.mark.asyncio
async def test_normalize_sleep() -> None:
    result = await GarminSleepNormalizer().normalize(sleep_payload())
    assert result.total_sleep_seconds == 28800
    assert result.sleep_score == 82


@pytest.mark.asyncio
async def test_normalize_hrv() -> None:
    result = await GarminHRVNormalizer().normalize(hrv_payload())
    assert result.hrv_ms == 48.0
    assert result.resting_heart_rate == 52


@pytest.mark.asyncio
async def test_normalize_readiness() -> None:
    result = await GarminReadinessNormalizer().normalize(readiness_payload())
    assert result.readiness_score == 78
    assert result.hrv_component == 80


@pytest.mark.asyncio
async def test_normalize_body_battery() -> None:
    result = await GarminBodyBatteryNormalizer().normalize(body_battery_payload())
    assert result.level == 58


@pytest.mark.asyncio
async def test_normalize_body_battery_nested_day_summary() -> None:
    from datetime import UTC, datetime
    from uuid import uuid4

    from endurance_coach.domain.enums import DataProviderType, ResourceType
    from endurance_coach.domain.models import RawPayload

    payload = RawPayload(
        id=uuid4(),
        user_id=uuid4(),
        provider=DataProviderType.GARMIN,
        resource_type=ResourceType.BODY_BATTERY,
        provider_record_id="2026-06-17",
        content_hash="battery-nested",
        fetched_at=datetime.now(UTC),
        payload={
            "date": "2026-06-17",
            "data": [
                {
                    "date": "2026-06-17",
                    "charged": 93,
                    "drained": 77,
                    "bodyBatteryValuesArray": [[1781676720000, 12], [1781758800000, 24]],
                }
            ],
        },
    )
    result = await GarminBodyBatteryNormalizer().normalize(payload)
    assert result.level == 24
    assert result.charged == 93
    assert result.drained == 77


@pytest.mark.asyncio
async def test_normalize_stress() -> None:
    result = await GarminStressNormalizer().normalize(stress_payload())
    assert result.avg_stress == 28
    assert result.max_stress == 65


@pytest.mark.asyncio
async def test_normalize_steps() -> None:
    result = await GarminStepsNormalizer().normalize(steps_payload())
    assert result.total_steps == 4207
    assert result.step_goal == 20000
    assert result.distance_meters == 3218.5
