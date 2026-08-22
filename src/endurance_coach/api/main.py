"""FastAPI application entrypoint."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from pydantic import BaseModel

from endurance_coach import __version__
from endurance_coach.api.deps import get_container
from endurance_coach.api.middleware import ApiKeyMiddleware
from endurance_coach.di.container import Container
from endurance_coach.api.schemas.temporal import ResponseMeta, build_response_meta
from endurance_coach.api.routes.analytics import router as analytics_router
from endurance_coach.api.routes.activities import router as activities_router
from endurance_coach.api.routes.coach import router as coach_router
from endurance_coach.api.routes.garmin import router as garmin_router
from endurance_coach.api.routes.process import router as process_router
from endurance_coach.api.routes.strava import router as strava_router
from endurance_coach.api.routes.samsung import router as samsung_router
from endurance_coach.api.routes.sync import router as sync_router
from endurance_coach.di.container import create_container


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.container = create_container()
    yield
    await app.state.container.shutdown()


app = FastAPI(
    title="Endurance Coach API",
    version=__version__,
    description="Self-hostable endurance coaching platform API",
    lifespan=lifespan,
)

app.add_middleware(ApiKeyMiddleware)

app.include_router(sync_router)
app.include_router(strava_router)
app.include_router(samsung_router)
app.include_router(garmin_router)
app.include_router(activities_router)
app.include_router(process_router)
app.include_router(analytics_router)
app.include_router(coach_router)


class HealthResponse(BaseModel):
    meta: ResponseMeta
    status: str
    version: str


@app.get("/health", response_model=HealthResponse)
async def health(container: Container = Depends(get_container)) -> HealthResponse:
    return HealthResponse(
        meta=build_response_meta(timezone=container.settings.app_timezone),
        status="ok",
        version=__version__,
    )


def run() -> None:
    import uvicorn

    from endurance_coach.config import get_settings

    settings = get_settings()
    uvicorn.run(
        "endurance_coach.api.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.app_debug,
    )
