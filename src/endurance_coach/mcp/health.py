"""MCP readiness / health checks (tool registry + optional DB probe)."""

from __future__ import annotations

import time
from typing import Any

from sqlalchemy import text

from endurance_coach.di.container import Container
from endurance_coach.mcp.logging_utils import log_event, logger
from endurance_coach.mcp.registry import list_registered_tool_names, missing_required_tools


async def probe_database(container: Container) -> dict[str, Any]:
    """Return DB connectivity details without unregistering tools on failure."""
    started = time.perf_counter()
    try:
        async with container.session_factory() as session:
            await session.execute(text("SELECT 1"))
            activity_count = (
                await session.execute(text("SELECT COUNT(*) FROM activities"))
            ).scalar_one()
        latency_ms = round((time.perf_counter() - started) * 1000, 1)
        log_event("db_probe_ok", latency_ms=latency_ms, activity_count=activity_count)
        return {
            "ok": True,
            "latency_ms": latency_ms,
            "activity_count": int(activity_count),
        }
    except Exception as exc:
        latency_ms = round((time.perf_counter() - started) * 1000, 1)
        logger.exception("db_probe_failed latency_ms=%s error=%s", latency_ms, exc)
        return {
            "ok": False,
            "latency_ms": latency_ms,
            "error": str(exc),
        }


def build_registry_status(mcp: object) -> dict[str, Any]:
    registered = list_registered_tool_names(mcp)
    missing = missing_required_tools(registered)
    return {
        "ok": not missing and len(registered) > 0,
        "tool_count": len(registered),
        "tools": registered,
        "missing_required": missing,
    }


async def build_health_payload(
    mcp: object,
    container: Container | None,
    *,
    check_database: bool = True,
) -> dict[str, Any]:
    """
    Health payload for connectors and Docker probes.

    Tool registry status is authoritative for discovery. Database failures make
    `ready` false for data calls but never clear the registered tool list.
    """
    registry = build_registry_status(mcp)
    database: dict[str, Any] | None = None
    if check_database and container is not None:
        database = await probe_database(container)
    elif check_database:
        database = {"ok": False, "error": "container_unavailable"}

    # Discovery-healthy when tools are registered, even if DB is down.
    discovery_ok = bool(registry["ok"])
    data_ok = bool(database and database.get("ok")) if database is not None else False
    status = "ok" if discovery_ok and (database is None or data_ok) else (
        "degraded" if discovery_ok else "error"
    )
    return {
        "status": status,
        "discovery_ok": discovery_ok,
        "ready_for_tool_calls": discovery_ok and (database is None or data_ok),
        "registry": registry,
        "database": database,
    }
