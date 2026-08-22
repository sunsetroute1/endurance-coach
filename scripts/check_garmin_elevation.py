"""Check Garmin API elevation availability for activity IDs."""
from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

from endurance_coach.collector.providers.garmin.client import GarminClient


async def main() -> None:
    sql = """
    SELECT a.provider_record_id, EXTRACT(YEAR FROM a.started_at)::int AS yr
    FROM activities a
    JOIN raw_payloads rp ON rp.id = a.source_payload_id
    WHERE a.provider = 'garmin'
      AND EXTRACT(YEAR FROM a.started_at) IN (2021, 2022)
      AND rp.fetched_at >= '2026-07-28 21:24:00+00'
    ORDER BY a.started_at
    LIMIT 40
    """
    out = subprocess.check_output(
        [
            "docker",
            "exec",
            "endurance-postgres",
            "psql",
            "-U",
            "endurance",
            "-d",
            "endurance_coach",
            "-t",
            "-A",
            "-c",
            sql,
        ],
        text=True,
    )
    rows = [line.split("|") for line in out.splitlines() if line.strip()]
    client = await GarminClient.from_token_path(Path.home() / ".garminconnect")

    has_elev = 0
    no_elev = 0
    examples: list[tuple] = []

    for aid, yr in rows:
        detail = await client.get_activity(aid)
        summary_dto = detail.get("summaryDTO", {}) if isinstance(detail, dict) else {}
        elev = summary_dto.get("elevationGain") or (detail.get("elevationGain") if isinstance(detail, dict) else None)
        dist = summary_dto.get("distance") or (detail.get("distance") if isinstance(detail, dict) else None)
        if elev:
            has_elev += 1
            examples.append((aid, yr, elev, dist))
        else:
            no_elev += 1

    print(f"sampled={len(rows)} has_elevation={has_elev} no_elevation={no_elev}")
    for ex in examples[:8]:
        print(f"  elev_found id={ex[0]} year={ex[1]} gain={ex[2]} dist={ex[3]}")

    if rows:
        aid = rows[0][0]
        detail = await client.get_activity(aid)
        print(f"\nFirst activity {aid} detail keys:", sorted(detail.keys()) if isinstance(detail, dict) else detail)
        dto = detail.get("summaryDTO") if isinstance(detail, dict) else None
        if isinstance(dto, dict):
            print("summaryDTO:", {k: dto.get(k) for k in dto if "elev" in k.lower() or k in ("distance", "duration")})


if __name__ == "__main__":
    asyncio.run(main())
