"""Tests for Garmin raw payload parsing helpers."""

from endurance_coach.garmin.payload_parsing import (
    parse_resting_heart_rate,
    parse_sleep_seconds,
    parse_weekly_hrv,
)


def test_parse_resting_heart_rate_from_sleep_payload() -> None:
    payload = {
        "date": "2026-07-14",
        "data": {"restingHeartRate": 51, "sleepTimeSeconds": 23580},
    }
    assert parse_resting_heart_rate(payload) == 51


def test_parse_sleep_seconds_from_stage_sum() -> None:
    payload = {
        "date": "2026-07-15",
        "data": {
            "dailySleepDTO": {
                "deepSleepSeconds": 3600,
                "remSleepSeconds": 5400,
                "lightSleepSeconds": 14580,
            }
        },
    }
    assert parse_sleep_seconds(payload) == 23580


def test_parse_weekly_hrv_from_summary() -> None:
    payload = {
        "date": "2026-07-14",
        "data": {"hrvSummary": {"weeklyAvg": 53, "lastNightAvg": 18}},
    }
    assert parse_weekly_hrv(payload) == 53
