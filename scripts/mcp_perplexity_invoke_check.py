"""Prove Perplexity-style invoke: tools/call with NO mcp-session-id and NO prior initialize."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import httpx


def _load_env() -> dict[str, str]:
    values: dict[str, str] = {}
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if not line or line.strip().startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            values[key.strip()] = val.strip().strip('"').strip("'")
    return values


def main() -> int:
    env = _load_env()
    token = os.environ.get("API_SECRET_KEY") or env.get("API_SECRET_KEY")
    if not token:
        print("FAIL: API_SECRET_KEY missing")
        return 1

    public = (os.environ.get("PUBLIC_BASE_URL") or env.get("PUBLIC_BASE_URL") or "").rstrip("/")
    urls = [f"http://127.0.0.1:{env.get('MCP_PORT', '8080')}/mcp"]
    if public.startswith("http"):
        urls.append(f"{public}/mcp")

    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "get_recent_activities",
            "arguments": {
                "days": 7,
                "start": 0,
                "limit": 50,
                "activitytype": "running",
                "summary_only": False,
                "include_metrics": True,
            },
        },
    }
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Origin": "https://www.perplexity.ai",
    }

    exit_code = 0
    with httpx.Client(timeout=60.0) as client:
        for url in urls:
            # OPTIONS must succeed for browser connectors
            opt = client.options(url, headers={"Origin": "https://www.perplexity.ai"})
            print(f"[{url}] OPTIONS -> {opt.status_code}")
            if opt.status_code not in {200, 204}:
                exit_code = 1

            # Direct tools/call with no session id / no initialize
            resp = client.post(url, headers=headers, json=body)
            print(f"[{url}] tools/call(no-session) -> {resp.status_code}")
            if resp.status_code != 200:
                print(resp.text[:500])
                exit_code = 1
                continue
            if "mcp-session-id" in {k.lower() for k in resp.headers}:
                # Stateless should not require clients to keep a session id.
                print(f"[{url}] note: server returned mcp-session-id={resp.headers.get('mcp-session-id')!r}")
            payload = resp.json()
            if "error" in payload:
                print(f"[{url}] JSON-RPC error: {payload['error']}")
                exit_code = 1
                continue
            result = payload.get("result") or {}
            if result.get("isError"):
                print(f"[{url}] tool isError: {result}")
                exit_code = 1
                continue
            content = result.get("content") or []
            text = next((c.get("text") for c in content if c.get("type") == "text"), None)
            if not text:
                print(f"[{url}] missing text content: {str(result)[:400]}")
                exit_code = 1
                continue
            data = json.loads(text)
            print(
                f"[{url}] PASS activities={data.get('count')} "
                f"total={data.get('total')} mode={data.get('mode')}"
            )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
