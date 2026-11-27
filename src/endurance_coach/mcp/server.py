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


async def _with_scope[T](
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
    days: Annotated[
        int,
        Field(description="Lookback window when start/end dates omitted.", ge=1),
    ] = 90,
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
async def get_running_training_plan(ctx: Context) -> dict[str, object]:
    """Return the active Garmin running plan and this week's workouts.

    Garmin Coach open-loop plans include the current week only. Workout
    steps are not on that payload.
    """
    return await _with_scope(
        ctx,
        "get_running_training_plan",
        lambda scope: scope.service.get_running_training_plan(scope.user_id),
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
async def get_garmin_performance(
    days: Annotated[
        int,
        Field(
            description="Calendar days to include ending today in the app timezone (default 28).",
            ge=1,
            le=365,
        ),
    ] = 28,
    *,
    ctx: Context,
) -> dict[str, object]:
    """Return stored Garmin Connect performance metrics (raw reads), not coaching scores.

    Data comes from persisted Garmin sync payloads only; nothing is recomputed here.
    Use only fields present in the response. Missing or empty sections mean the watch
    did not supply that metric in the stored sync.

    Often empty on Garmin Enduro 3: hill score, running economy, stamina curve, power
    curve, and weight.

    There is no separate time series for stamina zones, grade-adjusted pace workout
    targets, or Garmin Epic aggregation.

    Per-activity grade-adjusted pace and stamina fields already live on activity
    summaries (avgGradeAdjustedSpeed, beginPotentialStamina, endPotentialStamina,
    minAvailableStamina). Use get_recent_activities or get_detailed_activity for those.

    Do not invent or infer values that are not returned.
    """
    return await _with_scope(
        ctx,
        "get_garmin_performance",
        lambda scope: scope.service.get_garmin_performance(scope.user_id, days=days),
    )


@mcp.tool(**_TOOL_KW)
async def get_garmin_performance_trends(
    window_days: Annotated[
        int,
        Field(
            description="Comparison window in calendar days. Allowed: 7, 28, 90, 180, 365.",
            ge=7,
            le=365,
        ),
    ] = 28,
    *,
    ctx: Context,
) -> dict[str, object]:
    """Compare stored Garmin history across the current window and the previous window.

    Uses persisted rows only. It does not call Garmin Connect.

    Allowed windows are 7, 28, 90, 180, and 365 days. The previous period is the
    equal-length window immediately before the current one.

    Missing measurements are omitted, never filled with zero. Each block says whether
    the value is a Garmin measurement or a calculation, and includes the sample count.
    Percentage change is omitted when the previous value is missing or zero.

    VO2 max and lactate threshold are latest-known snapshots. This tool does not
    invent a history for them.

    Grade-adjusted pace is separate from actual pace. Comparable runs match distance
    within 15 percent and elevation gain within 25 percent, and only when both
    activities have grade-adjusted pace.

    A change or an association is not a cause.
    """
    if window_days not in (7, 28, 90, 180, 365):
        raise ValueError("window_days must be one of 7, 28, 90, 180, 365")
    return await _with_scope(
        ctx,
        "get_garmin_performance_trends",
        lambda scope: scope.service.get_garmin_performance_trends(
            scope.user_id,
            window_days=window_days,
        ),
    )


@mcp.tool(**_TOOL_KW)
async def get_garmin_data_quality(ctx: Context) -> dict[str, object]:
    """Explain stored Garmin coverage and why a trend may be insufficient.

    Reads the local database only. It does not call Garmin Connect.

    The report includes, for each stored metric, the earliest and latest day,
    populated days, missing date ranges, and duplicate rows. Activity fields
    show how many of the stored activities have elevation, training load,
    grade-adjusted speed, stamina, power, cadence, heart rate, pace, and
    temperature. HRV duplicates are split into same-value sync copies and
    dates that really have more than one measurement. Missing HRV is not zero.

    Recovery notes distinguish a metric Garmin can still return from a snapshot
    or a field the checked activity endpoints did not contain. full_sync is a
    365-day request. The default sync is 30 days. This report does not invent
    the days those syncs have not stored yet.
    """
    return await _with_scope(
        ctx,
        "get_garmin_data_quality",
        lambda scope: scope.service.get_garmin_data_quality(scope.user_id),
    )


@mcp.tool(**_TOOL_KW)
async def get_garmin_activity_details(
    provider_activity_id: Annotated[
        str,
        Field(description="Garmin activity id from get_recent_activities."),
    ],
    ctx: Context,
) -> dict[str, object]:
    """Return a decimated chart for one activity that has already been collected.

    Reads the local database only. It does not call Garmin Connect. The full
    chart stays stored. The response keeps every kth sample and does not
    interpolate missing points. Heart rate, power, cadence, and stamina are
    Garmin measurements. Descriptor factors are not applied.
    """
    return await _with_scope(
        ctx,
        "get_garmin_activity_details",
        lambda scope: scope.service.get_garmin_activity_details(
            scope.user_id,
            provider_activity_id,
        ),
    )


@mcp.tool(**_TOOL_KW)
async def get_garmin_activity_efficiency(
    provider_activity_id: Annotated[
        str,
        Field(description="Garmin activity id from get_recent_activities."),
    ],
    ctx: Context,
) -> dict[str, object]:
    """Separate drift, power fade, pace change, and stamina depletion.

    Cardiovascular drift is reported only when heart rate changes while power,
    or grade-adjusted speed when power is absent, stays within 5 percent.
    A fall in heart rate beside a fall in power is power fade, not improved
    efficiency. Speed drift is withheld when the climbing rate changes.
    Nulls and the minute after a pause are left out of the halves.
    Grade-adjusted speed is used only when the chart measured it.
    """
    return await _with_scope(
        ctx,
        "get_garmin_activity_efficiency",
        lambda scope: scope.service.get_garmin_activity_efficiency(
            scope.user_id,
            provider_activity_id,
        ),
    )


@mcp.tool(**_TOOL_KW)
async def get_garmin_activity_comparison(
    provider_activity_id: Annotated[
        str,
        Field(description="Garmin activity id from get_recent_activities."),
    ],
    ctx: Context,
) -> dict[str, object]:
    """Compare one collected activity with similar collected activities.

    Similar means distance within 15 percent and elevation gain within 25
    percent. Grade-adjusted speed is compared only when both charts measured it.
    """
    return await _with_scope(
        ctx,
        "get_garmin_activity_comparison",
        lambda scope: scope.service.get_garmin_activity_comparison(
            scope.user_id,
            provider_activity_id,
        ),
    )


@mcp.tool(**_TOOL_KW)
async def get_garmin_activity_longitudinal(ctx: Context) -> dict[str, object]:
    """Compare stored high-resolution charts across months.

    Reads the local database only. It does not call Garmin Connect and does
    not download remaining activities.

    Physiological comparisons use charts with power, grade-adjusted speed, and
    stamina at a median interval of 5 seconds or less, and only when distance,
    elevation, duration, and climbing rate all agree. Heart rate is compared
    only when power and grade-adjusted speed stay within 5 percent, so an
    easier pace is not read as improved fitness. A supported change needs at
    least four comparable runs in at least two months.

    Drift reasons and sample-quality flags are returned unchanged. A lower
    heart rate is not labeled as improved efficiency. Actual speed is not
    used as grade-adjusted speed. Missing values are omitted.
    """
    return await _with_scope(
        ctx,
        "get_garmin_activity_longitudinal",
        lambda scope: scope.service.get_garmin_activity_longitudinal(scope.user_id),
    )


@mcp.tool(**_TOOL_KW)
async def get_garmin_activity_backfill_status(ctx: Context) -> dict[str, object]:
    """Report activity-chart coverage, failures, and remaining outdoor runs.

    Reads the local database only. Eligible activities are Garmin runs and
    trail runs of at least 20 minutes. Collected and unsupported activities
    are not requested again. Failed activities can be retried.
    """
    return await _with_scope(
        ctx,
        "get_garmin_activity_backfill_status",
        lambda scope: scope.service.get_garmin_activity_backfill_status(scope.user_id),
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
    """Return daily Garmin readiness for one America/Denver calendar date.

    Sleep is the same row get_sleep_summary returns for that date. A required
    metric from another date is listed in stale_fields with its source date
    and is not copied into today's values. status is partial when a required
    target-day metric is missing.
    """
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
