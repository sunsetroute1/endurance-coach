"""Tests for provider protocol conformance."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from endurance_coach.collector.interfaces import DataProvider, TokenStore
from endurance_coach.collector.providers.garmin import garmin_setup_instructions
from endurance_coach.domain.enums import DataProviderType, ResourceType, SyncStatus
from endurance_coach.domain.models import (
    ProviderSetupInstructions,
    SyncRequest,
    SyncResult,
    TokenReference,
)


class StubTokenStore:
    async def get_reference(
        self,
        user_id: UUID,
        provider: DataProviderType,
    ) -> TokenReference | None:
        return TokenReference(
            provider=provider,
            reference_path="/tmp/tokens",
        )

    async def is_authenticated(
        self,
        user_id: UUID,
        provider: DataProviderType,
    ) -> bool:
        return provider == DataProviderType.GARMIN

    def get_setup_instructions(
        self,
        provider: DataProviderType,
    ) -> ProviderSetupInstructions:
        return garmin_setup_instructions()


class StubGarminProvider:
    @property
    def provider_type(self) -> DataProviderType:
        return DataProviderType.GARMIN

    def supported_resource_types(self) -> tuple[ResourceType, ...]:
        return (
            ResourceType.ACTIVITIES,
            ResourceType.SLEEP,
            ResourceType.HRV,
            ResourceType.TRAINING_READINESS,
        )

    async def is_available(self, user_id: UUID) -> bool:
        return True

    async def sync(self, request: SyncRequest) -> SyncResult:
        return SyncResult(
            job_id=uuid4(),
            provider=request.provider,
            status=SyncStatus.COMPLETED,
            resources_synced={ResourceType.ACTIVITIES: 3},
            completed_at=datetime.now(UTC),
        )


def test_stub_implements_token_store_protocol() -> None:
    store: TokenStore = StubTokenStore()
    assert store is not None


def test_stub_implements_data_provider_protocol() -> None:
    provider: DataProvider = StubGarminProvider()
    assert provider.provider_type == DataProviderType.GARMIN
    assert ResourceType.ACTIVITIES in provider.supported_resource_types()


@pytest.mark.asyncio
async def test_stub_provider_sync() -> None:
    provider = StubGarminProvider()
    result = await provider.sync(
        SyncRequest(
            user_id=uuid4(),
            provider=DataProviderType.GARMIN,
            resource_types=(ResourceType.ACTIVITIES,),
        )
    )
    assert result.status == SyncStatus.COMPLETED
    assert result.resources_synced[ResourceType.ACTIVITIES] == 3
