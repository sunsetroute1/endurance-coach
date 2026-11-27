"""Explain stored Garmin coverage without filling gaps."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

API_LIMITS: dict[str, dict[str, Any]] = {
    "endurance_score": {
        "maximum_chunk_days": 28,
        "kind": "daily_series",
        "recovery": "recoverable",
        "note": (
            "History from 2025-11-01 is stored. Garmin omitted 2026-06-21. "
            "The default sync asks for 30 days. A metric backfill skips activity files."
        ),
    },
    "running_tolerance": {
        "maximum_chunk_days": 28,
        "kind": "daily_series",
        "recovery": "recoverable",
        "note": "The stored series begins 2025-11-14. Earlier November 2025 days were empty.",
    },
    "training_status": {
        "maximum_chunk_days": 28,
        "kind": "daily_series",
        "recovery": "recoverable",
        "note": (
            "Weekly training-status rows include acute and chronic load. "
            "weeklyTrainingLoad is often null."
        ),
    },
    "race_predictions": {
        "maximum_chunk_days": 28,
        "kind": "daily_series",
        "recovery": "recoverable",
        "note": "The stored series begins 2025-11-06. Garmin omitted 2026-06-21.",
    },
    "respiration": {
        "maximum_chunk_days": 28,
        "kind": "daily_series",
        "recovery": "recoverable",
        "note": "History from 2025-11-01 is stored. Garmin omitted 2026-06-21.",
    },
    "heart_rate": {
        "maximum_chunk_days": 27,
        "kind": "daily_series",
        "recovery": "recoverable",
        "note": (
            "A span of 28 days is rejected. 27 days is the verified chunk. "
            "Resting heart rate is on this series."
        ),
    },
    "heat_acclimation": {
        "maximum_chunk_days": 28,
        "kind": "daily_series",
        "recovery": "recoverable",
        "note": "History from 2025-11-01 is stored with no missing day in that span.",
    },
    "hrv": {
        "maximum_chunk_days": 28,
        "kind": "daily_series",
        "recovery": "recoverable_where_garmin_has_a_night",
        "note": (
            "A range backfill filled missed nights from 2025-11-01. "
            "Nights Garmin omitted stay missing. The summary has no resting heart rate."
        ),
    },
    "spo2_acclimation": {
        "maximum_chunk_days": 1,
        "kind": "daily_series",
        "recovery": "partial",
        "note": (
            "Hourly SpO2 is stored from 2026-09-01. Sample days in April 2026 and "
            "November 2025 were empty and are not requested again."
        ),
    },
    "vo2_max": {
        "maximum_chunk_days": None,
        "kind": "snapshot",
        "recovery": "unavailable",
        "note": (
            "The date-range endpoint returned an empty list. "
            "Only the latest snapshot is stored."
        ),
    },
    "lactate_threshold": {
        "maximum_chunk_days": None,
        "kind": "snapshot",
        "recovery": "unavailable",
        "note": "The date-range series was empty. Only the latest snapshot is stored.",
    },
    "hill_score": {
        "maximum_chunk_days": 28,
        "kind": "daily_series",
        "recovery": "unavailable_on_this_account",
        "note": (
            "The collector stores a day only when a score is present. "
            "The last sync saved none."
        ),
    },
}

ACTIVITY_DETAIL_FINDINGS: dict[str, str] = {
    "elevation": (
        "Missing elevation is absent from the stored summary, laps, and GPX export on the "
        "sampled runs. Activity-detail metric names on those runs had no elevation series."
    ),
    "grade_adjusted_speed": (
        "Stored only when the activity summary includes avgGradeAdjustedSpeed. "
        "The sampled detail metrics did not include a grade-adjusted series."
    ),
    "stamina": (
        "Summary begin and end stamina stay on the activity. "
        "directPotentialStamina and directAvailableStamina are stored only for activities "
        "with a collected activity-detail chart."
    ),
    "running_power": (
        "Summary power stays on the activity. directPower samples are stored only for "
        "activities with a collected activity-detail chart."
    ),
    "heart_rate_samples": (
        "Average heart rate stays on the activity. directHeartRate samples are stored "
        "only for activities with a collected activity-detail chart."
    ),
    "cadence": (
        "Summary cadence stays on the activity. directRunCadence samples are stored "
        "only for activities with a collected activity-detail chart."
    ),
    "temperature": (
        "Temperature is present on 15 stored summaries. The sampled detail metrics did not add it."
    ),
}


def missing_date_ranges(days: list[date]) -> list[dict[str, Any]]:
    unique = sorted(set(days))
    if len(unique) < 2:
        return []
    present = set(unique)
    ranges: list[dict[str, Any]] = []
    gap_start: date | None = None
    cursor = unique[0]
    last = unique[-1]
    while cursor <= last:
        if cursor not in present and gap_start is None:
            gap_start = cursor
        if cursor in present and gap_start is not None:
            gap_end = cursor - timedelta(days=1)
            ranges.append(_gap(gap_start, gap_end))
            gap_start = None
        cursor += timedelta(days=1)
    if gap_start is not None:
        ranges.append(_gap(gap_start, last))
    return ranges


def _gap(start: date, end: date) -> dict[str, Any]:
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "days": (end - start).days + 1,
    }


def build_data_quality(
    *,
    series: list[dict[str, Any]],
    activities: dict[str, Any],
    hrv: dict[str, Any],
    last_sync: dict[str, Any] | None,
    default_sync_days: int = 30,
    full_sync_days: int = 365,
) -> dict[str, Any]:
    metrics: dict[str, Any] = {}
    for item in series:
        name = str(item["metric"])
        days = [day for day in item.get("days", []) if isinstance(day, date)]
        limits = API_LIMITS.get(name, {})
        ordered = sorted(set(days))
        metrics[name] = {
            "kind": limits.get("kind", item.get("kind")),
            "earliest": ordered[0].isoformat() if ordered else None,
            "latest": ordered[-1].isoformat() if ordered else None,
            "populated_days": len(ordered),
            "duplicate_rows": item.get("duplicate_rows", 0),
            "missing_ranges": missing_date_ranges(ordered),
            "recovery": limits.get("recovery", "unknown"),
            "maximum_chunk_days": limits.get("maximum_chunk_days"),
            "note": limits.get("note"),
        }
    duplicate_dates = int(hrv.get("duplicate_dates") or 0)
    different_values = int(hrv.get("dates_with_different_values") or 0)
    same_value = max(duplicate_dates - different_values, 0)
    return {
        "default_sync_days": default_sync_days,
        "full_sync_days": full_sync_days,
        "last_successful_sync": last_sync,
        "last_successful_full_sync": None,
        "full_sync_note": (
            "full_sync requests 365 days and re-downloads activity details in that window. "
            "The job row does not store a full_sync flag. Metric history is recovered by a "
            "separate backfill that skips activity files and days already stored."
        ),
        "metrics": metrics,
        "activities": {
            **activities,
            "field_recovery": ACTIVITY_DETAIL_FINDINGS,
        },
        "hrv": {
            "rows": hrv.get("rows"),
            "populated_days": hrv.get("populated_days"),
            "duplicate_dates": duplicate_dates,
            "dates_with_different_values": different_values,
            "dates_with_the_same_value": same_value,
            "resting_heart_rate_rows": hrv.get("resting_heart_rate_rows", 0),
            "aggregation": (
                "Same-day rows are averaged. Missing days are omitted. "
                "Source rows are kept."
            ),
            "duplicate_interpretation": (
                "Most duplicate dates repeat the same nightly value and are extra sync copies. "
                "A date with more than one distinct value is more than one stored measurement, "
                "and those values are averaged rather than discarded."
            ),
            "resting_heart_rate": (
                "Normalized resting heart rate is empty because the HRV payload has no "
                "restingHeartRate field. Resting heart rate comes from the daily heart-rate series."
            ),
        },
        "safeguards": [
            "Missing measurements are omitted and are never treated as zero.",
            "A 90-day baseline is omitted when the stored sample is too small.",
            "Snapshots are not expanded into a fabricated daily history.",
        ],
    }
