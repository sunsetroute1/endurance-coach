"""Tests for Garmin activity detail parsing."""

from endurance_coach.garmin.activity_parsing import (
    parse_heart_rate_zones,
    parse_pace_splits,
    parse_running_dynamics,
    parse_training_effect,
    pace_min_per_mile,
)
from tests.fixtures.garmin_payloads import activity_payload


def test_parse_training_effect() -> None:
    merged = activity_payload().payload["summary"]
    result = parse_training_effect(merged)
    assert result["aerobic"] == 1.2
    assert result["anaerobic"] == 0.0
    assert result["primary_benefit"] == "Base (Low Aerobic)"


def test_parse_heart_rate_zones() -> None:
    merged = activity_payload().payload["summary"]
    result = parse_heart_rate_zones(merged)
    assert result["z1_time_min"] == 20
    assert result["z2_time_min"] == 25
    assert result["z3_time_min"] == 5
    assert result["z4_time_min"] == 0
    assert result["z5_time_min"] == 0


def test_parse_running_dynamics() -> None:
    payload = activity_payload().payload
    result = parse_running_dynamics(payload["summary"], payload["detail"])
    assert result["avg_cadence_spm"] == 153
    assert result["max_cadence_spm"] == 185
    assert result["avg_stride_length_m"] == 0.98
    assert result["avg_vertical_ratio_pct"] == 8.5
    assert result["avg_vertical_oscillation_cm"] == 8.2
    assert result["avg_ground_contact_time_ms"] == 298


def test_parse_pace_splits() -> None:
    detail = activity_payload().payload["detail"]
    result = parse_pace_splits(detail)
    assert len(result) == 2
    assert result[0] == {"mile": 1, "time_sec": 600, "avg_hr": 115}
    assert result[1]["mile"] == 2


def test_pace_min_per_mile() -> None:
    assert pace_min_per_mile(1609.344, 600) == 10.0
