"""MCP server entrypoint — exposes coaching tools via stdio or streamable-HTTP."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import date
from typing import Annotated, TypeVar

from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import Context, FastMCP
from mcp.types import ToolAnnotations
from pydantic import AnyHttpUrl, Field, WithJsonSchema
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from endurance_coach.config import get_settings
from endurance_coach.di.container import Container, create_container
from endurance_coach.mcp.deps import MCPRequestScope, mcp_request_scope
from endurance_coach.mcp.health import build_health_payload
from endurance_coach.mcp.http_middleware import install_mcp_http_middleware
from endurance_coach.mcp.logging_utils import configure_mcp_logging, invoke_tool, log_event, logger
from endurance_coach.mcp.registry import list_registered_tool_names, missing_required_tools
from endurance_coach.security.api_key import StaticBearerTokenVerifier
from endurance_coach.security.mcp_transport import build_mcp_transport_security_settings

T = TypeVar("T")

# Disable structured output schemas — loose `additionalProperties: true` output
# schemas and `anyOf`/`null` input unions have caused connector clients
# (notably Perplexity) to show CONNECTED but refuse to bind/call tools.
_TOOL_KW = {
    "structured_output": False,
    "annotations": ToolAnnotations(readOnlyHint=True, openWorldHint=False),
}


@dataclass
class AppLifespan:
    container: Container


def _parse_optional_date(value: str | None) -> date | None:
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    return date.fromisoformat(cleaned)


def _optional_str(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _nullable_str_schema(description: str) -> dict[str, object]:
    """JSON Schema for optional strings: type [string, null], default null."""
    return {
        "type": ["string", "null"],
        "default": None,
        "description": description,
    }


@asynccontextmanager
async def lifespan(_server: FastMCP) -> AsyncIterator[AppLifespan]:
    """Per-session lifespan. Container/engine creation does not require DB connect.

    Tool registration happens at import time and is independent of this lifespan.
    """
    log_event("mcp_session_lifespan_start")
    container = create_container()
    try:
        yield AppLifespan(container=container)
    finally:
        await container.shutdown()
        log_event("mcp_session_lifespan_stop")


def _extra_origins(settings_value: str) -> tuple[str, ...]:
    return tuple(
        part.strip()
        for part in settings_value.split(",")
        if part.strip()
    )


def _build_mcp_server() -> FastMCP:
    settings = get_settings()
    configure_mcp_logging(settings.log_level)
    token_verifier = None
    auth = None
    if settings.api_secret_key:
        token_verifier = StaticBearerTokenVerifier(settings.api_secret_key)
        public_base = settings.public_base_url.rstrip("/")
        # FastMCP requires AuthSettings whenever token_verifier is set, but we
        # only support static Bearer API keys. Advertising a resource-server
        # metadata URL makes connectors attempt OAuth against a non-existent AS.
        auth = AuthSettings(
            issuer_url=AnyHttpUrl(public_base),
            resource_server_url=(
                AnyHttpUrl(f"{public_base}/mcp")
                if settings.mcp_advertise_oauth_resource
                else None
            ),
            required_scopes=["mcp:tools"],
        )

    transport_security = build_mcp_transport_security_settings(
        settings.public_base_url,
        mcp_port=settings.mcp_port,
        extra_allowed_origins=_extra_origins(settings.mcp_allowed_origins),
    )

    server = FastMCP(
        "endurance-coach",
        instructions=(
            "Endurance Coach MCP server. Tools expose pre-computed training metrics, "
            "recovery state, and deterministic coaching briefings. Tool discovery does "
            "not require database connectivity. Run /api/v1/analytics/compute on the "
            "API before expecting fresh coaching metrics."
        ),
        lifespan=lifespan,
        token_verifier=token_verifier,
        auth=auth,
        transport_security=transport_security,
        # Stateless HTTP is the default for Perplexity-compatible connectors; each
        # request is self-contained. Stateful sessions are optional via
        # MCP_STATELESS_HTTP=false (sticky mcp-session-id clients).
        # json_response avoids Accept 406s when clients omit text/event-stream.
        stateless_http=settings.mcp_stateless_http,
        json_response=settings.mcp_json_response,
    )
    log_event(
        "mcp_server_built",
        transport=settings.mcp_transport,
        auth_enabled=bool(settings.api_secret_key),
        public_base_url=settings.public_base_url,
        stateless_http=settings.mcp_stateless_http,
        json_response=settings.mcp_json_response,
        oauth_resource_advertised=settings.mcp_advertise_oauth_resource,
        session_idle_timeout_seconds=settings.mcp_session_idle_timeout_seconds,
    )
    return server


mcp = _build_mcp_server()


def _container(ctx: Context) -> Container:
    return ctx.request_context.lifespan_context.container


async def _with_scope(
    ctx: Context,
    tool_name: str,
    call: Callable[[MCPRequestScope], Awaitable[T]],
) -> T:
    async def _run() -> T:
        async with mcp_request_scope(_container(ctx)) as scope:
            return await call(scope)

    return await invoke_tool(tool_name, _run)


@mcp.custom_route("/health", methods=["GET"])
async def health_liveness(_request: Request) -> Response:
    """Liveness: process up + static tool registry non-empty (no DB required)."""
    registry_tools = list_registered_tool_names(mcp)
    missing = missing_required_tools(registry_tools)
    payload = {
        "status": "ok" if registry_tools and not missing else "error",
        "discovery_ok": bool(registry_tools) and not missing,
        "registry": {
            "ok": bool(registry_tools) and not missing,
            "tool_count": len(registry_tools),
            "tools": registry_tools,
            "missing_required": missing,
        },
    }
    log_event("health_liveness", status=payload["status"], tool_count=len(registry_tools))
    return JSONResponse(payload, status_code=200 if payload["discovery_ok"] else 503)


@mcp.custom_route("/ready", methods=["GET"])
async def health_readiness(_request: Request) -> Response:
    """Readiness: registry + database + activities table probe."""
    container: Container | None = None
    try:
        container = create_container()
        payload = await build_health_payload(mcp, container, check_database=True)
    except Exception as exc:
        logger.exception("ready_check_failed error=%s", exc)
        registry_tools = list_registered_tool_names(mcp)
        missing = missing_required_tools(registry_tools)
        payload = {
            "status": "degraded" if registry_tools and not missing else "error",
            "discovery_ok": bool(registry_tools) and not missing,
            "ready_for_tool_calls": False,
            "registry": {
                "ok": bool(registry_tools) and not missing,
                "tool_count": len(registry_tools),
                "tools": registry_tools,
                "missing_required": missing,
            },
            "database": {"ok": False, "error": str(exc)},
        }
    finally:
        if container is not None:
            await container.shutdown()

    log_event(
        "health_readiness",
        status=payload.get("status"),
        discovery_ok=payload.get("discovery_ok"),
        ready=payload.get("ready_for_tool_calls"),
    )
    # Discovery stays available even when DB is down (503 only if registry broken).
    status_code = 200 if payload.get("discovery_ok") else 503
    return JSONResponse(payload, status_code=status_code)


@mcp.tool(**_TOOL_KW)
async def get_recent_activities(
    days: Annotated[int, Field(description="Lookback window in days.", ge=1)] = 7,
    start: Annotated[
        int,
        Field(description="Zero-based pagination offset into the filtered activity list.", ge=0),
    ] = 0,
    limit: Annotated[
        int,
        Field(
            description="Page size. Max 500 in summary_only mode, max 100 in full mode.",
            ge=1,
        ),
    ] = 50,
    activitytype: Annotated[
        str | None,
        Field(
            default=None,
            description="Optional activity-type filter (case-insensitive substring).",
        ),
        WithJsonSchema(
            _nullable_str_schema(
                "Optional activity-type filter (case-insensitive substring)."
            )
        ),
    ] = None,
    summary_only: Annotated[
        bool,
        Field(
            description=(
                "When true (default), return compact rows with ids, date, type, duration, "
                "distance, avg HR, elevation, and training load."
            ),
        ),
    ] = True,
    include_metrics: Annotated[
        bool,
        Field(
            description=(
                "When true (default), attach coaching_metrics from stored Garmin payloads."
            ),
        ),
    ] = True,
    *,
    ctx: Context,
) -> dict[str, object]:
    """Return paginated activity rows for the last N days.

    Prefer summary_only=true when scanning many months. Response always includes
    activities_today for the current calendar day in the app timezone.
    """
    return await _with_scope(
        ctx,
        "get_recent_activities",
        lambda scope: scope.service.get_recent_activities(
            scope.user_id,
            days=days,
            start=start,
            limit=limit,
            activitytype=_optional_str(activitytype),
            summary_only=summary_only,
            include_metrics=include_metrics,
        ),
    )


@mcp.tool(**_TOOL_KW)
async def get_sleep_summary(
    target_date: Annotated[
        str | None,
        Field(default=None, description="Optional calendar date YYYY-MM-DD. Null = today."),
        WithJsonSchema(
            _nullable_str_schema("Optional calendar date YYYY-MM-DD. Null = today.")
        ),
    ] = None,
    *,
    ctx: Context,
) -> dict[str, object]:
    """Return sleep score, stages, recent nights, and sleep debt."""
    return await _with_scope(
        ctx,
        "get_sleep_summary",
        lambda scope: scope.service.get_sleep_summary(
            scope.user_id,
            target_date=_parse_optional_date(target_date),
        ),
    )


@mcp.tool(**_TOOL_KW)
async def get_hrv_trend(
    days: Annotated[int, Field(description="Lookback window in days.", ge=1)] = 14,
    rollup: Annotated[
        str,
        Field(description='Rollup mode: "daily" (default) or "weekly" (Mon–Sun averages).'),
    ] = "daily",
    *,
    ctx: Context,
) -> dict[str, object]:
    """Return HRV readings and deviation from baseline over the window."""
    return await _with_scope(
        ctx,
        "get_hrv_trend",
        lambda scope: scope.service.get_hrv_trend(scope.user_id, days=days, rollup=rollup),
    )


@mcp.tool(**_TOOL_KW)
async def get_weekly_aggregates(
    weeks: Annotated[
        int,
        Field(
            description=(
                "Number of Mon–Sun weeks to return when start_date is omitted "
                "(max 520, oldest first)."
            ),
            ge=1,
            le=520,
        ),
    ] = 12,
    start_date: Annotated[
        str | None,
        Field(default=None, description="Optional range start YYYY-MM-DD."),
        WithJsonSchema(_nullable_str_schema("Optional range start YYYY-MM-DD.")),
    ] = None,
    end_date: Annotated[
        str | None,
        Field(default=None, description="Optional range end YYYY-MM-DD."),
        WithJsonSchema(_nullable_str_schema("Optional range end YYYY-MM-DD.")),
    ] = None,
    *,
    ctx: Context,
) -> dict[str, object]:
    """Return Mon–Sun weekly rollups for training load, HRV, sleep, and daily health."""
    return await _with_scope(
        ctx,
        "get_weekly_aggregates",
        lambda scope: scope.service.get_weekly_aggregates(
            scope.user_id,
            weeks=weeks,
            start_date=_parse_optional_date(start_date),
            end_date=_parse_optional_date(end_date),
        ),
    )


@mcp.tool(**_TOOL_KW)
async def get_top_trail_efforts(
    days: Annotated[int, Field(description="Lookback window when start/end dates omitted.", ge=1)] = 90,
    start_date: Annotated[
        str | None,
        Field(default=None, description="Optional range start YYYY-MM-DD."),
        WithJsonSchema(_nullable_str_schema("Optional range start YYYY-MM-DD.")),
    ] = None,
    end_date: Annotated[
        str | None,
        Field(default=None, description="Optional range end YYYY-MM-DD."),
        WithJsonSchema(_nullable_str_schema("Optional range end YYYY-MM-DD.")),
    ] = None,
    limit: Annotated[int, Field(description="Top N trail efforts to return (max 50).", ge=1)] = 10,
    rank_by: Annotated[
        str,
        Field(
            description=(
                'Ranking metric: "vert_duration", "training_load", or "pace_terrain".'
            ),
        ),
    ] = "vert_duration",
    *,
    ctx: Context,
) -> dict[str, object]:
    """List top trail runs in a date range, ranked by vert/hour, load, or terrain-adjusted pace."""
    return await _with_scope(
        ctx,
        "get_top_trail_efforts",
        lambda scope: scope.service.get_top_trail_efforts(
            scope.user_id,
            days=days,
            start_date=_parse_optional_date(start_date),
            end_date=_parse_optional_date(end_date),
            limit=limit,
            rank_by=rank_by,
        ),
    )


@mcp.tool(**_TOOL_KW)
async def get_training_readiness(
    target_date: Annotated[
        str | None,
        Field(default=None, description="Optional calendar date YYYY-MM-DD. Null = today."),
        WithJsonSchema(
            _nullable_str_schema("Optional calendar date YYYY-MM-DD. Null = today.")
        ),
    ] = None,
    *,
    ctx: Context,
) -> dict[str, object]:
    """Return Garmin training readiness score and components."""
    return await _with_scope(
        ctx,
        "get_training_readiness",
        lambda scope: scope.service.get_training_readiness(
            scope.user_id,
            target_date=_parse_optional_date(target_date),
        ),
    )


@mcp.tool(**_TOOL_KW)
async def get_recovery_state(ctx: Context) -> dict[str, object]:
    """Return recovery score, fatigue, sleep debt, and HRV deviation."""
    return await _with_scope(
        ctx,
        "get_recovery_state",
        lambda scope: scope.service.get_recovery_state(scope.user_id),
    )


@mcp.tool(**_TOOL_KW)
async def get_weekly_load(ctx: Context) -> dict[str, object]:
    """Return CTL, ATL, TSB, ACWR, and weekly load metrics."""
    return await _with_scope(
        ctx,
        "get_weekly_load",
        lambda scope: scope.service.get_weekly_load(scope.user_id),
    )


@mcp.tool(**_TOOL_KW)
async def get_injury_risk(ctx: Context) -> dict[str, object]:
    """Return injury risk level, score, and contributing factors."""
    return await _with_scope(
        ctx,
        "get_injury_risk",
        lambda scope: scope.service.get_injury_risk(scope.user_id),
    )


@mcp.tool(**_TOOL_KW)
async def get_daily_garmin_readiness(
    target_date: Annotated[
        str | None,
        Field(default=None, description="Optional calendar date YYYY-MM-DD. Null = today."),
        WithJsonSchema(
            _nullable_str_schema("Optional calendar date YYYY-MM-DD. Null = today.")
        ),
    ] = None,
    *,
    ctx: Context,
) -> dict[str, object]:
    """Return daily Garmin readiness metrics when required morning fields are present."""
    return await _with_scope(
        ctx,
        "get_daily_garmin_readiness",
        lambda scope: scope.service.get_daily_garmin_readiness(
            scope.user_id,
            target_date=_parse_optional_date(target_date),
        ),
    )


@mcp.tool(**_TOOL_KW)
async def get_daily_recap(
    target_date: Annotated[
        str | None,
        Field(default=None, description="Optional calendar date YYYY-MM-DD. Null = today."),
        WithJsonSchema(
            _nullable_str_schema("Optional calendar date YYYY-MM-DD. Null = today.")
        ),
    ] = None,
    *,
    ctx: Context,
) -> dict[str, object]:
    """Return Garmin's evening daily recap for a calendar date."""
    return await _with_scope(
        ctx,
        "get_daily_recap",
        lambda scope: scope.service.get_daily_recap(
            scope.user_id,
            target_date=_parse_optional_date(target_date),
        ),
    )


@mcp.tool(**_TOOL_KW)
async def get_detailed_activity(
    target_date: Annotated[
        str | None,
        Field(
            default=None,
            description=(
                "Optional calendar date YYYY-MM-DD in the app timezone. "
                "Null means unset (use activity_id or most recent)."
            ),
        ),
        WithJsonSchema(
            _nullable_str_schema(
                "Optional calendar date YYYY-MM-DD in the app timezone. "
                "Null means unset (use activity_id or most recent)."
            )
        ),
    ] = None,
    activity_id: Annotated[
        str | None,
        Field(
            default=None,
            description=(
                "Activity id from get_recent_activities: internal UUID (`id`) or Garmin "
                "`provider_activity_id`. Null = use target_date or most recent activity."
            ),
        ),
        WithJsonSchema(
            _nullable_str_schema(
                "Activity id from get_recent_activities: internal UUID (`id`) or Garmin "
                "`provider_activity_id`. Null = use target_date or most recent activity."
            )
        ),
    ] = None,
    *,
    ctx: Context,
) -> dict[str, object]:
    """Return full coaching metrics for a run by date or activity id.

    Accepts internal UUID or Garmin provider id. Includes running dynamics, power,
    calories, HR zones, training effect, and per-lap splits when available.
    """
    parsed_date = _parse_optional_date(target_date)
    parsed_id = _optional_str(activity_id)
    return await _with_scope(
        ctx,
        "get_detailed_activity",
        lambda scope: scope.service.get_detailed_activity(
            scope.user_id,
            target_date=parsed_date,
            activity_id=parsed_id,
        ),
    )


@mcp.tool(**_TOOL_KW)
async def generate_daily_training_plan(
    ctx: Context,
) -> dict[str, object]:
    """Return a structured daily training plan from pre-computed metrics."""
    return await _with_scope(
        ctx,
        "generate_daily_training_plan",
        lambda scope: scope.service.generate_daily_training_plan(scope.user_id),
    )


@mcp.tool(**_TOOL_KW)
async def explain_today(ctx: Context) -> dict[str, object]:
    """Return a deterministic daily briefing from pre-computed metrics."""
    return await _with_scope(
        ctx,
        "explain_today",
        lambda scope: scope.service.explain_today(scope.user_id),
    )


@mcp.tool(**_TOOL_KW)
async def summarize_last_week(ctx: Context) -> dict[str, object]:
    """Return a weekly summary from activities and computed metrics."""
    return await _with_scope(
        ctx,
        "summarize_last_week",
        lambda scope: scope.service.summarize_last_week(scope.user_id),
    )


def run() -> None:
    settings = get_settings()
    configure_mcp_logging(settings.log_level)
    registered = list_registered_tool_names(mcp)
    missing = missing_required_tools(registered)
    log_event(
        "mcp_process_start",
        transport=settings.mcp_transport,
        host=settings.mcp_host,
        port=settings.mcp_port,
        tool_count=len(registered),
        tools=json.dumps(registered),
        missing_required=json.dumps(missing),
    )
    if missing:
        logger.error("mcp_registry_incomplete missing=%s", missing)
        raise SystemExit(f"MCP tool registry missing required tools: {missing}")

    transport = settings.mcp_transport
    try:
        if transport == "sse":
            mcp.settings.host = settings.mcp_host
            mcp.settings.port = settings.mcp_port
            mcp.run(transport="sse")
            return
        if transport == "streamable-http":
            mcp.settings.host = settings.mcp_host
            mcp.settings.port = settings.mcp_port
            # FastMCP builds the Starlette app inside run_streamable_http_async.
            # Wrap streamable_http_app so OPTIONS/CORS and request logging sit
            # outside RequireAuthMiddleware (preflight has no Authorization).
            # Also apply session_idle_timeout when configured (FastMCP does not
            # expose it on the constructor; StreamableHTTPSessionManager does).
            _orig_streamable_http_app = mcp.streamable_http_app

            def _streamable_http_app_with_edge():
                app = _orig_streamable_http_app()
                idle = settings.mcp_session_idle_timeout_seconds
                if idle is not None and mcp._session_manager is not None:
                    # None = no idle reap (SDK default). Positive seconds = reap.
                    mcp._session_manager.session_idle_timeout = float(idle)
                return install_mcp_http_middleware(app)

            mcp.streamable_http_app = _streamable_http_app_with_edge  # type: ignore[method-assign]
            mcp.run(transport="streamable-http")
            return
        mcp.run(transport="stdio")
    finally:
        log_event("mcp_process_stop", transport=transport)
