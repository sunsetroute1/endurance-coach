"""Coverage gaps, HRV duplicates, and baseline gates."""

from __future__ import annotations

from datetime import date, timedelta

from endurance_coach.garmin.data_quality import build_data_quality, missing_date_ranges


def test_missing_ranges_keep_the_gap_length() -> None:
    start = date(2026, 9, 1)
    days = [start + timedelta(days=offset) for offset in range(40) if offset not in {10, 11, 12}]
    ranges = missing_date_ranges(days)
    assert ranges == [{"start": "2026-09-11", "end": "2026-09-13", "days": 3}]


def test_hrv_duplicates_stay_distinct_from_missing_days() -> None:
    report = build_data_quality(
        series=[
            {
                "metric": "hrv",
                "days": [date(2026, 11, 1), date(2026, 11, 3)],
                "duplicate_rows": 1,
            }
        ],
        activities={"activities": 2, "elevation": 1},
        hrv={
            "rows": 3,
            "populated_days": 2,
            "duplicate_dates": 1,
            "dates_with_different_values": 0,
            "resting_heart_rate_rows": 0,
        },
        last_sync={"completed_at": "2026-11-09T00:00:00+00:00", "resources_synced": {}},
    )
    assert report["metrics"]["hrv"]["missing_ranges"] == [
        {"start": "2026-11-02", "end": "2026-11-02", "days": 1}
    ]
    assert report["hrv"]["dates_with_the_same_value"] == 1
    assert report["hrv"]["dates_with_different_values"] == 0
    assert report["hrv"]["resting_heart_rate_rows"] == 0
    assert report["last_successful_full_sync"] is None
    assert "never treated as zero" in " ".join(report["safeguards"])
