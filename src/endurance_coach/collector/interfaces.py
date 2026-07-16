"""Provider and sync interfaces for the collector layer."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from endurance_coach.domain.enums import DataProviderType, ResourceType
from endurance_coach.domain.models import (
    ProviderSetupInstructions,
    RawPayload,
    SyncRequest,
    SyncResult,
    TokenReference,
)


class TokenStore(Protocol):
    """Manages opaque token references — never stores raw credentials."""

    async def get_reference(
        self,
        user_id: UUID,
        provider: DataProviderType,
    ) -> TokenReference | None: ...

    async def is_authenticated(
        self,
        user_id: UUID,
        provider: DataProviderType,
    ) -> bool: ...

    def get_setup_instructions(
        self,
        provider: DataProviderType,
    ) -> ProviderSetupInstructions: ...


class RawPayloadRepository(Protocol):
    """Persists immutable provider JSON payloads."""

    async def save(self, payload: RawPayload) -> RawPayload: ...

    async def get_by_hash(
        self,
        user_id: UUID,
        content_hash: str,
    ) -> RawPayload | None: ...

    async def list_unprocessed(
        self,
        user_id: UUID,
        resource_type: ResourceType,
        limit: int = 100,
    ) -> list[RawPayload]: ...

    async def mark_processed(self, payload_id: UUID) -> None: ...


class DataProvider(Protocol):
    """Contract for all wearable data providers."""

    @property
    def provider_type(self) -> DataProviderType: ...

    def supported_resource_types(self) -> tuple[ResourceType, ...]: ...

    async def is_available(self, user_id: UUID) -> bool: ...

    async def sync(self, request: SyncRequest) -> SyncResult: ...


class SyncOrchestrator(Protocol):
    """Coordinates multi-provider sync jobs."""

    async def run_sync(self, request: SyncRequest) -> SyncResult: ...

    async def run_all_providers(
        self,
        user_id: UUID,
        resource_types: tuple[ResourceType, ...],
    ) -> list[SyncResult]: ...
