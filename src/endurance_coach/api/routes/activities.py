"""Activity detail API routes."""

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, Query

from endurance_coach.api.deps import RequestServices, get_container, get_request_services
from endurance_coach.collector.providers.garmin.client import GarminClient
from endurance_coach.di.container import Container
from endurance_coach.domain.enums import DataProviderType
from endurance_coach.garmin.activity_detail import DetailedActivityResponse, DetailedActivityService

router = APIRouter(prefix="/api/v1", tags=["activities"])


async def _build_activity_service(
    services: RequestServices,
    container: Container,
    user_id: Any,
) -> DetailedActivityService:
    lap_fetcher = None
    if await services.token_store.is_authenticated(user_id, DataProviderType.GARMIN):
        token_path = services.token_store.token_path

        async def fetch_laps(activity_id: str) -> list[dict]:
            client = await GarminClient.from_token_path(token_path)
            return await client.get_activity_laps(activity_id)

        lap_fetcher = fetch_laps

    return DetailedActivityService(
        services.analytics_repo,
        timezone=container.settings.app_timezone,
        lap_fetcher=lap_fetcher,
    )


@router.get("/activities/detailed", response_model=DetailedActivityResponse)
async def get_detailed_activity(
    target_date: date | None = Query(default=None, alias="date"),
    activity_id: str | None = Query(default=None),
    services: RequestServices = Depends(get_request_services),
    container: Container = Depends(get_container),
) -> DetailedActivityResponse:
    user = await services.user_repo.get_or_create_default(container.settings.default_user_email)
    service = await _build_activity_service(services, container, user.id)
    return await service.get_detailed_activity(
        user.id,
        target_date=target_date,
        activity_id=activity_id,
    )
