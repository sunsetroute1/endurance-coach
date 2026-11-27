"""Resolve Garmin activity start instants.

``startTimeLocal`` is the wall clock where the activity was recorded, and it
has no offset. ``startTimeGMT`` and ``beginTimestamp`` are that same moment
in UTC. ``timeZoneId`` on an activity is a Garmin integer, not an IANA name.
A string zone on the activity is used when Garmin sends one. Otherwise the
caller supplies the server timezone.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from endurance_coach.processor.parsing import parse_datetime
from endurance_coach.timezone_util import as_local, resolve_timezone, server_timezone_name, usable_timezone


def iana_from_garmin_fields(fields: dict[str, Any]) -> str | None:
    """IANA zone named in the activity, when Garmin sent one.

    Numeric ``timeZoneId`` values are ignored. They are an internal index,
    not a timezone name.
    """
    for key in ("timeZone", "timezone", "timeZoneKey"):
        found = _named_zone(fields.get(key))
        if found:
            return found
    found = _named_zone(fields.get("timeZoneId"))
    if found:
        return found
    unit = fields.get("timeZoneUnitDTO")
    if isinstance(unit, dict):
        for key in ("timeZone", "unitKey", "key"):
            found = _named_zone(unit.get(key))
            if found:
                return found
    return None


def activity_timezone(fields: dict[str, Any], timezone: str | None = None) -> str:
    return iana_from_garmin_fields(fields) or usable_timezone(timezone) or server_timezone_name()


def parse_garmin_activity_start(
    fields: dict[str, Any],
    *,
    timezone: str | None = None,
) -> datetime | None:
    """Return the activity start as a UTC instant."""
    started = _utc_instant(fields.get("beginTimestamp")) or _utc_instant(fields.get("startTimeGMT"))
    if started is not None:
        return started

    local_raw = fields.get("startTimeLocal")
    if local_raw is None or isinstance(local_raw, bool):
        return None
    if isinstance(local_raw, (int, float)):
        return None
    try:
        parsed = datetime.fromisoformat(str(local_raw).strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        return parsed.astimezone(UTC)
    zone = resolve_timezone(activity_timezone(fields, timezone))
    return parsed.replace(tzinfo=zone).astimezone(UTC)


def garmin_activity_local_date(
    fields: dict[str, Any],
    *,
    timezone: str | None = None,
) -> date | None:
    """Calendar day of the activity on the athlete's wall clock."""
    local_raw = fields.get("startTimeLocal")
    if isinstance(local_raw, str) and local_raw.strip():
        try:
            return datetime.fromisoformat(local_raw.strip().replace("Z", "+00:00")).date()
        except ValueError:
            pass
    started = parse_garmin_activity_start(fields, timezone=timezone)
    if started is None:
        return None
    return as_local(started, activity_timezone(fields, timezone)).date()


def _named_zone(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    return usable_timezone(value)


def _utc_instant(value: Any) -> datetime | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if text.isdigit():
            value = int(text)
        else:
            return parse_datetime(text)
    if isinstance(value, (int, float)):
        return parse_datetime(value)
    return None
