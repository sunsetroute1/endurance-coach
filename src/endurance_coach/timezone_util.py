"""Application timezone helpers."""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo


def resolve_timezone(name: str) -> ZoneInfo:
    return ZoneInfo(name)


def now_local(timezone: str) -> datetime:
    return datetime.now(resolve_timezone(timezone))


def today_local(timezone: str) -> date:
    return now_local(timezone).date()
