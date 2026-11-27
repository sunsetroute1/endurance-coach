"""Garmin activity start instants stay on the Mountain wall clock."""

from datetime import UTC, datetime

from endurance_coach.garmin.activity_time import (
    garmin_activity_local_date,
    parse_garmin_activity_start,
)


def test_gmt_and_begin_timestamp_are_the_stored_instant() -> None:
    # 2:15 PM MST is 21:15 UTC. The local string must not be labeled UTC.
    fields = {
        "startTimeLocal": "2026-11-11 14:15:36",
        "startTimeGMT": "2026-11-11 21:15:36",
        "beginTimestamp": 1_794_431_736_000,
    }
    started = parse_garmin_activity_start(fields)
    assert started == datetime(2026, 11, 11, 21, 15, 36, tzinfo=UTC)
    assert garmin_activity_local_date(fields).isoformat() == "2026-11-11"


def test_local_only_wall_clock_uses_mountain_time() -> None:
    # 4:52 PM MST in November is UTC-7, so the instant is 23:52 UTC.
    started = parse_garmin_activity_start(
        {"startTimeLocal": "2026-11-11 16:52:00"},
        timezone="America/Denver",
    )
    assert started == datetime(2026, 11, 11, 23, 52, tzinfo=UTC)


def test_summer_local_wall_clock_uses_daylight_offset() -> None:
    # July is MDT, UTC-6.
    started = parse_garmin_activity_start(
        {"startTimeLocal": "2026-07-15T08:20:26"},
        timezone="America/Denver",
    )
    assert started == datetime(2026, 7, 15, 14, 20, 26, tzinfo=UTC)


def test_numeric_timezone_id_is_not_a_zone_name() -> None:
    from endurance_coach.garmin.activity_time import iana_from_garmin_fields

    assert iana_from_garmin_fields({"timeZoneId": 153}) is None
    assert iana_from_garmin_fields({"timeZone": "America/Denver"}) == "America/Denver"


def test_evening_gmt_keeps_the_local_calendar_day() -> None:
    # 6:30 PM MST is 01:30 UTC the next day. The athlete's day is still the 11th.
    fields = {
        "startTimeLocal": "2026-11-11 18:30:00",
        "startTimeGMT": "2026-11-12 01:30:00",
    }
    assert parse_garmin_activity_start(fields) == datetime(2026, 11, 12, 1, 30, tzinfo=UTC)
    assert garmin_activity_local_date(fields).isoformat() == "2026-11-11"
