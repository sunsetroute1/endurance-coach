"""Probe Garmin elevation for long 2021-2022 backfilled activities."""
from __future__ import annotations

import subprocess
from pathlib import Path

from garminconnect import Garmin


def main() -> None:
    sql = """
    SELECT a.provider_record_id,
           ROUND((a.distance_meters/1609.34)::numeric, 2) AS mi,
           a.started_at::date
    FROM activities a
    JOIN raw_payloads rp ON rp.id = a.source_payload_id
    WHERE a.provider = 'garmin'
      AND EXTRACT(YEAR FROM a.started_at) IN (2021, 2022)
      AND rp.fetched_at >= '2026-07-28 21:24:00+00'
      AND a.distance_meters > 8000
    ORDER BY a.distance_meters DESC
    LIMIT 15
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

    client = Garmin()
    client.login(str(Path.home() / ".garminconnect"))

    print("Long 2021-2022 runs — elevation from get_activity summaryDTO:")
    for line in out.splitlines():
        if not line.strip():
            continue
        aid, mi, dt = line.split("|")
        act = client.get_activity(aid)
        dto = act.get("summaryDTO", {})
        meta = act.get("metadataDTO", {})
        print(
            f"  {dt} id={aid} mi={mi} "
            f"elev_gain={dto.get('elevationGain')} "
            f"min={dto.get('minElevation')} max={dto.get('maxElevation')} "
            f"corrected={meta.get('elevationCorrected')}"
        )

    # Cross-check list summary for same ID
    aid = out.splitlines()[0].split("|")[0] if out.strip() else None
    if aid:
        found = None
        start = 0
        while start < 900 and not found:
            batch = client.get_activities(start, 100)
            if not batch:
                break
            for s in batch:
                if str(s.get("activityId")) == aid:
                    found = s
                    break
            if len(batch) < 100:
                break
            start += 100
        print(f"\nList summary for {aid}:")
        if found:
            for k in ("elevationGain", "minElevation", "maxElevation", "distance", "duration"):
                print(f"  {k}: {found.get(k)}")
        else:
            print("  not found in first 900 list entries")


if __name__ == "__main__":
    main()
