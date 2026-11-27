"""Longitudinal comparisons stay inside effort-aligned, high-resolution charts."""

from __future__ import annotations

from datetime import date

from endurance_coach.garmin.longitudinal import build_longitudinal_report


def _chart(
    activity_id: str,
    day: date,
    *,
    heart: float,
    power_first: float = 200,
    power_second: float = 200,
    gap: float | None = 2.5,
    stamina: bool = True,
    distance: float = 10000,
    elevation: float = 500,
    duration: float = 3600,
    median: float = 1,
    status: str = "collected",
) -> dict:
    samples = []
    for index in range(60):
        power = power_first if index < 30 else power_second
        samples.append(
            {
                "elapsed_seconds": float(index),
                "heart_rate_bpm": heart if index % 2 == 0 else heart + 1,
                "power_watts": power,
                "speed_mps": 3.0,
                "potential_stamina": (80 - index) if stamina else None,
                "available_stamina": (70 - index) if stamina else None,
                "elevation_meters": 1000 + index,
                "grade_adjusted_speed_mps": gap,
            }
        )
    return {
        "provider_activity_id": activity_id,
        "local_day": day,
        "status": status,
        "distance_meters": distance,
        "elevation_gain_meters": elevation,
        "duration_seconds": duration,
        "median_interval_seconds": median,
        "samples": samples,
    }


def _aligned(offset: int, heart: float, **overrides: object) -> dict:
    day = date(2026, 5, 1) if offset < 2 else date(2026, 8, 1)
    if offset == 1:
        day = date(2026, 5, 20)
    if offset == 2:
        day = date(2026, 7, 2)
    values = {
        "distance": 10000 + offset * 150,
        "elevation": 500 + offset * 8,
        "duration": 3600 + offset * 40,
    }
    values.update(overrides)
    return _chart(
        f"run-{offset}",
        day,
        heart=heart,
        distance=float(values["distance"]),
        elevation=float(values["elevation"]),
        duration=float(values["duration"]),
        power_first=float(values.get("power_first", 200)),
        power_second=float(values.get("power_second", 200)),
    )


def test_heart_rate_falls_only_when_output_stays_comparable() -> None:
    report = build_longitudinal_report(
        [_aligned(index, 150 if index < 2 else 140) for index in range(4)]
    )
    group = report["comparable_groups"][0]
    heart = group["heart_rate_at_output"]
    assert report["summary"]["heart_rate_at_output_supported"] is True
    assert heart["supported"] is True
    assert heart["direction"] == "lower"
    assert heart["measurement_source"] == "garmin_measurement"
    assert heart["source"] == "calculated"
    assert all(member["labeled_as_improved_efficiency"] is False for member in group["members"])


def test_easier_power_is_not_read_as_a_heart_rate_improvement() -> None:
    runs = [_aligned(index, 150 if index < 2 else 140) for index in range(4)]
    easier = _chart("x", date(2026, 7, 2), heart=140, power_first=150, power_second=150)
    runs[2]["samples"] = easier["samples"]
    easier = _chart("y", date(2026, 8, 1), heart=140, power_first=150, power_second=150)
    runs[3]["samples"] = easier["samples"]
    heart = build_longitudinal_report(runs)["comparable_groups"][0]["heart_rate_at_output"]
    assert heart["supported"] is False
    assert heart["direction"] is None
    assert heart["reason"] == "not_enough_comparable_runs"


def test_output_change_across_months_withholds_the_heart_rate_direction() -> None:
    runs = [_aligned(index, 150 if index < 2 else 140) for index in range(4)]
    for run in runs[2:]:
        for sample in run["samples"]:
            sample["power_watts"] = 216
    heart = build_longitudinal_report(runs)["comparable_groups"][0]["heart_rate_at_output"]
    assert heart["included_run_count"] == 4
    assert heart["supported"] is False
    assert heart["reason"] == "output_not_held_across_months"
    assert heart["direction"] is None


def test_three_runs_do_not_support_a_trend() -> None:
    report = build_longitudinal_report([_aligned(index, 150) for index in range(3)])
    assert report["summary"]["heart_rate_at_output_supported"] is False
    heart = report["comparable_groups"][0]["heart_rate_at_output"]
    assert heart["reason"] == "not_enough_comparable_runs"
    assert heart["direction"] is None


def test_one_month_does_not_support_a_longitudinal_change() -> None:
    runs = [_aligned(index, 150) for index in range(4)]
    for index, run in enumerate(runs):
        run["local_day"] = date(2026, 6, index + 1)
    heart = build_longitudinal_report(runs)["comparable_groups"][0]["heart_rate_at_output"]
    assert heart["supported"] is False
    assert heart["reason"] == "single_month"


def test_duration_mismatch_stays_out_of_the_physiological_group() -> None:
    runs = [_aligned(index, 150) for index in range(4)]
    runs.append(
        _chart(
            "loose",
            date(2026, 8, 2),
            heart=120,
            distance=10600,
            elevation=530,
            duration=9000,
        )
    )
    report = build_longitudinal_report(runs)
    members = report["comparable_groups"][0]["members"]
    assert [member["provider_activity_id"] for member in members] == [
        "run-0",
        "run-1",
        "run-2",
        "run-3",
    ]


def test_power_fade_classification_is_retained() -> None:
    runs = [_aligned(index, 150 if index < 2 else 140) for index in range(4)]
    runs[0] = _aligned(0, 150, power_first=230, power_second=170)
    member = build_longitudinal_report(runs)["comparable_groups"][0]["members"][0]
    assert member["drift_reason"] == "output_not_maintained"
    assert member["power_faded"] is True
    assert member["labeled_as_improved_efficiency"] is False


def test_power_is_tracked_at_a_similar_grade_adjusted_speed() -> None:
    runs = [_aligned(index, 150) for index in range(4)]
    runs.append(_aligned(4, 150))
    for sample in runs[4]["samples"]:
        sample["grade_adjusted_speed_mps"] = 4.0
        sample["power_watts"] = 280
    power = build_longitudinal_report(runs)["comparable_groups"][0]["power_at_grade_adjusted_speed"]
    assert power["included_run_count"] == 4
    assert power["supported"] is True
    assert power["direction"] == "unchanged"


def test_stamina_rates_use_distance_and_climb_and_skip_missing() -> None:
    runs = [_aligned(index, 150) for index in range(4)]
    for sample in runs[3]["samples"]:
        sample["potential_stamina"] = None
        sample["available_stamina"] = None
    stamina = build_longitudinal_report(runs)["comparable_groups"][0]["stamina_depletion"]
    assert stamina["potential_per_km"]["included_run_count"] == 3
    assert stamina["potential_per_km"]["supported"] is False
    rates = build_longitudinal_report(runs[:3])["comparable_groups"][0]["members"][0]
    assert rates["stamina_rates"]["potential_per_km"] is not None
    assert rates["stamina_rates"]["potential_per_100m_climb"] is not None
    assert rates["stamina_rates"]["source"] == "calculated"


def test_coverage_keeps_flat_and_unsupported_charts_visible() -> None:
    flat = _chart("flat", date(2021, 8, 5), heart=140, power_first=0, power_second=0, gap=None)
    for sample in flat["samples"]:
        sample["power_watts"] = None
        sample["heart_rate_bpm"] = 140
        sample["speed_mps"] = 3.0
    flat["median_interval_seconds"] = 30
    unsupported = {
        "provider_activity_id": "old",
        "local_day": date(2021, 3, 20),
        "status": "unsupported",
        "distance_meters": 5000,
        "elevation_gain_meters": None,
        "duration_seconds": 2200,
        "median_interval_seconds": None,
        "samples": [],
    }
    report = build_longitudinal_report(
        [_aligned(0, 150), flat, unsupported]
    )
    qualities = {row["provider_activity_id"]: row for row in report["classifications"]}
    assert qualities["flat"]["sample_quality"] == "series_flat"
    assert qualities["flat"]["drift_reason"] == "series_flat"
    assert qualities["old"]["sample_quality"] == "unsupported"
    assert qualities["old"]["drift_reason"] is None
    assert report["coverage"]["totals"]["high_resolution"] == 1
    assert report["coverage"]["totals"]["series_flat"] == 1
    assert report["coverage"]["totals"]["unsupported"] == 1
    assert report["comparable_groups"] == []
