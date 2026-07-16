"""MCP server entrypoint — exposes coaching tools via stdio or SSE."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import date

from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import Context, FastMCP
from pydantic import AnyHttpUrl

from endurance_coach.config import get_settings
from endurance_coach.di.container import Container, create_container
from endurance_coach.mcp.deps import mcp_request_scope
from endurance_coach.security.api_key import StaticBearerTokenVerifier
from endurance_coach.security.mcp_transport import build_mcp_transport_security_settings


@dataclass
class AppLifespan:
    container: Container


@asynccontextmanager
async def lifespan(_server: FastMCP) -> AsyncIterator[AppLifespan]:
    container = create_container()
    try:
        yield AppLifespan(container=container)
    finally:
        await container.shutdown()


def _build_mcp_server() -> FastMCP:
    settings = get_settings()
    token_verifier = None
    auth = None
    if settings.api_secret_key:
        token_verifier = StaticBearerTokenVerifier(settings.api_secret_key)
        public_base = settings.public_base_url.rstrip("/")
        auth = AuthSettings(
            issuer_url=AnyHttpUrl(public_base),
            resource_server_url=AnyHttpUrl(f"{public_base}/mcp"),
            required_scopes=["mcp:tools"],
        )

    transport_security = build_mcp_transport_security_settings(
        settings.public_base_url,
        mcp_port=settings.mcp_port,
    )

    return FastMCP(
        "endurance-coach",
        instructions=(
            "Endurance Coach MCP server. Tools expose pre-computed training metrics, "
            "recovery state, and deterministic coaching briefings. Run "
            "/api/v1/analytics/compute on the API before expecting fresh metrics."
        ),
        lifespan=lifespan,
        token_verifier=token_verifier,
        auth=auth,
        transport_security=transport_security,
    )


mcp = _build_mcp_server()


def _container(ctx: Context) -> Container:
    return ctx.request_context.lifespan_context.container


@mcp.tool()
async def get_recent_activities(days: int = 7, ctx: Context | None = None) -> dict[str, object]:
    """Return normalized activity summaries for the last N days."""
    assert ctx is not None
    async with mcp_request_scope(_container(ctx)) as scope:
        return await scope.service.get_recent_activities(scope.user_id, days=days)


@mcp.tool()
async def get_sleep_summary(
    target_date: str | None = None,
    ctx: Context | None = None,
) -> dict[str, object]:
    """Return sleep score, stages, recent nights, and sleep debt."""
    assert ctx is not None
    parsed_date = date.fromisoformat(target_date) if target_date else None
    async with mcp_request_scope(_container(ctx)) as scope:
        return await scope.service.get_sleep_summary(scope.user_id, target_date=parsed_date)


@mcp.tool()
async def get_hrv_trend(days: int = 14, ctx: Context | None = None) -> dict[str, object]:
    """Return HRV readings and deviation from baseline over the window."""
    assert ctx is not None
    async with mcp_request_scope(_container(ctx)) as scope:
        return await scope.service.get_hrv_trend(scope.user_id, days=days)


@mcp.tool()
async def get_training_readiness(
    target_date: str | None = None,
    ctx: Context | None = None,
) -> dict[str, object]:
    """Return Garmin training readiness score and components."""
    assert ctx is not None
    parsed_date = date.fromisoformat(target_date) if target_date else None
    async with mcp_request_scope(_container(ctx)) as scope:
        return await scope.service.get_training_readiness(scope.user_id, target_date=parsed_date)


@mcp.tool()
async def get_recovery_state(ctx: Context | None = None) -> dict[str, object]:
    """Return recovery score, fatigue, sleep debt, and HRV deviation."""
    assert ctx is not None
    async with mcp_request_scope(_container(ctx)) as scope:
        return await scope.service.get_recovery_state(scope.user_id)


@mcp.tool()
async def get_weekly_load(ctx: Context | None = None) -> dict[str, object]:
    """Return CTL, ATL, TSB, ACWR, and weekly load metrics."""
    assert ctx is not None
    async with mcp_request_scope(_container(ctx)) as scope:
        return await scope.service.get_weekly_load(scope.user_id)


@mcp.tool()
async def get_injury_risk(ctx: Context | None = None) -> dict[str, object]:
    """Return injury risk level, score, and contributing factors."""
    assert ctx is not None
    async with mcp_request_scope(_container(ctx)) as scope:
        return await scope.service.get_injury_risk(scope.user_id)


@mcp.tool()
async def get_daily_garmin_readiness(
    target_date: str | None = None,
    ctx: Context | None = None,
) -> dict[str, object]:
    """Return daily Garmin readiness metrics when all required morning fields are present.

    Returns only a status payload (status=partial, missing_fields=[...]) until
    overnight HRV, morning RHR, 7-day HRV, target-date sleep, and last activity
    are available. Does not infer rest days or zero-fill missing values.
    """
    assert ctx is not None
    parsed_date = date.fromisoformat(target_date) if target_date else None
    async with mcp_request_scope(_container(ctx)) as scope:
        return await scope.service.get_daily_garmin_readiness(
            scope.user_id,
            target_date=parsed_date,
        )


@mcp.tool()
async def get_detailed_activity(
    target_date: str | None = None,
    activity_id: str | None = None,
    ctx: Context | None = None,
) -> dict[str, object]:
    """Return detailed metrics for a specific run by date or Garmin activity id."""
    assert ctx is not None
    parsed_date = date.fromisoformat(target_date) if target_date else None
    async with mcp_request_scope(_container(ctx)) as scope:
        return await scope.service.get_detailed_activity(
            scope.user_id,
            target_date=parsed_date,
            activity_id=activity_id,
        )


@mcp.tool()
async def generate_daily_training_plan(ctx: Context | None = None) -> dict[str, object]:
    """Return a structured daily training plan from pre-computed metrics."""
    assert ctx is not None
    async with mcp_request_scope(_container(ctx)) as scope:
        return await scope.service.generate_daily_training_plan(scope.user_id)


@mcp.tool()
async def explain_today(ctx: Context | None = None) -> dict[str, object]:
    """Return a deterministic daily briefing from pre-computed metrics."""
    assert ctx is not None
    async with mcp_request_scope(_container(ctx)) as scope:
        return await scope.service.explain_today(scope.user_id)


@mcp.tool()
async def summarize_last_week(ctx: Context | None = None) -> dict[str, object]:
    """Return a weekly summary from activities and computed metrics."""
    assert ctx is not None
    async with mcp_request_scope(_container(ctx)) as scope:
        return await scope.service.summarize_last_week(scope.user_id)


def run() -> None:
    settings = get_settings()
    transport = settings.mcp_transport
    if transport == "sse":
        mcp.settings.host = settings.mcp_host
        mcp.settings.port = settings.mcp_port
        mcp.run(transport="sse")
        return
    if transport == "streamable-http":
        mcp.settings.host = settings.mcp_host
        mcp.settings.port = settings.mcp_port
        mcp.run(transport="streamable-http")
        return
    mcp.run(transport="stdio")
