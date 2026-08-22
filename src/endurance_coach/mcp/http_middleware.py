"""Starlette middleware for MCP streamable-HTTP edge behavior."""

from __future__ import annotations

import json
import time
from typing import Any, Iterable

from starlette.datastructures import Headers
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from endurance_coach.mcp.logging_utils import log_event
from endurance_coach.security.mcp_transport import DEFAULT_CONNECTOR_ORIGINS

# Origins allowed for browser connectors (CORS + preflight).
_CORS_ORIGINS = frozenset(DEFAULT_CONNECTOR_ORIGINS)

# Cap body peek so we never buffer large uploads into memory for logging.
_MAX_BODY_PEEK = 65_536


def _header_map(scope: Scope) -> Headers:
    return Headers(scope=scope)


def _origin_allowed(origin: str | None) -> bool:
    if not origin:
        return False
    return origin in _CORS_ORIGINS


def _cors_headers(origin: str) -> list[tuple[bytes, bytes]]:
    return [
        (b"access-control-allow-origin", origin.encode("ascii")),
        (b"access-control-allow-credentials", b"true"),
        (
            b"access-control-allow-headers",
            b"authorization, content-type, accept, mcp-session-id, mcp-protocol-version",
        ),
        (b"access-control-allow-methods", b"GET, POST, DELETE, OPTIONS"),
        (b"access-control-max-age", b"86400"),
        (b"access-control-expose-headers", b"mcp-session-id, mcp-protocol-version"),
        (b"vary", b"Origin"),
    ]


def _truncate_session_id(session_id: str | None, *, keep: int = 8) -> str | None:
    if not session_id:
        return None
    if len(session_id) <= keep:
        return session_id
    return f"{session_id[:keep]}…"


def _parse_jsonrpc_fields(body: bytes) -> dict[str, Any]:
    """Extract safe JSON-RPC fields from a small POST body (never auth)."""
    out: dict[str, Any] = {
        "jsonrpc_id": None,
        "jsonrpc_method": None,
        "tool_name": None,
    }
    if not body:
        return out
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return out

    if isinstance(payload, list) and payload:
        payload = payload[0]
    if not isinstance(payload, dict):
        return out

    out["jsonrpc_id"] = payload.get("id")
    method = payload.get("method")
    if isinstance(method, str):
        out["jsonrpc_method"] = method
    params = payload.get("params")
    if method == "tools/call" and isinstance(params, dict):
        name = params.get("name")
        if isinstance(name, str):
            out["tool_name"] = name
    return out


class McpCorsOptionsMiddleware:
    """Bypass auth for OPTIONS and attach CORS headers for connector Origins.

    RequireAuthMiddleware wraps `/mcp`, so unauthenticated CORS preflights
    otherwise get HTTP 401. Browser connectors then fail to bind an invocable
    tools/call handle even when tools/list already succeeded via a non-browser path.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = _header_map(scope)
        origin = headers.get("origin")
        method = scope.get("method", "").upper()
        path = scope.get("path", "")

        if method == "OPTIONS" and path.rstrip("/").endswith("/mcp"):
            started = time.perf_counter()
            if origin and _origin_allowed(origin):
                body = b""
                out_headers = [
                    (b"content-length", b"0"),
                    *_cors_headers(origin),
                ]
                await send(
                    {
                        "type": "http.response.start",
                        "status": 204,
                        "headers": out_headers,
                    }
                )
                await send({"type": "http.response.body", "body": body})
                log_event(
                    "mcp_http",
                    method="OPTIONS",
                    path=path,
                    accept=headers.get("accept"),
                    origin=origin,
                    has_session_id=bool(headers.get("mcp-session-id")),
                    mcp_session_id=_truncate_session_id(headers.get("mcp-session-id")),
                    status=204,
                    latency_ms=round((time.perf_counter() - started) * 1000, 1),
                )
                return

            # Unknown Origin: still avoid 401 on preflight (spec: no credentials).
            await send(
                {
                    "type": "http.response.start",
                    "status": 204,
                    "headers": [(b"content-length", b"0")],
                }
            )
            await send({"type": "http.response.body", "body": b""})
            log_event(
                "mcp_http",
                method="OPTIONS",
                path=path,
                accept=headers.get("accept"),
                origin=origin,
                has_session_id=False,
                mcp_session_id=None,
                status=204,
                latency_ms=round((time.perf_counter() - started) * 1000, 1),
            )
            return

        if not (origin and _origin_allowed(origin)):
            await self.app(scope, receive, send)
            return

        async def send_with_cors(message: Message) -> None:
            if message["type"] == "http.response.start":
                raw_headers: list[tuple[bytes, bytes]] = list(message.get("headers") or [])
                # Don't duplicate if already present.
                existing = {k.lower() for k, _ in raw_headers}
                for key, value in _cors_headers(origin):
                    if key not in existing:
                        raw_headers.append((key, value))
                message = {**message, "headers": raw_headers}
            await send(message)

        await self.app(scope, receive, send_with_cors)


class McpRequestLogMiddleware:
    """Log method, Accept, Origin, session id, JSON-RPC method/tool, status, latency."""

    def __init__(self, app: ASGIApp, paths: Iterable[str] | None = None) -> None:
        self.app = app
        self._paths = frozenset(paths or ("/mcp",))

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if path.rstrip("/") not in {p.rstrip("/") for p in self._paths}:
            await self.app(scope, receive, send)
            return

        headers = _header_map(scope)
        method = scope.get("method", "")
        started = time.perf_counter()
        status_box: dict[str, int] = {"status": 0}
        rpc_fields: dict[str, Any] = {
            "jsonrpc_id": None,
            "jsonrpc_method": None,
            "tool_name": None,
        }
        body_chunks: list[bytes] = []
        body_size = 0
        body_complete = False
        receive_exhausted = False

        async def receive_wrapper() -> Message:
            nonlocal body_size, body_complete, receive_exhausted
            message = await receive()
            if message["type"] == "http.request":
                chunk = message.get("body", b"") or b""
                if body_size < _MAX_BODY_PEEK and chunk:
                    remaining = _MAX_BODY_PEEK - body_size
                    body_chunks.append(chunk[:remaining])
                    body_size += min(len(chunk), remaining)
                if not message.get("more_body", False):
                    body_complete = True
                    if method.upper() == "POST" and body_complete:
                        rpc_fields.update(_parse_jsonrpc_fields(b"".join(body_chunks)))
            elif message["type"] == "http.disconnect":
                receive_exhausted = True
            return message

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                status_box["status"] = int(message.get("status", 0))
            await send(message)

        await self.app(scope, receive_wrapper, send_wrapper)
        # If the app never drained the body (unlikely), still try to parse what we have.
        if (
            method.upper() == "POST"
            and rpc_fields["jsonrpc_method"] is None
            and body_chunks
            and not receive_exhausted
        ):
            rpc_fields.update(_parse_jsonrpc_fields(b"".join(body_chunks)))

        session_raw = headers.get("mcp-session-id")
        log_event(
            "mcp_http",
            method=method,
            path=path,
            accept=headers.get("accept"),
            origin=headers.get("origin"),
            has_session_id=bool(session_raw),
            mcp_session_id=_truncate_session_id(session_raw),
            status=status_box["status"],
            latency_ms=round((time.perf_counter() - started) * 1000, 1),
            jsonrpc_id=rpc_fields["jsonrpc_id"],
            jsonrpc_method=rpc_fields["jsonrpc_method"],
            tool_name=rpc_fields["tool_name"],
        )


def install_mcp_http_middleware(app: ASGIApp) -> ASGIApp:
    """Wrap a Starlette/ASGI app with CORS/OPTIONS bypass then request logging.

    Order: logging outermost so it records OPTIONS short-circuits too.
    """
    app = McpCorsOptionsMiddleware(app)
    app = McpRequestLogMiddleware(app)
    return app
