"""Samsung Health sync and import API routes."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from endurance_coach.api.deps import RequestServices, get_container, get_request_services
from endurance_coach.api.schemas.temporal import ResponseMeta, build_response_meta
from endurance_coach.collector.providers.samsung.import_service import SamsungImportRecord
from endurance_coach.collector.providers.samsung.provider import SUPPORTED_RESOURCES
from endurance_coach.collector.providers.samsung.setup import samsung_setup_instructions
from endurance_coach.di.container import Container
from endurance_coach.domain.enums import DataProviderType, ResourceType, SyncStatus
from endurance_coach.domain.models import SyncRequest

router = APIRouter(prefix="/api/v1", tags=["samsung"])


class SamsungImportRecordRequest(BaseModel):
    resource_type: ResourceType
    provider_record_id: str
    payload: dict[str, Any]


class SamsungImportRequest(BaseModel):
    schema_version: int = 1
    device_id: str | None = None
    records: list[SamsungImportRecordRequest] = Field(min_length=1)


class SyncSamsungRequest(BaseModel):
    resource_types: list[ResourceType] | None = None


class SyncResultResponse(BaseModel):
    meta: ResponseMeta
    job_id: UUID
    provider: DataProviderType
    status: SyncStatus
    resources_synced: dict[str, int]
    errors: list[str]
    completed_at: datetime | None = None


class SamsungStatusResponse(BaseModel):
    meta: ResponseMeta
    provider: DataProviderType
    configured: bool
    import_dir: str
    pending_files: int
    supported_resources: list[str]
    setup_steps: list[str]


def _sync_result_response(
    *,
    result,
    timezone: str,
) -> SyncResultResponse:
    return SyncResultResponse(
        meta=build_response_meta(timezone=timezone),
        job_id=result.job_id,
        provider=result.provider,
        status=result.status,
        resources_synced={k.value: v for k, v in result.resources_synced.items()},
        errors=list(result.errors),
        completed_at=result.completed_at,
    )


@router.get("/providers/samsung/status", response_model=SamsungStatusResponse)
async def samsung_status(
    services: RequestServices = Depends(get_request_services),
    container: Container = Depends(get_container),
) -> SamsungStatusResponse:
    user = await services.user_repo.get_or_create_default(container.settings.default_user_email)
    import_dir = container.settings.samsung_health_import_dir
    import_dir.mkdir(parents=True, exist_ok=True)
    configured = await services.samsung_provider.is_available(user.id)
    instructions = samsung_setup_instructions(str(import_dir), container.settings.public_base_url)

    return SamsungStatusResponse(
        meta=build_response_meta(timezone=container.settings.app_timezone),
        provider=DataProviderType.SAMSUNG_HEALTH,
        configured=configured,
        import_dir=str(import_dir),
        pending_files=len(list(import_dir.glob("*.json"))),
        supported_resources=[resource.value for resource in SUPPORTED_RESOURCES],
        setup_steps=list(instructions.steps),
    )


@router.post("/sync/samsung/import", response_model=SyncResultResponse)
async def samsung_import(
    body: SamsungImportRequest,
    services: RequestServices = Depends(get_request_services),
    container: Container = Depends(get_container),
) -> SyncResultResponse:
    user = await services.user_repo.get_or_create_default(container.settings.default_user_email)
    records = [
        SamsungImportRecord(
            resource_type=record.resource_type,
            provider_record_id=record.provider_record_id,
            payload=record.payload,
        )
        for record in body.records
    ]
    resource_types = tuple({record.resource_type for record in records})
    request = SyncRequest(
        user_id=user.id,
        provider=DataProviderType.SAMSUNG_HEALTH,
        resource_types=resource_types,
    )
    result = await services.samsung_import_service.import_records(
        request,
        records,
        device_id=body.device_id,
    )

    if result.status == SyncStatus.FAILED and not result.resources_synced:
        raise HTTPException(
            status_code=400,
            detail={"errors": list(result.errors), "job_id": str(result.job_id)},
        )

    return _sync_result_response(result=result, timezone=container.settings.app_timezone)


@router.post("/sync/samsung", response_model=SyncResultResponse)
async def sync_samsung(
    body: SyncSamsungRequest,
    services: RequestServices = Depends(get_request_services),
    container: Container = Depends(get_container),
) -> SyncResultResponse:
    user = await services.user_repo.get_or_create_default(container.settings.default_user_email)
    resource_types = tuple(body.resource_types) if body.resource_types else SUPPORTED_RESOURCES
    result = await services.sync_orchestrator.run_sync(
        SyncRequest(
            user_id=user.id,
            provider=DataProviderType.SAMSUNG_HEALTH,
            resource_types=resource_types,
        )
    )

    if result.status == SyncStatus.FAILED and not result.resources_synced:
        raise HTTPException(
            status_code=503,
            detail={"errors": list(result.errors), "job_id": str(result.job_id)},
        )

    return _sync_result_response(result=result, timezone=container.settings.app_timezone)
