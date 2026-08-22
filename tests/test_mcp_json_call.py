"""Regression: tools/call must work with application/json-only Accept."""

from __future__ import annotations

import json
import os
from pathlib import Path

import httpx
import pytest


def _load_secret() -> str | None:
    secret = os.environ.get("API_SECRET_KEY")
    if secret:
        return secret
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if not env_path.exists():
        return None
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("API_SECRET_KEY="):
            return line.split("=", 1)[1].strip().strip('"').strip("'") or None
    return None


@pytest.mark.asyncio
async def test_tools_call_accepts_application_json_only() -> None:
    """
    Perplexity-style clients often Accept only application/json on tools/call.
    With MCP_JSON_RESPONSE=true the server must return 200 JSON, not 406.
    """
    token = _load_secret()
    if not token:
        pytest.skip("API_SECRET_KEY not configured")

    url = "http://127.0.0.1:8080/mcp"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Origin": "https://www.perplexity.ai",
    }
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "get_recent_activities",
            "arguments": {"days": 7, "limit": 2, "summary_only": True},
        },
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(url, headers=headers, json=body)

    assert response.status_code == 200, (
        f"expected 200 for JSON-only Accept, got {response.status_code}: {response.text[:300]}"
    )
    assert "application/json" in response.headers.get("content-type", "")
    payload = response.json()
    assert "result" in payload
    # FastMCP may wrap content; ensure no JSON-RPC error
    assert "error" not in payload


@pytest.mark.asyncio
async def test_oauth_resource_metadata_not_advertised() -> None:
    """Static Bearer connectors must not be steered into fake OAuth AS discovery."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            "http://127.0.0.1:8080/.well-known/oauth-protected-resource/mcp"
        )
    # When resource_server_url is None, metadata route should be absent (404)
    # or not advertise authorization_servers for our public host as a real AS.
    assert response.status_code in {404, 401, 405, 200}
    if response.status_code == 200:
        data = response.json()
        # If somehow present, it must not claim a non-existent AS path that
        # breaks connector call binding. Prefer empty / missing.
        servers = data.get("authorization_servers") or []
        assert servers == [], (
            "OAuth resource metadata still advertises authorization_servers; "
            "set mcp_advertise_oauth_resource=false"
        )
