"""Tests for Samsung Health import service."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from endurance_coach.collector.providers.samsung.import_service import (
    SamsungHealthImportService,
    SamsungImportRecord,
    parse_import_batch,
)
from endurance_coach.domain.enums import DataProviderType, ResourceType, SyncStatus
from endurance_coach.domain.models import RawPayload, SyncRequest


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


@pytest.fixture
def fixture_batch() -> dict[str, Any]:
    path = Path(__file__).parent / "fixtures" / "samsung_import_batch.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_parse_import_batch(fixture_batch: dict[str, Any]) -> None:
    records = parse_import_batch(fixture_batch)
    assert len(records) == 3
    assert records[0].resource_type == ResourceType.SLEEP


@pytest.mark.asyncio
async def test_import_records(fixture_batch: dict[str, Any]) -> None:
    service = SamsungHealthImportService(
        raw_payload_repo=StubRawPayloadRepo(),
        sync_job_repo=StubSyncJobRepo(),
        connection_repo=StubConnectionRepo(),
    )
    user_id = uuid4()
    records = parse_import_batch(fixture_batch)
    request = SyncRequest(
        user_id=user_id,
        provider=DataProviderType.SAMSUNG_HEALTH,
        resource_types=tuple(ResourceType),
    )
    result = await service.import_records(request, records, device_id="phone-1")

    assert result.status == SyncStatus.COMPLETED
    assert result.resources_synced[ResourceType.SLEEP] == 1
    assert result.resources_synced[ResourceType.STEPS] == 1
    assert result.resources_synced[ResourceType.ACTIVITIES] == 1
    assert len(service._raw_payload_repo.saved) == 3  # type: ignore[attr-defined]
