"""SQLAlchemy repository implementations for the collector layer."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from endurance_coach.db.models import ProviderConnection, RawPayloadRecord, SyncJob, User
from endurance_coach.domain.enums import DataProviderType, ResourceType, SyncStatus
from endurance_coach.domain.models import RawPayload, SyncRequest


class SqlAlchemyUserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_or_create_default(self, email: str) -> User:
        result = await self._session.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()
        if user is not None:
            return user

        user = User(email=email)
        self._session.add(user)
        await self._session.flush()
        return user


class SqlAlchemyProviderConnectionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert_garmin_reference(self, user_id: UUID, token_path: str) -> ProviderConnection:
        return await self.upsert_provider_reference(
            user_id,
            DataProviderType.GARMIN,
            token_path,
        )

    async def upsert_provider_reference(
        self,
        user_id: UUID,
        provider: DataProviderType,
        token_reference: str,
    ) -> ProviderConnection:
        result = await self._session.execute(
            select(ProviderConnection).where(
                ProviderConnection.user_id == user_id,
                ProviderConnection.provider == provider,
            )
        )
        connection = result.scalar_one_or_none()
        if connection is None:
            connection = ProviderConnection(
                user_id=user_id,
                provider=provider,
                token_reference=token_reference,
                is_active=True,
            )
            self._session.add(connection)
        else:
            connection.token_reference = token_reference
            connection.is_active = True

        await self._session.flush()
        return connection


class SqlAlchemySyncJobRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, request: SyncRequest) -> SyncJob:
        job = SyncJob(
            user_id=request.user_id,
            provider=request.provider,
            status=SyncStatus.IN_PROGRESS,
            resource_types=[rt.value for rt in request.resource_types],
            started_at=datetime.now(UTC),
        )
        self._session.add(job)
        await self._session.flush()
        return job

    async def complete(
        self,
        job_id: UUID,
        *,
        status: SyncStatus,
        resources_synced: dict[ResourceType, int],
        error_message: str | None = None,
    ) -> None:
        result = await self._session.execute(select(SyncJob).where(SyncJob.id == job_id))
        job = result.scalar_one()
        job.status = status
        job.completed_at = datetime.now(UTC)
        job.resources_synced = {k.value: v for k, v in resources_synced.items()}
        job.error_message = error_message
        await self._session.flush()


class SqlAlchemyRawPayloadRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, payload: RawPayload) -> RawPayload:
        existing = await self.get_by_hash(payload.user_id, payload.content_hash)
        if existing is not None:
            return existing

        record = RawPayloadRecord(
            user_id=payload.user_id,
            sync_job_id=payload.sync_job_id,
            provider=payload.provider,
            resource_type=payload.resource_type,
            provider_record_id=payload.provider_record_id,
            payload=payload.payload,
            content_hash=payload.content_hash,
            fetched_at=payload.fetched_at,
        )
        self._session.add(record)
        await self._session.flush()

        return RawPayload(
            id=record.id,
            user_id=record.user_id,
            provider=DataProviderType(record.provider),
            resource_type=ResourceType(record.resource_type),
            provider_record_id=record.provider_record_id,
            payload=record.payload,
            content_hash=record.content_hash,
            fetched_at=record.fetched_at,
            sync_job_id=record.sync_job_id,
        )

    async def get_by_hash(self, user_id: UUID, content_hash: str) -> RawPayload | None:
        result = await self._session.execute(
            select(RawPayloadRecord).where(
                RawPayloadRecord.user_id == user_id,
                RawPayloadRecord.content_hash == content_hash,
            )
        )
        record = result.scalar_one_or_none()
        if record is None:
            return None

        return RawPayload(
            id=record.id,
            user_id=record.user_id,
            provider=DataProviderType(record.provider),
            resource_type=ResourceType(record.resource_type),
            provider_record_id=record.provider_record_id,
            payload=record.payload,
            content_hash=record.content_hash,
            fetched_at=record.fetched_at,
            sync_job_id=record.sync_job_id,
        )

    async def list_unprocessed(
        self,
        user_id: UUID,
        resource_type: ResourceType,
        limit: int = 100,
    ) -> list[RawPayload]:
        result = await self._session.execute(
            select(RawPayloadRecord)
            .where(
                RawPayloadRecord.user_id == user_id,
                RawPayloadRecord.resource_type == resource_type,
                RawPayloadRecord.processed_at.is_(None),
            )
            .order_by(RawPayloadRecord.fetched_at.desc())
            .limit(limit)
        )
        records = result.scalars().all()
        return [
            RawPayload(
                id=record.id,
                user_id=record.user_id,
                provider=DataProviderType(record.provider),
                resource_type=ResourceType(record.resource_type),
                provider_record_id=record.provider_record_id,
                payload=record.payload,
                content_hash=record.content_hash,
                fetched_at=record.fetched_at,
                sync_job_id=record.sync_job_id,
            )
            for record in records
        ]

    async def mark_processed(self, payload_id: UUID) -> None:
        result = await self._session.execute(
            select(RawPayloadRecord).where(RawPayloadRecord.id == payload_id)
        )
        record = result.scalar_one_or_none()
        if record is None:
            return
        record.processed_at = datetime.now(UTC)
        await self._session.flush()

    async def get_record_by_id(self, payload_id: UUID) -> RawPayloadRecord | None:
        result = await self._session.execute(
            select(RawPayloadRecord).where(RawPayloadRecord.id == payload_id)
        )
        return result.scalar_one_or_none()

    async def update_payload(
        self,
        payload_id: UUID,
        *,
        payload: dict,
        content_hash: str,
        fetched_at: datetime | None = None,
    ) -> None:
        record = await self.get_record_by_id(payload_id)
        if record is None:
            raise ValueError(f"Raw payload not found: {payload_id}")

        record.payload = payload
        record.content_hash = content_hash
        record.fetched_at = fetched_at or datetime.now(UTC)
        await self._session.flush()
