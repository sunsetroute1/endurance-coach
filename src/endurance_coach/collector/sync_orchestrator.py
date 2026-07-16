"""Sync orchestration across providers."""

from __future__ import annotations

from uuid import UUID, uuid4

from endurance_coach.collector.interfaces import DataProvider
from endurance_coach.domain.enums import DataProviderType, ResourceType, SyncStatus
from endurance_coach.domain.models import SyncRequest, SyncResult


class DefaultSyncOrchestrator:
    def __init__(self, providers: dict[DataProviderType, DataProvider]) -> None:
        self._providers = providers

    async def run_sync(self, request: SyncRequest) -> SyncResult:
        provider = self._providers.get(request.provider)
        if provider is None:
            return SyncResult(
                job_id=uuid4(),
                provider=request.provider,
                status=SyncStatus.FAILED,
                errors=(f"No provider registered for {request.provider}",),
            )

        return await provider.sync(request)

    async def run_all_providers(
        self,
        user_id: UUID,
        resource_types: tuple[ResourceType, ...],
    ) -> list[SyncResult]:
        results: list[SyncResult] = []
        for provider_type, provider in self._providers.items():
            if not await provider.is_available(user_id):
                continue
            result = await provider.sync(
                SyncRequest(
                    user_id=user_id,
                    provider=provider_type,
                    resource_types=resource_types,
                )
            )
            results.append(result)
        return results
