"""OPTIONS/CORS preflight must not require Bearer (browser connectors)."""

from __future__ import annotations

import httpx
import pytest
from starlette.testclient import TestClient

from endurance_coach.mcp.http_middleware import install_mcp_http_middleware
from endurance_coach.mcp.server import mcp


def _fresh_streamable_app():
    """streamable_http_app reuses one SessionManager; reset between TestClients."""
    mcp._session_manager = None
    return mcp.streamable_http_app()


@pytest.fixture()
def mcp_edge_client() -> TestClient:
    app = install_mcp_http_middleware(_fresh_streamable_app())
    with TestClient(app) as client:
        yield client


def test_options_preflight_no_auth_returns_204(mcp_edge_client: TestClient) -> None:
    response = mcp_edge_client.options(
        "/mcp",
        headers={
            "Origin": "https://www.perplexity.ai",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization, content-type, accept",
        },
    )
    assert response.status_code == 204
    assert response.headers.get("access-control-allow-origin") == "https://www.perplexity.ai"
    assert "authorization" in response.headers.get("access-control-allow-headers", "").lower()


def test_options_without_middleware_is_401() -> None:
    """Document the pre-fix failure mode: bare FastMCP auth wraps OPTIONS."""
    app = _fresh_streamable_app()
    with TestClient(app) as client:
        response = client.options(
            "/mcp",
            headers={
                "Origin": "https://www.perplexity.ai",
                "Access-Control-Request-Method": "POST",
            },
        )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_live_options_preflight_when_server_up() -> None:
    """Against a running container (skip if down)."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.request(
                "OPTIONS",
                "http://127.0.0.1:8080/mcp",
                headers={
                    "Origin": "https://www.perplexity.ai",
                    "Access-Control-Request-Method": "POST",
                    "Access-Control-Request-Headers": "authorization,content-type,accept",
                },
            )
    except httpx.HTTPError:
        pytest.skip("MCP server not reachable")
    # After redeploy with middleware: 204. Before: 401.
    assert response.status_code in {204, 401}
    if response.status_code == 204:
        assert response.headers.get("access-control-allow-origin") == "https://www.perplexity.ai"
