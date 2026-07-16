"""Tests for analytics math helpers."""

from datetime import date, timedelta

from endurance_coach.analytics.math import (
    assess_injury_risk,
    compute_acwr,
    compute_ctl_atl,
    compute_fatigue_score,
    compute_hrv_deviation_pct,
    compute_monotony_strain,
    compute_recovery_score,
    compute_sleep_debt_hours,
    compute_tsb,
    compute_weekly_load_progression,
    estimate_activity_load,
)


def test_estimate_activity_load_prefers_training_load() -> None:
    load = estimate_activity_load(
        training_load=85.0,
        duration_seconds=3600,
        avg_heart_rate=140,
    )
    assert load == 85.0


def test_ctl_atl_tsb_ewma() -> None:
    end = date(2026, 7, 14)
    daily = {end - timedelta(days=1): 100.0, end: 50.0}
    ctl, atl = compute_ctl_atl(daily, end, history_days=14)
    assert ctl > 0
    assert atl > 0
    assert compute_tsb(ctl, atl) == ctl - atl


def test_acwr() -> None:
    assert compute_acwr(70, 50) == 1.4


def test_monotony_strain() -> None:
    end = date(2026, 7, 14)
    daily = {end - timedelta(days=offset): 100.0 for offset in range(7)}
    monotony, strain = compute_monotony_strain(daily, end)
    assert monotony == 0.0  # zero variance => monotony 0 by design
    assert strain == 700.0


def test_weekly_load_progression() -> None:
    end = date(2026, 7, 14)
    daily: dict[date, float] = {}
    for offset in range(14):
        daily[end - timedelta(days=offset)] = 100.0 if offset < 7 else 50.0
    progression = compute_weekly_load_progression(daily, end)
    assert progression == 100.0


def test_sleep_debt() -> None:
    end = date(2026, 7, 14)
    sleep = {end: 6 * 3600}
    debt = compute_sleep_debt_hours(sleep, end, window_days=1)
    assert debt == 2.0


def test_hrv_deviation() -> None:
    assert compute_hrv_deviation_pct(45.0, 50.0) == -10.0


def test_recovery_and_fatigue_scores() -> None:
    recovery = compute_recovery_score(readiness_score=80.0, sleep_score=70.0, hrv_deviation_pct=5.0)
    fatigue = compute_fatigue_score(tsb=-10.0, sleep_debt_hours=2.0, hrv_deviation_pct=-5.0)
    assert 0 <= recovery <= 100
    assert 0 <= fatigue <= 100


def test_injury_risk_assessment() -> None:
    score, factors = assess_injury_risk(
        acwr=1.9,
        monotony=2.5,
        weekly_load_progression=25.0,
        tsb=-30.0,
    )
    assert score >= 50
    assert "acwr_elevated" in factors
    assert "monotony_high" in factors
