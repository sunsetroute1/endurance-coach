"""Audit every Samsung export CSV for Mar 2024 - Oct 2025 date coverage."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path

from endurance_coach.collector.providers.samsung.export_parser import read_samsung_csv, _parse_timestamp, _parse_date

START = date(2024, 3, 1)
END = date(2025, 10, 31)

DATE_KEY_RE = re.compile(
    r"(date|time|day|start|end|recorded|sleep|step|exercise)",
    re.I,
)


def _extract_dates(row: dict[str, str]) -> list[date]:
    found: list[date] = []
    for key, value in row.items():
        if not value or not DATE_KEY_RE.search(key):
            continue
        parsed = _parse_date(value)
        if parsed is None:
            ts = _parse_timestamp(value, row.get("time_offset"))
            parsed = ts.date() if ts else None
        if parsed and START <= parsed <= END:
            found.append(parsed)
    return found


def audit_csv(path: Path) -> dict[str, int | str]:
    rows = read_samsung_csv(path)
    if not rows:
        return {"rows": 0, "in_window": 0, "months": 0, "sample_keys": ""}

    in_window = 0
    months: Counter[str] = Counter()
    for row in rows:
        dates = _extract_dates(row)
        if dates:
            in_window += 1
            for d in dates:
                months[f"{d.year:04d}-{d.month:02d}"] += 1

    return {
        "rows": len(rows),
        "in_window": in_window,
        "months": len(months),
        "month_list": ", ".join(sorted(months.keys())[:24]),
    }


def main() -> None:
    root = Path("data/samsung_export")
    export_dirs = sorted(root.glob("**/samsunghealth_*"))
    print(f"Window: {START} to {END}")
    print(f"Export dirs: {len(export_dirs)}\n")

    for export_dir in export_dirs:
        print(f"{'=' * 80}")
        print(f"DIR: {export_dir.name}")
        print(f"{'=' * 80}")
        csvs = sorted(export_dir.glob("*.csv"))
        interesting = []
        for path in csvs:
            stats = audit_csv(path)
            if stats["in_window"]:
                interesting.append((path.name, stats))
        interesting.sort(key=lambda item: item[1]["in_window"], reverse=True)
        for name, stats in interesting:
            print(
                f"  {name}: rows={stats['rows']} in_window={stats['in_window']} "
                f"months={stats['months']}"
            )
            if stats.get("month_list"):
                print(f"    months: {stats['month_list']}")
        print(f"  ({len(interesting)}/{len(csvs)} files with data in window)\n")


if __name__ == "__main__":
    main()
