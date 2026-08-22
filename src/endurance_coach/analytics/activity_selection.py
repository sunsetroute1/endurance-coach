"""Pick the primary workout when multiple activities share a calendar day."""

from __future__ import annotations

from datetime import date
from zoneinfo import ZoneInfo

from endurance_coach.db.models import ActivityRecord

_GENERIC_NAMES = frozenset({"running", "trail running", "run", "unknown"})


def _name_quality_score(name: str | None) -> int:
    if not name:
        return 0
    normalized = name.strip().lower()
    if normalized in _GENERIC_NAMES:
        return 0
    return len(normalized)


def _dedupe_key(activity: ActivityRecord) -> tuple[int, int]:
    distance_bucket = int((activity.distance_meters or 0) // 100)
    duration_bucket = int((activity.duration_seconds or 0) // 60)
    return distance_bucket, duration_bucket


def dedupe_similar_activities(activities: list[ActivityRecord]) -> list[ActivityRecord]:
    """Collapse duplicate sync rows that describe the same workout."""
    best_by_key: dict[tuple[int, int], ActivityRecord] = {}
    for activity in activities:
        key = _dedupe_key(activity)
        current = best_by_key.get(key)
        if current is None or _activity_rank(activity) > _activity_rank(current):
            best_by_key[key] = activity
    return list(best_by_key.values())


def _activity_rank(activity: ActivityRecord) -> tuple[int, int, float, int, int]:
    provider_bonus = 1 if activity.provider == "garmin" else 0
    return (
        provider_bonus,
        _name_quality_score(activity.name),
        activity.elevation_gain_meters or 0,
        activity.duration_seconds or 0,
        int(activity.distance_meters or 0),
    )


def select_primary_activity(
    activities: list[ActivityRecord],
    target_date: date,
    *,
    timezone: str = "America/Denver",
) -> ActivityRecord | None:
    tz = ZoneInfo(timezone)
    day_activities = [
        activity
        for activity in activities
        if activity.started_at.astimezone(tz).date() == target_date
    ]
    if not day_activities:
        return None

    candidates = dedupe_similar_activities(day_activities)
    return max(
        candidates,
        key=lambda activity: (
            activity.elevation_gain_meters or 0,
            activity.distance_meters or 0,
            _name_quality_score(activity.name),
            activity.duration_seconds or 0,
        ),
    )
