"""Tests for detailed activity assembly."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from endurance_coach.db.models import ActivityRecord
from endurance_coach.garmin.activity_detail import DetailedActivityService
from tests.fixtures.garmin_payloads import PAYLOAD_ID, USER_ID, activity_payload


class StubActivity(ActivityRecord):
    def __init__(self) -> None:
        self.id = uuid4()
        self.user_id = USER_ID
        self.provider = "garmin"
        self.provider_record_id = "101"
        self.source_payload_id = PAYLOAD_ID
        self.name = "Treadmill Running"
        self.activity_type = "treadmill_running"
        self.started_at = datetime(2026, 7, 15, 14, 20, 26, tzinfo=UTC)
        self.duration_seconds = 3000
        self.distance_meters = 8170.6
        self.avg_heart_rate = 123
        self.max_heart_rate = 150
        self.avg_pace_sec_per_km = 367.0
        self.elevation_gain_meters = 0.0
        self.training_load = 32.0


class StubDataRepo:
    def __init__(self) -> None:
        self.activity = StubActivity()

    async def get_most_recent_activity(self, user_id):
        return self.activity

    async def get_activity_by_id(self, user_id, activity_id):
        return self.activity if activity_id == self.activity.id else None

    async def get_activity_by_provider_record_id(self, user_id, provider_record_id):
        return self.activity if provider_record_id == "101" else None

    async def get_activity_for_date(self, user_id, target_date):
        if target_date.isoformat() == "2026-07-15":
            return self.activity
        return None

    async def get_activity_payload(self, payload_id):
        if payload_id == PAYLOAD_ID:
            return activity_payload().payload
        return None


@pytest.mark.asyncio
async def test_detailed_activity_service_builds_response() -> None:
    repo = StubDataRepo()
    service = DetailedActivityService(repo, timezone="America/Denver")
    response = await service.get_detailed_activity(USER_ID)

    assert response.activity_id == "101"
    assert response.provider_activity_id == "101"
    assert response.id == str(repo.activity.id)
    assert response.date == "2026-07-15"
    assert response.start_time == "08:20:26"
    assert response.activity_type == "Treadmill Running"
    assert response.is_treadmill is True
    assert response.is_trail is False
    assert response.distance_miles == 5.08
    assert response.duration_minutes == 50.0
    assert response.avg_hr == 123
    assert response.max_hr == 150
    assert response.exercise_load == 32
    assert response.calories == 612
    assert response.min_hr == 98
    assert response.moving_duration_s == 2950
    assert response.training_effect.aerobic == 1.2
    assert response.training_effect.primary_benefit == "Base (Low Aerobic)"
    assert response.running_dynamics.avg_cadence_spm == 153
    assert response.power.avg_watts == 245
    assert response.power.max_watts == 410
    assert response.heart_rate_zones.z2_time_min == 25
    assert len(response.pace_splits) == 2
    assert response.pace_splits[0].lap == 1
    assert response.pace_splits[0].time_sec == 600
    assert response.pace_splits[0].avg_power_w == 230


@pytest.mark.asyncio
async def test_detailed_activity_resolves_internal_uuid() -> None:
    repo = StubDataRepo()
    service = DetailedActivityService(repo, timezone="America/Denver")
    response = await service.get_detailed_activity(USER_ID, activity_id=str(repo.activity.id))
    assert response.activity_id == "101"
    assert response.id == str(repo.activity.id)
