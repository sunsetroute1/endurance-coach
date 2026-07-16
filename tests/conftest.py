"""Shared test fixtures."""

from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from endurance_coach.db.base import Base
from endurance_coach.domain.enums import DataProviderType, ResourceType
from endurance_coach.domain.models import RawPayload, SyncRequest


@pytest.fixture
def user_id() -> UUID:
    return uuid4()


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session

    await engine.dispose()


@pytest.fixture
def sample_raw_payload(user_id: UUID) -> RawPayload:
    return RawPayload(
        user_id=user_id,
        provider=DataProviderType.GARMIN,
        resource_type=ResourceType.ACTIVITIES,
        provider_record_id="12345",
        payload={"activityId": 12345, "activityName": "Morning Run"},
        content_hash="abc123",
        fetched_at=datetime.now(UTC),
    )


@pytest.fixture
def sample_sync_request(user_id: UUID) -> SyncRequest:
    return SyncRequest(
        user_id=user_id,
        provider=DataProviderType.GARMIN,
        resource_types=(ResourceType.ACTIVITIES, ResourceType.SLEEP),
    )
