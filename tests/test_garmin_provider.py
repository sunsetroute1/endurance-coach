"""Tests for Garmin data provider sync logic."""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import uuid4

import pytest

from endurance_coach.collector.providers.garmin.provider import GarminDataProvider
from endurance_coach.collector.providers.garmin.token_store import GarminTokenStore
from endurance_coach.domain.enums import DataProviderType, ResourceType, SyncStatus
from endurance_coach.domain.models import RawPayload, SyncRequest


class StubTokenStore(GarminTokenStore):
    def __init__(self, authenticated: bool = True) -> None:
        super().__init__(__import__("pathlib").Path("/tmp/garmin"))
        self._authenticated = authenticated

    def token_file_exists(self) -> bool:
        return self._authenticated

    async def is_authenticated(self, user_id: Any, provider: DataProviderType) -> bool:
        return self._authenticated and provider == DataProviderType.GARMIN

    async def validate_tokens(self) -> tuple[bool, str]:
        return self._authenticated, "" if self._authenticated else "missing"


class StubRawPayloadRepo:
    def __init__(self) -> None:
        self.saved: list[RawPayload] = []

    async def save(self, payload: RawPayload) -> RawPayload:
        self.saved.append(payload)
        return payload

    async def get_by_hash(self, user_id: Any, content_hash: str) -> RawPayload | None:
        for item in self.saved:
            if item.user_id == user_id and item.content_hash == content_hash:
                return item
        return None

    async def list_unprocessed(self, user_id: Any, resource_type: ResourceType, limit: int = 100):
        return []


class StubSyncJobRepo:
    def __init__(self) -> None:
        self.jobs: list[dict[str, Any]] = []

    async def create(self, request: SyncRequest):
        job = type("Job", (), {"id": uuid4()})()
        self.jobs.append({"id": job.id, "request": request})
        return job

    async def complete(self, job_id, *, status, resources_synced, error_message=None) -> None:
        self.jobs.append(
            {
                "id": job_id,
                "status": status,
                "resources_synced": resources_synced,
                "error_message": error_message,
            }
        )


class StubConnectionRepo:
    async def upsert_garmin_reference(self, user_id, token_path: str):
        return None


class StubGarminClient:
    async def get_activities(self, start: int = 0, limit: int = 50):
        if start > 0:
            return []
        return [{"activityId": 101, "startTimeLocal": "2026-07-14T08:00:00"}]

    async def get_activity(self, activity_id: str):
        return {"activityId": activity_id, "activityName": "Morning Run"}

    async def get_activity_laps(self, activity_id: str):
        return [{"lapIndex": 1, "duration": 600.0, "averageHR": 120}]

    async def get_sleep_data(self, day: date):
        return {"sleepTimeSeconds": 28800}

    async def get_hrv_data(self, day: date):
        return {"lastNightAvg": 45}

    async def get_training_readiness(self, day: date):
        return [{"score": 80}]

    async def get_body_battery(self, day: date):
        return [{"bodyBatteryValuesArray": [[0, 50]]}]

    async def get_stress_data(self, day: date):
        return {"avgStressLevel": 25}

    async def get_daily_stats(self, day: date):
        return {"totalSteps": 5000, "dailyStepGoal": 10000}

    def iter_dates(self, start: date, end: date) -> list[date]:
        return [end]


@pytest.mark.asyncio
async def test_garmin_provider_sync_persists_payloads(monkeypatch: pytest.MonkeyPatch) -> None:
    token_store = StubTokenStore(authenticated=True)
    raw_repo = StubRawPayloadRepo()
    provider = GarminDataProvider(
        token_store=token_store,
        raw_payload_repo=raw_repo,  # type: ignore[arg-type]
        sync_job_repo=StubSyncJobRepo(),  # type: ignore[arg-type]
        connection_repo=StubConnectionRepo(),  # type: ignore[arg-type]
        sync_days=7,
    )

    async def fake_from_token_path(token_path):
        return StubGarminClient()

    monkeypatch.setattr(
        "endurance_coach.collector.providers.garmin.provider.GarminClient.from_token_path",
        fake_from_token_path,
    )

    result = await provider.sync(
        SyncRequest(
            user_id=uuid4(),
            provider=DataProviderType.GARMIN,
            resource_types=(ResourceType.ACTIVITIES, ResourceType.SLEEP, ResourceType.STEPS),
        )
    )

    assert result.status == SyncStatus.COMPLETED
    assert result.resources_synced[ResourceType.ACTIVITIES] == 1
    assert result.resources_synced[ResourceType.SLEEP] == 1
    assert result.resources_synced[ResourceType.STEPS] == 1
    assert len(raw_repo.saved) == 3


@pytest.mark.asyncio
async def test_garmin_provider_fails_without_tokens() -> None:
    provider = GarminDataProvider(
        token_store=StubTokenStore(authenticated=False),
        raw_payload_repo=StubRawPayloadRepo(),  # type: ignore[arg-type]
        sync_job_repo=StubSyncJobRepo(),  # type: ignore[arg-type]
        connection_repo=StubConnectionRepo(),  # type: ignore[arg-type]
    )

    result = await provider.sync(
        SyncRequest(
            user_id=uuid4(),
            provider=DataProviderType.GARMIN,
            resource_types=(ResourceType.ACTIVITIES,),
        )
    )

    assert result.status == SyncStatus.FAILED
    assert result.errors
