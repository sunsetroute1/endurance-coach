"""Structured logging helpers for the MCP server."""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from mcp.server.fastmcp.exceptions import ToolError

logger = logging.getLogger("endurance_coach.mcp")

T = TypeVar("T")


def configure_mcp_logging(level: str = "INFO") -> None:
    """Ensure the MCP logger emits to stderr with a stable format."""
    root = logging.getLogger("endurance_coach")
    if not root.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)s [%(name)s] %(message)s",
            )
        )
        root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))


def log_event(event: str, **fields: Any) -> None:
    extras = " ".join(f"{key}={value!r}" for key, value in fields.items())
    if extras:
        logger.info("%s %s", event, extras)
    else:
        logger.info("%s", event)


async def invoke_tool(
    tool_name: str,
    call: Callable[[], Awaitable[T]],
) -> T:
    """Run a tool body with latency logging; convert failures to ToolError."""
    started = time.perf_counter()
    log_event("tool_invoke_start", tool=tool_name)
    try:
        result = await call()
    except ToolError:
        elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
        log_event("tool_invoke_error", tool=tool_name, latency_ms=elapsed_ms)
        raise
    except Exception as exc:
        elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
        logger.exception(
            "tool_invoke_unhandled tool=%s latency_ms=%s error=%s",
            tool_name,
            elapsed_ms,
            exc,
        )
        raise ToolError(
            f"{tool_name} failed: {exc}. Tools remain registered; retry after the "
            "data layer recovers."
        ) from exc
    elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
    log_event("tool_invoke_ok", tool=tool_name, latency_ms=elapsed_ms)
    return result
