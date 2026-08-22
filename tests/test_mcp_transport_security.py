"""Tests for MCP streamable-HTTP host/origin validation."""

from __future__ import annotations

import json

import pytest
from starlette.requests import Request
from starlette.testclient import TestClient

from endurance_coach.api.main import app as api_app
from endurance_coach.config import get_settings
from endurance_coach.mcp.server import mcp
from endurance_coach.security.mcp_transport import (
    build_mcp_transport_security_settings,
    parse_host_header,
)
from mcp.server.transport_security import TransportSecurityMiddleware

PUBLIC_HOST = "example.duckdns.org"
TEST_SECRET = "test-mcp-secret"
INIT_BODY = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "test-client", "version": "1.0"},
    },
}


def _scope(
    *,
    host: str,
    path: str = "/mcp",
    method: str = "POST",
    origin: str | None = None,
    authorization: str | None = None,
) -> dict[str, object]:
    headers: list[tuple[bytes, bytes]] = [
        (b"host", host.encode()),
        (b"content-type", b"application/json"),
    ]
    if origin is not None:
        headers.append((b"origin", origin.encode()))
    if authorization is not None:
        headers.append((b"authorization", authorization.encode()))
    return {
        "type": "http",
        "http_version": "1.1",
        "method": method,
        "path": path,
        "headers": headers,
        "query_string": b"",
        "client": ("testclient", 50000),
        "server": ("127.0.0.1", 8080),
        "scheme": "https",
        "root_path": "",
        "app": None,
    }


@pytest.fixture
def transport_security():
    return build_mcp_transport_security_settings(
        f"https://{PUBLIC_HOST}",
        mcp_port=8080,
    )


@pytest.fixture
def security_middleware(transport_security):
    return TransportSecurityMiddleware(transport_security)


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        (PUBLIC_HOST, True),
        (f"{PUBLIC_HOST}:443", True),
        ("evil.example.com", False),
        ("127.0.0.1:8080", True),
    ],
)
def test_transport_security_host_validation(
    security_middleware: TransportSecurityMiddleware,
    host: str,
    expected: bool,
) -> None:
    assert security_middleware._validate_host(host) is expected


@pytest.mark.parametrize(
    ("origin", "expected"),
    [
        (None, True),
        (f"https://{PUBLIC_HOST}", True),
        ("https://www.perplexity.ai", True),
        ("https://perplexity.ai", True),
        ("https://evil.example.com", False),
        (f"http://{PUBLIC_HOST}", False),
    ],
)
def test_transport_security_origin_validation(
    security_middleware: TransportSecurityMiddleware,
    origin: str | None,
    expected: bool,
) -> None:
    assert security_middleware._validate_origin(origin) is expected


def test_parse_host_header_normalizes_port() -> None:
    assert parse_host_header("Example.DuckDNS.org:443") == ("example.duckdns.org", 443)
    assert parse_host_header("example.duckdns.org") == ("example.duckdns.org", None)


@pytest.mark.asyncio
async def test_validate_request_rejects_unknown_host(
    security_middleware: TransportSecurityMiddleware,
) -> None:
    request = Request(_scope(host="attacker.example.com"))
    response = await security_middleware.validate_request(request, is_post=True)
    assert response is not None
    assert response.status_code == 421
    assert response.body == b"Invalid Host header"


@pytest.mark.asyncio
async def test_validate_request_accepts_missing_origin(
    security_middleware: TransportSecurityMiddleware,
) -> None:
    request = Request(_scope(host=PUBLIC_HOST))
    response = await security_middleware.validate_request(request, is_post=True)
    assert response is None


@pytest.fixture
def mcp_client(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("API_SECRET_KEY", TEST_SECRET)
    monkeypatch.setenv("PUBLIC_BASE_URL", f"https://{PUBLIC_HOST}")
    get_settings.cache_clear()

    mcp.settings.transport_security = build_mcp_transport_security_settings(
        f"https://{PUBLIC_HOST}",
        mcp_port=8080,
    )
    from endurance_coach.security.api_key import StaticBearerTokenVerifier

    mcp._token_verifier = StaticBearerTokenVerifier(TEST_SECRET)
    mcp._session_manager = None

    with TestClient(mcp.streamable_http_app()) as client:
        yield client

    mcp._session_manager = None
    get_settings.cache_clear()


def test_mcp_initialize_accepts_public_host_without_origin(mcp_client: TestClient) -> None:
    response = mcp_client.post(
        "/mcp",
        headers={
            "Host": PUBLIC_HOST,
            "Authorization": f"Bearer {TEST_SECRET}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
        content=json.dumps(INIT_BODY),
    )
    assert response.status_code != 421
    assert response.status_code != 403
    assert response.status_code in {200, 202, 406}


def test_mcp_initialize_accepts_public_host_with_port(mcp_client: TestClient) -> None:
    response = mcp_client.post(
        "/mcp",
        headers={
            "Host": f"{PUBLIC_HOST}:443",
            "Authorization": f"Bearer {TEST_SECRET}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
        content=json.dumps(INIT_BODY),
    )
    assert response.status_code != 421
    assert response.status_code != 403


def test_mcp_initialize_rejects_unknown_host(mcp_client: TestClient) -> None:
    response = mcp_client.post(
        "/mcp",
        headers={
            "Host": "evil.example.com",
            "Authorization": f"Bearer {TEST_SECRET}",
            "Content-Type": "application/json",
        },
        content=json.dumps(INIT_BODY),
    )
    assert response.status_code == 421
    assert response.text == "Invalid Host header"


def test_mcp_initialize_requires_bearer_token(mcp_client: TestClient) -> None:
    response = mcp_client.post(
        "/mcp",
        headers={
            "Host": PUBLIC_HOST,
            "Content-Type": "application/json",
        },
        content=json.dumps(INIT_BODY),
    )
    assert response.status_code == 401


def test_mcp_initialize_accepts_perplexity_origin(mcp_client: TestClient) -> None:
    response = mcp_client.post(
        "/mcp",
        headers={
            "Host": PUBLIC_HOST,
            "Origin": "https://www.perplexity.ai",
            "Authorization": f"Bearer {TEST_SECRET}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
        content=json.dumps(INIT_BODY),
    )
    assert response.status_code != 421
    assert response.status_code != 403
    assert response.status_code in {200, 202, 406}


def test_rest_health_unchanged_without_mcp_host_requirements(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("API_SECRET_KEY", "")
    get_settings.cache_clear()
    with TestClient(api_app) as client:
        response = client.get("/health", headers={"Host": PUBLIC_HOST})
        assert response.status_code == 200
        assert response.json()["status"] == "ok"
    get_settings.cache_clear()
