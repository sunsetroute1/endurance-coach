"""Strava OAuth and sync API routes."""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from endurance_coach.api.deps import RequestServices, get_container, get_request_services
from endurance_coach.api.schemas.temporal import ResponseMeta, build_response_meta
from endurance_coach.collector.providers.strava import SUPPORTED_RESOURCES, strava_authorize_url
from endurance_coach.di.container import Container
from endurance_coach.domain.enums import DataProviderType, ResourceType, SyncStatus
from endurance_coach.domain.models import SyncRequest

router = APIRouter(prefix="/api/v1", tags=["strava"])


class SyncStravaRequest(BaseModel):
    resource_types: list[ResourceType] | None = None
    since: datetime | None = None
    full_sync: bool = False


class StravaStatusResponse(BaseModel):
    meta: ResponseMeta
    provider: DataProviderType
    authenticated: bool
    token_path: str
    validation_error: str | None = None
    authorize_url: str
    redirect_uri: str


class SyncResultResponse(BaseModel):
    meta: ResponseMeta
    job_id: UUID
    provider: DataProviderType
    status: SyncStatus
    resources_synced: dict[str, int]
    errors: list[str]
    completed_at: datetime | None = None


@router.get("/providers/strava/status", response_model=StravaStatusResponse)
async def strava_status(
    services: RequestServices = Depends(get_request_services),
    container: Container = Depends(get_container),
) -> StravaStatusResponse:
    await services.user_repo.get_or_create_default(container.settings.default_user_email)
    valid, error = await services.strava_token_store.validate_tokens()
    settings = container.settings
    return StravaStatusResponse(
        meta=build_response_meta(timezone=container.settings.app_timezone),
        provider=DataProviderType.STRAVA,
        authenticated=valid,
        token_path=str(services.strava_token_store.token_file),
        validation_error=error or None,
        authorize_url=strava_authorize_url(
            client_id=settings.strava_client_id,
            redirect_uri=settings.strava_redirect_uri,
        ),
        redirect_uri=settings.strava_redirect_uri,
    )


@router.get("/providers/strava/connect")
async def strava_connect(
    container: Container = Depends(get_container),
) -> RedirectResponse:
    settings = container.settings
    if not settings.strava_client_id:
        raise HTTPException(status_code=400, detail="STRAVA_CLIENT_ID is not configured")
    url = strava_authorize_url(
        client_id=settings.strava_client_id,
        redirect_uri=settings.strava_redirect_uri,
    )
    return RedirectResponse(url=url, status_code=302)


@router.get("/providers/strava/callback")
async def strava_callback(
    code: str = Query(...),
    services: RequestServices = Depends(get_request_services),
    container: Container = Depends(get_container),
) -> dict[str, str]:
    user = await services.user_repo.get_or_create_default(container.settings.default_user_email)
    tokens = await services.strava_token_store.exchange_code(code)
    await services.connection_repo.upsert_provider_reference(
        user.id,
        DataProviderType.STRAVA,
        str(services.strava_token_store.token_file),
    )
    athlete_id = str(tokens.athlete_id) if tokens.athlete_id is not None else "unknown"
    return {
        "status": "connected",
        "provider": DataProviderType.STRAVA.value,
        "athlete_id": athlete_id,
        "message": "Strava connected. Run POST /api/v1/sync/strava to pull activities.",
    }


@router.post("/sync/strava", response_model=SyncResultResponse)
async def sync_strava(
    body: SyncStravaRequest,
    services: RequestServices = Depends(get_request_services),
    container: Container = Depends(get_container),
) -> SyncResultResponse:
    user = await services.user_repo.get_or_create_default(container.settings.default_user_email)
    resource_types = tuple(body.resource_types) if body.resource_types else SUPPORTED_RESOURCES

    result = await services.sync_orchestrator.run_sync(
        SyncRequest(
            user_id=user.id,
            provider=DataProviderType.STRAVA,
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
