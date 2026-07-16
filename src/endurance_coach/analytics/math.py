"""Pure sports-science math helpers — no I/O, no LLM."""

from __future__ import annotations

import statistics
from datetime import date, timedelta

CTL_TIME_CONSTANT = 42
ATL_TIME_CONSTANT = 7
TARGET_SLEEP_SECONDS = 8 * 3600


def ewma_step(previous: float, today_load: float, time_constant: int) -> float:
    return previous + (today_load - previous) / time_constant


def compute_ctl_atl(
    daily_loads: dict[date, float],
    end_date: date,
    *,
    history_days: int = 120,
) -> tuple[float, float]:
    ctl = 0.0
    atl = 0.0
    start = end_date - timedelta(days=history_days)
    current = start
    while current <= end_date:
        load = daily_loads.get(current, 0.0)
        ctl = ewma_step(ctl, load, CTL_TIME_CONSTANT)
        atl = ewma_step(atl, load, ATL_TIME_CONSTANT)
        current += timedelta(days=1)
    return ctl, atl


def compute_tsb(ctl: float, atl: float) -> float:
    return ctl - atl


def compute_acwr(atl: float, ctl: float) -> float:
    if ctl <= 0:
        return 0.0
    return atl / ctl


def compute_monotony_strain(
    daily_loads: dict[date, float],
    end_date: date,
    window_days: int = 7,
) -> tuple[float, float]:
    loads = [
        daily_loads.get(end_date - timedelta(days=offset), 0.0)
        for offset in range(window_days - 1, -1, -1)
    ]
    if not loads:
        return 0.0, 0.0

    mean_load = statistics.mean(loads)
    std_load = statistics.pstdev(loads) if len(loads) > 1 else 0.0
    if std_load == 0:
        return 0.0, sum(loads)

    monotony = mean_load / std_load
    strain = sum(loads) * monotony
    return monotony, strain


def compute_weekly_load_progression(
    daily_loads: dict[date, float],
    end_date: date,
) -> float:
    this_week = sum(
        daily_loads.get(end_date - timedelta(days=offset), 0.0) for offset in range(7)
    )
    last_week = sum(
        daily_loads.get(end_date - timedelta(days=offset), 0.0) for offset in range(7, 14)
    )
    if last_week <= 0:
        return 0.0
    return ((this_week - last_week) / last_week) * 100.0


def estimate_activity_load(
    *,
    training_load: float | None,
    duration_seconds: int,
    avg_heart_rate: int | None,
) -> float:
    if training_load is not None and training_load > 0:
        return training_load
    if avg_heart_rate and duration_seconds > 0:
        return (duration_seconds / 60.0) * (avg_heart_rate / 100.0)
    return duration_seconds / 60.0


def compute_sleep_debt_hours(
    sleep_by_date: dict[date, int],
    end_date: date,
    window_days: int = 14,
) -> float:
    debt_seconds = 0
    for offset in range(window_days):
        day = end_date - timedelta(days=offset)
        actual = sleep_by_date.get(day, 0)
        debt_seconds += max(0, TARGET_SLEEP_SECONDS - actual)
    return debt_seconds / 3600.0


def compute_hrv_deviation_pct(hrv_ms: float, baseline_ms: float | None) -> float:
    if baseline_ms is None or baseline_ms <= 0:
        return 0.0
    return ((hrv_ms - baseline_ms) / baseline_ms) * 100.0


def compute_recovery_score(
    *,
    readiness_score: float | None,
    sleep_score: float | None,
    hrv_deviation_pct: float,
) -> float:
    components: list[float] = []
    if readiness_score is not None:
        components.append(readiness_score * 0.4)
    if sleep_score is not None:
        components.append(sleep_score * 0.3)
    hrv_component = max(0.0, min(100.0, 50.0 + hrv_deviation_pct))
    components.append(hrv_component * 0.3)
    if not components:
        return 50.0
    return max(0.0, min(100.0, sum(components)))


def compute_fatigue_score(
    *,
    tsb: float,
    sleep_debt_hours: float,
    hrv_deviation_pct: float,
) -> float:
    score = 50.0 - (tsb * 1.5) + (sleep_debt_hours * 4.0) + max(0.0, -hrv_deviation_pct) * 0.4
    return max(0.0, min(100.0, score))


def compute_aerobic_decoupling_pct(early_hr: float, late_hr: float) -> float:
    if early_hr <= 0:
        return 0.0
    return ((late_hr - early_hr) / early_hr) * 100.0


def compute_hr_drift_pct(early_hr: float, late_hr: float) -> float:
    return compute_aerobic_decoupling_pct(early_hr, late_hr)


def assess_injury_risk(
    *,
    acwr: float,
    monotony: float,
    weekly_load_progression: float,
    tsb: float,
) -> tuple[float, tuple[str, ...]]:
    score = 0.0
    factors: list[str] = []

    if acwr > 1.5:
        score += 30
        factors.append("acwr_elevated")
    if acwr > 1.8:
        score += 15
    if monotony > 2.0:
        score += 25
        factors.append("monotony_high")
    if weekly_load_progression > 20.0:
        score += 25
        factors.append("load_spike")
    if tsb < -25:
        score += 20
        factors.append("deep_fatigue")

    return min(100.0, score), tuple(factors)
