"""Application timezone helpers."""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from datetime import UTC, date, datetime, time
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

_WINDOWS_ZONE_MAP = Path(r"C:\Windows\Globalization\Time Zone\timezoneMapping.xml")


def resolve_timezone(name: str) -> ZoneInfo:
    return ZoneInfo(name)


def usable_timezone(name: str | None) -> str | None:
    """Return ``name`` when it is an IANA zone ZoneInfo can load."""
    if name is None:
        return None
    candidate = name.strip()
    if not candidate:
        return None
    try:
        ZoneInfo(candidate)
    except ZoneInfoNotFoundError:
        return None
    return candidate


@lru_cache(maxsize=1)
def server_timezone_name() -> str:
    """IANA timezone of the machine running this process.

    Windows reports a fixed-offset name such as ``Mountain Standard Time``.
    That name is mapped through the OS timezone table to an IANA id so
    daylight-saving rules stay intact.
    """
    local = datetime.now().astimezone().tzinfo
    key = getattr(local, "key", None)
    if isinstance(key, str) and usable_timezone(key):
        return key
    windows_id = _windows_timezone_id()
    if windows_id:
        mapped = _iana_from_windows(windows_id)
        if mapped:
            return mapped
    return "UTC"


def now_local(timezone: str) -> datetime:
    return datetime.now(resolve_timezone(timezone))


def today_local(timezone: str) -> date:
    return now_local(timezone).date()


# Sleep and activity dates are stored on the athlete's wall clock.
ATHLETE_TIMEZONE = "America/Denver"


def calendar_date(value: datetime, timezone: str = ATHLETE_TIMEZONE) -> date:
    """Calendar date of an instant on the athlete's wall clock."""
    return as_local(value, timezone).date()


def as_local(value: datetime, timezone: str) -> datetime:
    """Convert an instant to the athlete's wall clock."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(resolve_timezone(timezone))


def format_local(value: datetime | None, timezone: str) -> str | None:
    if value is None:
        return None
    return as_local(value, timezone).isoformat()


def local_range_bounds(start: date, end: date, timezone: str) -> tuple[datetime, datetime]:
    """UTC instants covering local midnights from ``start`` through ``end``."""
    tz = resolve_timezone(timezone)
    start_at = datetime.combine(start, time.min, tzinfo=tz).astimezone(UTC)
    end_at = datetime.combine(end, time.max, tzinfo=tz).astimezone(UTC)
    return start_at, end_at


def _windows_timezone_id() -> str | None:
    if sys.platform != "win32":
        return None
    import winreg

    try:
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Control\TimeZoneInformation",
        ) as key:
            value, _kind = winreg.QueryValueEx(key, "TimeZoneKeyName")
    except OSError:
        return None
    return value if isinstance(value, str) and value.strip() else None


def _iana_from_windows(windows_id: str) -> str | None:
    if not _WINDOWS_ZONE_MAP.is_file():
        return None
    preferred: str | None = None
    for node in ET.parse(_WINDOWS_ZONE_MAP).getroot().findall("MapTZ"):
        if node.get("WinID") != windows_id:
            continue
        tzid = usable_timezone(node.get("TZID"))
        if tzid is None:
            continue
        if node.get("Region") == "001":
            return tzid
        preferred = preferred or tzid
    return preferred
