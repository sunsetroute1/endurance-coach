"""Match and backfill Garmin elevation from Samsung export using local dates."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from datetime import date, timedelta
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
OUT = Path(__file__).resolve().parent.parent / "logs" / "backfill_garmin_elevation.sql"


@dataclass(frozen=True)
class GarminActivity:
    id: str
    started_at: str
    run_date: date
    distance_meters: float


@dataclass(frozen=True)
class ElevationRecord:
    local_date: date
    utc_date: date
    distance_meters: float
    elevation_meters: float
    samsung_id: str


def _load_garmin_activities() -> list[GarminActivity]:
    sql = """
    SELECT id, started_at::text, started_at::date::text, distance_meters
    FROM activities
    WHERE provider = 'garmin'
      AND started_at >= '2021-01-01' AND started_at < '2023-01-01'
      AND distance_meters IS NOT NULL
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
    activities: list[GarminActivity] = []
    for line in out.splitlines():
        if not line.strip():
            continue
        activity_id, started_at, run_date, distance = line.split("|")
        activities.append(
            GarminActivity(
                id=activity_id,
                started_at=started_at,
                run_date=date.fromisoformat(run_date),
                distance_meters=float(distance),
            )
        )
    return activities


def _distance_tolerance(distance_meters: float) -> float:
    return max(500.0, distance_meters * 0.02)


def _local_date_from_row(row: dict[str, str]) -> date | None:
    raw = row.get(f"{PREFIX}start_time", "").strip()
    if len(raw) >= 10:
        try:
            return date.fromisoformat(raw[:10])
        except ValueError:
            pass
    start = _parse_timestamp(raw, row.get(f"{PREFIX}time_offset"))
    return start.date() if start else None


def _iter_elevation_records(export_root: Path) -> list[ElevationRecord]:
    base = find_export_dir(export_root)
    rows = read_samsung_csv(_find_csv(base, "com.samsung.shealth.exercise"))
    records: list[ElevationRecord] = []
    for row in rows:
        start = _parse_timestamp(row.get(f"{PREFIX}start_time", ""), row.get(f"{PREFIX}time_offset"))
        local_date = _local_date_from_row(row)
        if start is None or local_date is None:
            continue
        if not (START <= local_date <= END):
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
        records.append(
            ElevationRecord(
                local_date=local_date,
                utc_date=start.date(),
                distance_meters=distance,
                elevation_meters=elev,
                samsung_id=provider_id,
            )
        )
    return records


def _match_garmin(record: ElevationRecord, garmin: list[GarminActivity]) -> GarminActivity | None:
    tolerance = _distance_tolerance(record.distance_meters)
    candidate_dates = {record.local_date, record.utc_date, record.local_date - timedelta(days=1)}
    best: GarminActivity | None = None
    best_score = float("inf")
    for activity in garmin:
        if activity.run_date not in candidate_dates:
            continue
        distance_delta = abs(activity.distance_meters - record.distance_meters)
        if distance_delta > tolerance:
            continue
        date_penalty = 0.0 if activity.run_date == record.local_date else 1000.0
        score = distance_delta + date_penalty
        if score < best_score:
            best = activity
            best_score = score
    return best


def main() -> None:
    garmin = _load_garmin_activities()
    records = _iter_elevation_records(Path("data/samsung_export"))
    statements: list[str] = ["BEGIN;"]
    matched = unmatched = 0

    for record in records:
        activity = _match_garmin(record, garmin)
        if activity is None:
            unmatched += 1
            continue
        matched += 1
        statements.append(
            f"UPDATE activities SET elevation_gain_meters = {record.elevation_meters:.1f} "
            f"WHERE id = '{activity.id}';"
        )

    statements.append("COMMIT;")
    OUT.write_text("\n".join(statements), encoding="utf-8")
    print(f"records={len(records)} matched={matched} unmatched={unmatched}")
    print(f"sql={OUT}")


if __name__ == "__main__":
    main()
