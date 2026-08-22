"""Compare Garmin Connect activities vs local DB (one-off diagnostic)."""
from __future__ import annotations

import asyncio
import subprocess
from collections import Counter
from pathlib import Path

from endurance_coach.collector.providers.garmin.client import GarminClient


async def main() -> None:
    client = await GarminClient.from_token_path(Path.home() / ".garminconnect")
    garmin_ids: dict[str, dict] = {}
    start = 0
    while True:
        batch = await client.get_activities(start=start, limit=50)
        if not batch:
            break
        for summary in batch:
            aid = str(summary.get("activityId"))
            garmin_ids[aid] = {
                "name": summary.get("activityName"),
                "manual": bool(summary.get("manualActivity")),
                "start": str(summary.get("startTimeLocal") or summary.get("startTimeGMT") or "")[:19],
            }
        if len(batch) < 50:
            break
        start += 50

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
            "SELECT provider_record_id FROM activities WHERE provider='garmin'",
        ],
        text=True,
    )
    db_ids = {line.strip() for line in out.splitlines() if line.strip()}

    missing = [aid for aid in garmin_ids if aid not in db_ids]
    missing_manual = [aid for aid in missing if garmin_ids[aid]["manual"]]

    print("garmin_connect_total", len(garmin_ids))
    print("db_garmin_total", len(db_ids))
    print("missing_from_db", len(missing))
    print("missing_manual", len(missing_manual))
    print("in_db_not_in_connect", len(db_ids - set(garmin_ids)))

    by_month = Counter(garmin_ids[aid]["start"][:7] for aid in missing if garmin_ids[aid]["start"])
    print("missing_by_month_top10", by_month.most_common(10))

    print("\nRecent missing:")
    for aid in sorted(missing, key=lambda a: garmin_ids[a]["start"], reverse=True)[:12]:
        g = garmin_ids[aid]
        print(f"  {aid} manual={g['manual']} {g['start']} {g['name']}")

    print("\nManual missing sample:")
    for aid in missing_manual[:12]:
        g = garmin_ids[aid]
        print(f"  {aid} {g['start']} {g['name']}")


if __name__ == "__main__":
    asyncio.run(main())
