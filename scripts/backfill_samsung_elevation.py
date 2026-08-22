"""Backfill elevation for 2021-2022 activities from Samsung export GPS tracks."""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from sqlalchemy import update

from endurance_coach.collector.providers.samsung.export_parser import (
    EXERCISE_TYPE_NAMES,
    _find_csv,
    _float,
    _parse_timestamp,
    elevation_gain_from_exercise_row,
    find_export_dir,
    read_samsung_csv,
)
from endurance_coach.db.models import ActivityRecord
from endurance_coach.di.container import create_container
from endurance_coach.domain.enums import DataProviderType

PREFIX = "com.samsung.health.exercise."
RUN_TYPES = {key for key in ("1002", "13001", "1006") if key in EXERCISE_TYPE_NAMES}
START = date(2021, 1, 1)
END = date(2022, 12, 31)


def _iter_elevations(export_root: Path) -> list[tuple[str, datetime, float, float]]:
    base = find_export_dir(export_root)
    rows = read_samsung_csv(_find_csv(base, "com.samsung.shealth.exercise"))
    results: list[tuple[str, datetime, float, float]] = []
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
        results.append((provider_id, start.astimezone(UTC), elev, distance))
    return results


async def main() -> None:
    export_root = Path("data/samsung_export")
    elevations = _iter_elevations(export_root)
    print(f"recoverable activities from export: {len(elevations)}")

    container = create_container()
    samsung_updated = garmin_updated = 0
    try:
        async with container.session_factory() as session:
            for provider_id, started_at, elev, distance in elevations:
                samsung_result = await session.execute(
                    update(ActivityRecord)
                    .where(
                        ActivityRecord.provider == DataProviderType.SAMSUNG_HEALTH.value,
                        ActivityRecord.provider_record_id == provider_id,
                    )
                    .values(elevation_gain_meters=elev)
                    .returning(ActivityRecord.id)
                )
                if samsung_result.first():
                    samsung_updated += 1

                garmin_result = await session.execute(
                    update(ActivityRecord)
                    .where(
                        ActivityRecord.provider == DataProviderType.GARMIN.value,
                        ActivityRecord.started_at >= started_at - timedelta(hours=2),
                        ActivityRecord.started_at <= started_at + timedelta(hours=2),
                        ActivityRecord.distance_meters.is_not(None),
                        ActivityRecord.distance_meters >= distance - 500,
                        ActivityRecord.distance_meters <= distance + 500,
                    )
                    .values(elevation_gain_meters=elev)
                    .returning(ActivityRecord.id)
                )
                garmin_updated += len(garmin_result.all())

            await session.commit()
    finally:
        await container.shutdown()

    print(f"samsung updated: {samsung_updated}")
    print(f"garmin matched/updated: {garmin_updated}")


if __name__ == "__main__":
    asyncio.run(main())
