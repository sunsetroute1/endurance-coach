"""Generate SQL to backfill 2021-2022 elevation from Samsung export."""

from __future__ import annotations

from datetime import UTC, date
from pathlib import Path

from endurance_coach.collector.providers.samsung.export_parser import (
    EXERCISE_TYPE_NAMES,
    _find_csv,
    _float,
    _parse_timestamp,
    elevation_gain_from_exercise_row,
    find_export_dir,
    read_samsung_csv,
)

PREFIX = "com.samsung.health.exercise."
RUN_TYPES = {key for key in ("1002", "13001", "1006") if key in EXERCISE_TYPE_NAMES}
START = date(2021, 1, 1)
END = date(2022, 12, 31)
OUT = Path(__file__).resolve().parent.parent / "logs" / "backfill_samsung_elevation.sql"


def main() -> None:
    base = find_export_dir(Path("data/samsung_export"))
    rows = read_samsung_csv(_find_csv(base, "com.samsung.shealth.exercise"))
    statements: list[str] = ["BEGIN;"]

    count = 0
    for row in rows:
        start = _parse_timestamp(row.get(f"{PREFIX}start_time", ""), row.get(f"{PREFIX}time_offset"))
        if start is None or not (START <= start.date() <= END):
            continue
        if row.get(f"{PREFIX}exercise_type", "") not in RUN_TYPES:
            continue
        elev = elevation_gain_from_exercise_row(base, row)
        if elev is None or elev <= 0:
            continue
        provider_id = row.get(f"{PREFIX}datauuid") or ""
        if not provider_id:
            continue
        distance = _float(row.get(f"{PREFIX}distance")) or 0.0
        started = start.astimezone(UTC)
        run_date = started.date().isoformat()
        dist_min = distance - 500
        dist_max = distance + 500

        statements.append(
            f"UPDATE activities SET elevation_gain_meters = {elev:.1f} "
            f"WHERE provider = 'samsung_health' AND provider_record_id = '{provider_id}';"
        )
        statements.append(
            f"UPDATE activities SET elevation_gain_meters = {elev:.1f} "
            f"WHERE provider = 'garmin' "
            f"AND started_at::date = '{run_date}' "
            f"AND distance_meters BETWEEN {dist_min} AND {dist_max};"
        )
        count += 1

    statements.append("COMMIT;")
    OUT.write_text("\n".join(statements), encoding="utf-8")
    print(f"wrote {count} elevation pairs to {OUT}")


if __name__ == "__main__":
    main()
