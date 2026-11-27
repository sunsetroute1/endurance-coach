"""Calculated drift, cadence, stamina, and comparisons."""

from endurance_coach.garmin.activity_efficiency import (
    analyze_activity_samples,
    compare_activity_analyses,
)


def _sample(index: int, *, heart: float, power: float, elevation: float, gap: float | None) -> dict:
    return {
        "elapsed_seconds": float(index),
        "heart_rate_bpm": heart,
        "power_watts": power,
        "speed_mps": 3.0,
        "run_cadence_spm": 85 if index < 30 else 80,
        "step_cadence_spm": 170 if index < 30 else 160,
        "potential_stamina": 90 - index,
        "available_stamina": 80 - index,
        "elevation_meters": elevation,
        "grade_adjusted_speed_mps": gap,
    }


def _steady_then_drift() -> list[dict]:
    rows = []
    for index in range(60):
        heart = 140 if index < 30 else 150
        elevation = 1000 + index
        gap = None if index < 30 else 2.5
        rows.append(_sample(index, heart=heart, power=200, elevation=elevation, gap=gap))
    return rows


def test_drift_uses_power_and_does_not_invent_grade_adjusted_speed() -> None:
    analysis = analyze_activity_samples(_steady_then_drift())
    drift = analysis["cardiovascular_drift"]
    assert drift["selection"] == "power"
    assert drift["available"] is True
    assert drift["heart_rate_change_bpm"] == 10
    assert drift["power"]["output_change"] == 0
    assert drift["grade_adjusted_speed"]["available"] is False
    assert "not substituted" in drift["grade_adjusted_speed"]["note"]


def test_cadence_and_stamina_keep_source_fields() -> None:
    analysis = analyze_activity_samples(_steady_then_drift())
    cadence = analysis["cadence"]["run_cadence"]
    assert cadence["source_field"] == "directRunCadence"
    assert cadence["change_spm"] == -5
    assert cadence["climbing_sample_count"] > 0
    stamina = analysis["stamina"]["potential"]
    assert stamina["source_field"] == "directPotentialStamina"
    assert stamina["depletion"] == 59
    assert analysis["running_power"]["maximum_watts"] == 200


def test_missing_elevation_does_not_invent_a_climbing_split() -> None:
    rows = [_sample(index, heart=140, power=200, elevation=0, gap=2.5) for index in range(60)]
    for row in rows:
        row["elevation_meters"] = None
        row["grade_adjusted_speed_mps"] = 2.5
    analysis = analyze_activity_samples(rows)
    assert analysis["cadence"]["run_cadence"]["climbing_mean_spm"] is None
    assert analysis["cardiovascular_drift"]["grade_adjusted_speed"]["available"] is True


def test_power_drop_is_not_labeled_as_improved_efficiency() -> None:
    rows = []
    for index in range(60):
        power = 200 if index < 30 else 100
        heart = 150 if index < 30 else 140
        rows.append(_sample(index, heart=heart, power=power, elevation=1000, gap=2.5))
    analysis = analyze_activity_samples(rows)
    drift = analysis["cardiovascular_drift"]
    assert drift["available"] is False
    assert drift["reason"] == "output_not_maintained"
    assert drift["labeled_as_improved_efficiency"] is False
    assert "not labeled as improved efficiency" in drift["note"]
    assert analysis["power_fade"]["faded"] is True
    assert analysis["power_fade"]["change_watts"] == -100


def test_null_power_is_left_out_of_the_heart_rate_pair() -> None:
    rows = []
    for index in range(90):
        if index < 30:
            heart, power = 140, 200
        elif index < 60:
            heart, power = 180, None
        else:
            heart, power = 150, 200
        row = _sample(index, heart=heart, power=200, elevation=1000, gap=2.5)
        row["power_watts"] = power
        rows.append(row)
    drift = analyze_activity_samples(rows)["cardiovascular_drift"]
    assert drift["available"] is True
    assert drift["heart_rate_change_bpm"] == 10


def test_pause_gap_is_not_used_as_half_of_the_effort() -> None:
    rows = []
    for index in range(40):
        rows.append(_sample(index, heart=140, power=200, elevation=1000, gap=2.5))
    for index in range(100):
        rows.append(_sample(400 + index, heart=160, power=200, elevation=1000, gap=2.5))
    drift = analyze_activity_samples(rows)["cardiovascular_drift"]
    assert drift["available"] is True
    assert drift["heart_rate_change_bpm"] == 20
    assert drift["sample_count"] < 140


def test_speed_drift_is_withheld_when_the_climb_changes() -> None:
    rows = []
    for index in range(60):
        elevation = 1000 if index < 30 else 1000 + (index - 29) * 2
        heart = 140 if index < 30 else 155
        row = _sample(index, heart=heart, power=0, elevation=elevation, gap=None)
        row["power_watts"] = None
        row["speed_mps"] = 3.0
        rows.append(row)
    drift = analyze_activity_samples(rows)["cardiovascular_drift"]
    assert drift["available"] is False
    assert drift["reason"] == "terrain_changed"


def test_flat_heart_rate_and_speed_is_not_a_drift_result() -> None:
    rows = []
    for index in range(60):
        row = _sample(index, heart=140, power=0, elevation=1000, gap=None)
        row["power_watts"] = None
        row["speed_mps"] = 3.0
        rows.append(row)
    drift = analyze_activity_samples(rows)["cardiovascular_drift"]
    assert drift["available"] is False
    assert drift["reason"] == "series_flat"
    assert drift["labeled_as_improved_efficiency"] is False


def test_comparison_requires_elevation_and_refuses_missing_gap() -> None:
    shared = analyze_activity_samples(_steady_then_drift())
    target = {
        "provider_activity_id": "a",
        "distance_meters": 10000,
        "elevation_gain_meters": 500,
        "duration_seconds": 3700,
        "analysis": shared,
    }
    close = {
        "provider_activity_id": "b",
        "distance_meters": 10500,
        "elevation_gain_meters": 520,
        "duration_seconds": 3600,
        "analysis": shared,
    }
    loose = {
        "provider_activity_id": "d",
        "distance_meters": 10800,
        "elevation_gain_meters": 550,
        "duration_seconds": 9000,
        "analysis": shared,
    }
    far = {
        "provider_activity_id": "c",
        "distance_meters": 20000,
        "elevation_gain_meters": 500,
        "duration_seconds": 3700,
        "analysis": shared,
    }
    report = compare_activity_analyses(target, [target, close, loose, far])
    by_id = {match["provider_activity_id"]: match for match in report["matches"]}
    assert report["match_count"] == 2
    assert by_id["b"]["grade_adjusted_speed"] == "unavailable"
    assert by_id["b"]["effort_review"] == "aligned"
    assert by_id["d"]["effort_review"] == "gates_match_but_effort_differs"
    assert report["threshold_review"]["duration_within_20_percent"] == 1
