"""Strava data provider — syncs activity payloads via OAuth2."""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

from endurance_coach.collector.hashing import payload_content_hash
from endurance_coach.collector.providers.strava.client import StravaClient, date_to_epoch
from endurance_coach.collector.providers.strava.token_store import StravaTokenStore
from endurance_coach.collector.repositories import (
    SqlAlchemyProviderConnectionRepository,
    SqlAlchemyRawPayloadRepository,
    SqlAlchemySyncJobRepository,
)
from endurance_coach.domain.enums import DataProviderType, ResourceType, SyncStatus
from endurance_coach.domain.models import RawPayload, SyncRequest, SyncResult
from endurance_coach.processor.parsing import parse_datetime

logger = logging.getLogger(__name__)

SUPPORTED_RESOURCES = (ResourceType.ACTIVITIES,)


class StravaDataProvider:
    def __init__(
        self,
        token_store: StravaTokenStore,
        raw_payload_repo: SqlAlchemyRawPayloadRepository,
        sync_job_repo: SqlAlchemySyncJobRepository,
        connection_repo: SqlAlchemyProviderConnectionRepository,
        sync_days: int = 30,
    ) -> None:
        self._token_store = token_store
        self._raw_payload_repo = raw_payload_repo
        self._sync_job_repo = sync_job_repo
        self._connection_repo = connection_repo
        self._sync_days = sync_days

    @property
    def provider_type(self) -> DataProviderType:
        return DataProviderType.STRAVA

    def supported_resource_types(self) -> tuple[ResourceType, ...]:
        return SUPPORTED_RESOURCES

    async def is_available(self, user_id: UUID) -> bool:
        return await self._token_store.is_authenticated(user_id, DataProviderType.STRAVA)

    async def sync(self, request: SyncRequest) -> SyncResult:
        errors: list[str] = []
        resources_synced: dict[ResourceType, int] = {}

        if not await self.is_available(request.user_id):
            instructions = self._token_store.get_setup_instructions(DataProviderType.STRAVA)
            job = await self._sync_job_repo.create(request)
            error_text = "; ".join((instructions.summary, *instructions.steps))
            await self._sync_job_repo.complete(
                job.id,
                status=SyncStatus.FAILED,
                resources_synced={},
                error_message=error_text,
            )
            return SyncResult(
                job_id=job.id,
                provider=self.provider_type,
                status=SyncStatus.FAILED,
                errors=(instructions.summary, *instructions.steps),
                completed_at=datetime.now(UTC),
            )

        job = await self._sync_job_repo.create(request)
        await self._connection_repo.upsert_provider_reference(
            request.user_id,
            DataProviderType.STRAVA,
            str(self._token_store.token_file),
        )

        try:
            client = await StravaClient.from_token_store(self._token_store)
            start_date, _end_date = self._resolve_date_window(request)
            after_epoch = date_to_epoch(start_date)

            for resource_type in request.resource_types:
                if resource_type not in SUPPORTED_RESOURCES:
                    errors.append(f"Unsupported resource type: {resource_type}")
                    continue
                try:
                    count = await self._sync_activities(
                        client=client,
                        request=request,
                        job_id=job.id,
                        after_epoch=after_epoch,
                    )
                    resources_synced[resource_type] = count
                except Exception as exc:
                    message = f"{resource_type}: {exc}"
                    logger.exception("Strava sync failed for %s", resource_type)
                    errors.append(message)

            status = SyncStatus.COMPLETED if not errors else SyncStatus.FAILED
            await self._sync_job_repo.complete(
                job.id,
                status=status,
                resources_synced=resources_synced,
                error_message="; ".join(errors) if errors else None,
            )
            return SyncResult(
                job_id=job.id,
                provider=self.provider_type,
                status=status,
                resources_synced=resources_synced,
                errors=tuple(errors),
                completed_at=datetime.now(UTC),
            )
        except Exception as exc:
            logger.exception("Strava sync failed")
            await self._sync_job_repo.complete(
                job.id,
                status=SyncStatus.FAILED,
                resources_synced=resources_synced,
                error_message=str(exc),
            )
            return SyncResult(
                job_id=job.id,
                provider=self.provider_type,
                status=SyncStatus.FAILED,
                resources_synced=resources_synced,
                errors=(*errors, str(exc)),
                completed_at=datetime.now(UTC),
            )

    def _resolve_date_window(self, request: SyncRequest) -> tuple[date, date]:
        end_date = date.today()
        if request.since is not None:
            start_date = request.since.date()
        elif request.full_sync:
            start_date = end_date - timedelta(days=365)
        else:
            start_date = end_date - timedelta(days=self._sync_days)
        return start_date, end_date

    async def _sync_activities(
        self,
        *,
        client: StravaClient,
        request: SyncRequest,
        job_id: UUID,
        after_epoch: int,
    ) -> int:
        saved = 0
        page = 1
        per_page = 50

        while True:
            summaries = await client.get_activities(
                after_epoch=after_epoch,
                page=page,
                per_page=per_page,
            )
            if not summaries:
                break

            for summary in summaries:
                activity_id = str(summary.get("id", ""))
                if not activity_id:
                    continue

                detail = await client.get_activity(activity_id)
                payload = {"summary": summary, "detail": detail}
                if await self._persist_payload(
                    request=request,
                    job_id=job_id,
                    resource_type=ResourceType.ACTIVITIES,
                    provider_record_id=activity_id,
                    payload=payload,
                ):
                    saved += 1

            if len(summaries) < per_page:
                break
            page += 1

        return saved

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
                provider=DataProviderType.STRAVA,
                resource_type=resource_type,
                provider_record_id=provider_record_id,
                payload=payload,
                content_hash=content_hash,
                fetched_at=datetime.now(UTC),
                sync_job_id=job_id,
            )
        )
        return True

    @staticmethod
    def _parse_activity_date(summary: dict[str, Any]) -> date | None:
        started_at = parse_datetime(summary.get("start_date_local") or summary.get("start_date"))
        return started_at.date() if started_at else None
