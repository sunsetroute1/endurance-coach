"""Longitudinal comparisons across stored activity charts.

Measured chart values stay marked as Garmin measurements. Matches, rates,
and directions are calculated. Raw drift reasons and sample-quality flags
are copied forward and are not replaced.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date
from statistics import median
from typing import Any

from endurance_coach.garmin.activity_efficiency import (
    analyze_activity_samples,
    efforts_are_comparable,
)

_MIN_RUNS = 4
_MIN_SIDE = 2
_MIN_MONTHS = 2
_OUTPUT_HOLD = 0.05
_HEART_BAND_BPM = 1.0
_HIGH_RES_INTERVAL = 5.0

SAFEGUARDS: tuple[str, ...] = (
    "Missing measurements are omitted and are never treated as zero.",
    "Physiological comparisons use high-resolution charts that are effort-aligned.",
    "Effort-aligned means distance, elevation, duration, and climbing rate all agree.",
    "Heart rate is compared only when power and grade-adjusted speed stay within 5 percent.",
    "A lower heart rate at a held output is not labeled as improved efficiency and is not a cause.",
    "Actual speed is not used as grade-adjusted speed.",
    "Raw drift reasons and sample-quality flags are retained.",
)


def build_longitudinal_report(activities: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize stored charts. This does not read or request Garmin."""
    classified = [_classify(activity) for activity in activities]
    classified.sort(key=lambda row: (row["local_day"], row["provider_activity_id"]))
    groups = _comparable_groups(classified)
    return {
        "coverage": _coverage(classified),
        "classifications": [_public_classification(row) for row in classified],
        "comparable_groups": groups,
        "summary": _summary(classified, groups),
        "safeguards": list(SAFEGUARDS),
    }


def _classify(activity: dict[str, Any]) -> dict[str, Any]:
    samples = list(activity.get("samples") or [])
    analysis = analyze_activity_samples(samples) if samples else None
    drift = analysis["cardiovascular_drift"] if analysis else {}
    quality = _sample_quality(activity, analysis, drift)
    measured = _measured(samples)
    stamina = _stamina_rates(activity, analysis)
    return {
        "provider_activity_id": str(activity.get("provider_activity_id")),
        "local_day": _day(activity.get("local_day")),
        "status": activity.get("status") or "unknown",
        "sample_quality": quality,
        "median_interval_seconds": activity.get("median_interval_seconds"),
        "distance_meters": activity.get("distance_meters"),
        "elevation_gain_meters": activity.get("elevation_gain_meters"),
        "duration_seconds": activity.get("duration_seconds"),
        "drift_reason": drift.get("reason"),
        "drift_assessed": bool(drift.get("drift_assessed")),
        "power_faded": bool(analysis["power_fade"].get("faded")) if analysis else False,
        "labeled_as_improved_efficiency": bool(drift.get("labeled_as_improved_efficiency")),
        "high_resolution": quality == "high_resolution",
        "measured": measured,
        "stamina_rates": stamina,
        "analysis": analysis,
    }


def _sample_quality(
    activity: dict[str, Any],
    analysis: dict[str, Any] | None,
    drift: dict[str, Any],
) -> str:
    status = activity.get("status")
    if status == "unsupported":
        return "unsupported"
    if status == "failed":
        return "failed"
    if analysis is None:
        return "missing_samples"
    if drift.get("reason") == "series_flat":
        return "series_flat"
    median_interval = activity.get("median_interval_seconds")
    interval = float(median_interval) if isinstance(median_interval, (int, float)) else None
    coarse = interval is None or interval > _HIGH_RES_INTERVAL
    if coarse:
        return "coarse"
    if _rich(analysis):
        return "high_resolution"
    return "partial"


def _rich(analysis: dict[str, Any]) -> bool:
    drift = analysis["cardiovascular_drift"]
    power = analysis["power_fade"].get("available")
    gap = drift["grade_adjusted_speed"].get("available")
    stamina = analysis["stamina"]["potential"].get("available")
    return bool(power and gap and stamina)


def _measured(samples: list[dict[str, Any]]) -> dict[str, Any]:
    heart, heart_count = _paired_mean(samples, "power_watts", "heart_rate_bpm")
    power, power_count = _paired_mean(samples, "power_watts", "power_watts")
    gap, gap_count = _mean(samples, "grade_adjusted_speed_mps")
    return {
        "source": "garmin_measurement",
        "heart_rate_bpm": _round(heart),
        "heart_rate_sample_count": heart_count,
        "power_watts": _round(power),
        "power_sample_count": power_count,
        "grade_adjusted_speed_mps": _round(gap, 3),
        "grade_adjusted_speed_sample_count": gap_count,
    }


def _stamina_rates(activity: dict[str, Any], analysis: dict[str, Any] | None) -> dict[str, Any]:
    distance = activity.get("distance_meters")
    elevation = activity.get("elevation_gain_meters")
    rates = {
        "source": "calculated",
        "measurement_source": "garmin_measurement",
        "potential_per_km": _per_distance(analysis, "potential", distance),
        "available_per_km": _per_distance(analysis, "available", distance),
        "potential_per_100m_climb": _per_climb(analysis, "potential", elevation),
        "available_per_100m_climb": _per_climb(analysis, "available", elevation),
    }
    return rates


def _per_distance(analysis: dict[str, Any] | None, field: str, distance: Any) -> float | None:
    depletion = _depletion(analysis, field)
    if depletion is None or not _num(distance) or float(distance) <= 0:
        return None
    return _round(depletion / (float(distance) / 1000.0))


def _per_climb(analysis: dict[str, Any] | None, field: str, elevation: Any) -> float | None:
    depletion = _depletion(analysis, field)
    if depletion is None or not _num(elevation) or float(elevation) <= 0:
        return None
    return _round(depletion / (float(elevation) / 100.0))


def _depletion(analysis: dict[str, Any] | None, field: str) -> float | None:
    if analysis is None:
        return None
    block = analysis["stamina"].get(field)
    if not isinstance(block, dict) or not block.get("available"):
        return None
    value = block.get("depletion")
    return float(value) if _num(value) else None


def _coverage(rows: list[dict[str, Any]]) -> dict[str, Any]:
    months: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        month = row["local_day"][:7]
        months[month]["charts"] += 1
        months[month][row["sample_quality"]] += 1
    by_month = [
        {"month": month, **counts, "source": "calculated"}
        for month, counts in sorted(months.items())
    ]
    return {
        "source": "calculated",
        "high_resolution_rule": (
            "A collected chart is high resolution when the median interval is at most "
            "5 seconds and power, grade-adjusted speed, and potential stamina were measured."
        ),
        "by_month": by_month,
        "totals": dict(Counter(row["sample_quality"] for row in rows)),
    }


def _comparable_groups(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rich = [row for row in rows if row["high_resolution"]]
    edges = {
        _edge(left["provider_activity_id"], right["provider_activity_id"])
        for left in rich
        for right in rich
        if efforts_are_comparable(left, right)
    }
    cliques = _maximal_cliques([row["provider_activity_id"] for row in rich], edges)
    by_id = {row["provider_activity_id"]: row for row in rich}
    groups = []
    for index, member_ids in enumerate(cliques, start=1):
        members = [by_id[member_id] for member_id in member_ids]
        groups.append(_group(index, members))
    return groups


def _group(index: int, members: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(members, key=lambda row: (row["local_day"], row["provider_activity_id"]))
    heart = _heart_rate_at_output(ordered)
    power = _power_at_gap(ordered)
    stamina = _stamina_trend(ordered)
    return {
        "group_id": f"comparable-{index}",
        "run_count": len(ordered),
        "months": sorted({row["local_day"][:7] for row in ordered}),
        "members": [_member(row) for row in ordered],
        "heart_rate_at_output": heart,
        "power_at_grade_adjusted_speed": power,
        "stamina_depletion": stamina,
    }


def _member(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "provider_activity_id": row["provider_activity_id"],
        "local_day": row["local_day"],
        "sample_quality": row["sample_quality"],
        "drift_reason": row["drift_reason"],
        "drift_assessed": row["drift_assessed"],
        "power_faded": row["power_faded"],
        "labeled_as_improved_efficiency": row["labeled_as_improved_efficiency"],
        "measured": row["measured"],
        "stamina_rates": row["stamina_rates"],
    }


def _heart_rate_at_output(members: list[dict[str, Any]]) -> dict[str, Any]:
    power_level = _median_measured(members, "power_watts")
    gap_level = _median_measured(members, "grade_adjusted_speed_mps")
    held = [
        row
        for row in members
        if _close(row["measured"].get("power_watts"), power_level)
        and _close(row["measured"].get("grade_adjusted_speed_mps"), gap_level)
    ]
    change = _sided_change(
        held,
        "heart_rate_bpm",
        hold_keys=("power_watts", "grade_adjusted_speed_mps"),
        absolute_band=_HEART_BAND_BPM,
    )
    return {
        "source": "calculated",
        "measurement_source": "garmin_measurement",
        "output": "power_and_grade_adjusted_speed",
        "group_median_power_watts": _round(power_level),
        "group_median_grade_adjusted_speed_mps": _round(gap_level, 3),
        "included_run_count": len(held),
        **change,
        "note": (
            "Heart rate is included only when that run's power and grade-adjusted speed "
            "are both within 5 percent of the group medians. A later drop in output "
            "withholds the heart-rate comparison. This is not labeled as improved efficiency."
        ),
    }


def _power_at_gap(members: list[dict[str, Any]]) -> dict[str, Any]:
    gap_level = _median_measured(members, "grade_adjusted_speed_mps")
    held = [
        row
        for row in members
        if _close(row["measured"].get("grade_adjusted_speed_mps"), gap_level)
        and row["measured"].get("power_watts") is not None
    ]
    change = _sided_change(
        held,
        "power_watts",
        hold_keys=("grade_adjusted_speed_mps",),
        relative_band=_OUTPUT_HOLD,
    )
    return {
        "source": "calculated",
        "measurement_source": "garmin_measurement",
        "group_median_grade_adjusted_speed_mps": _round(gap_level, 3),
        "included_run_count": len(held),
        **change,
        "note": (
            "Power is compared only among runs whose grade-adjusted speed stays within "
            "5 percent. Actual speed is not substituted."
        ),
    }


def _stamina_trend(members: list[dict[str, Any]]) -> dict[str, Any]:
    blocks = {}
    for key in (
        "potential_per_km",
        "available_per_km",
        "potential_per_100m_climb",
        "available_per_100m_climb",
    ):
        usable = [row for row in members if row["stamina_rates"].get(key) is not None]
        blocks[key] = {
            "included_run_count": len(usable),
            **_sided_change(usable, key, value_from="stamina_rates", relative_band=_OUTPUT_HOLD),
        }
    return {
        "source": "calculated",
        "measurement_source": "garmin_measurement",
        **blocks,
        "note": (
            "Depletion per kilometer and per 100 meters of climb uses measured stamina, "
            "distance, and elevation gain. Missing stamina is omitted."
        ),
    }


def _sided_change(
    rows: list[dict[str, Any]],
    key: str,
    *,
    hold_keys: tuple[str, ...] = (),
    value_from: str = "measured",
    absolute_band: float | None = None,
    relative_band: float | None = None,
) -> dict[str, Any]:
    support = _support(rows)
    earlier, later = _split(rows)
    earlier_value = _side_mean(earlier, key, value_from)
    later_value = _side_mean(later, key, value_from)
    result = {
        **support,
        "earlier_value": earlier_value,
        "later_value": later_value,
        "direction": None,
    }
    if not support["supported"]:
        return result
    for hold in hold_keys:
        if not _close(_side_mean(earlier, hold, "measured"), _side_mean(later, hold, "measured")):
            result["supported"] = False
            result["reason"] = "output_not_held_across_months"
            return result
    result["direction"] = _direction(
        earlier_value,
        later_value,
        absolute_band=absolute_band,
        relative_band=relative_band,
    )
    result["reason"] = "supported"
    return result


def _support(rows: list[dict[str, Any]]) -> dict[str, Any]:
    months = sorted({row["local_day"][:7] for row in rows})
    earlier, later = _split(rows)
    supported = (
        len(rows) >= _MIN_RUNS
        and len(months) >= _MIN_MONTHS
        and len(earlier) >= _MIN_SIDE
        and len(later) >= _MIN_SIDE
    )
    if len(rows) < _MIN_RUNS or len(earlier) < _MIN_SIDE or len(later) < _MIN_SIDE:
        reason = "not_enough_comparable_runs"
    elif len(months) < _MIN_MONTHS:
        reason = "single_month"
    else:
        reason = "enough_runs"
    return {
        "supported": supported,
        "reason": reason,
        "run_count": len(rows),
        "months": months,
        "minimum_runs": _MIN_RUNS,
        "minimum_months": _MIN_MONTHS,
    }


def _summary(rows: list[dict[str, Any]], groups: list[dict[str, Any]]) -> dict[str, Any]:
    largest = max((group["run_count"] for group in groups), default=0)
    return {
        "charts": len(rows),
        "high_resolution_charts": sum(row["high_resolution"] for row in rows),
        "comparable_groups": len(groups),
        "largest_comparable_group": largest,
        "minimum_runs_for_a_trend": _MIN_RUNS,
        "heart_rate_at_output_supported": any(
            group["heart_rate_at_output"]["supported"] for group in groups
        ),
        "power_at_grade_adjusted_speed_supported": any(
            group["power_at_grade_adjusted_speed"]["supported"] for group in groups
        ),
        "stamina_depletion_supported": any(
            group["stamina_depletion"]["potential_per_km"]["supported"] for group in groups
        ),
        "note": (
            "A supported trend needs at least four effort-aligned runs in at least "
            "two months, with two runs on each side of the time split."
        ),
    }


def _public_classification(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "provider_activity_id": row["provider_activity_id"],
        "local_day": row["local_day"],
        "status": row["status"],
        "sample_quality": row["sample_quality"],
        "median_interval_seconds": row["median_interval_seconds"],
        "drift_reason": row["drift_reason"],
        "drift_assessed": row["drift_assessed"],
        "power_faded": row["power_faded"],
        "labeled_as_improved_efficiency": row["labeled_as_improved_efficiency"],
    }


def _maximal_cliques(ids: list[str], edges: set[tuple[str, str]]) -> list[list[str]]:
    neighbors = {item: set() for item in ids}
    for left, right in edges:
        neighbors[left].add(right)
        neighbors[right].add(left)
    found: list[list[str]] = []

    def search(chosen: set[str], pending: set[str], excluded: set[str]) -> None:
        if not pending and not excluded and len(chosen) >= 2:
            found.append(sorted(chosen))
            return
        for node in list(pending):
            search(chosen | {node}, pending & neighbors[node], excluded & neighbors[node])
            pending.remove(node)
            excluded.add(node)

    search(set(), set(ids), set())
    found.sort(key=lambda group: (-len(group), group))
    return found


def _split(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    ordered = sorted(rows, key=lambda row: (row["local_day"], row["provider_activity_id"]))
    mid = len(ordered) // 2
    return ordered[:mid], ordered[mid:]


def _side_mean(rows: list[dict[str, Any]], key: str, source: str) -> float | None:
    values = [float(row[source][key]) for row in rows if _num(row[source].get(key))]
    if not values:
        return None
    return _round(sum(values) / len(values))


def _median_measured(rows: list[dict[str, Any]], key: str) -> float | None:
    values = [float(row["measured"][key]) for row in rows if _num(row["measured"].get(key))]
    if not values:
        return None
    return float(median(values))


def _direction(
    earlier: float | None,
    later: float | None,
    *,
    absolute_band: float | None,
    relative_band: float | None,
) -> str | None:
    if earlier is None or later is None:
        return None
    change = later - earlier
    if absolute_band is not None and abs(change) <= absolute_band:
        return "unchanged"
    if relative_band is not None and earlier != 0 and abs(change) / abs(earlier) <= relative_band:
        return "unchanged"
    if change < 0:
        return "lower"
    if change > 0:
        return "higher"
    return "unchanged"


def _close(value: Any, baseline: Any) -> bool:
    if not _num(value) or not _num(baseline) or float(baseline) == 0:
        return False
    return abs(float(value) - float(baseline)) / abs(float(baseline)) <= _OUTPUT_HOLD


def _paired_mean(
    samples: list[dict[str, Any]],
    required: str,
    key: str,
) -> tuple[float | None, int]:
    values = [
        float(sample[key])
        for sample in samples
        if _num(sample.get(required)) and _num(sample.get(key))
    ]
    if not values:
        return None, 0
    return sum(values) / len(values), len(values)


def _mean(samples: list[dict[str, Any]], key: str) -> tuple[float | None, int]:
    values = [float(sample[key]) for sample in samples if _num(sample.get(key))]
    if not values:
        return None, 0
    return sum(values) / len(values), len(values)


def _day(value: Any) -> str:
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _edge(left: str, right: str) -> tuple[str, str]:
    return (left, right) if left < right else (right, left)


def _round(value: float | None, digits: int = 2) -> float | None:
    if value is None:
        return None
    return round(value, digits)


def _num(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)
