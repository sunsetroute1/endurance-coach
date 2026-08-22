"""E2E MCP protocol: initialize → list → call → call, repeated 50x on public URL."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from endurance_coach.config import get_settings
from endurance_coach.mcp.registry import REQUIRED_MCP_TOOLS

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
    env_path = Path(__file__).resolve().parents[1] / ".env"
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


async def _run_protocol_once(url: str, token: str) -> None:
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json, text/event-stream",
    }
    async with httpx.AsyncClient(headers=headers, timeout=httpx.Timeout(120.0)) as http:
        async with streamable_http_client(url, http_client=http) as (read, write, _):
            async with ClientSession(read, write) as session:
                # ClientSession.initialize() sends initialize + notifications/initialized.
                await session.initialize()
                await asyncio.sleep(0.05)

                tools = await session.list_tools()
                names = {tool.name for tool in tools.tools}
                missing = [name for name in REQUIRED_MCP_TOOLS if name not in names]
                assert not missing, f"missing tools: {missing}"

                recent = await session.call_tool("get_recent_activities", dict(_RECENT_ARGS))
                assert not recent.isError, _text_payload(recent)[:500]
                recent_data = json.loads(_text_payload(recent))
                assert "activities" in recent_data

                detail = await session.call_tool(
                    "get_detailed_activity",
                    {"target_date": "2026-08-20"},
                )
                assert not detail.isError, _text_payload(detail)[:500]
                detail_data = json.loads(_text_payload(detail))
                assert detail_data.get("date") == "2026-08-20"


@pytest.mark.asyncio
async def test_mcp_protocol_e2e_fifty_same_session_cycles() -> None:
    """Full stateful protocol 50x: init → list → call → call on public /mcp."""
    token = _load_api_secret()
    if not token:
        pytest.skip("API_SECRET_KEY not configured")

    url = _mcp_url()
    for i in range(_ITERATIONS):
        await _run_protocol_once(url, token)
        await asyncio.sleep(0.05)


try:
    import pytest_timeout  # noqa: F401
except ImportError:
    pass
else:
    test_mcp_protocol_e2e_fifty_same_session_cycles = pytest.mark.timeout(600)(
        test_mcp_protocol_e2e_fifty_same_session_cycles
    )
