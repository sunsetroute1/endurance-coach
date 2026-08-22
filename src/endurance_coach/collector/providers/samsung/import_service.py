"""Shared Samsung Health import helpers."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from endurance_coach.collector.hashing import payload_content_hash
from endurance_coach.collector.repositories import (
    SqlAlchemyProviderConnectionRepository,
    SqlAlchemyRawPayloadRepository,
    SqlAlchemySyncJobRepository,
)
from endurance_coach.domain.enums import DataProviderType, ResourceType, SyncStatus
from endurance_coach.domain.models import RawPayload, SyncRequest, SyncResult


class SamsungImportRecord:
    __slots__ = ("resource_type", "provider_record_id", "payload")

    def __init__(
        self,
        *,
        resource_type: ResourceType,
        provider_record_id: str,
        payload: dict[str, Any],
    ) -> None:
        self.resource_type = resource_type
        self.provider_record_id = provider_record_id
        self.payload = payload


class SamsungHealthImportService:
    """Persist Samsung Health batches into raw_payloads."""

    def __init__(
        self,
        raw_payload_repo: SqlAlchemyRawPayloadRepository,
        sync_job_repo: SqlAlchemySyncJobRepository,
        connection_repo: SqlAlchemyProviderConnectionRepository,
    ) -> None:
        self._raw_payload_repo = raw_payload_repo
        self._sync_job_repo = sync_job_repo
        self._connection_repo = connection_repo

    async def import_records(
        self,
        request: SyncRequest,
        records: list[SamsungImportRecord],
        *,
        device_id: str | None = None,
    ) -> SyncResult:
        job = await self._sync_job_repo.create(request)
        reference = device_id or "android-companion"
        await self._connection_repo.upsert_provider_reference(
            request.user_id,
            DataProviderType.SAMSUNG_HEALTH,
            reference,
        )

        resources_synced: dict[ResourceType, int] = {}
        errors: list[str] = []

        for index, record in enumerate(records):
            try:
                if record.resource_type not in request.resource_types:
                    continue
                saved = await self._persist_payload(
                    request=request,
                    job_id=job.id,
                    resource_type=record.resource_type,
                    provider_record_id=record.provider_record_id,
                    payload=record.payload,
                )
                if saved:
                    resources_synced[record.resource_type] = (
                        resources_synced.get(record.resource_type, 0) + 1
                    )
            except Exception as exc:
                errors.append(f"record[{index}] {record.resource_type}: {exc}")

        status = SyncStatus.COMPLETED if not errors else SyncStatus.FAILED
        await self._sync_job_repo.complete(
            job.id,
            status=status,
            resources_synced=resources_synced,
            error_message="; ".join(errors) if errors else None,
        )

        return SyncResult(
            job_id=job.id,
            provider=DataProviderType.SAMSUNG_HEALTH,
            status=status,
            resources_synced=resources_synced,
            errors=tuple(errors),
            completed_at=datetime.now(UTC),
        )

    async def import_json_file(
        self,
        request: SyncRequest,
        path: Path,
    ) -> SyncResult:
        text = path.read_text(encoding="utf-8")
        data = json.loads(text)
        records = parse_import_batch(data)
        if not records:
            job = await self._sync_job_repo.create(request)
            message = f"No importable records in {path.name}"
            await self._sync_job_repo.complete(
                job.id,
                status=SyncStatus.FAILED,
                resources_synced={},
                error_message=message,
            )
            return SyncResult(
                job_id=job.id,
                provider=DataProviderType.SAMSUNG_HEALTH,
                status=SyncStatus.FAILED,
                errors=(message,),
                completed_at=datetime.now(UTC),
            )

        device_id = data.get("device_id") if isinstance(data, dict) else None
        return await self.import_records(request, records, device_id=device_id)

    async def _persist_payload(
        self,
        *,
        request: SyncRequest,
        job_id: UUID,
        resource_type: ResourceType,
        provider_record_id: str,
        payload: dict[str, Any],
    ) -> bool:
        content_hash = payload_content_hash(payload)
        existing = await self._raw_payload_repo.get_by_hash(request.user_id, content_hash)
        if existing is not None:
            return False

        await self._raw_payload_repo.save(
            RawPayload(
                user_id=request.user_id,
                provider=DataProviderType.SAMSUNG_HEALTH,
                resource_type=resource_type,
                provider_record_id=provider_record_id,
                payload=payload,
                content_hash=content_hash,
                fetched_at=datetime.now(UTC),
                sync_job_id=job_id,
            )
        )
        return True


def parse_import_batch(data: Any) -> list[SamsungImportRecord]:
    """Parse API/file batch payloads into import records."""
    if isinstance(data, list):
        return [_parse_record(item) for item in data if _is_record_dict(item)]

    if not isinstance(data, dict):
        return []

    records = data.get("records")
    if isinstance(records, list):
        return [_parse_record(item) for item in records if _is_record_dict(item)]

    if _is_record_dict(data):
        return [_parse_record(data)]

    return []


def _is_record_dict(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and "resource_type" in value
        and "provider_record_id" in value
        and "payload" in value
    )


def _parse_record(item: dict[str, Any]) -> SamsungImportRecord:
    resource_type = ResourceType(str(item["resource_type"]))
    provider_record_id = str(item["provider_record_id"])
    payload = item["payload"]
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")
    return SamsungImportRecord(
        resource_type=resource_type,
        provider_record_id=provider_record_id,
        payload=payload,
    )
