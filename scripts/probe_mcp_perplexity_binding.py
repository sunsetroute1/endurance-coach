"""Raw httpx probe matrix for Perplexity-style MCP discovery vs invoke.

Does NOT print secrets. Reads API_SECRET_KEY from env or .env.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import httpx

URL = "http://127.0.0.1:8080/mcp"
ARGS = {
    "days": 7,
    "start": 0,
    "limit": 50,
    "activitytype": "running",
    "summary_only": False,
    "include_metrics": True,
}


def _load_secret() -> str:
    secret = os.environ.get("API_SECRET_KEY")
    if secret:
        return secret
    env_path = Path(__file__).resolve().parents[1] / ".env"
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("API_SECRET_KEY="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("API_SECRET_KEY missing")


def _excerpt(text: str, n: int = 800) -> str:
    text = text.replace("\r\n", "\n")
    return text[:n] + ("…" if len(text) > n else "")


def _classify(body: str) -> str:
    try:
        data = json.loads(body)
    except Exception:
        if "event:" in body or "data:" in body:
            return "sse"
        return "non-json"
    if "error" in data:
        return f"error:{data['error'].get('code')}:{data['error'].get('message', '')[:80]}"
    if "result" in data:
        return "result"
    return "json-other"


def _log_response(label: str, resp: httpx.Response) -> dict[str, Any]:
    sid = resp.headers.get("mcp-session-id")
    ct = resp.headers.get("content-type", "")
    interesting = {
        k: v
        for k, v in resp.headers.items()
        if k.lower()
        in {
            "content-type",
            "mcp-session-id",
            "www-authenticate",
            "mcp-protocol-version",
            "cache-control",
            "access-control-allow-origin",
            "access-control-expose-headers",
        }
    }
    body = resp.text
    row = {
        "label": label,
        "status": resp.status_code,
        "content_type": ct,
        "mcp_session_id": bool(sid),
        "session_id_prefix": (sid[:12] + "…") if sid else None,
        "headers": interesting,
        "kind": _classify(body),
        "body_excerpt": _excerpt(body),
    }
    print("=" * 72)
    print(f"LABEL: {label}")
    print(f"status={row['status']} content-type={ct!r} kind={row['kind']}")
    print(f"mcp-session-id present={row['mcp_session_id']} prefix={row['session_id_prefix']}")
    print(f"headers={json.dumps(interesting, indent=2)}")
    print(f"body_excerpt:\n{row['body_excerpt']}")
    return row


def _rpc(method: str, params: dict | None = None, id_: int = 1) -> dict:
    msg: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
    if id_ is not None:
        msg["id"] = id_
    if params is not None:
        msg["params"] = params
    return msg


def _base_headers(accept: str, origin: str | None, session_id: str | None = None) -> dict[str, str]:
    h = {
        "Authorization": f"Bearer {_load_secret()}",
        "Content-Type": "application/json",
        "Accept": accept,
    }
    if origin:
        h["Origin"] = origin
    if session_id:
        h["mcp-session-id"] = session_id
    return h


def run_sequence(
    client: httpx.Client,
    *,
    label_prefix: str,
    accept: str,
    origin: str | None,
    sticky: bool,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    session_id: str | None = None

    # a) initialize
    init = _rpc(
        "initialize",
        {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "perplexity-probe", "version": "0.0.1"},
        },
        id_=1,
    )
    r = client.post(URL, headers=_base_headers(accept, origin, session_id if sticky else None), json=init)
    rows.append(_log_response(f"{label_prefix}/initialize", r))
    if sticky and r.headers.get("mcp-session-id"):
        session_id = r.headers["mcp-session-id"]

    capabilities = None
    try:
        capabilities = r.json().get("result", {}).get("capabilities")
    except Exception:
        pass
    print(f"initialize.capabilities={json.dumps(capabilities)}")

    # b) notifications/initialized (no id)
    notif = {"jsonrpc": "2.0", "method": "notifications/initialized"}
    r2 = client.post(
        URL,
        headers=_base_headers(accept, origin, session_id if sticky else None),
        json=notif,
    )
    rows.append(_log_response(f"{label_prefix}/notifications/initialized", r2))
    if sticky and r2.headers.get("mcp-session-id"):
        session_id = r2.headers.get("mcp-session-id") or session_id

    # c) tools/list
    lst = _rpc("tools/list", {}, id_=2)
    r3 = client.post(
        URL,
        headers=_base_headers(accept, origin, session_id if sticky else None),
        json=lst,
    )
    rows.append(_log_response(f"{label_prefix}/tools/list", r3))
    if sticky and r3.headers.get("mcp-session-id"):
        session_id = r3.headers.get("mcp-session-id") or session_id

    schema = None
    annotations = None
    output_schema = None
    try:
        tools = r3.json().get("result", {}).get("tools", [])
        for t in tools:
            if t.get("name") == "get_recent_activities":
                schema = t.get("inputSchema")
                annotations = t.get("annotations")
                output_schema = t.get("outputSchema")
                break
        print(
            f"get_recent_activities inputSchema={json.dumps(schema, indent=2) if schema else None}"
        )
        print(f"annotations={json.dumps(annotations)}")
        print(f"outputSchema={json.dumps(output_schema)}")
    except Exception as exc:
        print(f"tools/list parse error: {exc}")

    # d) tools/call
    call = _rpc(
        "tools/call",
        {"name": "get_recent_activities", "arguments": ARGS},
        id_=3,
    )
    r4 = client.post(
        URL,
        headers=_base_headers(accept, origin, session_id if sticky else None),
        json=call,
    )
    rows.append(_log_response(f"{label_prefix}/tools/call", r4))
    return rows


def run_stateless_split(
    *,
    label_prefix: str,
    accept: str,
    origin: str | None,
) -> list[dict[str, Any]]:
    """Separate HTTP clients for list vs call (no session sticky)."""
    rows: list[dict[str, Any]] = []
    with httpx.Client(timeout=60.0) as c1:
        init = _rpc(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "perplexity-probe-a", "version": "0.0.1"},
            },
            id_=1,
        )
        r = c1.post(URL, headers=_base_headers(accept, origin), json=init)
        rows.append(_log_response(f"{label_prefix}/A-initialize", r))
        c1.post(
            URL,
            headers=_base_headers(accept, origin),
            json={"jsonrpc": "2.0", "method": "notifications/initialized"},
        )
        r3 = c1.post(
            URL,
            headers=_base_headers(accept, origin),
            json=_rpc("tools/list", {}, id_=2),
        )
        rows.append(_log_response(f"{label_prefix}/A-tools/list", r3))

    with httpx.Client(timeout=60.0) as c2:
        r = c2.post(
            URL,
            headers=_base_headers(accept, origin),
            json=_rpc(
                "initialize",
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "perplexity-probe-b", "version": "0.0.1"},
                },
                id_=10,
            ),
        )
        rows.append(_log_response(f"{label_prefix}/B-initialize", r))
        c2.post(
            URL,
            headers=_base_headers(accept, origin),
            json={"jsonrpc": "2.0", "method": "notifications/initialized"},
        )
        r4 = c2.post(
            URL,
            headers=_base_headers(accept, origin),
            json=_rpc(
                "tools/call",
                {"name": "get_recent_activities", "arguments": ARGS},
                id_=11,
            ),
        )
        rows.append(_log_response(f"{label_prefix}/B-tools/call", r4))
    return rows


def validate_schema(schema: dict | None) -> list[str]:
    flags: list[str] = []
    if not schema:
        flags.append("MISSING_SCHEMA")
        return flags
    if "anyOf" in json.dumps(schema):
        flags.append("HAS_anyOf")
    props = schema.get("properties") or {}
    required = schema.get("required") or []
    for key, expected_type in [
        ("days", "integer"),
        ("start", "integer"),
        ("limit", "integer"),
        ("activitytype", "string"),
        ("summary_only", "boolean"),
        ("include_metrics", "boolean"),
    ]:
        if key not in props:
            flags.append(f"MISSING_PROP:{key}")
            continue
        p = props[key]
        if "anyOf" in p:
            flags.append(f"anyOf:{key}")
        if "type" in p and p["type"] != expected_type:
            flags.append(f"WRONG_TYPE:{key}:{p['type']}")
        if p.get("type") is None and "anyOf" not in p:
            flags.append(f"NO_TYPE:{key}")
    # Desired args vs required
    for key in required:
        if key not in ARGS and key != "ctx":
            # all our desired keys present; flag if required something we don't send
            if key not in ARGS:
                flags.append(f"REQUIRED_NOT_IN_ARGS:{key}")
    # jsonschema-ish type check of ARGS
    type_map = {
        "integer": int,
        "string": str,
        "boolean": bool,
        "number": (int, float),
    }
    for key, val in ARGS.items():
        if key not in props:
            flags.append(f"ARG_NOT_IN_SCHEMA:{key}")
            continue
        t = props[key].get("type")
        if t and not isinstance(val, type_map.get(t, object)):
            flags.append(f"ARG_TYPE_MISMATCH:{key}:{type(val).__name__}!={t}")
    if not flags:
        flags.append("OK")
    return flags


def main() -> int:
    all_rows: list[dict[str, Any]] = []
    accepts = [
        "application/json",
        "application/json, text/event-stream",
    ]
    origins = [None, "https://www.perplexity.ai"]

    # Sticky same-connection sequences
    for accept in accepts:
        for origin in origins:
            otag = "origin" if origin else "no-origin"
            atag = "json-only" if accept == "application/json" else "json+sse"
            with httpx.Client(timeout=60.0) as client:
                rows = run_sequence(
                    client,
                    label_prefix=f"sticky|{atag}|{otag}",
                    accept=accept,
                    origin=origin,
                    sticky=True,
                )
                all_rows.extend(rows)

    # Stateless split (list vs call separate connections)
    for accept in accepts:
        for origin in origins:
            otag = "origin" if origin else "no-origin"
            atag = "json-only" if accept == "application/json" else "json+sse"
            rows = run_stateless_split(
                label_prefix=f"split|{atag}|{otag}",
                accept=accept,
                origin=origin,
            )
            all_rows.extend(rows)

    # Pull schema once for validation summary
    with httpx.Client(timeout=60.0) as client:
        accept = "application/json, text/event-stream"
        origin = "https://www.perplexity.ai"
        client.post(
            URL,
            headers=_base_headers(accept, origin),
            json=_rpc(
                "initialize",
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "schema-check", "version": "0"},
                },
            ),
        )
        client.post(
            URL,
            headers=_base_headers(accept, origin),
            json={"jsonrpc": "2.0", "method": "notifications/initialized"},
        )
        r = client.post(
            URL,
            headers=_base_headers(accept, origin),
            json=_rpc("tools/list", {}, id_=2),
        )
        tools = r.json().get("result", {}).get("tools", [])
        schema = None
        meta = {}
        for t in tools:
            if t.get("name") == "get_recent_activities":
                schema = t.get("inputSchema")
                meta = {
                    k: t.get(k)
                    for k in ("annotations", "outputSchema", "description", "title")
                    if k in t
                }
                # also dump full tool keys
                print(f"tool_keys={sorted(t.keys())}")
                break
        flags = validate_schema(schema)
        print("=" * 72)
        print("SCHEMA_VALIDATION_FLAGS:", flags)
        print("TOOL_META:", json.dumps(meta, indent=2))

    # Summary table
    print("\n\n=== SUMMARY TABLE ===")
    print(f"{'label':<55} {'status':>6} {'kind':<40} {'sid':>5}")
    for row in all_rows:
        print(
            f"{row['label']:<55} {row['status']:>6} {row['kind']:<40} {str(row['mcp_session_id']):>5}"
        )

    out = Path(__file__).resolve().parents[1] / "logs" / "mcp_perplexity_probe.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"rows": all_rows, "schema_flags": flags}, indent=2), encoding="utf-8")
    print(f"\nWrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
