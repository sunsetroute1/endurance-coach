"""Categorize Garmin activities backfilled on a given date."""
from __future__ import annotations

import json
import subprocess
from collections import Counter
from datetime import datetime

BACKFILL_SINCE = "2026-07-28 21:24:00+00"


def main() -> None:
    sql = f"""
    SELECT
        provider_record_id,
        payload->'summary'->>'activityName' AS name,
        payload->'summary'->>'startTimeLocal' AS started,
        COALESCE(payload->'summary'->>'manualActivity', 'false') AS manual,
        COALESCE(payload->'summary'->'activityType'->>'typeKey', 'unknown') AS activity_type
    FROM raw_payloads
    WHERE provider = 'garmin'
      AND resource_type = 'activities'
      AND fetched_at >= '{BACKFILL_SINCE}'
    ORDER BY started DESC
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
            "-F",
            "\t",
            "-c",
            sql,
        ],
        text=True,
    )

    rows: list[dict] = []
    for line in out.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) < 5:
            continue
        aid, name, started, manual, activity_type = parts[:5]
        year = started[:4] if started else "unknown"
        rows.append(
            {
                "id": aid,
                "name": name or "",
                "started": started or "",
                "manual": manual.lower() == "true",
                "type": activity_type or "unknown",
                "year": year,
            }
        )

    print(f"backfilled_total: {len(rows)}")
    print("\nBy year:")
    for year, count in sorted(Counter(r["year"] for r in rows).items()):
        print(f"  {year}: {count}")

    print("\nBy activity type:")
    for activity_type, count in Counter(r["type"] for r in rows).most_common(15):
        print(f"  {activity_type}: {count}")

    manual = [r for r in rows if r["manual"]]
    watch = [r for r in rows if not r["manual"]]
    print(f"\nBy source:")
    print(f"  watch/device: {len(watch)}")
    print(f"  manual entry: {len(manual)}")

    mfp = [r for r in rows if "MyFitnessPal" in r["name"]]
    print(f"  MyFitnessPal imports: {len(mfp)}")

    name_patterns = Counter()
    for r in rows:
        name = r["name"]
        if "MyFitnessPal" in name:
            name_patterns["MyFitnessPal import"] += 1
        elif name.startswith("Santa Fe"):
            name_patterns["Santa Fe (location-named)"] += 1
        elif "Treadmill" in name:
            name_patterns["Treadmill"] += 1
        elif "Trail Running" in name or r["type"] == "trail_running":
            name_patterns["Trail running"] += 1
        elif r["type"] == "running":
            name_patterns["Generic running"] += 1
        elif r["type"] == "cycling" or r["type"] == "e_bike_fitness":
            name_patterns["Cycling / e-bike"] += 1
        elif r["type"] == "strength_training":
            name_patterns["Strength"] += 1
        else:
            name_patterns["Other"] += 1

    print("\nBy name/category pattern:")
    for label, count in name_patterns.most_common():
        print(f"  {label}: {count}")

    print("\nOldest backfilled:")
    for r in sorted(rows, key=lambda x: x["started"])[:6]:
        print(f"  {r['started'][:16]} | {r['type']:18} | manual={r['manual']} | {r['name'][:55]}")

    print("\nNewest backfilled (that were missing before today):")
    for r in sorted(rows, key=lambda x: x["started"], reverse=True)[:8]:
        print(f"  {r['started'][:16]} | {r['type']:18} | manual={r['manual']} | {r['name'][:55]}")


if __name__ == "__main__":
    main()
