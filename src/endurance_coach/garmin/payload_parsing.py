"""Parse Garmin wellness fields from raw payloads."""

from __future__ import annotations

from typing import Any

from endurance_coach.processor.parsing import as_int, dig


def parse_resting_heart_rate(payload: dict[str, Any]) -> int | None:
    data = payload.get("data", payload)
    if not isinstance(data, dict):
        return None

    sleep_hr = data.get("sleepHeartRate")
    if isinstance(sleep_hr, dict):
        return as_int(
            sleep_hr.get("restingHeartRate")
            or sleep_hr.get("value")
            or sleep_hr.get("average")
            or sleep_hr.get("avg")
        )

    return as_int(dig(data, "restingHeartRate"))


def parse_sleep_seconds(payload: dict[str, Any]) -> int | None:
    data = payload.get("data", payload)
    if not isinstance(data, dict):
        return None

    daily = data.get("dailySleepDTO", {})
    if not isinstance(daily, dict):
        daily = {}

    total = as_int(dig(data, "sleepTimeSeconds")) or as_int(dig(daily, "sleepTimeSeconds"))
    if total and total > 0:
        return total

    deep = as_int(dig(data, "deepSleepSeconds")) or as_int(dig(daily, "deepSleepSeconds")) or 0
    rem = as_int(dig(data, "remSleepSeconds")) or as_int(dig(daily, "remSleepSeconds")) or 0
    light = as_int(dig(data, "lightSleepSeconds")) or as_int(dig(daily, "lightSleepSeconds")) or 0
    stage_sum = deep + rem + light
    return stage_sum if stage_sum > 0 else None


def parse_weekly_hrv(payload: dict[str, Any]) -> int | None:
    data = payload.get("data", payload)
    if not isinstance(data, dict):
        return None

    weekly = (
        as_int(dig(data, "weeklyAvg"))
        or as_int(dig(data, "hrvSummary", "weeklyAvg"))
        or as_int(dig(data, "lastWeekAvg"))
    )
    return weekly
