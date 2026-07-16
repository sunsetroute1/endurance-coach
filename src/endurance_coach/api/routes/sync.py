"""Sync and provider status API routes."""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from endurance_coach.api.deps import RequestServices, get_container, get_request_services
from endurance_coach.api.schemas.temporal import ResponseMeta, build_response_meta
from endurance_coach.collector.providers.garmin.provider import SUPPORTED_RESOURCES
from endurance_coach.di.container import Container
from endurance_coach.domain.enums import DataProviderType, ResourceType, SyncStatus
from endurance_coach.domain.models import SyncRequest

router = APIRouter(prefix="/api/v1", tags=["sync"])


class SyncGarminRequest(BaseModel):
    resource_types: list[ResourceType] | None = None
    since: datetime | None = None
    full_sync: bool = False


class SyncResultResponse(BaseModel):
    meta: ResponseMeta
    job_id: UUID
    provider: DataProviderType
    status: SyncStatus
    resources_synced: dict[str, int]
    errors: list[str]
    completed_at: datetime | None = None


class ProviderStatusResponse(BaseModel):
    meta: ResponseMeta
    provider: DataProviderType
    authenticated: bool
    token_path: str
    validation_error: str | None = None
    setup_command: str
    verify_command: str
    reauth_command: str
    mfa_note: str


class ServerInfoResponse(BaseModel):
    meta: ResponseMeta
    public_base_url: str
    version: str


@router.get("/server", response_model=ServerInfoResponse)
async def server_info(container: Container = Depends(get_container)) -> ServerInfoResponse:
    from endurance_coach import __version__

    return ServerInfoResponse(
        meta=build_response_meta(timezone=container.settings.app_timezone),
        public_base_url=container.settings.public_base_url,
        version=__version__,
    )


@router.get("/providers/garmin/status", response_model=ProviderStatusResponse)
async def garmin_status(
    services: RequestServices = Depends(get_request_services),
    container: Container = Depends(get_container),
) -> ProviderStatusResponse:
    from endurance_coach.collector.providers.garmin import (
        GARMIN_MCP_AUTH_COMMAND,
        GARMIN_MCP_FORCE_REAUTH_COMMAND,
        GARMIN_MCP_VERIFY_COMMAND,
    )

    await services.user_repo.get_or_create_default(container.settings.default_user_email)
    valid, error = await services.token_store.validate_tokens()
    return ProviderStatusResponse(
        meta=build_response_meta(timezone=container.settings.app_timezone),
        provider=DataProviderType.GARMIN,
        authenticated=valid,
        token_path=str(services.token_store.token_path),
        validation_error=error or None,
        setup_command=GARMIN_MCP_AUTH_COMMAND,
        verify_command=GARMIN_MCP_VERIFY_COMMAND,
        reauth_command=GARMIN_MCP_FORCE_REAUTH_COMMAND,
        mfa_note=(
            "Garmin 2FA is handled by garmin-mcp-auth in an interactive terminal on the host. "
            "The API server only reads saved OAuth tokens — it cannot prompt for MFA codes. "
            "Run setup_command once, enter your MFA code when prompted, then sync via the API."
        ),
    )


@router.post("/sync/garmin", response_model=SyncResultResponse)
async def sync_garmin(
    body: SyncGarminRequest,
    services: RequestServices = Depends(get_request_services),
    container: Container = Depends(get_container),
) -> SyncResultResponse:
    user = await services.user_repo.get_or_create_default(container.settings.default_user_email)
    resource_types = tuple(body.resource_types) if body.resource_types else SUPPORTED_RESOURCES

    result = await services.sync_orchestrator.run_sync(
        SyncRequest(
            user_id=user.id,
            provider=DataProviderType.GARMIN,
            resource_types=resource_types,
            since=body.since,
            full_sync=body.full_sync,
        )
    )

    if result.status == SyncStatus.FAILED and not result.resources_synced:
        raise HTTPException(
            status_code=503,
            detail={"errors": list(result.errors), "job_id": str(result.job_id)},
        )

    return SyncResultResponse(
        meta=build_response_meta(timezone=container.settings.app_timezone),
        job_id=result.job_id,
        provider=result.provider,
        status=result.status,
        resources_synced={k.value: v for k, v in result.resources_synced.items()},
        errors=list(result.errors),
        completed_at=result.completed_at,
    )
