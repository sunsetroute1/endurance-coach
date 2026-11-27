"""Compare stored Garmin observations across two equal windows.

Missing measurements are omitted. They are never filled with zero.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from statistics import median
from typing import Any

TREND_WINDOWS: tuple[int, ...] = (7, 28, 90, 180, 365)
_FLAT_PERCENT = 2.0
_MIN_ASSOCIATION_GROUP = 4
_MIN_CHRONIC_LOADS = 4
_BASELINE_28_MIN = 28
_BASELINE_90_MIN = 60
_LONG_TERM_MIN = 14

SAFEGUARDS: tuple[str, ...] = (
    "Missing measurements are omitted and are never treated as zero.",
    "Percentage change is omitted when the previous value is missing or zero.",
    "A change describes the numbers only. It is not a claim about cause.",
    "Actual pace and grade-adjusted pace are reported separately.",
    "Similar activities are compared only when distance and climb are both close.",
    "Estimates are marked calculated. Garmin fields are marked garmin_measurement.",
)


def build_performance_trends(
    *,
    end: date,
    window_days: int,
    performance_metrics: dict[str, list[dict[str, Any]]] | None = None,
    hrv: list[tuple[date, float]] | None = None,
    resting_hr: list[tuple[date, float]] | None = None,
    respiration: list[tuple[date, float]] | None = None,
    spo2: list[tuple[date, float]] | None = None,
    sleep_seconds: list[tuple[date, float]] | None = None,
    body_battery: list[tuple[date, float]] | None = None,
    activities: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if window_days not in TREND_WINDOWS:
        raise ValueError(f"window_days must be one of {TREND_WINDOWS}")

    current_start = end - timedelta(days=window_days - 1)
    previous_end = current_start - timedelta(days=1)
    previous_start = previous_end - timedelta(days=window_days - 1)
    metrics = performance_metrics or {}
    runs = activities or []

    endurance = {
        "endurance_score": _metric_trend(
            _pairs(metrics.get("endurance_score"), "overallScore", "groupAverage"),
            end=end,
            window_days=window_days,
            source="garmin_measurement",
            kind="daily_series",
            unit="score",
            aggregate="mean",
        ),
        "running_tolerance": _metric_trend(
            _pairs(metrics.get("running_tolerance"), "acuteTolerance"),
            end=end,
            window_days=window_days,
            source="garmin_measurement",
            kind="daily_series",
            unit="score",
            aggregate="mean",
        ),
        "hill_score": _metric_trend(
            _pairs(metrics.get("hill_score"), "overallScore"),
            end=end,
            window_days=window_days,
            source="garmin_measurement",
            kind="daily_series",
            unit="score",
            aggregate="mean",
        ),
        "race_prediction_5k_sec": _race_trend(metrics, "time5K", end, window_days),
        "race_prediction_10k_sec": _race_trend(metrics, "time10K", end, window_days),
        "race_prediction_half_marathon_sec": _race_trend(
            metrics, "timeHalfMarathon", end, window_days
        ),
        "race_prediction_marathon_sec": _race_trend(metrics, "timeMarathon", end, window_days),
        "training_status": _label_change(
            metrics.get("training_status"),
            end=end,
            window_days=window_days,
        ),
        "training_status_load": _metric_trend(
            _pairs(
                metrics.get("training_status"),
                "dailyTrainingLoadAcute",
                "weeklyTrainingLoad",
            ),
            end=end,
            window_days=window_days,
            source="garmin_measurement",
            kind="daily_series",
            unit="load",
            aggregate="mean",
            note=(
                "Uses stored dailyTrainingLoadAcute when weeklyTrainingLoad is null. "
                "A null weekly load is omitted, not treated as zero."
            ),
        ),
    }
    recovery = {
        "hrv_ms": _metric_trend(
            hrv or [],
            end=end,
            window_days=window_days,
            source="garmin_measurement",
            kind="daily_series",
            unit="ms",
            aggregate="mean",
            note=(
                "Same-day rows are averaged before the comparison. "
                "Missing days stay missing and are not treated as zero."
            ),
        ),
        "resting_heart_rate_bpm": _metric_trend(
            resting_hr or [],
            end=end,
            window_days=window_days,
            source="garmin_measurement",
            kind="daily_series",
            unit="bpm",
            aggregate="mean",
            lower_is_better=True,
        ),
        "respiration": _metric_trend(
            respiration or _pairs(metrics.get("respiration"), "avgWakingRespiration"),
            end=end,
            window_days=window_days,
            source="garmin_measurement",
            kind="daily_series",
            unit="breaths_per_min",
            aggregate="mean",
        ),
        "spo2": _spo2_trend(metrics, spo2, end=end, window_days=window_days),
        "sleep_hours": _metric_trend(
            [(day, seconds / 3600.0) for day, seconds in (sleep_seconds or [])],
            end=end,
            window_days=window_days,
            source="garmin_measurement",
            kind="daily_series",
            unit="hours",
            aggregate="mean",
        ),
        "body_battery": _metric_trend(
            body_battery or [],
            end=end,
            window_days=window_days,
            source="garmin_measurement",
            kind="daily_series",
            unit="level",
            aggregate="mean",
        ),
        "sleep_and_body_battery": _sleep_battery_association(
            sleep_seconds or [],
            body_battery or [],
            start=current_start,
            end=end,
        ),
    }
    mountain = _mountain_section(
        runs,
        start=current_start,
        end=end,
        previous_start=previous_start,
        previous_end=previous_end,
    )
    load = _load_section(
        runs,
        current_start=current_start,
        end=end,
        previous_start=previous_start,
        previous_end=previous_end,
        window_days=window_days,
    )
    load.update(_garmin_load_trends(metrics, end=end, window_days=window_days))
    report: dict[str, Any] = {
        "window_days": window_days,
        "current_period": {"start": current_start.isoformat(), "end": end.isoformat()},
        "previous_period": {
            "start": previous_start.isoformat(),
            "end": previous_end.isoformat(),
        },
        "safeguards": list(SAFEGUARDS),
        "endurance": endurance,
        "recovery": recovery,
        "mountain_running": mountain,
        "training_load": load,
        "snapshots": {
            "vo2_max": _snapshot_trend(
                _pairs(metrics.get("vo2_max"), "vo2MaxValue", "vo2MaxPreciseValue"),
                unit="ml_per_kg_min",
            ),
            "lactate_threshold_heart_rate": _snapshot_trend(
                _pairs(metrics.get("lactate_threshold"), "heartRate"),
                unit="bpm",
            ),
            "lactate_threshold_speed": _snapshot_trend(
                _pairs(metrics.get("lactate_threshold"), "speed"),
                unit="meters_per_second",
            ),
        },
    }
    report["stored_coverage"] = _coverage_index(report)
    return report


def _spo2_trend(
    metrics: dict[str, list[dict[str, Any]]],
    explicit: list[tuple[date, float]] | None,
    *,
    end: date,
    window_days: int,
) -> dict[str, Any]:
    direct = explicit or _pairs(
        metrics.get("spo2_acclimation"),
        "averageSpO2",
        "latestSpO2",
        "avgSleepSpO2",
    )
    if direct:
        return _metric_trend(
            direct,
            end=end,
            window_days=window_days,
            source="garmin_measurement",
            kind="daily_series",
            unit="percent",
            aggregate="mean",
        )
    return _metric_trend(
        _pairs(metrics.get("spo2_acclimation"), "hourlyMeanSpO2"),
        end=end,
        window_days=window_days,
        source="calculated",
        kind="daily_series",
        unit="percent",
        aggregate="mean",
        note=(
            "Daily mean of stored hourly SpO2 samples. "
            "Garmin averageSpO2 is null on these rows and is not filled with zero."
        ),
    )


def _garmin_load_trends(
    metrics: dict[str, list[dict[str, Any]]],
    *,
    end: date,
    window_days: int,
) -> dict[str, Any]:
    rows = metrics.get("training_status")
    note = (
        "Stored on the Garmin training-status record. "
        "This is separate from the activity-sum ratio, which only counts activities "
        "that have a training_load."
    )
    return {
        "garmin_acute_load": _metric_trend(
            _pairs(rows, "dailyTrainingLoadAcute"),
            end=end,
            window_days=window_days,
            source="garmin_measurement",
            kind="daily_series",
            unit="load",
            aggregate="mean",
            note=note,
        ),
        "garmin_chronic_load": _metric_trend(
            _pairs(rows, "dailyTrainingLoadChronic"),
            end=end,
            window_days=window_days,
            source="garmin_measurement",
            kind="daily_series",
            unit="load",
            aggregate="mean",
            note=note,
        ),
        "garmin_acute_chronic_ratio": _metric_trend(
            _pairs(rows, "dailyAcuteChronicWorkloadRatio"),
            end=end,
            window_days=window_days,
            source="garmin_measurement",
            kind="daily_series",
            unit="ratio",
            aggregate="mean",
            note=note,
        ),
    }


def metric_points(rows: list[dict[str, Any]] | None, *keys: str) -> list[tuple[date, float]]:
    """Return dated numbers from projected rows. Missing values are skipped."""
    return _pairs(rows, *keys)


def _race_trend(
    metrics: dict[str, list[dict[str, Any]]],
    key: str,
    end: date,
    window_days: int,
) -> dict[str, Any]:
    trend = _metric_trend(
        _pairs(metrics.get("race_predictions"), key),
        end=end,
        window_days=window_days,
        source="garmin_measurement",
        kind="daily_series",
        unit="seconds",
        aggregate="mean",
        lower_is_better=True,
    )
    trend["note"] = (
        "Predicted finish time in seconds. A lower number is faster. "
        "Trend up means the stored prediction got slower."
    )
    return trend


def _label_change(
    rows: list[dict[str, Any]] | None,
    *,
    end: date,
    window_days: int,
) -> dict[str, Any]:
    current_start = end - timedelta(days=window_days - 1)
    previous_end = current_start - timedelta(days=1)
    previous_start = previous_end - timedelta(days=window_days - 1)
    labels: dict[date, str] = {}
    duplicates = 0
    for row in rows or []:
        day = _as_date(row.get("date"))
        label = row.get("statusLabel")
        if day is None or not isinstance(label, str) or not label.strip():
            continue
        text = label.strip()
        if day in labels and labels[day] != text:
            duplicates += 1
        labels[day] = text
    current_days = [day for day in sorted(labels) if current_start <= day <= end]
    previous_days = [day for day in sorted(labels) if previous_start <= day <= previous_end]
    current_label = labels[current_days[-1]] if current_days else None
    previous_label = labels[previous_days[-1]] if previous_days else None
    changed = None
    if current_label is not None and previous_label is not None:
        changed = current_label != previous_label
    if current_label is None or previous_label is None:
        trend = "insufficient"
    elif changed:
        trend = "changed"
    else:
        trend = "flat"
    days = sorted(labels)
    return {
        "source": "garmin_measurement",
        "kind": "daily_series",
        "unit": "label",
        "current": current_label,
        "previous_period_value": previous_label,
        "changed": changed,
        "absolute_change": None,
        "percentage_change": None,
        "trend": trend,
        "coverage": {
            "window_days": window_days,
            "populated_days": len(current_days),
            "missing_days": window_days - len(current_days),
            "duplicate_dates": duplicates,
            "sample_count": len(current_days),
            "earliest": days[0].isoformat() if days else None,
            "latest": days[-1].isoformat() if days else None,
        },
        "history": {
            "earliest": days[0].isoformat() if days else None,
            "latest": days[-1].isoformat() if days else None,
            "populated_days": len(days),
            "duplicate_dates": duplicates,
            "kind": "daily_series",
        },
        "note": (
            "Latest stored training-status label in each window. "
            "A label change is not a cause."
        ),
    }


def _coverage_index(report: dict[str, Any]) -> dict[str, Any]:
    index: dict[str, Any] = {}
    for section in ("endurance", "recovery", "mountain_running", "training_load", "snapshots"):
        block = report.get(section)
        if not isinstance(block, dict):
            continue
        for name, item in block.items():
            if not isinstance(item, dict):
                continue
            coverage = item.get("coverage") if isinstance(item.get("coverage"), dict) else {}
            index[f"{section}.{name}"] = {
                "source": item.get("source"),
                "kind": item.get("kind"),
                "history": item.get("history"),
                "coverage": item.get("coverage"),
                "sample_count": item.get("sample_count", coverage.get("sample_count")),
            }
    return index


def _pairs(rows: list[dict[str, Any]] | None, *keys: str) -> list[tuple[date, float]]:
    points: list[tuple[date, float]] = []
    for row in rows or []:
        day = _as_date(row.get("date"))
        if day is None:
            continue
        value = _first_number(row, keys)
        if value is None:
            continue
        points.append((day, value))
    return points


def _as_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    text = str(value or "")
    if len(text) >= 10 and text[4:5] == "-" and text[7:8] == "-":
        try:
            return date.fromisoformat(text[:10])
        except ValueError:
            return None
    return None


def _first_number(row: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        value = row.get(key)
        if isinstance(value, bool) or value is None:
            continue
        if isinstance(value, (int, float)):
            return float(value)
    return None


def _daily_means(points: list[tuple[date, float]]) -> tuple[dict[date, float], int]:
    grouped: dict[date, list[float]] = defaultdict(list)
    for day, value in points:
        grouped[day].append(value)
    duplicates = sum(len(values) - 1 for values in grouped.values())
    return {day: sum(values) / len(values) for day, values in grouped.items()}, duplicates


def _history(daily: dict[date, float], duplicates: int, kind: str) -> dict[str, Any]:
    days = sorted(daily)
    return {
        "earliest": days[0].isoformat() if days else None,
        "latest": days[-1].isoformat() if days else None,
        "populated_days": len(days),
        "duplicate_dates": duplicates,
        "kind": kind,
    }


def _metric_trend(
    points: list[tuple[date, float]],
    *,
    end: date,
    window_days: int,
    source: str,
    kind: str,
    unit: str,
    aggregate: str,
    lower_is_better: bool = False,
    note: str | None = None,
) -> dict[str, Any]:
    daily, duplicates = _daily_means(points)
    current_start = end - timedelta(days=window_days - 1)
    previous_end = current_start - timedelta(days=1)
    previous_start = previous_end - timedelta(days=window_days - 1)
    current_days = [day for day in daily if current_start <= day <= end]
    previous_days = [day for day in daily if previous_start <= day <= previous_end]
    current_values = [daily[day] for day in current_days]
    previous_values = [daily[day] for day in previous_days]
    current_period = _aggregate(current_values, aggregate)
    previous_period = _aggregate(previous_values, aggregate)
    absolute, percent = _changes(current_period, previous_period)
    return {
        "source": source,
        "kind": kind,
        "unit": unit,
        "lower_is_better": lower_is_better,
        "aggregate": aggregate,
        "current": daily[max(current_days)] if current_days else None,
        "current_period_value": _round(current_period),
        "previous_period_value": _round(previous_period),
        "absolute_change": _round(absolute),
        "percentage_change": _round(percent),
        "trend": _direction(absolute, percent, current_period, previous_period),
        "coverage": {
            "window_days": window_days,
            "populated_days": len(current_days),
            "missing_days": window_days - len(current_days),
            "duplicate_dates": duplicates,
            "sample_count": len(current_values),
            "earliest": min(daily).isoformat() if daily else None,
            "latest": max(daily).isoformat() if daily else None,
        },
        "history": _history(daily, duplicates, kind),
        "baselines": _baselines(daily, end=end, lower_is_better=lower_is_better),
        "note": note,
    }


def _snapshot_trend(points: list[tuple[date, float]], *, unit: str) -> dict[str, Any]:
    daily, duplicates = _daily_means(points)
    days = sorted(daily)
    latest = days[-1] if days else None
    return {
        "source": "garmin_measurement",
        "kind": "snapshot",
        "unit": unit,
        "current": daily[latest] if latest else None,
        "current_period_value": daily[latest] if latest else None,
        "previous_period_value": None,
        "absolute_change": None,
        "percentage_change": None,
        "trend": "insufficient",
        "coverage": {
            "window_days": None,
            "populated_days": len(days),
            "missing_days": None,
            "duplicate_dates": duplicates,
            "sample_count": len(days),
            "earliest": days[0].isoformat() if days else None,
            "latest": latest.isoformat() if latest else None,
        },
        "history": _history(daily, duplicates, "snapshot"),
        "note": "Latest stored snapshot. No historical series is manufactured.",
    }


def _window_values(daily: dict[date, float], start: date, end: date) -> list[float]:
    return [daily[day] for day in daily if start <= day <= end]


def _baseline_window(
    daily: dict[date, float],
    *,
    end: date,
    days: int,
    minimum: int,
) -> dict[str, Any]:
    start = end - timedelta(days=days - 1)
    values = _window_values(daily, start, end)
    if len(values) < minimum:
        return {
            "available": False,
            "window_days": days,
            "sample_count": len(values),
            "required_samples": minimum,
            "median": None,
            "mean": None,
            "note": (
                f"{days}-day baseline omitted because {len(values)} observations "
                f"are stored in that span."
            ),
        }
    return {
        "available": True,
        "window_days": days,
        "sample_count": len(values),
        "required_samples": minimum,
        "median": _round(float(median(values))),
        "mean": _round(sum(values) / len(values)),
        "note": None,
    }


def _baselines(
    daily: dict[date, float],
    *,
    end: date,
    lower_is_better: bool,
) -> dict[str, Any]:
    values = list(daily.values())
    historical_median = float(median(values)) if values else None
    historical_best = None
    if values:
        historical_best = min(values) if lower_is_better else max(values)
    rolling_28 = _baseline_window(daily, end=end, days=28, minimum=_BASELINE_28_MIN)
    rolling_90 = _baseline_window(daily, end=end, days=90, minimum=_BASELINE_90_MIN)
    current_values = _window_values(daily, end - timedelta(days=27), end)
    current_mean = sum(current_values) / len(current_values) if current_values else None
    baseline_value = rolling_28["median"] if rolling_28["available"] else None
    absolute, percent = _changes(current_mean, baseline_value)
    recent_start = end - timedelta(days=27)
    prior_end = recent_start - timedelta(days=1)
    prior_start = prior_end - timedelta(days=27)
    recent = _window_values(daily, recent_start, end)
    prior = _window_values(daily, prior_start, prior_end)
    long_term = "insufficient"
    if len(recent) >= _LONG_TERM_MIN and len(prior) >= _LONG_TERM_MIN:
        long_absolute, long_percent = _changes(
            sum(recent) / len(recent),
            sum(prior) / len(prior),
        )
        long_term = _direction(
            long_absolute,
            long_percent,
            sum(recent) / len(recent),
            sum(prior) / len(prior),
        )
    return {
        "rolling_28": rolling_28,
        "rolling_90": rolling_90,
        "historical_median": _round(historical_median),
        "historical_best": _round(historical_best),
        "historical_sample_count": len(values),
        "current_versus_baseline": {
            "baseline": "rolling_28_median",
            "current_mean": _round(current_mean),
            "baseline_value": baseline_value,
            "absolute_change": _round(absolute),
            "percentage_change": _round(percent),
            "trend": _direction(absolute, percent, current_mean, baseline_value),
        },
        "long_term_direction": long_term,
        "note": (
            "The 90-day baseline is omitted below 60 stored observations in those 90 days. "
            "Historical median and best use every stored observation and report that sample count."
        ),
    }


def _aggregate(values: list[float], how: str) -> float | None:
    if not values:
        return None
    if how == "sum":
        return float(sum(values))
    return float(sum(values) / len(values))


def _changes(current: float | None, previous: float | None) -> tuple[float | None, float | None]:
    if current is None or previous is None:
        return None, None
    absolute = current - previous
    if previous == 0:
        return absolute, None
    return absolute, (absolute / abs(previous)) * 100.0


def _direction(
    absolute: float | None,
    percent: float | None,
    current: float | None,
    previous: float | None,
) -> str:
    if current is None or previous is None or absolute is None:
        return "insufficient"
    if percent is not None and abs(percent) < _FLAT_PERCENT:
        return "flat"
    if percent is None and abs(absolute) == 0:
        return "flat"
    if absolute > 0:
        return "up"
    if absolute < 0:
        return "down"
    return "flat"


def _round(value: float | None) -> float | None:
    if value is None:
        return None
    return round(value, 2)


def _in_span(day: date, start: date, end: date) -> bool:
    return start <= day <= end


def _activity_day(row: dict[str, Any]) -> date | None:
    return _as_date(row.get("day"))


def _num(row: dict[str, Any], key: str) -> float | None:
    value = row.get(key)
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _mountain_section(
    activities: list[dict[str, Any]],
    *,
    start: date,
    end: date,
    previous_start: date,
    previous_end: date,
) -> dict[str, Any]:
    window_days = (end - start).days + 1
    activity_note = (
        "Built from stored activities. missing_days counts calendar days without this "
        "measurement, which is expected for activities. Those days are not zeros."
    )
    vert_points: list[tuple[date, float]] = []
    gap_points: list[tuple[date, float]] = []
    pace_points: list[tuple[date, float]] = []
    stamina_points: list[tuple[date, float]] = []
    for row in activities:
        day = _activity_day(row)
        if day is None or not _is_mountain_effort(row):
            continue
        duration = _num(row, "duration_seconds")
        elevation = _num(row, "elevation_meters")
        if duration is not None and duration > 0 and elevation is not None:
            vert_points.append((day, elevation / (duration / 3600.0)))
        gap = _gap_sec_per_km(row)
        if gap is not None:
            gap_points.append((day, gap))
        pace = _num(row, "pace_sec_per_km")
        if pace is not None:
            pace_points.append((day, pace))
        depletion = _stamina_depletion(row)
        if depletion is not None:
            stamina_points.append((day, depletion))

    return {
        "elevation_gain_per_hour": _metric_trend(
            vert_points,
            end=end,
            window_days=window_days,
            source="calculated",
            kind="activity_series",
            unit="meters_per_hour",
            aggregate="mean",
            note=activity_note + " Elevation per hour uses stored elevation and duration.",
        ),
        "grade_adjusted_pace_sec_per_km": _metric_trend(
            gap_points,
            end=end,
            window_days=window_days,
            source="calculated",
            kind="activity_series",
            unit="sec_per_km",
            aggregate="mean",
            lower_is_better=True,
            note=(
                activity_note
                + " Seconds per kilometer is 1000 divided by stored avgGradeAdjustedSpeed "
                + "in meters per second. This is not actual pace."
            ),
        ),
        "actual_pace_sec_per_km": _metric_trend(
            pace_points,
            end=end,
            window_days=window_days,
            source="garmin_measurement",
            kind="activity_series",
            unit="sec_per_km",
            aggregate="mean",
            lower_is_better=True,
            note=activity_note + " Actual pace is not grade-adjusted pace.",
        ),
        "heart_rate_and_grade_adjusted_pace": _hr_gap_association(
            activities, start=start, end=end
        ),
        "cardiovascular_efficiency": _cardio_efficiency(activities, start=start, end=end),
        "comparable_runs": _comparable_runs(
            activities,
            current_start=start,
            current_end=end,
            previous_start=previous_start,
            previous_end=previous_end,
        ),
        "stamina_depletion": _metric_trend(
            stamina_points,
            end=end,
            window_days=window_days,
            source="calculated",
            kind="activity_series",
            unit="stamina_points",
            aggregate="mean",
            note=(
                activity_note
                + " Depletion is stored beginPotentialStamina minus endPotentialStamina."
            ),
        ),
    }


def _is_mountain_effort(row: dict[str, Any]) -> bool:
    activity_type = str(row.get("activity_type") or "").lower()
    elevation = _num(row, "elevation_meters")
    if any(token in activity_type for token in ("trail", "hik", "climb", "mount")):
        return True
    return elevation is not None and elevation >= 150


def _gap_sec_per_km(row: dict[str, Any]) -> float | None:
    speed = _num(row, "grade_adjusted_speed_mps")
    if speed is None or speed <= 0:
        return None
    return 1000.0 / speed


def _stamina_depletion(row: dict[str, Any]) -> float | None:
    begin = _num(row, "stamina_begin")
    end = _num(row, "stamina_end")
    if begin is None or end is None:
        return None
    return begin - end


def _hr_gap_association(
    activities: list[dict[str, Any]],
    *,
    start: date,
    end: date,
) -> dict[str, Any]:
    paired: list[tuple[float, float]] = []
    for row in activities:
        day = _activity_day(row)
        if day is None or not _in_span(day, start, end) or not _is_mountain_effort(row):
            continue
        heart_rate = _num(row, "avg_heart_rate")
        gap = _gap_sec_per_km(row)
        if heart_rate is None or gap is None:
            continue
        paired.append((heart_rate, gap))
    note = (
        "Paired Garmin heart rate and grade-adjusted pace on the same activity. "
        "This is not a causal claim, and actual pace is not used as a substitute."
    )
    if len(paired) < _MIN_ASSOCIATION_GROUP:
        return {
            "source": "calculated",
            "kind": "association",
            "sample_count": len(paired),
            "mean_heart_rate": None,
            "mean_grade_adjusted_pace_sec_per_km": None,
            "note": note + " Too few paired activities to summarize.",
        }
    return {
        "source": "calculated",
        "kind": "association",
        "sample_count": len(paired),
        "mean_heart_rate": _round(sum(item[0] for item in paired) / len(paired)),
        "mean_grade_adjusted_pace_sec_per_km": _round(
            sum(item[1] for item in paired) / len(paired)
        ),
        "note": note,
    }


def _cardio_efficiency(
    activities: list[dict[str, Any]],
    *,
    start: date,
    end: date,
) -> dict[str, Any]:
    ratios: list[float] = []
    for row in activities:
        day = _activity_day(row)
        if day is None or not _in_span(day, start, end) or not _is_mountain_effort(row):
            continue
        heart_rate = _num(row, "avg_heart_rate")
        speed = _num(row, "grade_adjusted_speed_mps")
        if heart_rate is None or speed is None or speed <= 0:
            continue
        ratios.append(heart_rate / speed)
    note = (
        "Calculated heart rate divided by stored grade-adjusted speed in meters per second. "
        "Actual pace is not used. This is not a cause."
    )
    if len(ratios) < _MIN_ASSOCIATION_GROUP:
        return {
            "source": "calculated",
            "kind": "association",
            "unit": "bpm_per_mps",
            "sample_count": len(ratios),
            "current_period_value": None,
            "note": note + " Too few paired activities to summarize.",
        }
    return {
        "source": "calculated",
        "kind": "association",
        "unit": "bpm_per_mps",
        "sample_count": len(ratios),
        "current_period_value": _round(sum(ratios) / len(ratios)),
        "note": note,
    }


def _comparable_runs(
    activities: list[dict[str, Any]],
    *,
    current_start: date,
    current_end: date,
    previous_start: date,
    previous_end: date,
) -> dict[str, Any]:
    current = [
        row
        for row in activities
        if (day := _activity_day(row)) is not None
        and _in_span(day, current_start, current_end)
        and _gap_sec_per_km(row) is not None
    ]
    previous = [
        row
        for row in activities
        if (day := _activity_day(row)) is not None
        and _in_span(day, previous_start, previous_end)
        and _gap_sec_per_km(row) is not None
    ]
    pairs: list[tuple[float, float]] = []
    stamina_deltas: list[float] = []
    for row in current:
        match = _closest_prior(row, previous)
        current_gap = _gap_sec_per_km(row)
        prior_gap = _gap_sec_per_km(match) if match else None
        if current_gap is None or prior_gap is None:
            continue
        pairs.append((current_gap, prior_gap))
        current_stamina = _stamina_depletion(row)
        prior_stamina = _stamina_depletion(match) if match else None
        if current_stamina is not None and prior_stamina is not None:
            stamina_deltas.append(current_stamina - prior_stamina)
    note = (
        "Each current activity is matched to one earlier activity within 15% distance "
        "and 25% elevation gain. Grade-adjusted pace is required on both. "
        "A negative change means the current matched runs were faster."
    )
    if not pairs:
        return {
            "source": "calculated",
            "kind": "matched_activities",
            "sample_count": 0,
            "current_period_value": None,
            "previous_period_value": None,
            "absolute_change": None,
            "percentage_change": None,
            "trend": "insufficient",
            "stamina_depletion_change": None,
            "stamina_sample_count": 0,
            "note": note + " No matched pair was found.",
        }
    current_mean = sum(item[0] for item in pairs) / len(pairs)
    previous_mean = sum(item[1] for item in pairs) / len(pairs)
    absolute, percent = _changes(current_mean, previous_mean)
    return {
        "source": "calculated",
        "kind": "matched_activities",
        "unit": "sec_per_km",
        "lower_is_better": True,
        "sample_count": len(pairs),
        "current_period_value": _round(current_mean),
        "previous_period_value": _round(previous_mean),
        "absolute_change": _round(absolute),
        "percentage_change": _round(percent),
        "trend": _direction(absolute, percent, current_mean, previous_mean),
        "stamina_depletion_change": _round(sum(stamina_deltas) / len(stamina_deltas))
        if stamina_deltas
        else None,
        "stamina_sample_count": len(stamina_deltas),
        "note": note
        + " Stamina depletion is included only when both matched activities stored it.",
    }


def _closest_prior(row: dict[str, Any], previous: list[dict[str, Any]]) -> dict[str, Any] | None:
    distance = _num(row, "distance_meters")
    elevation = _num(row, "elevation_meters")
    if distance is None or distance <= 0 or elevation is None:
        return None
    best: dict[str, Any] | None = None
    best_score: float | None = None
    for candidate in previous:
        other_distance = _num(candidate, "distance_meters")
        other_elevation = _num(candidate, "elevation_meters")
        if other_distance is None or other_elevation is None or other_distance <= 0:
            continue
        if abs(other_distance - distance) / distance > 0.15:
            continue
        baseline = max(abs(elevation), 1.0)
        if abs(other_elevation - elevation) / baseline > 0.25:
            continue
        score = abs(other_distance - distance) / distance
        if best_score is None or score < best_score:
            best = candidate
            best_score = score
    return best


def _load_section(
    activities: list[dict[str, Any]],
    *,
    current_start: date,
    end: date,
    previous_start: date,
    previous_end: date,
    window_days: int,
) -> dict[str, Any]:
    distance_now = _sum_field(activities, "distance_meters", current_start, end)
    distance_then = _sum_field(activities, "distance_meters", previous_start, previous_end)
    climb_now = _sum_field(activities, "elevation_meters", current_start, end)
    climb_then = _sum_field(activities, "elevation_meters", previous_start, previous_end)
    count_now = _count_activities(activities, current_start, end)
    count_then = _count_activities(activities, previous_start, previous_end)
    return {
        "distance_meters": _sum_trend(distance_now, distance_then, window_days, "meters"),
        "elevation_gain_meters": _sum_trend(climb_now, climb_then, window_days, "meters"),
        "activity_count": _sum_trend(count_now, count_then, window_days, "activities"),
        "acute_versus_chronic_load": _acute_chronic(activities, end=end),
        "consistency": _consistency(activities, current_start, end, window_days),
        "recovery_between_demanding_sessions": _recovery_gaps(
            activities, current_start, end, previous_start, previous_end
        ),
    }


def _sum_field(
    activities: list[dict[str, Any]],
    key: str,
    start: date,
    end: date,
) -> tuple[float | None, int, int]:
    present = 0
    absent = 0
    total = 0.0
    for row in activities:
        day = _activity_day(row)
        if day is None or not _in_span(day, start, end):
            continue
        value = _num(row, key)
        if value is None:
            absent += 1
            continue
        present += 1
        total += value
    if present == 0:
        return None, 0, absent
    return total, present, absent


def _count_activities(
    activities: list[dict[str, Any]], start: date, end: date
) -> tuple[float | None, int, int]:
    count = 0
    for row in activities:
        day = _activity_day(row)
        if day is not None and _in_span(day, start, end):
            count += 1
    return float(count), count, 0


def _sum_trend(
    current: tuple[float | None, int, int],
    previous: tuple[float | None, int, int],
    window_days: int,
    unit: str,
) -> dict[str, Any]:
    absolute, percent = _changes(current[0], previous[0])
    return {
        "source": "calculated",
        "kind": "window_sum",
        "unit": unit,
        "current_period_value": _round(current[0]),
        "previous_period_value": _round(previous[0]),
        "absolute_change": _round(absolute),
        "percentage_change": _round(percent),
        "trend": _direction(absolute, percent, current[0], previous[0]),
        "coverage": {
            "window_days": window_days,
            "sample_count": current[1],
            "activities_missing_measurement": current[2],
        },
        "note": "Activities missing this measurement are excluded, not added as zero.",
    }


def _acute_chronic(activities: list[dict[str, Any]], *, end: date) -> dict[str, Any]:
    acute_start = end - timedelta(days=6)
    chronic_start = end - timedelta(days=27)
    acute, acute_n, acute_missing = _sum_field(activities, "training_load", acute_start, end)
    chronic, chronic_n, chronic_missing = _sum_field(
        activities, "training_load", chronic_start, end
    )
    ratio = None
    if (
        acute is not None
        and chronic is not None
        and chronic > 0
        and chronic_n >= _MIN_CHRONIC_LOADS
    ):
        ratio = acute / (chronic / 4.0)
    return {
        "source": "calculated",
        "kind": "load_ratio",
        "acute_7d_load_sum": _round(acute),
        "acute_sample_count": acute_n,
        "chronic_28d_load_sum": _round(chronic),
        "chronic_sample_count": chronic_n,
        "acute_to_chronic_ratio": _round(ratio),
        "activities_missing_load_in_28d": chronic_missing,
        "note": (
            "Sums include only activities with a stored training_load. "
            "Missing loads are not zero. The ratio is omitted below 4 loaded activities "
            "in 28 days. This is a calculated comparison, not a Garmin metric."
        ),
    }


def _consistency(
    activities: list[dict[str, Any]], start: date, end: date, window_days: int
) -> dict[str, Any]:
    days = {
        day
        for row in activities
        if (day := _activity_day(row)) is not None and _in_span(day, start, end)
    }
    return {
        "source": "calculated",
        "kind": "coverage",
        "active_days": len(days),
        "window_days": window_days,
        "active_day_share": _round(len(days) / window_days) if window_days else None,
        "note": (
            "Share of calendar days with at least one stored activity. "
            "Idle days are not a zero-load measurement."
        ),
    }


def _recovery_gaps(
    activities: list[dict[str, Any]],
    current_start: date,
    current_end: date,
    previous_start: date,
    previous_end: date,
) -> dict[str, Any]:
    ordered = sorted(
        (row for row in activities if _activity_day(row) is not None),
        key=lambda row: _activity_day(row) or date.min,
    )
    current_gaps = _gaps_after_demanding(ordered, current_start, current_end)
    previous_gaps = _gaps_after_demanding(ordered, previous_start, previous_end)
    current_median = median(current_gaps) if current_gaps else None
    previous_median = median(previous_gaps) if previous_gaps else None
    absolute, percent = _changes(
        float(current_median) if current_median is not None else None,
        float(previous_median) if previous_median is not None else None,
    )
    return {
        "source": "calculated",
        "kind": "session_gap",
        "unit": "days",
        "current_period_value": _round(
            float(current_median) if current_median is not None else None
        ),
        "previous_period_value": _round(
            float(previous_median) if previous_median is not None else None
        ),
        "absolute_change": _round(absolute),
        "percentage_change": _round(percent),
        "trend": _direction(
            absolute,
            percent,
            float(current_median) if current_median is not None else None,
            float(previous_median) if previous_median is not None else None,
        ),
        "coverage": {
            "sample_count": len(current_gaps),
            "previous_sample_count": len(previous_gaps),
        },
        "note": (
            "Median days from a demanding session (at least 300 m of climb or 90 minutes) "
            "to the next stored activity. Fewer than one such gap leaves the comparison empty."
        ),
    }


def _gaps_after_demanding(
    ordered: list[dict[str, Any]], start: date, end: date
) -> list[int]:
    gaps: list[int] = []
    for index, row in enumerate(ordered):
        day = _activity_day(row)
        if day is None or not _in_span(day, start, end) or not _is_demanding(row):
            continue
        for later in ordered[index + 1 :]:
            later_day = _activity_day(later)
            if later_day is None or later_day <= day:
                continue
            gaps.append((later_day - day).days)
            break
    return gaps


def _is_demanding(row: dict[str, Any]) -> bool:
    elevation = _num(row, "elevation_meters")
    duration = _num(row, "duration_seconds")
    if elevation is not None and elevation >= 300:
        return True
    return duration is not None and duration >= 5400


def _sleep_battery_association(
    sleep_seconds: list[tuple[date, float]],
    body_battery: list[tuple[date, float]],
    *,
    start: date,
    end: date,
) -> dict[str, Any]:
    sleep_daily, _sleep_dupes = _daily_means(
        [(day, value) for day, value in sleep_seconds if _in_span(day, start, end)]
    )
    battery_daily, _battery_dupes = _daily_means(
        [(day, value) for day, value in body_battery if _in_span(day, start, end)]
    )
    paired = [
        (sleep_daily[day], battery_daily[day])
        for day in sleep_daily
        if day in battery_daily
    ]
    note = (
        "Same-calendar-day association between stored sleep and body battery. "
        "It does not show that one caused the other."
    )
    if len(paired) < _MIN_ASSOCIATION_GROUP * 2:
        return {
            "source": "calculated",
            "kind": "association",
            "paired_days": len(paired),
            "shorter_sleep_mean_body_battery": None,
            "longer_sleep_mean_body_battery": None,
            "absolute_difference": None,
            "note": note + " Too few paired days to split the sample.",
        }
    midpoint = median(item[0] for item in paired)
    shorter = [battery for sleep, battery in paired if sleep < midpoint]
    longer = [battery for sleep, battery in paired if sleep >= midpoint]
    if len(shorter) < _MIN_ASSOCIATION_GROUP or len(longer) < _MIN_ASSOCIATION_GROUP:
        return {
            "source": "calculated",
            "kind": "association",
            "paired_days": len(paired),
            "shorter_sleep_mean_body_battery": None,
            "longer_sleep_mean_body_battery": None,
            "absolute_difference": None,
            "note": note + " One side of the sleep split has fewer than 4 days.",
        }
    short_mean = sum(shorter) / len(shorter)
    long_mean = sum(longer) / len(longer)
    return {
        "source": "calculated",
        "kind": "association",
        "paired_days": len(paired),
        "shorter_sleep_sample_count": len(shorter),
        "longer_sleep_sample_count": len(longer),
        "shorter_sleep_mean_body_battery": _round(short_mean),
        "longer_sleep_mean_body_battery": _round(long_mean),
        "absolute_difference": _round(long_mean - short_mean),
        "note": note,
    }
