"""Compact projections of stored Garmin performance raw payloads."""

from __future__ import annotations

import re
from datetime import date
from typing import Any

RESOURCE_TYPES: tuple[str, ...] = (
    "endurance_score",
    "hill_score",
    "running_tolerance",
    "training_status",
    "race_predictions",
    "vo2_max",
    "heat_acclimation",
    "running_economy",
    "stamina_curve",
    "power_curve",
    "lactate_threshold",
    "respiration",
    "spo2_acclimation",
    "heart_rate",
    "weight",
    "devices",
    "solar_gain",
)

OFTEN_EMPTY: tuple[str, ...] = (
    "hill_score",
    "running_economy",
    "stamina_curve",
    "power_curve",
    "weight",
)

ACTIVITY_FIELDS_ALREADY_STORED: tuple[str, ...] = (
    "avgGradeAdjustedSpeed",
    "summaryDTO.beginPotentialStamina",
    "summaryDTO.endPotentialStamina",
    "summaryDTO.minAvailableStamina",
)

_DATE_IN_TEXT = re.compile(r"\d{4}-\d{2}-\d{2}")
_SENSITIVE_FRAGMENTS = (
    "serial",
    "email",
    "token",
    "image",
    "userprofile",
    "userid",
)
_CAPABILITY_FLAG_HINTS = ("stamina", "epic", "economy", "solar", "secondaryworkout")


def project_performance_records(
    rows: Any,
    *,
    start: date,
    end: date,
) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = {rtype: [] for rtype in RESOURCE_TYPES}

    for row in rows:
        resource_type, provider_record_id, payload = _row_parts(row)
        if resource_type not in grouped or not isinstance(payload, dict):
            continue
        if not _row_in_window(provider_record_id, payload, start=start, end=end):
            continue
        projected = _project_row(resource_type, provider_record_id, payload)
        if projected is None:
            continue
        grouped[resource_type].append(projected)

    metrics: dict[str, list[dict[str, Any]]] = {}
    for resource_type, items in grouped.items():
        if not items:
            continue
        if resource_type == "devices":
            metrics[resource_type] = items
            continue
        metrics[resource_type] = sorted(
            items,
            key=lambda item: str(item.get("date") or ""),
        )

    return {
        "window": {"start": start.isoformat(), "end": end.isoformat()},
        "notes": {
            "use_only_fields_present": True,
            "often_empty_on_enduro_3": list(OFTEN_EMPTY),
            "activity_fields_already_on_activities": list(ACTIVITY_FIELDS_ALREADY_STORED),
            "no_separate_series": [
                "stamina zones",
                "grade-adjusted pace workout targets",
                "Garmin Epic aggregation",
            ],
        },
        "metrics": metrics,
    }


def _row_parts(row: Any) -> tuple[str, str, dict[str, Any]]:
    if isinstance(row, tuple):
        if len(row) < 3:
            raise ValueError("row tuple must include resource_type, provider_record_id, payload")
        resource_type, provider_record_id, payload = row[0], row[1], row[2]
    else:
        resource_type = row.resource_type
        provider_record_id = row.provider_record_id
        payload = row.payload
    if not isinstance(payload, dict):
        return str(resource_type), str(provider_record_id), {}
    return str(resource_type), str(provider_record_id), payload


def _record_day(value: Any) -> date | None:
    text = str(value or "")
    if len(text) >= 10 and text[4:5] == "-" and text[7:8] == "-":
        try:
            return date.fromisoformat(text[:10])
        except ValueError:
            return None
    return None


def _dates_in_text(text: str) -> list[date]:
    found: list[date] = []
    for match in _DATE_IN_TEXT.findall(text):
        parsed = _record_day(match)
        if parsed is not None:
            found.append(parsed)
    return found


def _row_in_window(
    provider_record_id: str,
    payload: dict[str, Any],
    *,
    start: date,
    end: date,
) -> bool:
    if provider_record_id in ("inventory", "latest"):
        return True
    for key in ("calendarDate", "localConnectDate"):
        day = _record_day(payload.get(key))
        if day is not None and start <= day <= end:
            return True
    return any(start <= day <= end for day in _dates_in_text(provider_record_id))


def _is_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    if lowered == "userid":
        return True
    return any(fragment in lowered for fragment in _SENSITIVE_FRAGMENTS)


def _strip_training_nested(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            if _should_drop_training_key(key):
                continue
            cleaned[key] = _strip_training_nested(item)
        return cleaned
    if isinstance(value, list):
        return [_strip_training_nested(item) for item in value]
    return value


def _should_drop_training_key(key: str) -> bool:
    if key in ("imageURL", "deviceName"):
        return True
    if key.endswith("Id") or key.endswith("PK"):
        return True
    return _is_sensitive_key(key)


def _strip_payload(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            if _is_sensitive_key(key) or key in ("deviceId", "serialNumber"):
                continue
            cleaned[key] = _strip_payload(item)
        return cleaned
    if isinstance(value, list):
        return [_strip_payload(item) for item in value]
    return value


def _has_non_null_metric(compact: dict[str, Any]) -> bool:
    for key, value in compact.items():
        if key == "date":
            continue
        if value is not None:
            if isinstance(value, dict):
                if any(item is not None for item in value.values()):
                    return True
            elif isinstance(value, list):
                if value:
                    return True
            else:
                return True
    return False


def _has_numeric_value(value: Any) -> bool:
    if isinstance(value, bool) or value is None:
        return False
    if isinstance(value, (int, float)):
        return True
    if isinstance(value, dict):
        return any(_has_numeric_value(item) for item in value.values())
    if isinstance(value, list):
        return any(_has_numeric_value(item) for item in value)
    return False


def _project_row(
    resource_type: str,
    provider_record_id: str,
    payload: dict[str, Any],
) -> dict[str, Any] | None:
    projectors = {
        "endurance_score": _project_endurance,
        "hill_score": _project_hill,
        "running_tolerance": _project_running_tolerance,
        "training_status": _project_training_status,
        "race_predictions": _project_race_predictions,
        "vo2_max": _project_vo2_max,
        "heat_acclimation": _project_heat_acclimation,
        "running_economy": _project_running_economy,
        "stamina_curve": _project_stamina_curve,
        "power_curve": _project_power_curve,
        "lactate_threshold": _project_lactate_threshold,
        "respiration": _project_respiration,
        "spo2_acclimation": _project_spo2,
        "heart_rate": _project_heart_rate,
        "weight": _project_weight,
        "devices": _project_devices,
        "solar_gain": _project_solar_gain,
    }
    projector = projectors.get(resource_type)
    if projector is None:
        return None
    compact = projector(provider_record_id, payload)
    if compact is None:
        return None
    if resource_type != "devices" and not _has_non_null_metric(compact):
        return None
    return compact


def _project_endurance(_provider_record_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    dto = payload.get("enduranceScoreDTO")
    overall = dto.get("overallScore") if isinstance(dto, dict) else None
    day = _record_day(payload.get("calendarDate")) or _record_day(
        dto.get("calendarDate") if isinstance(dto, dict) else None
    )
    return {
        "date": day.isoformat() if day else None,
        "groupAverage": payload.get("groupAverage"),
        "groupMax": payload.get("groupMax"),
        "overallScore": overall,
    }


def _project_hill(_provider_record_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    overall = payload.get("overallScore")
    if overall is None:
        return None
    day = _record_day(payload.get("calendarDate"))
    return {"date": day.isoformat() if day else None, "overallScore": overall}


def _project_running_tolerance(_provider_record_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    day = _record_day(payload.get("calendarDate"))
    return {
        "date": day.isoformat() if day else None,
        "acuteImpactLoad": payload.get("acuteImpactLoad"),
        "acuteDistance": payload.get("acuteDistance"),
        "acuteTolerance": payload.get("acuteTolerance"),
    }


def _plain_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _mean_of_samples(values: Any) -> float | None:
    if not isinstance(values, list):
        return None
    numbers: list[float] = []
    for item in values:
        candidate = item[-1] if isinstance(item, list) and item else item
        if _plain_number(candidate):
            numbers.append(float(candidate))
    if not numbers:
        return None
    return sum(numbers) / len(numbers)


def _training_status_label(device_row: dict[str, Any]) -> str | None:
    phrase = device_row.get("trainingStatusFeedbackPhrase")
    if isinstance(phrase, str) and phrase.strip():
        return phrase.strip()
    status = device_row.get("trainingStatus")
    if isinstance(status, str) and status.strip():
        return status.strip()
    if isinstance(status, int) and not isinstance(status, bool):
        return str(status)
    return None


def _snapshot_device_rows(snapshot: Any) -> list[dict[str, Any]]:
    if not isinstance(snapshot, dict):
        return []
    status = snapshot.get("mostRecentTrainingStatus")
    latest = status.get("latestTrainingStatusData") if isinstance(status, dict) else None
    if not isinstance(latest, dict):
        return []
    return [row for row in latest.values() if isinstance(row, dict)]


def _project_training_status(_provider_record_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    day = _record_day(payload.get("calendarDate"))
    weekly_training_load = None
    status_label = None
    acute_load = None
    chronic_load = None
    acute_chronic_ratio = None
    devices = payload.get("devices")
    if not isinstance(devices, list):
        devices = _snapshot_device_rows(payload.get("snapshot"))
    if isinstance(devices, list):
        for device_row in devices:
            if not isinstance(device_row, dict):
                continue
            if weekly_training_load is None and _plain_number(device_row.get("weeklyTrainingLoad")):
                weekly_training_load = device_row.get("weeklyTrainingLoad")
            if status_label is None:
                status_label = _training_status_label(device_row)
            acute = device_row.get("acuteTrainingLoadDTO")
            if not isinstance(acute, dict):
                continue
            if acute_load is None and _plain_number(acute.get("dailyTrainingLoadAcute")):
                acute_load = acute.get("dailyTrainingLoadAcute")
            if chronic_load is None and _plain_number(acute.get("dailyTrainingLoadChronic")):
                chronic_load = acute.get("dailyTrainingLoadChronic")
            ratio = acute.get("dailyAcuteChronicWorkloadRatio")
            if acute_chronic_ratio is None and _plain_number(ratio):
                acute_chronic_ratio = ratio

    compact: dict[str, Any] = {
        "date": day.isoformat() if day else None,
        "weeklyTrainingLoad": weekly_training_load,
    }
    if status_label is not None:
        compact["statusLabel"] = status_label
    if acute_load is not None:
        compact["dailyTrainingLoadAcute"] = acute_load
    if chronic_load is not None:
        compact["dailyTrainingLoadChronic"] = chronic_load
    if acute_chronic_ratio is not None:
        compact["dailyAcuteChronicWorkloadRatio"] = acute_chronic_ratio
    if payload.get("trainingLoadBalance") is not None:
        compact["trainingLoadBalance"] = _strip_training_nested(payload["trainingLoadBalance"])
    if payload.get("mostRecentVO2Max") is not None:
        compact["mostRecentVO2Max"] = _strip_training_nested(payload["mostRecentVO2Max"])
    return compact


def _project_race_predictions(_provider_record_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    day = _record_day(payload.get("calendarDate"))
    return {
        "date": day.isoformat() if day else None,
        "time5K": payload.get("time5K"),
        "time10K": payload.get("time10K"),
        "timeHalfMarathon": payload.get("timeHalfMarathon"),
        "timeMarathon": payload.get("timeMarathon"),
    }


def _project_vo2_max(_provider_record_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    generic = payload.get("generic") if isinstance(payload.get("generic"), dict) else {}
    day = _record_day(generic.get("calendarDate"))
    return {
        "date": day.isoformat() if day else None,
        "vo2MaxValue": generic.get("vo2MaxValue"),
        "vo2MaxPreciseValue": generic.get("vo2MaxPreciseValue"),
    }


def _project_heat_acclimation(_provider_record_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    day = _record_day(payload.get("calendarDate"))
    return {
        "date": day.isoformat() if day else None,
        "heatAcclimationPercentage": payload.get("heatAcclimationPercentage"),
        "altitudeAcclimation": payload.get("altitudeAcclimation"),
        "acclimationPercentage": payload.get("acclimationPercentage"),
    }


def _project_running_economy(_provider_record_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    day = _record_day(payload.get("calendarDate"))
    compact: dict[str, Any] = {
        "date": day.isoformat() if day else None,
        "score": payload.get("score"),
    }
    if payload.get("classification") is not None:
        compact["classification"] = payload.get("classification")
    return compact


def _project_stamina_curve(
    provider_record_id: str,
    payload: dict[str, Any],
) -> dict[str, Any] | None:
    day = _record_day(payload.get("calendarDate")) or _record_day(provider_record_id)
    stripped = _strip_payload(payload)
    if not _has_numeric_value(stripped):
        return None
    compact: dict[str, Any] = {"date": day.isoformat() if day else None}
    for key, value in stripped.items():
        if key in ("calendarDate", "localConnectDate"):
            continue
        compact[key] = value
    return compact


def _project_power_curve(provider_record_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    sport, _, suffix = provider_record_id.partition(":")
    day = _record_day(suffix) if suffix else None
    entries = payload.get("entries")
    if not isinstance(entries, list) or not entries:
        return None
    return {
        "date": day.isoformat() if day else None,
        "sport": sport or None,
        "entry_count": len(entries),
    }


def _project_lactate_threshold(provider_record_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    speed_block = payload.get("speed_and_heart_rate")
    power_block = payload.get("power")
    day = None
    if isinstance(speed_block, dict):
        day = _record_day(speed_block.get("calendarDate"))
    if day is None and isinstance(power_block, dict):
        day = _record_day(power_block.get("calendarDate"))
    if day is None and provider_record_id != "latest":
        for parsed in _dates_in_text(provider_record_id):
            day = parsed
            break

    speed = speed_block.get("speed") if isinstance(speed_block, dict) else None
    heart_rate = speed_block.get("heartRate") if isinstance(speed_block, dict) else None
    ftp = None
    if isinstance(power_block, dict):
        ftp = power_block.get("functionalThresholdPower")

    return {
        "date": day.isoformat() if day else None,
        "speed": speed,
        "heartRate": heart_rate,
        "functionalThresholdPower": ftp,
    }


def _project_respiration(_provider_record_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    day = _record_day(payload.get("calendarDate"))
    return {
        "date": day.isoformat() if day else None,
        "avgWakingRespiration": payload.get("avgWakingRespiration"),
        "avgSleepRespiration": payload.get("avgSleepRespiration"),
    }


def _project_spo2(_provider_record_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    day = _record_day(payload.get("calendarDate")) or _record_day(payload.get("localConnectDate"))
    hourly = payload.get("spO2HourlyAverages")
    hourly_count = len(hourly) if isinstance(hourly, list) else 0
    compact: dict[str, Any] = {
        "date": day.isoformat() if day else None,
        "averageSpO2": payload.get("averageSpO2"),
        "lowestSpO2": payload.get("lowestSpO2"),
        "latestSpO2": payload.get("latestSpO2"),
        "hourly_count": hourly_count,
    }
    hourly_mean = _mean_of_samples(hourly)
    if hourly_mean is not None:
        compact["hourlyMeanSpO2"] = hourly_mean
    return compact


def _project_heart_rate(_provider_record_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    values = payload.get("values") if isinstance(payload.get("values"), dict) else {}
    day = _record_day(payload.get("calendarDate"))
    return {
        "date": day.isoformat() if day else None,
        "restingHR": values.get("restingHR"),
        "wellnessMinAvgHR": values.get("wellnessMinAvgHR"),
        "wellnessMaxAvgHR": values.get("wellnessMaxAvgHR"),
    }


def _project_weight(_provider_record_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    day = _record_day(payload.get("calendarDate"))
    weight = payload.get("weight")
    if weight is None and isinstance(payload.get("day"), dict):
        day_obj = payload["day"]
        day = day or _record_day(day_obj.get("calendarDate"))
        weight = day_obj.get("weight")
    return {"date": day.isoformat() if day else None, "weight": weight}


def _capability_flags(device: dict[str, Any]) -> dict[str, bool]:
    flags: dict[str, bool] = {}
    for key, value in device.items():
        if not isinstance(value, bool):
            continue
        lowered = key.lower()
        if any(hint in lowered for hint in _CAPABILITY_FLAG_HINTS):
            flags[key] = value
    return flags


def _project_devices(_provider_record_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    if _provider_record_id != "inventory":
        return None
    devices_out: list[dict[str, Any]] = []
    registered = payload.get("registeredDevices")
    if isinstance(registered, list):
        for device in registered:
            if not isinstance(device, dict):
                continue
            compact: dict[str, Any] = {}
            if device.get("applicationKey") is not None:
                compact["applicationKey"] = device.get("applicationKey")
            if device.get("productDisplayName") is not None:
                compact["productDisplayName"] = device.get("productDisplayName")
            compact.update(_capability_flags(device))
            if compact:
                devices_out.append(compact)
    if not devices_out:
        return None
    return {"devices": devices_out}


def _project_solar_gain(provider_record_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    day = _record_day(payload.get("localConnectDate")) or _record_day(payload.get("calendarDate"))
    if day is None:
        for parsed in _dates_in_text(provider_record_id):
            day = parsed
            break
    return {
        "date": day.isoformat() if day else None,
        "totalActivityTimeGainedMs": payload.get("totalActivityTimeGainedMs"),
    }
