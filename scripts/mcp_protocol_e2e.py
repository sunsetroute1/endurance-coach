#!/usr/bin/env python3
"""Standalone MCP protocol E2E: initialize → list → call → call × 50."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from endurance_coach.config import get_settings  # noqa: E402
from endurance_coach.mcp.registry import REQUIRED_MCP_TOOLS  # noqa: E402

_ITERATIONS = 50
_RECENT_ARGS = {
    "days": 7,
    "start": 0,
    "limit": 5,
    "activitytype": None,
    "summary_only": True,
    "include_metrics": True,
}


def _load_api_secret() -> str | None:
    settings = get_settings()
    if settings.api_secret_key:
        return settings.api_secret_key
    env_secret = os.environ.get("API_SECRET_KEY")
    if env_secret:
        return env_secret
    env_path = ROOT / ".env"
    if env_path.is_file():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("API_SECRET_KEY="):
                value = line.split("=", 1)[1].strip().strip('"').strip("'")
                return value or None
    return None


def _mcp_url() -> str:
    settings = get_settings()
    base = (
        os.environ.get("PUBLIC_BASE_URL")
        or settings.public_base_url
        or "http://127.0.0.1:8080"
    ).rstrip("/")
    if base.endswith("/mcp"):
        return base
    return f"{base}/mcp"


def _text_payload(result) -> str:
    if not result.content:
        return ""
    first = result.content[0]
    return getattr(first, "text", "") or ""


async def _run_once(url: str, token: str) -> None:
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json, text/event-stream",
    }
    async with httpx.AsyncClient(headers=headers, timeout=httpx.Timeout(120.0)) as http:
        async with streamable_http_client(url, http_client=http) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                await asyncio.sleep(0.05)

                tools = await session.list_tools()
                names = {tool.name for tool in tools.tools}
                missing = [name for name in REQUIRED_MCP_TOOLS if name not in names]
                if missing:
                    raise AssertionError(f"missing tools: {missing}")

                recent = await session.call_tool("get_recent_activities", dict(_RECENT_ARGS))
                if recent.isError:
                    raise AssertionError(_text_payload(recent)[:500] or "get_recent_activities error")
                recent_data = json.loads(_text_payload(recent))
                if "activities" not in recent_data:
                    raise AssertionError("get_recent_activities missing activities key")

                detail = await session.call_tool(
                    "get_detailed_activity",
                    {"target_date": "2026-08-20"},
                )
                if detail.isError:
                    raise AssertionError(_text_payload(detail)[:500] or "get_detailed_activity error")
                detail_data = json.loads(_text_payload(detail))
                if detail_data.get("date") != "2026-08-20":
                    raise AssertionError(f"unexpected detail date: {detail_data.get('date')!r}")


async def main() -> int:
    token = _load_api_secret()
    if not token:
        print("FAIL: API_SECRET_KEY not configured", file=sys.stderr)
        return 2

    url = _mcp_url()
    print(f"MCP protocol E2E against {url} ({_ITERATIONS} iterations)")
    failures = 0
    for i in range(1, _ITERATIONS + 1):
        try:
            await _run_once(url, token)
            print(f"PASS iteration {i}/{_ITERATIONS}")
        except Exception as exc:
            failures += 1
            print(f"FAIL iteration {i}/{_ITERATIONS}: {exc}", file=sys.stderr)
        await asyncio.sleep(0.05)

    if failures:
        print(f"FAILED: {failures}/{_ITERATIONS} iterations", file=sys.stderr)
        return 1
    print(f"OK: {_ITERATIONS}/{_ITERATIONS} iterations passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
