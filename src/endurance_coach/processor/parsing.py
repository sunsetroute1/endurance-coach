"""Shared parsing helpers for provider payloads."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any


def dig(data: dict[str, Any], *keys: str, default: Any = None) -> Any:
    current: Any = data
    for key in keys:
        if not isinstance(current, dict):
            return default
        current = current.get(key)
        if current is None:
            return default
    return current


def parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, (int, float)):
        timestamp = value / 1000 if value > 1_000_000_000_000 else value
        return datetime.fromtimestamp(timestamp, tz=UTC)
    text = str(value).replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except ValueError:
        return None


def parse_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def as_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def pace_sec_per_km_from_speed_mps(speed_mps: float | None) -> float | None:
    if speed_mps is None or speed_mps <= 0:
        return None
    return 1000.0 / speed_mps


def pace_from_distance_duration(
    distance_meters: float | None,
    duration_seconds: int | None,
) -> float | None:
    if not distance_meters or not duration_seconds or distance_meters <= 0:
        return None
    return duration_seconds / (distance_meters / 1000.0)
