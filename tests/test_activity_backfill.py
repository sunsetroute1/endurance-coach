"""Tests for Garmin activity backfill helpers."""

from endurance_coach.collector.providers.garmin.activity_backfill import _payload_has_laps


def test_payload_has_laps_true() -> None:
    payload = {"detail": {"lapDTOs": [{"lapIndex": 1, "duration": 600}]}}
    assert _payload_has_laps(payload) is True


def test_payload_has_laps_false_when_missing() -> None:
    assert _payload_has_laps({"detail": {}}) is False
    assert _payload_has_laps({"detail": {"lapDTOs": []}}) is False
