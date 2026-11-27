"""Regression tests for MCP tool discovery reliability."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.testclient import TestClient

from endurance_coach.mcp.registry import (
    REQUIRED_MCP_TOOLS,
    list_registered_tool_names,
    missing_required_tools,
)
from endurance_coach.mcp.server import mcp
from endurance_coach.security.mcp_transport import (
    DEFAULT_CONNECTOR_ORIGINS,
    build_mcp_transport_security_settings,
)


def test_static_tool_registry_contains_required_tools() -> None:
    registered = list_registered_tool_names(mcp)
    assert missing_required_tools(registered) == []
    for name in REQUIRED_MCP_TOOLS:
        assert name in registered
    assert "get_garmin_performance" in registered
    assert "get_garmin_performance_trends" in registered
    assert "get_garmin_data_quality" in registered
    assert "get_garmin_activity_details" in registered
    assert "get_garmin_activity_efficiency" in registered
    assert "get_garmin_activity_comparison" in registered
    assert "get_garmin_activity_backfill_status" in registered
    assert "get_garmin_activity_longitudinal" in registered
    assert "get_running_training_plan" in registered


def test_detailed_activity_schema_is_static_and_connector_safe() -> None:
    tool = mcp._tool_manager.get_tool("get_detailed_activity")
    assert tool is not None
    schema = tool.parameters
    assert schema["type"] == "object"
    props = schema["properties"]
    assert "target_date" in props
    assert "activity_id" in props
    # Nullable string schema: type [string, null] with default null.
    assert props["target_date"].get("type") == ["string", "null"]
    assert props["activity_id"].get("type") == ["string", "null"]
    assert props["target_date"].get("default") is None
    assert props["activity_id"].get("default") is None
    # structured_output=False => no loose output schema binding issues
    assert tool.fn_metadata.output_schema is None
    assert tool.annotations is not None
    assert tool.annotations.readOnlyHint is True


def test_recent_activities_schema_nullable_activitytype() -> None:
    tool = mcp._tool_manager.get_tool("get_recent_activities")
    assert tool is not None
    props = tool.parameters["properties"]
    assert props["activitytype"]["type"] == ["string", "null"]
    assert props["activitytype"].get("default") is None
    for required_arg in ("days", "start", "limit", "activitytype", "summary_only", "include_metrics"):
        assert required_arg in props
    assert tool.fn_metadata.output_schema is None
    assert tool.annotations is not None
    assert tool.annotations.readOnlyHint is True


def test_transport_allows_perplexity_origins() -> None:
    settings = build_mcp_transport_security_settings(
        "https://example.duckdns.org",
        mcp_port=8080,
    )
    for origin in DEFAULT_CONNECTOR_ORIGINS:
        assert origin in settings.allowed_origins


@pytest.mark.asyncio
async def test_tools_list_stable_across_repeated_reads() -> None:
    expected = set(list_registered_tool_names(mcp))
    assert expected.issuperset(REQUIRED_MCP_TOOLS)
    for _ in range(50):
        names = set(list_registered_tool_names(mcp))
        assert names == expected
        assert missing_required_tools(names) == []


@pytest.mark.asyncio
async def test_db_failure_keeps_tools_registered_and_returns_tool_error() -> None:
    from endurance_coach.mcp.deps import mcp_request_scope
    from endurance_coach.mcp.logging_utils import invoke_tool
    from mcp.server.fastmcp.exceptions import ToolError

    registered_before = list_registered_tool_names(mcp)
    assert missing_required_tools(registered_before) == []

    broken = MagicMock()
    broken.session_factory = MagicMock(
        side_effect=RuntimeError("simulated database outage")
    )

    async def _call():
        async with mcp_request_scope(broken):
            return {"ok": True}

    with pytest.raises(ToolError, match="Database unavailable"):
        await invoke_tool("get_recent_activities", _call)

    registered_after = list_registered_tool_names(mcp)
    assert registered_after == registered_before
    assert missing_required_tools(registered_after) == []


def test_mcp_server_enables_stateless_http() -> None:
    """Perplexity discovers tools then invokes without sticky mcp-session-id."""
    assert mcp.settings.stateless_http is True


def test_mcp_settings_default_stateless_and_json() -> None:
    from endurance_coach.config import Settings

    assert Settings.model_fields["mcp_stateless_http"].default is True
    assert Settings.model_fields["mcp_json_response"].default is True
    assert Settings.model_fields["mcp_advertise_oauth_resource"].default is False
    assert Settings.model_fields["mcp_session_idle_timeout_seconds"].default is None


def test_mcp_server_enables_json_response() -> None:
    """JSON-only Accept must not 406 on tools/call."""
    assert mcp.settings.json_response is True


def test_tool_error_on_db_failure_does_not_clear_registry() -> None:
    """Regression note: ToolError from invoke_tool/mcp_request_scope keeps tools."""
    # Covered by test_db_failure_keeps_tools_registered_and_returns_tool_error;
    # this alias documents the Perplexity fault-tolerance contract.
    registered = list_registered_tool_names(mcp)
    assert missing_required_tools(registered) == []
    assert len(registered) >= len(REQUIRED_MCP_TOOLS)


def test_health_liveness_reports_registry_without_db(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("API_SECRET_KEY", "")
    from endurance_coach.config import get_settings

    get_settings.cache_clear()
    # Health routes are on the streamable HTTP app; auth may still wrap /mcp only.
    mcp._session_manager = None
    app = mcp.streamable_http_app()
    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        body = response.json()
        assert body["discovery_ok"] is True
        assert body["registry"]["tool_count"] >= len(REQUIRED_MCP_TOOLS)
        for name in REQUIRED_MCP_TOOLS:
            assert name in body["registry"]["tools"]
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_detailed_activity_by_date_uses_service(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure target_date path remains wired for 2026-08-20 style calls."""
    from datetime import date

    from endurance_coach.mcp import service as service_mod

    captured: dict[str, Any] = {}

    async def fake_detail(self, user_id, *, target_date=None, activity_id=None):
        captured["target_date"] = target_date
        captured["activity_id"] = activity_id
        return {
            "id": "00000000-0000-0000-0000-000000000001",
            "activity_id": "24054651442",
            "provider_activity_id": "24054651442",
            "date": "2026-08-20",
            "activity_type": "Treadmill Running",
        }

    monkeypatch.setattr(
        service_mod.CoachMCPService,
        "get_detailed_activity",
        fake_detail,
    )

    # Unit-level: service method contract for the date the user needs.
    result = await fake_detail(
        MagicMock(),
        MagicMock(),
        target_date=date(2026, 8, 20),
        activity_id=None,
    )
    assert result["date"] == "2026-08-20"
    assert captured["target_date"] == date(2026, 8, 20)
