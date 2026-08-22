"""Samsung Health data provider — ingests JSON batches from Android companion or import dir."""

from __future__ import annotations

import logging
import shutil
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from endurance_coach.collector.providers.samsung.import_service import SamsungHealthImportService
from endurance_coach.collector.providers.samsung.setup import samsung_setup_instructions
from endurance_coach.collector.repositories import (
    SqlAlchemyProviderConnectionRepository,
    SqlAlchemySyncJobRepository,
)
from endurance_coach.domain.enums import DataProviderType, ResourceType, SyncStatus
from endurance_coach.domain.models import SyncRequest, SyncResult

logger = logging.getLogger(__name__)

SUPPORTED_RESOURCES = (
    ResourceType.ACTIVITIES,
    ResourceType.SLEEP,
    ResourceType.STEPS,
    ResourceType.HRV,
)


class SamsungHealthDataProvider:
    def __init__(
        self,
        import_service: SamsungHealthImportService,
        sync_job_repo: SqlAlchemySyncJobRepository,
        connection_repo: SqlAlchemyProviderConnectionRepository,
        import_dir: Path,
        public_base_url: str,
    ) -> None:
        self._import_service = import_service
        self._sync_job_repo = sync_job_repo
        self._connection_repo = connection_repo
        self._import_dir = import_dir
        self._public_base_url = public_base_url

    @property
    def provider_type(self) -> DataProviderType:
        return DataProviderType.SAMSUNG_HEALTH

    def supported_resource_types(self) -> tuple[ResourceType, ...]:
        return SUPPORTED_RESOURCES

    async def is_available(self, user_id: UUID) -> bool:
        connection = await self._connection_repo.get_connection(user_id, DataProviderType.SAMSUNG_HEALTH)
        if connection is not None:
            return True
        if not self._import_dir.exists():
            return False
        return any(self._import_dir.glob("*.json"))

    async def sync(self, request: SyncRequest) -> SyncResult:
        self._import_dir.mkdir(parents=True, exist_ok=True)
        pending = sorted(self._import_dir.glob("*.json"))

        if not pending:
            instructions = samsung_setup_instructions(str(self._import_dir), self._public_base_url)
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

        processed_dir = self._import_dir / "processed"
        processed_dir.mkdir(parents=True, exist_ok=True)

        resources_synced: dict[ResourceType, int] = {}
        errors: list[str] = []
        last_job_id: UUID | None = None

        for path in pending:
            try:
                result = await self._import_service.import_json_file(request, path)
                last_job_id = result.job_id
                for resource_type, count in result.resources_synced.items():
                    resources_synced[resource_type] = resources_synced.get(resource_type, 0) + count
                errors.extend(result.errors)
                destination = processed_dir / f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%S')}_{path.name}"
                shutil.move(str(path), str(destination))
            except Exception as exc:
                logger.exception("Failed to import Samsung Health file %s", path)
                errors.append(f"{path.name}: {exc}")

        saved = sum(resources_synced.values())
        status = SyncStatus.COMPLETED if saved and not errors else SyncStatus.FAILED
        if saved and errors:
            status = SyncStatus.COMPLETED

        if last_job_id is None:
            job = await self._sync_job_repo.create(request)
            last_job_id = job.id

        return SyncResult(
            job_id=last_job_id,
            provider=self.provider_type,
            status=status,
            resources_synced=resources_synced,
            errors=tuple(errors),
            completed_at=datetime.now(UTC),
        )
