"""Tests for timezone helpers."""

from datetime import datetime
from zoneinfo import ZoneInfo

from endurance_coach.timezone_util import now_local, today_local


def test_today_local_uses_configured_timezone() -> None:
    # 2026-07-16 02:51 UTC is still 2026-07-15 evening in Denver (MDT, UTC-6).
    frozen_utc = datetime(2026, 7, 16, 2, 51, tzinfo=ZoneInfo("UTC"))

    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz == ZoneInfo("America/Denver"):
                return frozen_utc.astimezone(ZoneInfo("America/Denver"))
            return frozen_utc

    import endurance_coach.timezone_util as tz_module

    original_datetime = tz_module.datetime
    tz_module.datetime = FixedDatetime  # type: ignore[misc]
    try:
        assert today_local("America/Denver").isoformat() == "2026-07-15"
        local_now = now_local("America/Denver")
        assert local_now.date().isoformat() == "2026-07-15"
        assert local_now.utcoffset().total_seconds() == -6 * 3600
    finally:
        tz_module.datetime = original_datetime
