"""Static bearer token verification for self-hosted deployments."""

from __future__ import annotations

import secrets

from mcp.server.auth.provider import AccessToken


def verify_bearer_token(header_value: str | None, expected_key: str | None) -> bool:
    if not expected_key:
        return True
    if not header_value or not header_value.lower().startswith("bearer "):
        return False
    provided = header_value[7:].strip()
    if not provided:
        return False
    return secrets.compare_digest(provided, expected_key)


class StaticBearerTokenVerifier:
    """MCP TokenVerifier backed by a single shared API secret."""

    def __init__(self, expected_key: str) -> None:
        self._expected_key = expected_key

    async def verify_token(self, token: str) -> AccessToken | None:
        if not token or not secrets.compare_digest(token, self._expected_key):
            return None
        return AccessToken(
            token=token,
            client_id="endurance-coach",
            scopes=["mcp:tools"],
        )
