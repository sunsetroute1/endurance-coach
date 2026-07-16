"""Garmin-specific API routes."""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query

from endurance_coach.api.deps import RequestServices, get_container, get_request_services
from endurance_coach.di.container import Container
from endurance_coach.garmin.daily_readiness import (
    DailyGarminReadinessResponse,
    DailyGarminReadinessService,
    MorningReadinessIncompleteError,
    MorningReadinessStatusResponse,
)

router = APIRouter(prefix="/api/v1", tags=["garmin"])


@router.get("/garmin/morning-readiness-status", response_model=MorningReadinessStatusResponse)
async def get_morning_readiness_status(
    target_date: date | None = Query(default=None, alias="date"),
    services: RequestServices = Depends(get_request_services),
    container: Container = Depends(get_container),
) -> MorningReadinessStatusResponse:
    user = await services.user_repo.get_or_create_default(container.settings.default_user_email)
    readiness_service = DailyGarminReadinessService(services.analytics_repo)
    return await readiness_service.get_morning_readiness_status(
        user.id,
        timezone=container.settings.app_timezone,
        target_date=target_date,
    )


@router.get("/garmin/daily-readiness", response_model=DailyGarminReadinessResponse)
async def get_daily_garmin_readiness(
    target_date: date | None = Query(default=None, alias="date"),
    allow_partial: bool = Query(
        default=False,
        description="Return best-effort metrics even when required morning fields are missing.",
    ),
    services: RequestServices = Depends(get_request_services),
    container: Container = Depends(get_container),
) -> DailyGarminReadinessResponse:
    user = await services.user_repo.get_or_create_default(container.settings.default_user_email)
    readiness_service = DailyGarminReadinessService(services.analytics_repo)
    try:
        return await readiness_service.get_daily_readiness(
            user.id,
            timezone=container.settings.app_timezone,
            target_date=target_date,
            require_complete=not allow_partial,
        )
    except MorningReadinessIncompleteError as exc:
        raise HTTPException(status_code=404, detail=exc.status.model_dump(mode="json")) from exc
