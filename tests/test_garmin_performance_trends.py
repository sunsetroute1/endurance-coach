"""Historical comparisons, missing data, and window boundaries."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from endurance_coach.garmin.performance_metrics import project_performance_records
from endurance_coach.garmin.performance_trends import build_performance_trends

END = date(2026, 11, 9)


def _run(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "day": END,
        "activity_type": "trail_running",
        "duration_seconds": 3600,
        "distance_meters": 10000,
        "avg_heart_rate": 150,
        "pace_sec_per_km": 360,
        "elevation_meters": 400,
        "training_load": 80,
        "grade_adjusted_speed_mps": 3.0,
        "stamina_begin": 90,
        "stamina_end": 40,
    }
    row.update(overrides)
    return row


def test_ninety_day_baseline_is_omitted_when_only_thirty_days_exist() -> None:
    points = [(date(2026, 10, 11) + timedelta(days=offset), 40.0 + offset) for offset in range(30)]
    report = build_performance_trends(end=END, window_days=28, hrv=points)
    baselines = report["recovery"]["hrv_ms"]["baselines"]
    assert baselines["rolling_28"]["available"] is True
    assert baselines["rolling_28"]["sample_count"] == 28
    assert baselines["rolling_90"]["available"] is False
    assert baselines["rolling_90"]["median"] is None
    assert baselines["rolling_90"]["sample_count"] == 30
    assert baselines["historical_sample_count"] == 30
    assert baselines["historical_median"] is not None
    assert baselines["long_term_direction"] == "insufficient"


def test_window_must_be_one_of_the_supported_lengths() -> None:
    with pytest.raises(ValueError, match="window_days"):
        build_performance_trends(end=END, window_days=14)


def test_missing_days_do_not_pull_the_mean_toward_zero() -> None:
    report = build_performance_trends(
        end=END,
        window_days=7,
        hrv=[(date(2026, 11, 9), 80.0), (date(2026, 11, 2), 40.0)],
    )
    trend = report["recovery"]["hrv_ms"]
    assert trend["current_period_value"] == 80.0
    assert trend["previous_period_value"] == 40.0
    assert trend["absolute_change"] == 40.0
    assert trend["percentage_change"] == 100.0
    assert trend["coverage"]["populated_days"] == 1
    assert trend["coverage"]["missing_days"] == 6
    assert trend["coverage"]["sample_count"] == 1
    assert trend["trend"] == "up"


def test_observation_on_the_window_edge_stays_in_that_window() -> None:
    report = build_performance_trends(
        end=END,
        window_days=7,
        hrv=[
            (date(2026, 11, 3), 70.0),
            (date(2026, 11, 2), 50.0),
            (date(2026, 11, 10), 99.0),
        ],
    )
    trend = report["recovery"]["hrv_ms"]
    assert report["current_period"] == {"start": "2026-11-03", "end": "2026-11-09"}
    assert report["previous_period"] == {"start": "2026-10-27", "end": "2026-11-02"}
    assert trend["current_period_value"] == 70.0
    assert trend["previous_period_value"] == 50.0
    assert trend["current"] == 70.0
    assert trend["history"]["latest"] == "2026-11-10"


def test_duplicate_dates_are_averaged_and_counted() -> None:
    report = build_performance_trends(
        end=END,
        window_days=7,
        hrv=[
            (date(2026, 11, 9), 10.0),
            (date(2026, 11, 9), 30.0),
            (date(2026, 11, 2), 20.0),
        ],
    )
    trend = report["recovery"]["hrv_ms"]
    assert trend["current_period_value"] == 20.0
    assert trend["coverage"]["duplicate_dates"] == 1
    assert trend["coverage"]["populated_days"] == 1


def test_percentage_change_is_omitted_when_the_previous_value_is_zero() -> None:
    report = build_performance_trends(
        end=END,
        window_days=7,
        activities=[
            _run(day=date(2026, 11, 9), training_load=0, distance_meters=5000),
            _run(day=date(2026, 11, 2), training_load=0, distance_meters=0),
        ],
    )
    distance = report["training_load"]["distance_meters"]
    assert distance["current_period_value"] == 5000.0
    assert distance["previous_period_value"] == 0.0
    assert distance["absolute_change"] == 5000.0
    assert distance["percentage_change"] is None
    assert distance["trend"] == "up"


def test_activities_missing_distance_are_excluded_from_the_sum() -> None:
    report = build_performance_trends(
        end=END,
        window_days=7,
        activities=[
            _run(day=date(2026, 11, 9), distance_meters=1000),
            _run(day=date(2026, 11, 8), distance_meters=None),
        ],
    )
    distance = report["training_load"]["distance_meters"]
    assert distance["current_period_value"] == 1000.0
    assert distance["coverage"]["sample_count"] == 1
    assert distance["coverage"]["activities_missing_measurement"] == 1
    assert report["training_load"]["activity_count"]["current_period_value"] == 2.0


def test_vo2_max_snapshot_does_not_invent_a_previous_period() -> None:
    report = build_performance_trends(
        end=END,
        window_days=28,
        performance_metrics={
            "vo2_max": [{"date": "2026-11-09", "vo2MaxValue": 52}],
        },
    )
    snapshot = report["snapshots"]["vo2_max"]
    assert snapshot["kind"] == "snapshot"
    assert snapshot["current"] == 52.0
    assert snapshot["previous_period_value"] is None
    assert snapshot["absolute_change"] is None
    assert snapshot["percentage_change"] is None
    assert snapshot["trend"] == "insufficient"
    assert snapshot["history"]["populated_days"] == 1
    assert "manufactured" in snapshot["note"]


def test_empty_series_reports_zero_coverage_instead_of_zeros() -> None:
    report = build_performance_trends(end=END, window_days=90)
    score = report["endurance"]["endurance_score"]
    assert score["current"] is None
    assert score["current_period_value"] is None
    assert score["trend"] == "insufficient"
    assert score["coverage"]["populated_days"] == 0
    assert score["coverage"]["missing_days"] == 90
    assert score["history"]["populated_days"] == 0


def test_training_status_label_change_is_not_a_numeric_delta() -> None:
    rows = [
        (
            "training_status",
            "2026-11-09",
            {
                "calendarDate": "2026-11-09",
                "devices": [
                    {
                        "weeklyTrainingLoad": 400,
                        "trainingStatusFeedbackPhrase": "PRODUCTIVE",
                    }
                ],
            },
        ),
        (
            "training_status",
            "2026-09-20",
            {
                "calendarDate": "2026-09-20",
                "devices": [
                    {
                        "weeklyTrainingLoad": 300,
                        "trainingStatusFeedbackPhrase": "MAINTAINING",
                    }
                ],
            },
        ),
    ]
    projected = project_performance_records(rows, start=date(2026, 1, 1), end=END)
    report = build_performance_trends(
        end=END,
        window_days=28,
        performance_metrics=projected["metrics"],
    )
    status = report["endurance"]["training_status"]
    assert projected["metrics"]["training_status"][1]["statusLabel"] == "PRODUCTIVE"
    assert status["current"] == "PRODUCTIVE"
    assert status["previous_period_value"] == "MAINTAINING"
    assert status["changed"] is True
    assert status["trend"] == "changed"
    assert status["absolute_change"] is None
    load = report["endurance"]["training_status_load"]
    assert load["current_period_value"] == 400.0
    assert load["previous_period_value"] == 300.0


def test_comparable_runs_require_grade_adjusted_pace_on_both_sides() -> None:
    report = build_performance_trends(
        end=END,
        window_days=28,
        activities=[
            _run(day=date(2026, 11, 9), grade_adjusted_speed_mps=3.0),
            _run(
                day=date(2026, 10, 1),
                grade_adjusted_speed_mps=2.5,
                pace_sec_per_km=400,
            ),
            _run(
                day=date(2026, 11, 8),
                grade_adjusted_speed_mps=None,
                pace_sec_per_km=300,
                distance_meters=10000,
            ),
        ],
    )
    matched = report["mountain_running"]["comparable_runs"]
    assert matched["sample_count"] == 1
    assert matched["absolute_change"] < 0
    assert matched["trend"] == "down"
    pace = report["mountain_running"]["actual_pace_sec_per_km"]
    gap = report["mountain_running"]["grade_adjusted_pace_sec_per_km"]
    assert pace["unit"] == "sec_per_km"
    assert gap["unit"] == "sec_per_km"
    assert gap["source"] == "calculated"
    assert pace["current_period_value"] != gap["current_period_value"]


def test_unmatched_actual_pace_does_not_create_a_comparable_pair() -> None:
    report = build_performance_trends(
        end=END,
        window_days=28,
        activities=[
            _run(day=date(2026, 11, 9), grade_adjusted_speed_mps=None, pace_sec_per_km=300),
            _run(day=date(2026, 10, 20), grade_adjusted_speed_mps=None, pace_sec_per_km=280),
        ],
    )
    matched = report["mountain_running"]["comparable_runs"]
    assert matched["sample_count"] == 0
    assert matched["trend"] == "insufficient"
    assert matched["absolute_change"] is None


def test_acute_chronic_ratio_waits_for_enough_stored_loads() -> None:
    loads = [
        _run(day=date(2026, 11, 9), training_load=40, elevation_meters=0, activity_type="run"),
        _run(day=date(2026, 11, 8), training_load=40, elevation_meters=0, activity_type="run"),
        _run(day=date(2026, 11, 7), training_load=40, elevation_meters=0, activity_type="run"),
    ]
    thin = build_performance_trends(end=END, window_days=28, activities=loads)
    assert thin["training_load"]["acute_versus_chronic_load"]["acute_to_chronic_ratio"] is None
    loads.append(
        _run(day=date(2026, 10, 20), training_load=80, elevation_meters=0, activity_type="run")
    )
    enough = build_performance_trends(end=END, window_days=28, activities=loads)
    ratio = enough["training_load"]["acute_versus_chronic_load"]
    assert ratio["chronic_sample_count"] == 4
    assert ratio["acute_to_chronic_ratio"] is not None
    assert "not zero" in ratio["note"]


def test_recovery_gap_uses_the_next_stored_activity() -> None:
    report = build_performance_trends(
        end=END,
        window_days=28,
        activities=[
            _run(day=date(2026, 11, 1), elevation_meters=500, duration_seconds=3600),
            _run(
                day=date(2026, 11, 4),
                elevation_meters=0,
                activity_type="run",
                duration_seconds=1800,
            ),
            _run(day=date(2026, 10, 10), elevation_meters=500, duration_seconds=3600),
            _run(
                day=date(2026, 10, 12),
                elevation_meters=0,
                activity_type="run",
                duration_seconds=1800,
            ),
        ],
    )
    gaps = report["training_load"]["recovery_between_demanding_sessions"]
    assert gaps["current_period_value"] == 3.0
    assert gaps["previous_period_value"] == 2.0
    assert gaps["coverage"]["sample_count"] == 1


def test_sleep_and_body_battery_stays_an_association() -> None:
    sleep = [(date(2026, 11, day), 6 * 3600) for day in range(1, 5)]
    sleep += [(date(2026, 11, day), 8 * 3600) for day in range(5, 9)]
    battery = [(date(2026, 11, day), 40.0) for day in range(1, 5)]
    battery += [(date(2026, 11, day), 70.0) for day in range(5, 9)]
    report = build_performance_trends(
        end=END,
        window_days=28,
        sleep_seconds=sleep,
        body_battery=battery,
    )
    link = report["recovery"]["sleep_and_body_battery"]
    assert link["kind"] == "association"
    assert link["paired_days"] == 8
    assert link["absolute_difference"] == 30.0
    assert "not show that one caused" in link["note"]


def test_null_weekly_load_uses_stored_acute_load_and_hourly_spo2() -> None:
    rows = [
        (
            "training_status",
            "2026-11-09",
            {
                "calendarDate": "2026-11-09",
                "devices": [
                    {
                        "weeklyTrainingLoad": None,
                        "trainingStatusFeedbackPhrase": "PRODUCTIVE",
                        "acuteTrainingLoadDTO": {
                            "dailyTrainingLoadAcute": 120,
                            "dailyTrainingLoadChronic": 100,
                            "dailyAcuteChronicWorkloadRatio": 1.2,
                        },
                    }
                ],
            },
        ),
        (
            "training_status",
            "2026-09-20",
            {
                "calendarDate": "2026-09-20",
                "devices": [
                    {
                        "weeklyTrainingLoad": None,
                        "trainingStatusFeedbackPhrase": "PRODUCTIVE",
                        "acuteTrainingLoadDTO": {
                            "dailyTrainingLoadAcute": 80,
                            "dailyTrainingLoadChronic": 100,
                            "dailyAcuteChronicWorkloadRatio": 0.8,
                        },
                    }
                ],
            },
        ),
        (
            "spo2_acclimation",
            "2026-11-09",
            {
                "calendarDate": "2026-11-09",
                "averageSpO2": None,
                "latestSpO2": None,
                "spO2HourlyAverages": [[1, 96], [2, None], [3, 94]],
            },
        ),
        (
            "spo2_acclimation",
            "2026-09-20",
            {
                "calendarDate": "2026-09-20",
                "averageSpO2": None,
                "spO2HourlyAverages": [[1, 90], [2, 92]],
            },
        ),
    ]
    projected = project_performance_records(rows, start=date(2026, 1, 1), end=END)
    report = build_performance_trends(
        end=END,
        window_days=28,
        performance_metrics=projected["metrics"],
    )
    load = report["endurance"]["training_status_load"]
    assert load["current_period_value"] == 120.0
    assert load["previous_period_value"] == 80.0
    assert load["trend"] == "up"
    ratio = report["training_load"]["garmin_acute_chronic_ratio"]
    assert ratio["source"] == "garmin_measurement"
    assert ratio["current_period_value"] == 1.2
    assert ratio["previous_period_value"] == 0.8
    spo2 = report["recovery"]["spo2"]
    assert spo2["source"] == "calculated"
    assert spo2["current_period_value"] == 95.0
    assert spo2["previous_period_value"] == 91.0
    assert "not filled with zero" in spo2["note"]


def test_heart_rate_and_gap_needs_paired_samples() -> None:
    sparse = build_performance_trends(
        end=END,
        window_days=28,
        activities=[_run(day=date(2026, 11, 9))],
    )
    assert sparse["mountain_running"]["heart_rate_and_grade_adjusted_pace"]["sample_count"] == 1
    sparse_link = sparse["mountain_running"]["heart_rate_and_grade_adjusted_pace"]
    assert sparse_link["mean_heart_rate"] is None
    runs = [_run(day=date(2026, 11, day), avg_heart_rate=140 + day) for day in range(6, 10)]
    paired = build_performance_trends(end=END, window_days=28, activities=runs)
    summary = paired["mountain_running"]["heart_rate_and_grade_adjusted_pace"]
    assert summary["sample_count"] == 4
    assert summary["mean_heart_rate"] is not None
    assert "not a causal claim" in summary["note"]
