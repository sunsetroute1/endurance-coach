"""Search raw payloads and live Garmin API for daily recap text."""

from __future__ import annotations

import asyncio
import json
from datetime import date
from pathlib import Path

from sqlalchemy import text

from endurance_coach.collector.providers.garmin.client import GarminClient
from endurance_coach.config import get_settings
from endurance_coach.db.session import create_engine, create_session_factory


SEARCH_TERMS = ("stressful", "daily recap", "You had", "recap", "insight", "summary message")


async def search_db() -> None:
    settings = get_settings()
    engine = create_engine(settings)
    factory = create_session_factory(engine)
    async with factory() as session:
        for term in SEARCH_TERMS:
            result = await session.execute(
                text(
                    """
                    SELECT resource_type, provider_record_id, fetched_at,
                           substring(payload::text from 1 for 800) AS snippet
                    FROM raw_payloads
                    WHERE payload::text ILIKE :pattern
                    ORDER BY fetched_at DESC
                    LIMIT 5
                    """
                ),
                {"pattern": f"%{term}%"},
            )
            rows = result.fetchall()
            print(f"\n=== DB search: {term!r} ({len(rows)} hits) ===")
            for row in rows:
                print(f"  {row.resource_type} | {row.provider_record_id} | {row.fetched_at}")
                print(f"  {row.snippet[:300]}...")


async def probe_garmin_api() -> None:
    settings = get_settings()
    token_path = Path(settings.garmin_token_path).expanduser()
    if not token_path.exists():
        print("\nGarmin token not found; skipping live API probe")
        return

    client = await GarminClient.from_token_path(token_path)
    today = date.today()
    print(f"\n=== Live Garmin API probe for {today} ===")

    probes: list[tuple[str, object]] = [
        ("get_stress_data", client.get_stress_data(today)),
        ("get_training_readiness", client.get_training_readiness(today)),
        ("get_daily_stats", client.get_daily_stats(today)),
        ("get_sleep_data", client.get_sleep_data(today)),
        ("get_hrv_data", client.get_hrv_data(today)),
    ]

    # Extra methods if garminconnect exposes them
    sync_client = client._client
    extra_methods = [
        name
        for name in dir(sync_client)
        if any(k in name.lower() for k in ("recap", "insight", "summary", "report", "wellness", "daily"))
        and not name.startswith("_")
        and callable(getattr(sync_client, name))
    ]
    print(f"Interesting garminconnect methods: {sorted(extra_methods)[:30]}")

    for label, coro in probes:
        try:
            data = await coro
            blob = json.dumps(data, default=str)
            hits = [t for t in SEARCH_TERMS if t.lower() in blob.lower()]
            print(f"\n{label}: {len(blob)} chars, hits={hits}")
            if hits:
                print(blob[:1200])
        except Exception as exc:
            print(f"\n{label}: ERROR {exc}")

    # Try promising methods dynamically
    for method_name in extra_methods:
        if method_name in {
            "get_stress_data",
            "get_training_readiness",
            "get_stats",
            "get_sleep_data",
            "get_hrv_data",
            "get_body_battery",
            "get_activities",
            "get_activity",
        }:
            continue
        method = getattr(sync_client, method_name)
        try:
            result = await asyncio.to_thread(method, today.isoformat())
            blob = json.dumps(result, default=str)
            hits = [t for t in SEARCH_TERMS if t.lower() in blob.lower()]
            if hits or "message" in blob.lower() or "description" in blob.lower():
                print(f"\n{method_name}: hits={hits}, size={len(blob)}")
                print(blob[:1500])
        except Exception:
            pass


async def main() -> None:
    await search_db()
    await probe_garmin_api()


if __name__ == "__main__":
    asyncio.run(main())
