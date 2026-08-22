"""Regression: same ClientSession supports multiple tool calls (stateful HTTP)."""

from __future__ import annotations

import json

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from endurance_coach.config import get_settings


@pytest.mark.asyncio
async def test_same_session_two_tool_calls() -> None:
    """Stateful protocol: initialize once, then two tools/call in the same session."""
    settings = get_settings()
    token = settings.api_secret_key
    if not token:
        pytest.skip("API_SECRET_KEY not configured")

    url = f"http://127.0.0.1:{settings.mcp_port}/mcp"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json, text/event-stream",
    }

    async with httpx.AsyncClient(headers=headers, timeout=httpx.Timeout(60.0)) as http:
        async with streamable_http_client(url, http_client=http) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                names = {tool.name for tool in tools.tools}
                assert "get_recent_activities" in names
                assert "get_detailed_activity" in names

                recent = await session.call_tool(
                    "get_recent_activities",
                    {
                        "days": 7,
                        "start": 0,
                        "limit": 3,
                        "activitytype": None,
                        "summary_only": True,
                        "include_metrics": True,
                    },
                )
                assert not recent.isError, (
                    recent.content[0].text if recent.content else "get_recent_activities failed"
                )
                recent_data = json.loads(recent.content[0].text)
                assert "activities" in recent_data

                detail = await session.call_tool(
                    "get_detailed_activity",
                    {"target_date": "2026-08-20"},
                )
                assert not detail.isError, (
                    detail.content[0].text if detail.content else "get_detailed_activity failed"
                )
                detail_data = json.loads(detail.content[0].text)
                assert detail_data.get("date") == "2026-08-20"


@pytest.mark.asyncio
@pytest.mark.skipif(
    not get_settings().mcp_stateless_http,
    reason="Split-session invoke requires MCP_STATELESS_HTTP=true",
)
async def test_stateless_call_after_separate_discovery_session() -> None:
    """
    Optional: list tools in one HTTP session, call a tool in another without
    reusing mcp-session-id. Only meaningful when the server is stateless.
    """
    settings = get_settings()
    token = settings.api_secret_key
    if not token:
        pytest.skip("API_SECRET_KEY not configured")

    url = f"http://127.0.0.1:{settings.mcp_port}/mcp"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json, text/event-stream",
    }

    async with httpx.AsyncClient(headers=headers, timeout=httpx.Timeout(60.0)) as http_a:
        async with streamable_http_client(url, http_client=http_a) as (read_a, write_a, _):
            async with ClientSession(read_a, write_a) as session_a:
                await session_a.initialize()
                tools = await session_a.list_tools()
                names = {tool.name for tool in tools.tools}
                assert "get_recent_activities" in names

    async with httpx.AsyncClient(headers=headers, timeout=httpx.Timeout(60.0)) as http_b:
        async with streamable_http_client(url, http_client=http_b) as (read_b, write_b, _):
            async with ClientSession(read_b, write_b) as session_b:
                await session_b.initialize()
                recent = await session_b.call_tool(
                    "get_recent_activities",
                    {"days": 7, "summary_only": True, "limit": 3},
                )
                assert not recent.isError, (
                    recent.content[0].text if recent.content else "get_recent_activities failed"
                )
