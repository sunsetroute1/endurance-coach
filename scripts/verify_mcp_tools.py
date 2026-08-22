"""Verify live MCP tools via streamable-http (local + optional public URL)."""

from __future__ import annotations

import asyncio
import json
import sys

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from endurance_coach.config import get_settings


async def _probe(url: str, token: str, host: str | None = None) -> dict[str, object]:
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json, text/event-stream",
    }
    if host:
        headers["Host"] = host

    async with httpx.AsyncClient(headers=headers, timeout=httpx.Timeout(60.0)) as http_client:
        async with streamable_http_client(url, http_client=http_client) as (read, write, _get_sid):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                names = sorted(t.name for t in tools.tools)
                target = {
                    "get_weekly_aggregates",
                    "get_top_trail_efforts",
                    "get_recent_activities",
                    "get_detailed_activity",
                }
                missing = sorted(target - set(names))

                weekly = await session.call_tool("get_weekly_aggregates", {"weeks": 2})
                trail = await session.call_tool(
                    "get_top_trail_efforts",
                    {"days": 90, "limit": 3, "rank_by": "vert_duration"},
                )
                recent = await session.call_tool(
                    "get_recent_activities",
                    {"days": 14, "summary_only": True, "limit": 5},
                )

                weekly_text = weekly.content[0].text if weekly.content else ""
                trail_text = trail.content[0].text if trail.content else ""
                recent_text = recent.content[0].text if recent.content else ""
                weekly_data = json.loads(weekly_text) if weekly_text else {}
                trail_data = json.loads(trail_text) if trail_text else {}
                recent_data = json.loads(recent_text) if recent_text else {}

                detail_ok = False
                detail_via = None
                detail_error = None
                activities = recent_data.get("activities", []) if isinstance(recent_data, dict) else []
                first = activities[0] if activities else {}
                for via, value in (
                    ("id", first.get("id")),
                    ("provider_activity_id", first.get("provider_activity_id")),
                ):
                    if not value:
                        continue
                    detail = await session.call_tool(
                        "get_detailed_activity",
                        {"activity_id": str(value)},
                    )
                    detail_text = detail.content[0].text if detail.content else ""
                    if detail.isError:
                        detail_error = detail_text[:300]
                        continue
                    detail_ok = True
                    detail_via = via
                    break
                if not activities:
                    detail = await session.call_tool("get_detailed_activity", {})
                    detail_text = detail.content[0].text if detail.content else ""
                    detail_ok = not detail.isError
                    detail_via = "most_recent"
                    if detail.isError:
                        detail_error = detail_text[:300]

                return {
                    "url": url,
                    "host_header": host,
                    "tool_count": len(names),
                    "has_weekly_tool": "get_weekly_aggregates" in names,
                    "has_trail_tool": "get_top_trail_efforts" in names,
                    "has_recent_tool": "get_recent_activities" in names,
                    "has_detailed_tool": "get_detailed_activity" in names,
                    "missing_tools": missing,
                    "weekly_ok": not weekly.isError,
                    "weekly_aggregate_rows": len(weekly_data.get("aggregates", []))
                    if isinstance(weekly_data, dict)
                    else None,
                    "trail_ok": not trail.isError,
                    "trail_efforts": trail_data.get("count") if isinstance(trail_data, dict) else None,
                    "total_trail_activities": trail_data.get("total_trail_activities")
                    if isinstance(trail_data, dict)
                    else None,
                    "recent_ok": not recent.isError,
                    "recent_count": recent_data.get("count") if isinstance(recent_data, dict) else None,
                    "recent_has_ids": bool(first.get("id") and first.get("provider_activity_id")),
                    "detail_ok": detail_ok,
                    "detail_via": detail_via,
                    "weekly_error": weekly_text[:300] if weekly.isError else None,
                    "trail_error": trail_text[:300] if trail.isError else None,
                    "recent_error": recent_text[:300] if recent.isError else None,
                    "detail_error": detail_error,
                }


async def main() -> int:
    settings = get_settings()
    token = settings.api_secret_key
    if not token:
        print("ERROR: API_SECRET_KEY not configured")
        return 1

    public_host = settings.public_base_url.replace("https://", "").replace("http://", "").rstrip("/")
    public_url = f"{settings.public_base_url.rstrip('/')}/mcp"
    probes = [
        ("local", f"http://127.0.0.1:{settings.mcp_port}/mcp", None),
        ("public-host", f"http://127.0.0.1:{settings.mcp_port}/mcp", public_host),
        ("public-https", public_url, None),
    ]

    exit_code = 0
    for label, url, host in probes:
        try:
            result = await _probe(url, token, host)
            print(f"[{label}] OK")
            print(json.dumps(result, indent=2))
            if (
                result["missing_tools"]
                or not result["weekly_ok"]
                or not result["trail_ok"]
                or not result["recent_ok"]
                or not result["detail_ok"]
                or not result["recent_has_ids"]
            ):
                exit_code = 1
        except Exception as exc:
            exit_code = 1
            print(f"[{label}] FAILED: {type(exc).__name__}: {exc}")

    return exit_code


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
