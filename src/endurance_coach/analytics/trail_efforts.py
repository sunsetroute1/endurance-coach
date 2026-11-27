"""Trail effort filtering and ranking for MCP analytics."""

from __future__ import annotations

from typing import Any, Literal

from endurance_coach.db.models import ActivityRecord
from endurance_coach.timezone_util import as_local

METERS_TO_MILES = 0.000621371
METERS_TO_FEET = 3.28084

TrailRankBy = Literal["vert_duration", "training_load", "pace_terrain"]

VALID_RANK_BY: frozenset[str] = frozenset({"vert_duration", "training_load", "pace_terrain"})


def is_trail_activity(activity: ActivityRecord) -> bool:
    """Trail run if type or name suggests trail terrain."""
    activity_type = activity.activity_type.lower()
    name = activity.name.lower()
    return (
        "trail" in activity_type
        or "trail" in name
        or activity_type == "trail_running"
    )


def _duration_hours(activity: ActivityRecord) -> float:
    return max(activity.duration_seconds / 3600.0, 0.01)


def _distance_meters(activity: ActivityRecord) -> float:
    return max(activity.distance_meters or 0.0, 0.0)


def _pace_sec_per_km(activity: ActivityRecord) -> float | None:
    if activity.avg_pace_sec_per_km and activity.avg_pace_sec_per_km > 0:
        return float(activity.avg_pace_sec_per_km)
    distance_m = _distance_meters(activity)
    if distance_m <= 0:
        return None
    return activity.duration_seconds / (distance_m / 1000.0)


def compute_rank_score(activity: ActivityRecord, rank_by: TrailRankBy) -> float:
    """Higher score = harder/better effort for ranking (descending sort)."""
    elevation_m = activity.elevation_gain_meters or 0.0
    duration_h = _duration_hours(activity)
    load = activity.training_load or 0.0

    if rank_by == "training_load":
        return float(load)

    if rank_by == "vert_duration":
        # Vertical meters gained per hour of moving time.
        return round(elevation_m / duration_h, 2)

    # pace_terrain: steep grade combined with faster pace (lower sec/km).
    # score = (vert_m per km) * (reference_pace / actual_pace)
    # Reference ~10:00/km (600s). Steep + fast trail runs score highest.
    distance_m = _distance_meters(activity)
    pace = _pace_sec_per_km(activity)
    if distance_m <= 0 or pace is None or pace <= 0:
        return round((elevation_m / duration_h) + load, 2)

    vert_per_km = (elevation_m / distance_m) * 1000.0
    reference_pace = 600.0
    return round(vert_per_km * (reference_pace / pace), 2)


def trail_effort_to_dict(
    activity: ActivityRecord,
    *,
    rank_by: TrailRankBy,
    timezone: str = "America/Denver",
) -> dict[str, Any]:
    elevation_m = activity.elevation_gain_meters or 0.0
    distance_m = _distance_meters(activity)
    duration_h = round(_duration_hours(activity), 2)
    pace = _pace_sec_per_km(activity)
    rank_score = compute_rank_score(activity, rank_by)
    started = as_local(activity.started_at, timezone)

    return {
        "id": str(activity.id),
        "provider_activity_id": activity.provider_record_id,
        "date": started.date().isoformat(),
        "name": activity.name,
        "type": activity.activity_type,
        "distance_mi": round(distance_m * METERS_TO_MILES, 2) if distance_m else 0.0,
        "duration_h": duration_h,
        "elevation_m": round(elevation_m, 1),
        "elevation_ft": round(elevation_m * METERS_TO_FEET, 0),
        "training_load": round(activity.training_load or 0.0, 1),
        "avg_hr": activity.avg_heart_rate,
        "avg_pace_sec_per_km": round(pace, 1) if pace else None,
        "rank_by": rank_by,
        "rank_score": rank_score,
    }


def rank_trail_efforts(
    activities: list[ActivityRecord],
    *,
    rank_by: TrailRankBy,
    limit: int = 10,
    timezone: str = "America/Denver",
) -> list[dict[str, Any]]:
    trails = [activity for activity in activities if is_trail_activity(activity)]
    scored = [(compute_rank_score(activity, rank_by), activity) for activity in trails]
    scored.sort(key=lambda pair: pair[0], reverse=True)
    top = scored[: max(limit, 1)]
    return [
        trail_effort_to_dict(activity, rank_by=rank_by, timezone=timezone)
        for _score, activity in top
    ]
