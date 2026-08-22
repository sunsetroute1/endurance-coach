"""Shared MCP streamable-HTTP transport security settings."""

from __future__ import annotations

from urllib.parse import urlparse

from mcp.server.transport_security import TransportSecuritySettings

LOOPBACK_HOSTS = (
    "127.0.0.1",
    "localhost",
    "[::1]",
)


def parse_host_header(host: str) -> tuple[str, int | None]:
    """Return normalized hostname and optional port from a Host header value."""
    normalized = host.strip().lower()
    if not normalized:
        return "", None

    if normalized.startswith("["):
        closing = normalized.find("]")
        if closing == -1:
            return normalized, None
        hostname = normalized[: closing + 1]
        remainder = normalized[closing + 1 :]
        if remainder.startswith(":"):
            return hostname, int(remainder[1:])
        return hostname, None

    if ":" in normalized:
        hostname, port_text = normalized.rsplit(":", 1)
        if port_text.isdigit():
            return hostname, int(port_text)

    return normalized, None


def expand_trusted_hosts(hostnames: tuple[str, ...]) -> list[str]:
    """Build MCP allowlist entries for bare hosts and explicit port-qualified hosts."""
    entries: list[str] = []
    for hostname in hostnames:
        bare = hostname.strip().lower()
        if not bare:
            continue
        entries.append(bare)
        entries.append(f"{bare}:*")
        entries.append(f"{bare}:443")
        entries.append(f"{bare}:80")
    return entries


# Connector / browser Origins that may appear on streamable-HTTP POSTs.
# Missing Origin is always allowed by the MCP SDK; foreign Origins are rejected
# unless listed here (common Perplexity TEMPORARILY_UNAVAILABLE cause).
DEFAULT_CONNECTOR_ORIGINS: tuple[str, ...] = (
    "https://www.perplexity.ai",
    "https://perplexity.ai",
    "https://www.perplexity.com",
    "https://perplexity.com",
)


def build_mcp_transport_security_settings(
    public_base_url: str,
    *,
    mcp_port: int = 8080,
    extra_allowed_origins: tuple[str, ...] | list[str] | None = None,
) -> TransportSecuritySettings:
    """Return DNS rebinding settings for the public MCP endpoint and local dev."""
    parsed = urlparse(public_base_url)
    public_host = (parsed.hostname or "localhost").lower()

    allowed_hosts = expand_trusted_hosts((*LOOPBACK_HOSTS, public_host))
    allowed_hosts.extend(
        [
            f"127.0.0.1:{mcp_port}",
            f"localhost:{mcp_port}",
            f"[::1]:{mcp_port}",
        ]
    )

    origins = [
        f"https://{public_host}",
        f"https://{public_host}:443",
        "http://127.0.0.1:*",
        "http://localhost:*",
        f"http://127.0.0.1:{mcp_port}",
        f"http://localhost:{mcp_port}",
        *DEFAULT_CONNECTOR_ORIGINS,
    ]
    if extra_allowed_origins:
        origins.extend(str(origin).strip() for origin in extra_allowed_origins if str(origin).strip())

    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=_dedupe(allowed_hosts),
        allowed_origins=_dedupe(origins),
    )


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            ordered.append(value)
    return ordered
