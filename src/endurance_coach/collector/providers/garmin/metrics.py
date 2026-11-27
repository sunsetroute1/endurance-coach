"""Split verified garminconnect responses into raw records.

These helpers do not call Garmin. The provider fetches a response, then uses
this module to keep one raw object per day without renaming Garmin's fields.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

# Live reads on 2026-11-09 accepted a 28-day span for the metrics below and
# rejected a 28-day span for daily heart-rate stats ("cannot be more than 28 days").
VERIFIED_RANGE_SPAN_DAYS = 28
HEART_RATE_SPAN_DAYS = 27
# Garmin's power-curve endpoint accepts cycling and rowing. "running" returns HTTP 400.
POWER_CURVE_SPORTS = ("cycling", "rowing")

_STATUS_RE = re.compile(r"API Error (\d{3})")
_DATE_KEYS = ("calendarDate", "localConnectDate", "date", "summaryDate")


def chunk_dates(start: date, end: date, max_span_days: int) -> list[tuple[date, date]]:
    """Inclusive date chunks whose start-to-end difference stays within the span."""
    if max_span_days < 1:
        raise ValueError("max_span_days must be positive")
    if end < start:
        return []
    chunks: list[tuple[date, date]] = []
    cursor = start
    while cursor <= end:
        chunk_end = min(end, cursor + timedelta(days=max_span_days))
        chunks.append((cursor, chunk_end))
        cursor = chunk_end + timedelta(days=1)
    return chunks


def garmin_http_status(exc: BaseException) -> int | None:
    match = _STATUS_RE.search(str(exc))
    if match is None:
        return None
    return int(match.group(1))


def is_missing_garmin_feature(exc: BaseException) -> bool:
    """404 means this account or device does not serve the endpoint."""
    return garmin_http_status(exc) == 404


def is_unsupported_power_sport(exc: BaseException) -> bool:
    """Power curve rejects sports other than cycling and rowing with HTTP 400."""
    if garmin_http_status(exc) == 404:
        return True
    return "invalid activity type" in str(exc).lower()


def record_day(value: Any) -> str | None:
    text = str(value or "")
    if len(text) >= 10 and text[4:5] == "-" and text[7:8] == "-":
        return text[:10]
    return None


def has_measurement(value: Any, key: str = "") -> bool:
    """True when a payload carries a metric, not only ids and empty shells."""
    lowered = key.lower()
    if lowered.endswith(("pk", "id")) or lowered in {"userid", "userprofilepk"}:
        return False
    if isinstance(value, bool) or value is None:
        return False
    if isinstance(value, (int, float)):
        return True
    if isinstance(value, str):
        return False
    if isinstance(value, list):
        return any(has_measurement(item) for item in value)
    if isinstance(value, dict):
        return any(has_measurement(item, child_key) for child_key, item in value.items())
    return False


def _dated_items(items: Any) -> list[tuple[str, dict[str, Any]]]:
    records: list[tuple[str, dict[str, Any]]] = []
    if not isinstance(items, list):
        return records
    for item in items:
        if not isinstance(item, dict) or not has_measurement(item):
            continue
        day = next((record_day(item.get(key)) for key in _DATE_KEYS if item.get(key)), None)
        if day is None:
            continue
        records.append((day, item))
    return records


def endurance_records(payload: Any) -> list[tuple[str, dict[str, Any]]]:
    if not isinstance(payload, dict):
        return []
    groups = payload.get("groupMap")
    if not isinstance(groups, dict):
        return []
    current = payload.get("enduranceScoreDTO")
    current_day = record_day(current.get("calendarDate")) if isinstance(current, dict) else None
    records: list[tuple[str, dict[str, Any]]] = []
    for raw_day, group in groups.items():
        day = record_day(raw_day)
        if day is None or not isinstance(group, dict) or not has_measurement(group):
            continue
        stored = {"calendarDate": day, **group}
        if current_day == day and isinstance(current, dict):
            stored["enduranceScoreDTO"] = current
        records.append((day, stored))
    return records


def hill_records(payload: Any) -> list[tuple[str, dict[str, Any]]]:
    if not isinstance(payload, dict):
        return []
    return _dated_items(payload.get("hillScoreDTOList"))


def tolerance_records(payload: Any) -> list[tuple[str, dict[str, Any]]]:
    return _dated_items(payload)


def training_status_records(
    weekly: Any,
    snapshot: Any | None = None,
) -> list[tuple[str, dict[str, Any]]]:
    by_date: dict[str, list[dict[str, Any]]] = {}
    report = weekly.get("reportData") if isinstance(weekly, dict) else None
    if isinstance(report, dict):
        for rows in report.values():
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                day = record_day(row.get("calendarDate"))
                if day is None:
                    continue
                by_date.setdefault(day, []).append(row)
    records = [
        (day, {"calendarDate": day, "devices": rows})
        for day, rows in sorted(by_date.items())
        if has_measurement(rows)
    ]
    if not isinstance(snapshot, dict) or not has_measurement(snapshot):
        return records
    if records:
        day, payload = records[-1]
        payload["trainingLoadBalance"] = snapshot.get("mostRecentTrainingLoadBalance")
        payload["mostRecentVO2Max"] = snapshot.get("mostRecentVO2Max")
        records[-1] = (day, payload)
        return records
    status = snapshot.get("mostRecentTrainingStatus")
    latest = status.get("latestTrainingStatusData") if isinstance(status, dict) else None
    day = None
    if isinstance(latest, dict):
        for device_row in latest.values():
            if isinstance(device_row, dict):
                day = record_day(device_row.get("calendarDate"))
                if day:
                    break
    if day is None:
        return []
    return [(day, {"calendarDate": day, "snapshot": snapshot})]


def race_prediction_records(payload: Any) -> list[tuple[str, dict[str, Any]]]:
    return _dated_items(payload)


def vo2_records(latest: Any, ranged: Any) -> list[tuple[str, dict[str, Any]]]:
    records = _dated_items(ranged)
    seen = {day for day, _payload in records}
    if not isinstance(latest, dict):
        return records
    generic = latest.get("generic") if isinstance(latest.get("generic"), dict) else {}
    cycling = latest.get("cycling") if isinstance(latest.get("cycling"), dict) else {}
    if not has_measurement(generic) and not has_measurement(cycling):
        return records
    day = record_day(generic.get("calendarDate")) or record_day(cycling.get("calendarDate"))
    if not day:
        return records
    if day in seen:
        return [(existing, latest if existing == day else payload) for existing, payload in records]
    records.append((day, latest))
    return records


def heat_records(payload: Any) -> list[tuple[str, dict[str, Any]]]:
    return _dated_items(payload)


def economy_records(payload: Any) -> list[tuple[str, dict[str, Any]]]:
    return _dated_items(payload)


def stamina_record(day: date, payload: Any) -> list[tuple[str, dict[str, Any]]]:
    if isinstance(payload, dict) and has_measurement(payload):
        return [(day.isoformat(), payload)]
    return []


def power_curve_record(
    sport: str,
    end: date,
    payload: Any,
) -> list[tuple[str, dict[str, Any]]]:
    if not isinstance(payload, dict):
        return []
    entries = payload.get("entries")
    if not isinstance(entries, list) or not entries:
        return []
    return [(f"{sport}:{end.isoformat()}", payload)]


def lactate_records(latest: Any, ranged: Any) -> list[tuple[str, dict[str, Any]]]:
    records: list[tuple[str, dict[str, Any]]] = []
    if isinstance(ranged, dict):
        for series in ranged.values():
            records.extend(_dated_items(series))
    if not isinstance(latest, dict) or not has_measurement(latest):
        return records
    speed = latest.get("speed_and_heart_rate")
    power = latest.get("power")
    day = None
    if isinstance(speed, dict):
        day = record_day(speed.get("calendarDate"))
    if day is None and isinstance(power, dict):
        day = record_day(power.get("calendarDate"))
    record_id = day or "latest"
    if all(existing_id != record_id for existing_id, _payload in records):
        records.append((record_id, latest))
    return records


def respiration_records(payload: Any) -> list[tuple[str, dict[str, Any]]]:
    return _dated_items(payload)


def spo2_record(day: date, payload: Any) -> list[tuple[str, dict[str, Any]]]:
    if isinstance(payload, dict) and has_measurement(payload):
        stored = {"calendarDate": day.isoformat(), **payload}
        return [(day.isoformat(), stored)]
    return []


def hrv_range_records(payload: Any) -> list[tuple[str, dict[str, Any]]]:
    """Split a range HRV response into the same per-day shape the daily call stores."""
    summaries = payload.get("hrvSummaries") if isinstance(payload, dict) else None
    if not isinstance(summaries, list):
        return []
    records: list[tuple[str, dict[str, Any]]] = []
    for item in summaries:
        if not isinstance(item, dict) or not has_measurement(item):
            continue
        day = record_day(item.get("calendarDate"))
        if day is None:
            continue
        records.append((day, {"date": day, "data": item}))
    return records


def heart_rate_records(payload: Any) -> list[tuple[str, dict[str, Any]]]:
    return _dated_items(payload)


def weight_records(payload: Any) -> list[tuple[str, dict[str, Any]]]:
    if not isinstance(payload, dict):
        return []
    dated = _dated_items(payload.get("dateWeightList"))
    if dated:
        return dated
    if has_measurement(payload.get("totalAverage")):
        start = record_day(payload.get("startDate")) or "start"
        end = record_day(payload.get("endDate")) or "end"
        return [(f"{start}:{end}", payload)]
    return []


def device_inventory_record(
    devices: Any,
    primary: Any,
    last_used: Any,
) -> list[tuple[str, dict[str, Any]]]:
    registered = devices if isinstance(devices, list) else []
    if not registered and not isinstance(primary, dict):
        return []
    payload: dict[str, Any] = {"registeredDevices": registered}
    if isinstance(primary, dict):
        payload["primaryTrainingDevice"] = primary
    if isinstance(last_used, dict):
        payload["lastUsed"] = last_used
    return [("inventory", payload)]


def device_ids(devices: Any) -> list[str]:
    if not isinstance(devices, list):
        return []
    found: list[str] = []
    for device in devices:
        if not isinstance(device, dict) or device.get("deviceId") is None:
            continue
        device_id = str(device["deviceId"])
        if device_id not in found:
            found.append(device_id)
    return found


def solar_records(device_id: str, payload: Any) -> list[tuple[str, dict[str, Any]]]:
    if not isinstance(payload, dict):
        return []
    records: list[tuple[str, dict[str, Any]]] = []
    for day, item in _dated_items(payload.get("solarGainDailyDetailDTOList")):
        records.append((f"{device_id}:{day}", {"deviceId": device_id, **item}))
    return records
