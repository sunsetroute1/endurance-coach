"""Coach API routes."""

from endurance_coach.timezone_util import today_local
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from endurance_coach.api.deps import RequestServices, get_container, get_request_services
from endurance_coach.api.schemas.temporal import ResponseMeta, build_response_meta
from endurance_coach.di.container import Container
from endurance_coach.domain.models import CoachResponse

router = APIRouter(prefix="/api/v1", tags=["coach"])


class CoachRecommendationResponse(BaseModel):
    category: str
    action: str
    rationale: str
    metric_citations: list[str]


class CoachResponseModel(BaseModel):
    meta: ResponseMeta
    briefing_for_date: str = Field(
        description="Calendar date (YYYY-MM-DD) this coaching briefing refers to.",
    )
    explanation: str
    recommendations: list[CoachRecommendationResponse]
    metrics_used: list[str]
    confidence: float = Field(ge=0.0, le=1.0)


def _to_response_model(response: CoachResponse, timezone: str) -> CoachResponseModel:
    today = today_local(timezone)
    return CoachResponseModel(
        meta=build_response_meta(timezone=timezone, data_date=today),
        briefing_for_date=today.isoformat(),
        explanation=response.explanation,
        recommendations=[
            CoachRecommendationResponse(
                category=item.category,
                action=item.action,
                rationale=item.rationale,
                metric_citations=list(item.metric_citations),
            )
            for item in response.recommendations
        ],
        metrics_used=list(response.metrics_used),
        confidence=response.confidence,
    )


async def _default_user_id(
    services: RequestServices,
    container: Container,
) -> UUID:
    user = await services.user_repo.get_or_create_default(container.settings.default_user_email)
    return user.id


@router.post("/coach/explain-today", response_model=CoachResponseModel)
async def explain_today(
    services: RequestServices = Depends(get_request_services),
    container: Container = Depends(get_container),
) -> CoachResponseModel:
    user_id = await _default_user_id(services, container)
    response = await services.coach_service.explain_today(user_id)
    return _to_response_model(response, container.settings.app_timezone)


@router.post("/coach/daily-plan", response_model=CoachResponseModel)
async def daily_plan(
    services: RequestServices = Depends(get_request_services),
    container: Container = Depends(get_container),
) -> CoachResponseModel:
    user_id = await _default_user_id(services, container)
    response = await services.coach_service.generate_daily_training_plan(user_id)
    return _to_response_model(response, container.settings.app_timezone)


@router.post("/coach/weekly-summary", response_model=CoachResponseModel)
async def weekly_summary(
    services: RequestServices = Depends(get_request_services),
    container: Container = Depends(get_container),
) -> CoachResponseModel:
    user_id = await _default_user_id(services, container)
    response = await services.coach_service.summarize_last_week(user_id)
    return _to_response_model(response, container.settings.app_timezone)
