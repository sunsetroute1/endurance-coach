"""Tests for Strava data provider sync logic."""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import uuid4

import pytest

from endurance_coach.collector.providers.strava.provider import StravaDataProvider
from endurance_coach.collector.providers.strava.token_store import StravaTokenData, StravaTokenStore
from endurance_coach.domain.enums import DataProviderType, ResourceType, SyncStatus
from endurance_coach.domain.models import RawPayload, SyncRequest
from tests.fixtures.strava_payloads import STRAVA_ACTIVITY_DETAIL, STRAVA_ACTIVITY_SUMMARY


class StubTokenStore(StravaTokenStore):
    def __init__(self, authenticated: bool = True) -> None:
        super().__init__(__import__("pathlib").Path("/tmp/strava.json"), client_id="id", client_secret="secret")
        self._authenticated = authenticated

    def token_file_exists(self) -> bool:
        return self._authenticated

    async def is_authenticated(self, user_id: Any, provider: DataProviderType) -> bool:
        return self._authenticated and provider == DataProviderType.STRAVA

    async def validate_tokens(self) -> tuple[bool, str]:
        return self._authenticated, "" if self._authenticated else "missing"

    async def get_valid_tokens(self) -> StravaTokenData | None:
        if not self._authenticated:
            return None
        return StravaTokenData(
            access_token="token",
            refresh_token="refresh",
            expires_at=9999999999,
            athlete_id=42,
        )


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


class StubSyncJobRepo:
    async def create(self, request: SyncRequest):
        return type("Job", (), {"id": uuid4()})()

    async def complete(self, job_id, *, status, resources_synced, error_message=None) -> None:
        return None


class StubConnectionRepo:
    async def upsert_provider_reference(self, user_id, provider, token_reference):
        return None


class StubStravaClient:
    async def get_activities(self, *, after_epoch, page=1, per_page=50):
        if page > 1:
            return []
        return [STRAVA_ACTIVITY_SUMMARY]

    async def get_activity(self, activity_id: str):
        return STRAVA_ACTIVITY_DETAIL


@pytest.mark.asyncio
async def test_strava_provider_sync_activities(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = StravaDataProvider(
        token_store=StubTokenStore(),
        raw_payload_repo=StubRawPayloadRepo(),  # type: ignore[arg-type]
        sync_job_repo=StubSyncJobRepo(),  # type: ignore[arg-type]
        connection_repo=StubConnectionRepo(),  # type: ignore[arg-type]
        sync_days=30,
    )

    async def fake_from_token_store(token_store):
        return StubStravaClient()

    monkeypatch.setattr(
        "endurance_coach.collector.providers.strava.provider.StravaClient.from_token_store",
        fake_from_token_store,
    )

    result = await provider.sync(
        SyncRequest(
            user_id=uuid4(),
            provider=DataProviderType.STRAVA,
            resource_types=(ResourceType.ACTIVITIES,),
            since=None,
            full_sync=False,
        )
    )

    assert result.status == SyncStatus.COMPLETED
    assert result.resources_synced[ResourceType.ACTIVITIES] == 1


@pytest.mark.asyncio
async def test_strava_provider_fails_without_auth() -> None:
    provider = StravaDataProvider(
        token_store=StubTokenStore(authenticated=False),
        raw_payload_repo=StubRawPayloadRepo(),  # type: ignore[arg-type]
        sync_job_repo=StubSyncJobRepo(),  # type: ignore[arg-type]
        connection_repo=StubConnectionRepo(),  # type: ignore[arg-type]
    )

    result = await provider.sync(
        SyncRequest(
            user_id=uuid4(),
            provider=DataProviderType.STRAVA,
            resource_types=(ResourceType.ACTIVITIES,),
        )
    )

    assert result.status == SyncStatus.FAILED
    assert result.errors
