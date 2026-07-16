"""Process API routes."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from endurance_coach.api.deps import RequestServices, get_container, get_request_services
from endurance_coach.api.schemas.temporal import ResponseMeta, build_response_meta
from endurance_coach.di.container import Container
from endurance_coach.domain.enums import ResourceType

router = APIRouter(prefix="/api/v1", tags=["process"])


class ProcessRequest(BaseModel):
    resource_type: ResourceType | None = None
    limit: int = 100


class ProcessResponse(BaseModel):
    meta: ResponseMeta
    processed: dict[str, int]


@router.post("/process", response_model=ProcessResponse)
async def process_pending(
    body: ProcessRequest,
    services: RequestServices = Depends(get_request_services),
    container: Container = Depends(get_container),
) -> ProcessResponse:
    user = await services.user_repo.get_or_create_default(container.settings.default_user_email)

    if body.resource_type is not None:
        count = await services.processor_pipeline.process_pending(
            user.id,
            body.resource_type,
            body.limit,
        )
        return ProcessResponse(
            meta=build_response_meta(timezone=container.settings.app_timezone),
            processed={body.resource_type.value: count},
        )

    results = await services.processor_pipeline.process_all_pending(user.id, body.limit)
    return ProcessResponse(
        meta=build_response_meta(timezone=container.settings.app_timezone),
        processed={key.value: value for key, value in results.items()},
    )
