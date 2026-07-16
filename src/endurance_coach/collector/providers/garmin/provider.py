"""Garmin Connect data provider — syncs raw payloads via garmin_mcp tokens."""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

from endurance_coach.collector.hashing import payload_content_hash
from endurance_coach.collector.providers.garmin.client import GarminClient
from endurance_coach.collector.providers.garmin.token_store import GarminTokenStore
from endurance_coach.collector.repositories import (
    SqlAlchemyProviderConnectionRepository,
    SqlAlchemyRawPayloadRepository,
    SqlAlchemySyncJobRepository,
)
from endurance_coach.domain.enums import DataProviderType, ResourceType, SyncStatus
from endurance_coach.domain.models import RawPayload, SyncRequest, SyncResult

logger = logging.getLogger(__name__)

SUPPORTED_RESOURCES = (
    ResourceType.ACTIVITIES,
    ResourceType.SLEEP,
    ResourceType.HRV,
    ResourceType.BODY_BATTERY,
    ResourceType.TRAINING_READINESS,
    ResourceType.STRESS,
    ResourceType.STEPS,
)


class GarminDataProvider:
    def __init__(
        self,
        token_store: GarminTokenStore,
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
        return DataProviderType.GARMIN

    def supported_resource_types(self) -> tuple[ResourceType, ...]:
        return SUPPORTED_RESOURCES

    async def is_available(self, user_id: UUID) -> bool:
        return await self._token_store.is_authenticated(user_id, DataProviderType.GARMIN)

    async def sync(self, request: SyncRequest) -> SyncResult:
        errors: list[str] = []
        resources_synced: dict[ResourceType, int] = {}

        if not await self.is_available(request.user_id):
            instructions = self._token_store.get_setup_instructions(DataProviderType.GARMIN)
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
        await self._connection_repo.upsert_garmin_reference(
            request.user_id,
            str(self._token_store.token_path),
        )

        try:
            client = await GarminClient.from_token_path(self._token_store.token_path)
            start_date, end_date = self._resolve_date_window(request)

            for resource_type in request.resource_types:
                if resource_type not in SUPPORTED_RESOURCES:
                    errors.append(f"Unsupported resource type: {resource_type}")
                    continue

                try:
                    count = await self._sync_resource(
                        client=client,
                        request=request,
                        job_id=job.id,
                        resource_type=resource_type,
                        start_date=start_date,
                        end_date=end_date,
                    )
                    resources_synced[resource_type] = count
                except Exception as exc:
                    message = f"{resource_type}: {exc}"
                    logger.exception("Garmin sync failed for %s", resource_type)
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
            logger.exception("Garmin sync failed")
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

    async def _sync_resource(
        self,
        *,
        client: GarminClient,
        request: SyncRequest,
        job_id: UUID,
        resource_type: ResourceType,
        start_date: date,
        end_date: date,
    ) -> int:
        if resource_type == ResourceType.ACTIVITIES:
            return await self._sync_activities(client, request, job_id, start_date)
        return await self._sync_daily_resource(
            client, request, job_id, resource_type, start_date, end_date
        )

    async def _sync_activities(
        self,
        client: GarminClient,
        request: SyncRequest,
        job_id: UUID,
        start_date: date,
    ) -> int:
        saved = 0
        start = 0
        limit = 50

        while True:
            activities = await client.get_activities(start=start, limit=limit)
            if not activities:
                break

            for summary in activities:
                activity_id = str(summary.get("activityId") or summary.get("activity_id", ""))
                if not activity_id:
                    continue

                activity_date = self._parse_activity_date(summary)
                if activity_date is not None and activity_date < start_date:
                    continue

                detail = await client.get_activity(activity_id)
                laps = await client.get_activity_laps(activity_id)
                if laps and isinstance(detail, dict):
                    detail = {**detail, "lapDTOs": laps}
                payload = {"summary": summary, "detail": detail}
                if await self._persist_payload(
                    request=request,
                    job_id=job_id,
                    resource_type=ResourceType.ACTIVITIES,
                    provider_record_id=activity_id,
                    payload=payload,
                ):
                    saved += 1

            if len(activities) < limit:
                break
            start += limit

        return saved

    async def _sync_daily_resource(
        self,
        client: GarminClient,
        request: SyncRequest,
        job_id: UUID,
        resource_type: ResourceType,
        start_date: date,
        end_date: date,
    ) -> int:
        saved = 0
        fetchers = {
            ResourceType.SLEEP: client.get_sleep_data,
            ResourceType.HRV: client.get_hrv_data,
            ResourceType.BODY_BATTERY: client.get_body_battery,
            ResourceType.TRAINING_READINESS: client.get_training_readiness,
            ResourceType.STRESS: client.get_stress_data,
            ResourceType.STEPS: client.get_daily_stats,
        }
        fetcher = fetchers[resource_type]

        for day in client.iter_dates(start_date, end_date):
            data = await fetcher(day)
            if not data:
                continue

            if await self._persist_payload(
                request=request,
                job_id=job_id,
                resource_type=resource_type,
                provider_record_id=day.isoformat(),
                payload={"date": day.isoformat(), "data": data},
            ):
                saved += 1

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
                provider=DataProviderType.GARMIN,
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
        for key in ("startTimeLocal", "startTimeGMT", "beginTimestamp"):
            value = summary.get(key)
            if not value:
                continue
            try:
                if isinstance(value, (int, float)):
                    return datetime.fromtimestamp(value / 1000, tz=UTC).date()
                return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
            except (TypeError, ValueError):
                continue
        return None
