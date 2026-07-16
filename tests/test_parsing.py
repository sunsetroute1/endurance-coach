"""Tests for parsing helpers."""

from endurance_coach.processor.parsing import (
    pace_from_distance_duration,
    pace_sec_per_km_from_speed_mps,
    parse_date,
    parse_datetime,
)


def test_parse_datetime_iso() -> None:
    result = parse_datetime("2026-07-14T08:00:00")
    assert result is not None
    assert result.year == 2026


def test_parse_date() -> None:
    assert parse_date("2026-07-14") is not None


def test_pace_from_speed() -> None:
    pace = pace_sec_per_km_from_speed_mps(2.5)
    assert pace is not None
    assert 350 < pace < 450


def test_pace_from_distance_duration() -> None:
    pace = pace_from_distance_duration(10000, 3600)
    assert pace == 360.0
