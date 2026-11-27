"""Tests for Garmin normalizers."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest
from tests.fixtures.garmin_payloads import (
    FETCHED_AT,
    USER_ID,
    activity_payload,
    body_battery_payload,
    hrv_payload,
    readiness_payload,
    sleep_payload,
    steps_payload,
    stress_payload,
)

from endurance_coach.domain.enums import DataProviderType, ResourceType
from endurance_coach.domain.models import RawPayload
from endurance_coach.processor.providers.garmin.normalizers import (
    GarminActivityNormalizer,
    GarminBodyBatteryNormalizer,
    GarminHRVNormalizer,
    GarminReadinessNormalizer,
    GarminSleepNormalizer,
    GarminStepsNormalizer,
    GarminStressNormalizer,
    UnmeasuredPayload,
)
from endurance_coach.timezone_util import server_timezone_name


@pytest.mark.asyncio
async def test_normalize_activity() -> None:
    normalizer = GarminActivityNormalizer()
    result = await normalizer.normalize(activity_payload())

    assert result.name == "Treadmill Running"
    assert result.activity_type == "treadmill_running"
    local = datetime(2026, 7, 15, 8, 20, 26, tzinfo=ZoneInfo(server_timezone_name()))
    assert result.started_at == local.astimezone(UTC)
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
    assert result.baseline_ms == 50.0


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


def _payload(resource: ResourceType, body: dict) -> RawPayload:
    return RawPayload(
        id=USER_ID,
        user_id=USER_ID,
        provider=DataProviderType.GARMIN,
        resource_type=resource,
        provider_record_id="2026-11-15",
        content_hash="hash",
        fetched_at=FETCHED_AT,
        payload=body,
    )


@pytest.mark.asyncio
async def test_hrv_baseline_is_the_middle_of_the_balanced_band() -> None:
    payload = _payload(
        ResourceType.HRV,
        {
            "date": "2026-11-15",
            "data": {
                "hrvSummary": {
                    "lastNightAvg": 100,
                    "status": "UNBALANCED",
                    "baseline": {"balancedLow": 30, "balancedUpper": 62},
                }
            },
        },
    )
    result = await GarminHRVNormalizer().normalize(payload)
    assert result.hrv_ms == 100
    assert result.baseline_ms == 46


@pytest.mark.asyncio
async def test_readiness_uses_latest_snapshot_and_garmin_factor_names() -> None:
    payload = _payload(
        ResourceType.TRAINING_READINESS,
        {
            "date": "2026-11-15",
            "data": [
                {
                    "score": 36,
                    "timestamp": "2026-11-15T21:47:22.0",
                    "hrvFactorPercent": 46,
                    "sleepScoreFactorPercent": 88,
                    "recoveryTimeFactorPercent": 84,
                },
                {
                    "score": 43,
                    "timestamp": "2026-11-15T16:07:27.0",
                    "hrvFactorPercent": 46,
                    "sleepScoreFactorPercent": 88,
                    "recoveryTimeFactorPercent": 99,
                },
            ],
        },
    )
    result = await GarminReadinessNormalizer().normalize(payload)
    assert result.readiness_score == 36
    assert result.hrv_component == 46
    assert result.sleep_component == 88
    assert result.recovery_component == 84


@pytest.mark.asyncio
async def test_empty_sleep_is_not_stored_as_zero() -> None:
    payload = _payload(
        ResourceType.SLEEP,
        {"date": "2026-11-16", "data": {"dailySleepDTO": {"sleepTimeSeconds": None}}},
    )
    with pytest.raises(UnmeasuredPayload):
        await GarminSleepNormalizer().normalize(payload)
