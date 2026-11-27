"""Static MCP tool registry — independent of database availability."""

from __future__ import annotations

REQUIRED_MCP_TOOLS: tuple[str, ...] = (
    "get_recent_activities",
    "get_detailed_activity",
    "get_training_readiness",
    "get_recovery_state",
    "get_weekly_load",
    "get_injury_risk",
    "get_sleep_summary",
    "get_hrv_trend",
    "get_daily_garmin_readiness",
    "get_daily_recap",
    "generate_daily_training_plan",
    "explain_today",
    "summarize_last_week",
)

# Also registered (analytics helpers); kept discoverable but not required for readiness.
OPTIONAL_MCP_TOOLS: tuple[str, ...] = (
    "get_weekly_aggregates",
    "get_top_trail_efforts",
    "get_garmin_performance",
    "get_garmin_performance_trends",
    "get_garmin_data_quality",
    "get_garmin_activity_details",
    "get_garmin_activity_efficiency",
    "get_garmin_activity_comparison",
    "get_garmin_activity_backfill_status",
    "get_garmin_activity_longitudinal",
    "get_running_training_plan",
)


def list_registered_tool_names(mcp: object) -> list[str]:
    """Return sorted tool names from a FastMCP instance without touching the DB."""
    manager = getattr(mcp, "_tool_manager", None)
    if manager is None:
        return []
    return sorted(tool.name for tool in manager.list_tools())


def missing_required_tools(registered: list[str] | set[str]) -> list[str]:
    present = set(registered)
    return [name for name in REQUIRED_MCP_TOOLS if name not in present]
