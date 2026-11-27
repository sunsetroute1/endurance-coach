"""Tests for Garmin data provider sync logic."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest

from endurance_coach.collector.providers.garmin.provider import GarminDataProvider
from endurance_coach.collector.providers.garmin.token_store import GarminTokenStore
from endurance_coach.domain.enums import DataProviderType, ResourceType, SyncStatus
from endurance_coach.domain.models import RawPayload, SyncRequest
from endurance_coach.timezone_util import server_timezone_name, today_local


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
        today = today_local(server_timezone_name()).isoformat()
        return [{"activityId": 101, "startTimeLocal": f"{today}T08:00:00"}]

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
async def test_activity_sync_stops_paging_after_a_full_page_older_than_the_window() -> None:
    class PagingClient:
        def __init__(self) -> None:
            self.pages: list[int] = []
            self.details: list[str] = []

        async def get_activities(self, start: int = 0, limit: int = 50) -> list[dict[str, Any]]:
            self.pages.append(start)
            if start == 0:
                today = today_local(server_timezone_name())
                recent = f"{today.isoformat()}T08:00:00"
                older = f"{(today - timedelta(days=30)).isoformat()}T08:00:00"
                return [
                    {"activityId": 2, "startTimeLocal": recent},
                    *({"activityId": 100 + index, "startTimeLocal": older} for index in range(limit - 1)),
                ]
            return [
                {
                    "activityId": 999,
                    "startTimeLocal": (
                        f"{(today_local(server_timezone_name()) - timedelta(days=40)).isoformat()}T08:00:00"
                    ),
                }
            ]

        async def get_activity(self, activity_id: str) -> dict[str, Any]:
            self.details.append(activity_id)
            return {"activityId": activity_id}

        async def get_activity_laps(self, activity_id: str) -> list[dict[str, Any]]:
            return []

    client = PagingClient()
    raw_repo = StubRawPayloadRepo()
    provider = GarminDataProvider(
        token_store=StubTokenStore(authenticated=True),
        raw_payload_repo=raw_repo,  # type: ignore[arg-type]
        sync_job_repo=StubSyncJobRepo(),  # type: ignore[arg-type]
        connection_repo=StubConnectionRepo(),  # type: ignore[arg-type]
    )
    saved = await provider._sync_activities(
        client,  # type: ignore[arg-type]
        SyncRequest(
            user_id=uuid4(),
            provider=DataProviderType.GARMIN,
            resource_types=(ResourceType.ACTIVITIES,),
        ),
        uuid4(),
        date(2026, 11, 8),
    )

    assert client.pages == [0]
    assert client.details == ["2"]
    assert saved == 1
    assert len(raw_repo.saved) == 1


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


class MetricGarminClient:
    def __init__(self) -> None:
        self.heart_rate_spans: list[tuple[date, date]] = []
        self.power_sports: list[str] = []

    def iter_dates(self, start: date, end: date) -> list[date]:
        return [end]

    async def get_endurance_score(self, start: date, end: date):
        return {
            "groupMap": {end.isoformat(): {"groupAverage": 40, "groupMax": 44}},
            "enduranceScoreDTO": {"calendarDate": end.isoformat(), "overallScore": 44},
        }

    async def get_hill_score(self, start: date, end: date):
        raise RuntimeError("API Error 404 - hill score is not available")

    async def get_stamina_curve(self, day: date):
        return {}

    async def get_heart_rate_stats(self, start: date, end: date):
        self.heart_rate_spans.append((start, end))
        return [{"calendarDate": end.isoformat(), "values": {"restingHR": 47}}]

    async def get_power_curve(self, start: date, end: date, sport: str):
        self.power_sports.append(sport)
        if sport == "rowing":
            raise RuntimeError("API Error 400 - Invalid activity type: rowing")
        return {
            "startDate": start.isoformat(),
            "endDate": end.isoformat(),
            "entries": [{"watts": 200}],
        }

    async def get_spo2_acclimation(self, day: date):
        return {"calendarDate": day.isoformat(), "latestSpO2": 96}

    async def get_devices(self):
        return [{"deviceId": 15, "applicationKey": "enduro3"}]

    async def get_primary_training_device(self):
        return {"PrimaryTrainingDevice": {"deviceId": 15}}

    async def get_device_last_used(self):
        raise RuntimeError("API Error 404 - no last used device")

    async def get_device_solar_gain(self, device_id: str, start: date, end: date):
        return {
            "solarGainDailyDetailDTOList": [
                {"localConnectDate": end.isoformat(), "totalActivityTimeGainedMs": 500}
            ]
        }


@pytest.mark.asyncio
async def test_metric_sync_stores_raw_records_and_skips_missing_features(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = MetricGarminClient()
    raw_repo = StubRawPayloadRepo()
    provider = GarminDataProvider(
        token_store=StubTokenStore(authenticated=True),
        raw_payload_repo=raw_repo,  # type: ignore[arg-type]
        sync_job_repo=StubSyncJobRepo(),  # type: ignore[arg-type]
        connection_repo=StubConnectionRepo(),  # type: ignore[arg-type]
        sync_days=40,
    )

    async def fake_from_token_path(token_path):
        return client

    monkeypatch.setattr(
        "endurance_coach.collector.providers.garmin.provider.GarminClient.from_token_path",
        fake_from_token_path,
    )

    result = await provider.sync(
        SyncRequest(
            user_id=uuid4(),
            provider=DataProviderType.GARMIN,
            since=datetime.now(UTC) - timedelta(days=40),
            resource_types=(
                ResourceType.ENDURANCE_SCORE,
                ResourceType.HILL_SCORE,
                ResourceType.STAMINA_CURVE,
                ResourceType.HEART_RATE,
                ResourceType.POWER_CURVE,
                ResourceType.SPO2_ACCLIMATION,
                ResourceType.DEVICES,
                ResourceType.SOLAR_GAIN,
            ),
        )
    )

    assert result.status == SyncStatus.COMPLETED
    assert result.errors == ()
    assert result.resources_synced[ResourceType.ENDURANCE_SCORE] >= 1
    assert result.resources_synced[ResourceType.HILL_SCORE] == 0
    assert result.resources_synced[ResourceType.STAMINA_CURVE] == 0
    assert result.resources_synced[ResourceType.POWER_CURVE] == 1
    assert result.resources_synced[ResourceType.DEVICES] == 1
    assert result.resources_synced[ResourceType.SOLAR_GAIN] >= 1
    assert client.power_sports == ["cycling", "rowing"]
    assert len(client.heart_rate_spans) >= 2
    assert all(
        (span_end - span_start).days <= 27 for span_start, span_end in client.heart_rate_spans
    )
    stored_types = {item.resource_type for item in raw_repo.saved}
    assert ResourceType.HILL_SCORE not in stored_types
    endurance = next(
        item for item in raw_repo.saved if item.resource_type == ResourceType.ENDURANCE_SCORE
    )
    assert endurance.payload["enduranceScoreDTO"]["overallScore"] == 44
    inventory = next(item for item in raw_repo.saved if item.resource_type == ResourceType.DEVICES)
    assert inventory.provider_record_id == "inventory"
    assert "lastUsed" not in inventory.payload


class _BackfillRepo:
    def __init__(self) -> None:
        self.saved: list[RawPayload] = []

    async def record_ids(self, user_id: Any, provider: str, resource_type: str) -> set[str]:
        return {"2026-09-13"} if resource_type == "hrv" else set()

    async def get_by_hash(self, user_id: Any, content_hash: str) -> None:
        return None

    async def save(self, payload: RawPayload) -> RawPayload:
        self.saved.append(payload)
        return payload


class _BackfillClient:
    def __init__(self) -> None:
        self.activity_calls = 0

    async def get_activities(self, start: int = 0, limit: int = 50) -> list[dict[str, Any]]:
        self.activity_calls += 1
        return []

    async def get_hrv_data_range(self, start: date, end: date) -> dict[str, Any]:
        return {
            "hrvSummaries": [
                {"calendarDate": "2026-09-12", "lastNightAvg": 50},
                {"calendarDate": "2026-09-13", "lastNightAvg": 51},
            ]
        }

    async def get_endurance_score(self, start: date, end: date) -> dict[str, Any]:
        return {"groupMap": {"2026-09-12": {"groupAverage": 40, "groupMax": 44}}}


@pytest.mark.asyncio
async def test_metric_backfill_skips_stored_days_and_activity_files(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _BackfillClient()
    raw_repo = _BackfillRepo()
    provider = GarminDataProvider(
        token_store=StubTokenStore(authenticated=True),
        raw_payload_repo=raw_repo,  # type: ignore[arg-type]
        sync_job_repo=StubSyncJobRepo(),  # type: ignore[arg-type]
        connection_repo=StubConnectionRepo(),  # type: ignore[arg-type]
    )

    async def fake_from_token_path(token_path: Any) -> _BackfillClient:
        return client

    monkeypatch.setattr(
        "endurance_coach.collector.providers.garmin.provider.GarminClient.from_token_path",
        fake_from_token_path,
    )
    result = await provider.backfill_history(
        SyncRequest(
            user_id=uuid4(),
            provider=DataProviderType.GARMIN,
            resource_types=(
                ResourceType.HRV,
                ResourceType.ENDURANCE_SCORE,
                ResourceType.ACTIVITIES,
            ),
        ),
        start_date=date(2026, 9, 12),
        end_date=date(2026, 9, 13),
    )
    assert result.status == SyncStatus.FAILED
    assert client.activity_calls == 0
    stored_ids = {item.provider_record_id for item in raw_repo.saved}
    assert "2026-09-12" in stored_ids
    assert "2026-09-13" not in stored_ids
    assert any(item.resource_type == ResourceType.ENDURANCE_SCORE for item in raw_repo.saved)
