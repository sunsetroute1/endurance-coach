"""Compare Samsung export vs DB coverage for a date window."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import date
from pathlib import Path

from sqlalchemy import text

from endurance_coach.collector.providers.samsung.export_parser import (
    _parse_timestamp,
    find_export_dir,
    parse_export_records,
)
from endurance_coach.domain.enums import ResourceType
from endurance_coach.di.container import create_container

START = date(2024, 3, 1)
END = date(2025, 10, 31)


def month_keys(start: date, end: date) -> list[str]:
    months: list[str] = []
    cur = date(start.year, start.month, 1)
    while cur <= end:
        months.append(f"{cur.year:04d}-{cur.month:02d}")
        if cur.month == 12:
            cur = date(cur.year + 1, 1, 1)
        else:
            cur = date(cur.year, cur.month + 1, 1)
    return months


def scan_export(export_root: Path) -> dict[str, object]:
    base = find_export_dir(export_root)
    records = parse_export_records(export_root, start_date=START, end_date=END)
    out: dict[str, object] = {
        "export_dir": str(base),
        "sleep": set(),
        "steps": set(),
        "activities": set(),
        "stress": set(),
        "hrv": set(),
    }

    for record in records:
        kind = record.resource_type.value
        if kind not in out:
            continue
        month = None
        if record.resource_type == ResourceType.ACTIVITIES:
            start = _parse_timestamp(str(record.payload.get("start_time", "")))
            month = f"{start.date().year:04d}-{start.date().month:02d}" if start else None
        elif record.resource_type == ResourceType.HRV:
            month = str(record.payload.get("date", record.provider_record_id))[:7]
        else:
            month = record.provider_record_id[:7]
        if month:
            out[kind].add(month)  # type: ignore[union-attr]

    return out


async def scan_db() -> dict[str, dict[str, dict[str, int]]]:
    container = create_container()
    queries = {
        "sleep": (
            "SELECT to_char(sleep_date, 'YYYY-MM') AS ym, provider, COUNT(*) "
            "FROM sleep_records WHERE sleep_date BETWEEN :s AND :e "
            "GROUP BY 1, 2 ORDER BY 1, 2"
        ),
        "steps": (
            "SELECT to_char(step_date, 'YYYY-MM') AS ym, provider, COUNT(*) "
            "FROM steps_records WHERE step_date BETWEEN :s AND :e "
            "GROUP BY 1, 2 ORDER BY 1, 2"
        ),
        "activities": (
            "SELECT to_char(started_at::date, 'YYYY-MM') AS ym, provider, COUNT(*) "
            "FROM activities WHERE started_at::date BETWEEN :s AND :e "
            "GROUP BY 1, 2 ORDER BY 1, 2"
        ),
        "hrv": (
            "SELECT to_char(recorded_at::date, 'YYYY-MM') AS ym, provider, COUNT(*) "
            "FROM hrv_records WHERE recorded_at::date BETWEEN :s AND :e "
            "GROUP BY 1, 2 ORDER BY 1, 2"
        ),
        "stress": (
            "SELECT to_char(recorded_at::date, 'YYYY-MM') AS ym, provider, COUNT(*) "
            "FROM stress_records WHERE recorded_at::date BETWEEN :s AND :e "
            "GROUP BY 1, 2 ORDER BY 1, 2"
        ),
    }
    out: dict[str, dict[str, dict[str, int]]] = {
        kind: defaultdict(lambda: defaultdict(int)) for kind in queries
    }
    async with container.session_factory() as session:
        for kind, sql in queries.items():
            rows = (await session.execute(text(sql), {"s": START, "e": END})).fetchall()
            for ym, provider, count in rows:
                out[kind][ym][provider] = count
    await container.shutdown()
    return out


def _missing(all_months: list[str], present: set[str]) -> list[str]:
    return [month for month in all_months if month not in present]


async def main() -> None:
    all_months = month_keys(START, END)
    export = scan_export(Path("data/samsung_export"))
    db = await scan_db()

    print(f"Window: {START.isoformat()} to {END.isoformat()} ({len(all_months)} months)")
    print()
    print("=== SAMSUNG EXPORT (newest folder) ===")
    print(f"dir: {export['export_dir']}")
    for kind in ("sleep", "steps", "activities", "stress", "hrv"):
        months = export[kind]  # type: ignore[index]
        missing = _missing(all_months, months)  # type: ignore[arg-type]
        print(f"{kind}: {len(months)}/{len(all_months)} months with data")
        if missing:
            print(f"  missing months: {', '.join(missing)}")

    print()
    print("=== DATABASE (combined providers) ===")
    for kind in ("sleep", "steps", "activities", "hrv", "stress"):
        by_month = db[kind]
        any_provider = {
            month for month in all_months if sum(by_month.get(month, {}).values()) > 0
        }
        samsung = {
            month
            for month in all_months
            if by_month.get(month, {}).get("samsung_health", 0) > 0
        }
        garmin = {
            month for month in all_months if by_month.get(month, {}).get("garmin", 0) > 0
        }
        combined_missing = _missing(all_months, any_provider)
        print(f"{kind}: combined {len(any_provider)}/{len(all_months)} months")
        print(f"  samsung {len(samsung)}, garmin {len(garmin)}")
        if combined_missing:
            print(f"  NO DATA ANY SOURCE: {', '.join(combined_missing)}")
        samsung_missing = _missing(all_months, samsung)
        garmin_missing = _missing(all_months, garmin)
        if samsung_missing:
            print(f"  samsung missing: {', '.join(samsung_missing)}")
        if garmin_missing:
            print(f"  garmin missing: {', '.join(garmin_missing)}")

    print()
    print("=== EXPORT vs DB (samsung_health only) ===")
    for kind in ("sleep", "steps", "activities", "hrv", "stress"):
        export_months = export[kind]  # type: ignore[index]
        db_months = {
            month
            for month in all_months
            if db[kind].get(month, {}).get("samsung_health", 0) > 0
        }
        in_export_not_db = sorted(export_months - db_months)  # type: ignore[operator]
        in_db_not_export = sorted(db_months - export_months)  # type: ignore[operator]
        if in_export_not_db or in_db_not_export:
            print(kind + ":")
            if in_export_not_db:
                print(f"  in export but not DB: {', '.join(in_export_not_db)}")
            if in_db_not_export:
                print(f"  in DB but not export: {', '.join(in_db_not_export)}")

    print()
    print("=== MONTHLY COUNTS ===")
    for kind in ("sleep", "steps", "activities", "hrv", "stress"):
        print(kind + ":")
        for month in all_months:
            counts = db[kind].get(month, {})
            total = sum(counts.values())
            if total:
                detail = ", ".join(f"{provider}={count}" for provider, count in sorted(counts.items()))
                print(f"  {month}: {total} ({detail})")
            else:
                print(f"  {month}: 0")


if __name__ == "__main__":
    asyncio.run(main())
