"""Serialize domain and ORM records for MCP tool responses."""

from __future__ import annotations

from datetime import date, datetime

from endurance_coach.coach.metrics import (
    injury_risk_factors_from_snapshot,
    injury_risk_level_from_snapshot,
    snapshot_metrics,
    snapshot_to_dict,
)
from endurance_coach.db.models import (
    ActivityRecord,
    HRVRecord,
    SleepRecord,
    TrainingReadinessRecord,
)
from endurance_coach.domain.models import CoachResponse
from endurance_coach.garmin.activity_parsing import build_activity_coaching_metrics

__all__ = [
    "activity_to_dict",
    "activity_to_summary_dict",
    "attach_coaching_metrics",
    "coach_response_to_dict",
    "format_date",
    "format_duration",
    "hrv_to_dict",
    "injury_risk_factors_from_snapshot",
    "injury_risk_level_from_snapshot",
    "readiness_to_dict",
    "sleep_to_dict",
    "snapshot_metrics",
    "snapshot_to_dict",
]


def attach_coaching_metrics(
    row: dict[str, object],
    payload: dict[str, object] | None,
) -> dict[str, object]:
    if payload is None:
        return row
    return {**row, "coaching_metrics": build_activity_coaching_metrics(payload)}


def activity_to_summary_dict(
    activity: ActivityRecord,
    *,
    payload: dict[str, object] | None = None,
) -> dict[str, object]:
    """Compact activity row for multi-month MCP sweeps (no lap/time-series data)."""
    row: dict[str, object] = {
        "id": str(activity.id),
        "provider_activity_id": activity.provider_record_id,
        "name": activity.name,
        "started_at": activity.started_at.isoformat(),
        "date": activity.started_at.date().isoformat(),
        "type": activity.activity_type,
        "duration_s": activity.duration_seconds,
        "distance_m": activity.distance_meters,
        "avg_hr": activity.avg_heart_rate,
        "vert_m": activity.elevation_gain_meters,
        "load": activity.training_load,
    }
    return attach_coaching_metrics(row, payload)


def activity_to_dict(
    activity: ActivityRecord,
    *,
    payload: dict[str, object] | None = None,
) -> dict[str, object]:
    row: dict[str, object] = {
        "id": str(activity.id),
        "provider": activity.provider,
        "provider_activity_id": activity.provider_record_id,
        "name": activity.name,
        "activity_type": activity.activity_type,
        "started_at": activity.started_at.isoformat(),
        "duration_seconds": activity.duration_seconds,
        "distance_meters": activity.distance_meters,
        "avg_heart_rate": activity.avg_heart_rate,
        "max_heart_rate": activity.max_heart_rate,
        "avg_pace_sec_per_km": activity.avg_pace_sec_per_km,
        "elevation_gain_meters": activity.elevation_gain_meters,
        "training_load": activity.training_load,
    }
    return attach_coaching_metrics(row, payload)


def sleep_to_dict(record: SleepRecord) -> dict[str, object]:
    return {
        "sleep_date": record.sleep_date.isoformat(),
        "provider": record.provider,
        "total_sleep_seconds": record.total_sleep_seconds,
        "deep_sleep_seconds": record.deep_sleep_seconds,
        "rem_sleep_seconds": record.rem_sleep_seconds,
        "light_sleep_seconds": record.light_sleep_seconds,
        "awake_seconds": record.awake_seconds,
        "sleep_score": record.sleep_score,
    }


def hrv_to_dict(record: HRVRecord) -> dict[str, object]:
    return {
        "recorded_at": record.recorded_at.isoformat(),
        "provider": record.provider,
        "hrv_ms": record.hrv_ms,
        "resting_heart_rate": record.resting_heart_rate,
        "baseline_ms": record.baseline_ms,
    }


def readiness_to_dict(record: TrainingReadinessRecord) -> dict[str, object]:
    return {
        "recorded_at": record.recorded_at.isoformat(),
        "provider": record.provider,
        "readiness_score": record.readiness_score,
        "hrv_component": record.hrv_component,
        "sleep_component": record.sleep_component,
        "recovery_component": record.recovery_component,
    }


def coach_response_to_dict(response: CoachResponse) -> dict[str, object]:
    return {
        "explanation": response.explanation,
        "recommendations": [
            {
                "category": recommendation.category,
                "action": recommendation.action,
                "rationale": recommendation.rationale,
                "metric_citations": list(recommendation.metric_citations),
            }
            for recommendation in response.recommendations
        ],
        "metrics_used": list(response.metrics_used),
        "confidence": response.confidence,
    }


def format_duration(seconds: int) -> str:
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m {secs}s"


def format_date(value: date | datetime) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    return value.isoformat()
