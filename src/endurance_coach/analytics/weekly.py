"""Monday–Sunday weekly rollup helpers (pure functions, no I/O)."""

from __future__ import annotations

import statistics
from collections.abc import Callable
from datetime import date, timedelta
from typing import Any, TypeVar

T = TypeVar("T")

from endurance_coach.analytics.math import compute_acwr, compute_ctl_atl, compute_tsb
from endurance_coach.db.models import (
    ActivityRecord,
    BodyBatteryRecord,
    HRVRecord,
    SleepRecord,
    StepsRecord,
    StressRecord,
    TrainingReadinessRecord,
)

METERS_TO_MILES = 0.000621371
METERS_TO_FEET = 3.28084

# ~10 years of Mon–Sun buckets; covers typical wearable backfill depth.
MAX_WEEKLY_AGGREGATES_WEEKS = 520


def is_running_activity(activity_type: str) -> bool:
    """True for Garmin/Strava run variants (road, trail, treadmill, track, etc.)."""
    return "run" in activity_type.lower()


def monday_of(value: date) -> date:
    """Return the Monday that starts the ISO week containing `value`."""
    return value - timedelta(days=value.weekday())


def week_end(week_start: date) -> date:
    return week_start + timedelta(days=6)


def iter_week_starts(end_date: date, weeks: int) -> list[date]:
    """Return Monday dates oldest-first for `weeks` complete Mon–Sun buckets."""
    count = max(weeks, 1)
    anchor = monday_of(end_date)
    starts = [anchor - timedelta(days=7 * offset) for offset in range(count - 1, -1, -1)]
    return starts


def iter_week_starts_between(start_date: date, end_date: date) -> list[date]:
    """Return Monday dates oldest-first for every Mon–Sun week overlapping the range."""
    if start_date > end_date:
        start_date, end_date = end_date, start_date
    first = monday_of(start_date)
    last = monday_of(end_date)
    starts: list[date] = []
    current = first
    while current <= last:
        starts.append(current)
        current += timedelta(days=7)
    return starts


def resolve_week_window(
    *,
    end_date: date,
    weeks: int = 12,
    start_date: date | None = None,
    max_weeks: int = MAX_WEEKLY_AGGREGATES_WEEKS,
) -> tuple[list[date], date, date, int]:
    """Resolve week buckets for weekly aggregates (oldest first)."""
    cap = max(max_weeks, 1)
    if start_date is not None:
        week_starts = iter_week_starts_between(start_date, end_date)
        if len(week_starts) > cap:
            week_starts = week_starts[:cap]
    else:
        week_count = max(min(weeks, cap), 1)
        week_starts = iter_week_starts(end_date, weeks=week_count)

    if not week_starts:
        week_starts = [monday_of(end_date)]

    range_start = week_starts[0]
    range_end = week_end(week_starts[-1])
    return week_starts, range_start, range_end, len(week_starts)


def group_by_week(records: list[T], day_of: Callable[[T], date]) -> dict[date, list[T]]:
    grouped: dict[date, list[T]] = {}
    for record in records:
        key = monday_of(day_of(record))
        grouped.setdefault(key, []).append(record)
    return grouped


def _mean(values: list[float]) -> float | None:
    return round(statistics.mean(values), 2) if values else None


def _mean_int(values: list[int]) -> float | None:
    return round(statistics.mean(values), 1) if values else None


def _hours_from_seconds(seconds: int) -> float:
    return round(seconds / 3600, 1)


def _activity_distance_fields(activities: list[ActivityRecord]) -> dict[str, Any]:
    distance_m = sum(activity.distance_meters or 0.0 for activity in activities)
    duration_s = sum(activity.duration_seconds for activity in activities)
    elevation_m = sum(activity.elevation_gain_meters or 0.0 for activity in activities)
    hr_values = [activity.avg_heart_rate for activity in activities if activity.avg_heart_rate]
    return {
        "count": len(activities),
        "duration_s": duration_s,
        "duration_h": _hours_from_seconds(duration_s),
        "distance_m": round(distance_m, 1),
        "distance_mi": round(distance_m * METERS_TO_MILES, 2),
        "elevation_m": round(elevation_m, 1),
        "elevation_ft": round(elevation_m * METERS_TO_FEET, 1),
        "training_load": round(
            sum(activity.training_load or 0.0 for activity in activities),
            1,
        ),
        "avg_hr": round(statistics.mean(hr_values)) if hr_values else None,
    }


def aggregate_activity_week(activities: list[ActivityRecord]) -> dict[str, Any]:
    if not activities:
        return {
            "count": 0,
            "duration_s": 0,
            "duration_h": 0.0,
            "distance_m": 0.0,
            "distance_mi": 0.0,
            "elevation_m": 0.0,
            "elevation_ft": 0.0,
            "training_load": 0.0,
            "avg_hr": None,
        }
    return _activity_distance_fields(activities)


def aggregate_running_week(activities: list[ActivityRecord]) -> dict[str, Any]:
    runs = [activity for activity in activities if is_running_activity(activity.activity_type)]
    if not runs:
        return {
            "count": 0,
            "duration_s": 0,
            "duration_h": 0.0,
            "distance_m": 0.0,
            "distance_mi": 0.0,
            "elevation_m": 0.0,
            "elevation_ft": 0.0,
            "training_load": 0.0,
            "avg_hr": None,
        }
    return _activity_distance_fields(runs)


def aggregate_hrv_week(records: list[HRVRecord]) -> dict[str, Any]:
    if not records:
        return {
            "readings": 0,
            "avg_ms": None,
            "min_ms": None,
            "max_ms": None,
            "avg_rhr": None,
            "min_rhr": None,
        }
    values = [record.hrv_ms for record in records]
    rhr_values = [record.resting_heart_rate for record in records if record.resting_heart_rate]
    return {
        "readings": len(records),
        "avg_ms": _mean(values),
        "min_ms": round(min(values), 1),
        "max_ms": round(max(values), 1),
        "avg_rhr": round(statistics.mean(rhr_values)) if rhr_values else None,
        "min_rhr": min(rhr_values) if rhr_values else None,
    }


def aggregate_sleep_week(records: list[SleepRecord]) -> dict[str, Any]:
    if not records:
        return {"nights": 0, "avg_hours": None, "avg_score": None}
    hours = [record.total_sleep_seconds / 3600 for record in records]
    scores = [record.sleep_score for record in records if record.sleep_score is not None]
    return {
        "nights": len(records),
        "avg_hours": _mean(hours),
        "avg_score": _mean_int(scores) if scores else None,
    }


def aggregate_health_week(
    steps: list[StepsRecord],
    stress: list[StressRecord],
    body_battery: list[BodyBatteryRecord],
) -> dict[str, Any]:
    stress_values = [record.avg_stress for record in stress]
    battery_values = [record.level for record in body_battery]
    return {
        "total_steps": sum(record.total_steps for record in steps) if steps else 0,
        "avg_stress": _mean_int(stress_values),
        "avg_body_battery": _mean_int(battery_values),
    }


def aggregate_training_week(
    readiness: list[TrainingReadinessRecord],
    daily_loads: dict[date, float],
    week_start: date,
) -> dict[str, Any]:
    week_end_date = week_end(week_start)
    readiness_values = [record.readiness_score for record in readiness]
    weekly_load = round(
        sum(daily_loads.get(week_start + timedelta(days=offset), 0.0) for offset in range(7)),
        1,
    )
    ctl, atl = compute_ctl_atl(daily_loads, week_end_date)
    tsb = compute_tsb(ctl, atl)
    chronic = round(ctl, 1)
    acute = round(atl, 1)
    return {
        "avg_readiness": _mean_int(readiness_values),
        "weekly_load": weekly_load,
        "chronic_load": chronic,
        "acute_load": acute,
        "ctl": chronic,
        "atl": acute,
        "tsb": round(tsb, 1),
        "acwr": round(compute_acwr(atl, ctl), 2),
    }


def build_weekly_aggregate_row(
    week_start: date,
    *,
    activities: list[ActivityRecord],
    hrv: list[HRVRecord],
    sleep: list[SleepRecord],
    steps: list[StepsRecord],
    stress: list[StressRecord],
    body_battery: list[BodyBatteryRecord],
    readiness: list[TrainingReadinessRecord],
    daily_loads: dict[date, float],
) -> dict[str, Any]:
    return {
        "week_start": week_start.isoformat(),
        "week_end": week_end(week_start).isoformat(),
        "running": aggregate_running_week(activities),
        "activities": aggregate_activity_week(activities),
        "hrv": aggregate_hrv_week(hrv),
        "sleep": aggregate_sleep_week(sleep),
        "health": aggregate_health_week(steps, stress, body_battery),
        "training": aggregate_training_week(readiness, daily_loads, week_start),
    }
