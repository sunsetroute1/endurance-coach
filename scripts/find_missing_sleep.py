"""Find export sleep dates missing from DB."""

from __future__ import annotations

import asyncio
from datetime import date
from pathlib import Path

from sqlalchemy import text

from endurance_coach.collector.providers.samsung.export_parser import parse_export_records
from endurance_coach.di.container import create_container
from endurance_coach.domain.enums import ResourceType

START = date(2024, 3, 1)
END = date(2025, 10, 31)


async def main() -> None:
    records = parse_export_records(Path("data/samsung_export"), start_date=START, end_date=END)
    export_dates = {
        date.fromisoformat(record.provider_record_id)
        for record in records
        if record.resource_type == ResourceType.SLEEP
    }

    container = create_container()
    async with container.session_factory() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT sleep_date, provider FROM sleep_records "
                    "WHERE sleep_date BETWEEN :s AND :e ORDER BY sleep_date"
                ),
                {"s": START, "e": END},
            )
        ).fetchall()
    await container.shutdown()

    db_dates = {row[0] for row in rows}
    samsung_dates = {row[0] for row in rows if row[1] == "samsung_health"}
    missing_any = sorted(export_dates - db_dates)
    missing_samsung = sorted(export_dates - samsung_dates)

    print(f"Export sleep nights: {len(export_dates)}")
    print(f"DB sleep nights (any): {len(db_dates)}")
    print(f"DB samsung sleep nights: {len(samsung_dates)}")
    print(f"Export dates with no DB row at all: {len(missing_any)}")
    if missing_any:
        print("  ", ", ".join(d.isoformat() for d in missing_any[:20]))
        if len(missing_any) > 20:
            print(f"  ... and {len(missing_any) - 20} more")
    print(f"Export dates missing samsung row: {len(missing_samsung)}")


if __name__ == "__main__":
    asyncio.run(main())
