"""Garmin-specific API routes."""

import asyncio
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from endurance_coach.api.deps import RequestServices, get_container, get_request_services
from endurance_coach.di.container import Container
from endurance_coach.garmin.daily_readiness import (
    DailyGarminReadinessResponse,
    DailyGarminReadinessService,
    MorningReadinessIncompleteError,
    MorningReadinessStatusResponse,
)
from endurance_coach.garmin.login_page import LOGIN_PAGE_HTML
from endurance_coach.garmin.phone_login import (
    LoginResult,
    PhoneLoginError,
    start_phone_login,
    submit_phone_code,
)

router = APIRouter(prefix="/api/v1", tags=["garmin"])


class GarminPasswordLogin(BaseModel):
    email: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=1, max_length=200)


class GarminCodeLogin(BaseModel):
    code: str = Field(min_length=1, max_length=20)


class GarminLoginResponse(BaseModel):
    status: str
    message: str
    login_id: str | None = None
    name: str | None = None


def _login_http_error(exc: PhoneLoginError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.message)


def _login_response(result: LoginResult) -> GarminLoginResponse:
    return GarminLoginResponse(
        status=result.status,
        message=result.message,
        login_id=result.login_id,
        name=result.name,
    )


@router.get("/garmin/login", response_class=HTMLResponse)
async def garmin_login_page() -> HTMLResponse:
    return HTMLResponse(
        LOGIN_PAGE_HTML,
        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
    )


@router.post("/garmin/login", response_model=GarminLoginResponse)
async def garmin_login_start(
    body: GarminPasswordLogin,
    container: Container = Depends(get_container),
) -> GarminLoginResponse:
    try:
        result = await asyncio.to_thread(
            start_phone_login,
            body.email,
            body.password,
            container.settings.garmin_token_path,
        )
    except PhoneLoginError as exc:
        raise _login_http_error(exc) from exc
    return _login_response(result)


@router.post("/garmin/login/{login_id}/code", response_model=GarminLoginResponse)
async def garmin_login_code(
    login_id: str,
    body: GarminCodeLogin,
    container: Container = Depends(get_container),
) -> GarminLoginResponse:
    try:
        result = await asyncio.to_thread(
            submit_phone_code,
            login_id,
            body.code,
            container.settings.garmin_token_path,
        )
    except PhoneLoginError as exc:
        raise _login_http_error(exc) from exc
    return _login_response(result)


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
