"""Compare Samsung export parse counts vs DB for Mar 2024 - Oct 2025."""

from __future__ import annotations

import asyncio
from collections import Counter
from datetime import date

from sqlalchemy import text

from endurance_coach.collector.providers.samsung.export_parser import parse_export_records
from endurance_coach.di.container import create_container
from endurance_coach.domain.enums import ResourceType
from pathlib import Path

START = date(2024, 3, 1)
END = date(2025, 10, 31)


async def main() -> None:
    records = parse_export_records(Path("data/samsung_export"), start_date=START, end_date=END)
    by_type = Counter(r.resource_type.value for r in records)
    print("Parsed from export:", dict(by_type))

    container = create_container()
    async with container.session_factory() as session:
        queries = {
            "sleep": (
                "SELECT COUNT(*) FROM sleep_records WHERE provider='samsung_health' "
                "AND sleep_date BETWEEN :s AND :e"
            ),
            "steps": (
                "SELECT COUNT(*) FROM steps_records WHERE provider='samsung_health' "
                "AND step_date BETWEEN :s AND :e"
            ),
            "activities": (
                "SELECT COUNT(*) FROM activities WHERE provider='samsung_health' "
                "AND started_at::date BETWEEN :s AND :e"
            ),
            "hrv": (
                "SELECT COUNT(*) FROM hrv_records WHERE provider='samsung_health' "
                "AND recorded_at::date BETWEEN :s AND :e"
            ),
            "stress": (
                "SELECT COUNT(*) FROM stress_records WHERE provider='samsung_health' "
                "AND recorded_at::date BETWEEN :s AND :e"
            ),
        }
        print("\nDB samsung_health counts:")
        for kind, sql in queries.items():
            count = (await session.execute(text(sql), {"s": START, "e": END})).scalar()
            parsed = by_type.get(kind, 0)
            delta = parsed - count
            print(f"  {kind}: export={parsed} db={count} delta={delta:+d}")
    await container.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
