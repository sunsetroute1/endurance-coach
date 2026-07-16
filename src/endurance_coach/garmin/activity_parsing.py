"""Parse detailed Garmin activity fields from stored raw payloads."""

from __future__ import annotations

from typing import Any

from endurance_coach.processor.parsing import as_float, as_int, dig

METERS_PER_MILE = 1609.344
SECONDS_PER_MINUTE = 60.0

TRAINING_EFFECT_LABELS: dict[str, str] = {
    "AEROBIC_BASE": "Base (Low Aerobic)",
    "AEROBIC_LOW": "Low Aerobic",
    "AEROBIC_HIGH": "High Aerobic",
    "ANAEROBIC": "Anaerobic",
    "ANAEROBIC_CAPACITY": "Anaerobic Capacity",
    "ANAEROBIC_POWER": "Anaerobic Power",
    "TEMPO": "Tempo",
    "THRESHOLD": "Threshold",
    "VO2_MAX": "VO2 Max",
    "RECOVERY": "Recovery",
    "MAINTAINING": "Maintaining",
}


def _merged_summary(payload: dict[str, Any]) -> dict[str, Any]:
    summary = payload.get("summary", payload)
    detail = payload.get("detail", {})
    dto = detail.get("summaryDTO", {}) if isinstance(detail, dict) else {}
    if not isinstance(summary, dict):
        summary = {}
    if not isinstance(dto, dict):
        dto = {}
    return {**summary, **dto}


def format_activity_type_name(type_key: str | None, fallback_name: str | None = None) -> str:
    if fallback_name and fallback_name.strip():
        return fallback_name.strip()
    if not type_key:
        return "Unknown"
    return type_key.replace("_", " ").title()


def parse_activity_flags(merged: dict[str, Any], activity_name: str, type_key: str) -> tuple[bool, bool]:
    lowered_type = type_key.lower()
    lowered_name = activity_name.lower()
    is_treadmill = (
        "treadmill" in lowered_type
        or "treadmill" in lowered_name
        or bool(merged.get("treadmill"))
        or bool(merged.get("indoor"))
    )
    is_trail = (
        "trail" in lowered_type
        or "trail" in lowered_name
        or bool(merged.get("trail"))
    )
    return is_treadmill, is_trail


def parse_training_effect(merged: dict[str, Any]) -> dict[str, Any]:
    aerobic = as_float(merged.get("aerobicTrainingEffect") or merged.get("trainingEffect"))
    anaerobic = as_float(merged.get("anaerobicTrainingEffect"))
    label = merged.get("trainingEffectLabel") or merged.get("aerobicTrainingEffectMessage")
    primary_benefit = None
    if isinstance(label, str):
        primary_benefit = TRAINING_EFFECT_LABELS.get(label.upper(), label.replace("_", " ").title())
    return {
        "aerobic": round(aerobic, 1) if aerobic is not None else None,
        "anaerobic": round(anaerobic, 1) if anaerobic is not None else None,
        "primary_benefit": primary_benefit,
    }


def parse_heart_rate_zones(merged: dict[str, Any]) -> dict[str, int | None]:
    zones: dict[str, int | None] = {}
    for zone in range(1, 6):
        seconds = as_float(
            merged.get(f"hrTimeInZone_{zone}")
            or merged.get(f"timeInHrZone{zone}")
            or merged.get(f"timeInHeartRateZone{zone}")
        )
        zones[f"z{zone}_time_min"] = round(seconds / SECONDS_PER_MINUTE) if seconds else 0
    return zones


def _stride_length_meters(value: float | None) -> float | None:
    if value is None:
        return None
    # Garmin stores stride length in centimeters for running activities.
    if value > 10:
        return round(value / 100.0, 2)
    return round(value, 2)


def parse_running_dynamics(merged: dict[str, Any], detail: dict[str, Any]) -> dict[str, float | int | None]:
    dto = detail.get("summaryDTO", merged) if isinstance(detail, dict) else merged
    if not isinstance(dto, dict):
        dto = merged

    cadence = as_float(
        dto.get("averageRunCadence")
        or dto.get("avgCadence")
        or merged.get("averageRunningCadenceInStepsPerMinute")
    )
    max_cadence = as_float(dto.get("maxRunCadence") or merged.get("maxRunCadence"))
    stride = _stride_length_meters(
        as_float(dto.get("avgStrideLength") or dto.get("strideLength") or merged.get("avgStrideLength"))
    )
    vertical_ratio = as_float(dto.get("avgVerticalRatio") or dto.get("verticalRatio") or merged.get("avgVerticalRatio"))
    vertical_osc = as_float(
        dto.get("avgVerticalOscillation")
        or dto.get("verticalOscillation")
        or merged.get("avgVerticalOscillation")
    )
    gct = as_float(
        dto.get("avgGroundContactTime")
        or dto.get("groundContactTime")
        or merged.get("avgGroundContactTime")
    )

    if vertical_osc is not None and vertical_osc > 20:
        vertical_osc = round(vertical_osc / 10.0, 1)

    return {
        "avg_cadence_spm": round(cadence) if cadence is not None else None,
        "max_cadence_spm": round(max_cadence) if max_cadence is not None else None,
        "avg_stride_length_m": stride,
        "avg_vertical_ratio_pct": round(vertical_ratio, 1) if vertical_ratio is not None else None,
        "avg_vertical_oscillation_cm": round(vertical_osc, 1) if vertical_osc is not None else None,
        "avg_ground_contact_time_ms": round(gct) if gct is not None else None,
    }


def parse_pace_splits(detail: dict[str, Any]) -> list[dict[str, int | float | None]]:
    if not isinstance(detail, dict):
        return []

    laps = detail.get("lapDTOs") or []
    if not isinstance(laps, list):
        return []

    splits: list[dict[str, int | float | None]] = []
    for lap in laps:
        if not isinstance(lap, dict):
            continue
        duration = as_float(lap.get("duration") or lap.get("movingDuration"))
        if duration is None or duration <= 0:
            continue
        mile_index = as_int(lap.get("lapIndex")) or len(splits) + 1
        splits.append(
            {
                "mile": mile_index,
                "time_sec": round(duration),
                "avg_hr": as_int(lap.get("averageHR") or lap.get("avgHr")),
            }
        )
    return splits


def pace_min_per_mile(distance_meters: float | None, duration_seconds: int | None) -> float | None:
    if not distance_meters or not duration_seconds or distance_meters <= 0:
        return None
    miles = distance_meters / METERS_PER_MILE
    if miles <= 0:
        return None
    return round((duration_seconds / SECONDS_PER_MINUTE) / miles, 2)


def type_key_from_payload(payload: dict[str, Any], merged: dict[str, Any]) -> str:
    detail = payload.get("detail", {})
    return str(
        dig(merged, "activityType", "typeKey")
        or dig(merged, "activityTypeDTO", "typeKey")
        or dig(detail, "activityTypeDTO", "typeKey")
        or merged.get("activity_type", "unknown")
    )
