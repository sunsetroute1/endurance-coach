"""Garmin body battery payload parsing helpers."""

from __future__ import annotations

from typing import Any

from endurance_coach.processor.parsing import as_int


def _level_from_values_array(values: list[Any]) -> int | None:
    if not values:
        return None
    last = values[-1]
    if isinstance(last, list) and len(last) >= 2:
        return as_int(last[1])
    if isinstance(last, dict):
        return as_int(last.get("bodyBatteryLevel") or last.get("level"))
    return None


def extract_body_battery_day_stats(data: Any) -> tuple[int | None, int | None, int | None, list[int]]:
    """Return end level, charged, drained, and all sampled levels from a payload data node."""
    charged: int | None = None
    drained: int | None = None
    levels: list[int] = []

    day_entry: dict[str, Any] | None = None
    if isinstance(data, list):
        if not data:
            return None, None, None, []
        first = data[0]
        if isinstance(first, dict) and (
            "bodyBatteryValuesArray" in first
            or "bodyBatteryValueDescriptorDTOList" in first
            or "charged" in first
        ):
            day_entry = first
        else:
            for point in data:
                if isinstance(point, dict):
                    level = as_int(point.get("level") or point.get("bodyBatteryLevel"))
                elif isinstance(point, list) and len(point) >= 2:
                    level = as_int(point[1])
                else:
                    level = None
                if level is not None:
                    levels.append(level)
            if levels:
                return levels[-1], None, None, levels
            return None, None, None, []
    elif isinstance(data, dict):
        day_entry = data

    if day_entry is None:
        return None, None, None, []

    charged = as_int(day_entry.get("charged"))
    drained = as_int(day_entry.get("drained"))
    values = day_entry.get("bodyBatteryValuesArray") or day_entry.get(
        "bodyBatteryValueDescriptorDTOList"
    )
    if isinstance(values, list):
        for point in values:
            if isinstance(point, list) and len(point) >= 2:
                level = as_int(point[1])
            elif isinstance(point, dict):
                level = as_int(point.get("bodyBatteryLevel") or point.get("level"))
            else:
                level = None
            if level is not None:
                levels.append(level)

    end_level = levels[-1] if levels else None
    if end_level is None:
        end_level = as_int(day_entry.get("charged")) or as_int(day_entry.get("chargedValue"))
    return end_level, charged, drained, levels
