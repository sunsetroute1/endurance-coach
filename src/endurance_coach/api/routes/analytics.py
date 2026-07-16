"""Analytics API routes."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from endurance_coach.api.deps import RequestServices, get_container, get_request_services
from endurance_coach.api.schemas.temporal import ResponseMeta, build_response_meta
from endurance_coach.di.container import Container
from endurance_coach.domain.enums import MetricFamily

router = APIRouter(prefix="/api/v1", tags=["analytics"])


class ComputeAnalyticsResponse(BaseModel):
    meta: ResponseMeta
    computed_at: datetime = Field(
        description="ISO-8601 UTC timestamp when metrics were computed.",
    )
    families: list[str]
    metric_counts: dict[str, int]


class MetricSnapshotResponse(BaseModel):
    meta: ResponseMeta
    family: MetricFamily
    metrics_as_of: datetime = Field(
        description="ISO-8601 UTC timestamp when these metrics were last computed.",
    )
    metrics: dict[str, float]
    as_of: datetime = Field(
        description="Deprecated alias for metrics_as_of; kept for backward compatibility.",
    )


@router.post("/analytics/compute", response_model=ComputeAnalyticsResponse)
async def compute_analytics(
    services: RequestServices = Depends(get_request_services),
    container: Container = Depends(get_container),
) -> ComputeAnalyticsResponse:
    user = await services.user_repo.get_or_create_default(container.settings.default_user_email)
    snapshots = await services.metric_engine.compute_all(user.id)
    computed_at = max((snapshot.as_of for snapshot in snapshots), default=datetime.now(UTC))

    return ComputeAnalyticsResponse(
        meta=build_response_meta(timezone=container.settings.app_timezone),
        computed_at=computed_at,
        families=[snapshot.family.value for snapshot in snapshots],
        metric_counts={snapshot.family.value: len(snapshot.metrics) for snapshot in snapshots},
    )


@router.get("/analytics/{family}", response_model=MetricSnapshotResponse)
async def get_latest_metrics(
    family: MetricFamily,
    services: RequestServices = Depends(get_request_services),
    container: Container = Depends(get_container),
) -> MetricSnapshotResponse:
    user = await services.user_repo.get_or_create_default(container.settings.default_user_email)
    snapshot = await services.metric_engine.get_latest_snapshot(user.id, family)
    if snapshot is None:
        raise HTTPException(status_code=404, detail=f"No computed metrics for {family.value}")

    return MetricSnapshotResponse(
        meta=build_response_meta(timezone=container.settings.app_timezone),
        family=snapshot.family,
        metrics_as_of=snapshot.as_of,
        metrics={metric.key: metric.value for metric in snapshot.metrics},
        as_of=snapshot.as_of,
    )
