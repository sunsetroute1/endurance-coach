"""Calculated activity analysis. Garmin samples stay labeled as measurements."""

from __future__ import annotations

from typing import Any

_MIN_HALF = 20
_PAUSE_SECONDS = 30.0
_POST_PAUSE_SECONDS = 60.0
_OUTPUT_HOLD = 0.05
_TERRAIN_FRACTION = 0.5
_TERRAIN_METERS_PER_HOUR = 100.0


def _num(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def analyze_activity_samples(samples: list[dict[str, Any]]) -> dict[str, Any]:
    prepared = _prepare(samples)
    power_drift = _output_drift(prepared, "power_watts", "garmin_measurement")
    speed_drift = _output_drift(prepared, "speed_mps", "garmin_measurement")
    gap_drift = _output_drift(prepared, "grade_adjusted_speed_mps", "garmin_measurement")
    if not gap_drift["available"]:
        gap_drift["note"] = (
            "Grade-adjusted speed is missing on too many samples. Actual speed was not substituted."
        )
    verdict = _drift_verdict(prepared, power_drift, speed_drift, gap_drift)
    return {
        "sample_count": len(samples),
        "cardiovascular_drift": {
            **verdict,
            "power": power_drift,
            "speed": speed_drift,
            "grade_adjusted_speed": gap_drift,
            "selection": _selection(power_drift, speed_drift, gap_drift),
        },
        "power_fade": _power_fade(power_drift),
        "pace_economy": _pace_economy(power_drift, speed_drift, gap_drift),
        "running_power": _power(prepared),
        "cadence": _cadence(prepared),
        "stamina": _stamina(prepared),
        "safeguard": (
            "Missing samples stay missing. A drop in heart rate beside a drop in power "
            "is not labeled as improved efficiency."
        ),
    }


def efforts_are_comparable(left: dict[str, Any], right: dict[str, Any]) -> bool:
    """True when distance, climb, duration, and grade all agree."""
    if left.get("provider_activity_id") == right.get("provider_activity_id"):
        return False
    if not _similar(left, right):
        return False
    review = _effort_review(left, right)
    return bool(review["duration_within_20_percent"] and review["grade_within_25_percent"])


def compare_activity_analyses(
    target: dict[str, Any],
    others: list[dict[str, Any]],
) -> dict[str, Any]:
    """Match distance within 15 percent and elevation within 25 percent."""
    matches = []
    for other in others:
        if other.get("provider_activity_id") == target.get("provider_activity_id"):
            continue
        if not _similar(target, other):
            continue
        matches.append(_pair(target, other))
    duration_close = sum(bool(match.get("duration_within_20_percent")) for match in matches)
    grade_close = sum(bool(match.get("grade_within_25_percent")) for match in matches)
    return {
        "match_count": len(matches),
        "matches": matches,
        "threshold_review": {
            "distance_and_elevation_matches": len(matches),
            "duration_within_20_percent": duration_close,
            "grade_meters_per_km_within_25_percent": grade_close,
            "note": (
                "The 15 percent distance and 25 percent elevation gates can still pair "
                "efforts whose duration or climbing rate differ. Those pairs are flagged."
            ),
        },
        "note": (
            "Similar means distance within 15 percent and elevation gain within 25 percent. "
            "Grade-adjusted speed is compared only when both activities measured it."
        ),
    }


def _selection(
    power_drift: dict[str, Any],
    speed_drift: dict[str, Any],
    gap_drift: dict[str, Any],
) -> str:
    if power_drift["available"]:
        return "power"
    if gap_drift["available"]:
        return "grade_adjusted_speed"
    if speed_drift["available"]:
        return "speed"
    return "none"


def _output_drift(
    samples: list[dict[str, Any]],
    output_key: str,
    output_source: str,
) -> dict[str, Any]:
    first, second = _halves(samples)
    heart_first, output_first, first_count = _paired(first, output_key)
    heart_second, output_second, second_count = _paired(second, output_key)
    counts = first_count + second_count
    if (
        min(first_count, second_count) < _MIN_HALF
        or None in {heart_first, heart_second, output_first, output_second}
    ):
        return {
            "available": False,
            "output_field": output_key,
            "sample_count": counts,
            "required_samples_per_half": _MIN_HALF,
            "source": "calculated",
        }
    assert heart_first is not None and heart_second is not None
    assert output_first is not None and output_second is not None
    return {
        "available": True,
        "source": "calculated",
        "heart_rate_source": "garmin_measurement",
        "output_source": output_source,
        "output_field": output_key,
        "heart_rate_first_bpm": round(heart_first, 2),
        "heart_rate_second_bpm": round(heart_second, 2),
        "heart_rate_change_bpm": round(heart_second - heart_first, 2),
        "output_first": round(output_first, 4),
        "output_second": round(output_second, 4),
        "output_change": round(output_second - output_first, 4),
        "sample_count": counts,
        "note": (
            "Each half uses samples where heart rate and this output are both present. "
            "Nulls are omitted. The minute after a pause is omitted."
        ),
    }


def _drift_verdict(
    samples: list[dict[str, Any]],
    power_drift: dict[str, Any],
    speed_drift: dict[str, Any],
    gap_drift: dict[str, Any],
) -> dict[str, Any]:
    if power_drift["available"]:
        chosen = power_drift
    elif gap_drift["available"]:
        chosen = gap_drift
    else:
        chosen = speed_drift
    terrain = chosen["output_field"] != "power_watts" and _terrain_changed(samples)
    if not chosen["available"]:
        return {
            "available": False,
            "drift_assessed": False,
            "reason": "insufficient_paired_samples",
            "output_field": chosen["output_field"],
            "labeled_as_improved_efficiency": False,
            "source": "calculated",
        }
    if _series_flat(samples, "heart_rate_bpm", chosen["output_field"]):
        return {
            "available": False,
            "drift_assessed": False,
            "reason": "series_flat",
            "output_field": chosen["output_field"],
            "labeled_as_improved_efficiency": False,
            "source": "calculated",
            "note": (
                "Heart rate and the chosen output do not vary across the chart. "
                "That is not a half-to-half efficiency result."
            ),
        }
    relative = _relative(chosen.get("output_change"), chosen.get("output_first"))
    held = relative is not None and abs(relative) <= _OUTPUT_HOLD
    heart_change = chosen.get("heart_rate_change_bpm")
    base = {
        **chosen,
        "output_held": held,
        "relative_output_change": _round(relative, 4),
        "labeled_as_improved_efficiency": False,
        "terrain_changed": terrain,
    }
    if terrain:
        base["available"] = False
        base["drift_assessed"] = False
        base["reason"] = "terrain_changed"
        base["note"] = (
            "Climbing rate changed between halves. Speed was not treated as maintained "
            "output, so this is not cardiovascular drift."
        )
        return base
    if not held:
        base["available"] = False
        base["drift_assessed"] = False
        base["reason"] = "output_not_maintained"
        base["note"] = (
            "Output changed between halves, so the heart-rate change is not "
            "cardiovascular drift and is not labeled as improved efficiency."
        )
        return base
    assert isinstance(heart_change, (int, float))
    if heart_change > 1:
        reason = "heart_rate_rose_while_output_held"
        note = (
            "Heart rate rose while output stayed within 5 percent. "
            "This is cardiovascular drift. It is not a cause."
        )
    elif heart_change < -1:
        reason = "heart_rate_fell_while_output_held"
        note = (
            "Heart rate fell while output stayed within 5 percent. "
            "This is not labeled as improved efficiency."
        )
    else:
        reason = "heart_rate_steady_while_output_held"
        note = "Heart rate and output both stayed nearly steady."
    base["available"] = True
    base["drift_assessed"] = True
    base["reason"] = reason
    base["note"] = note
    return base


def _series_flat(samples: list[dict[str, Any]], heart_key: str, output_key: str) -> bool:
    paired = [
        sample
        for sample in samples
        if not sample.get("suppressed_after_pause")
        and _num(sample.get(heart_key))
        and _num(sample.get(output_key))
    ]
    return _distinct(paired, heart_key) < 2 and _distinct(paired, output_key) < 2


def _distinct(samples: list[dict[str, Any]], key: str) -> int:
    return len({round(float(sample[key]), 3) for sample in samples})


def _power_fade(power_drift: dict[str, Any]) -> dict[str, Any]:
    if not power_drift["available"]:
        return {"available": False, "faded": False, "source": "calculated"}
    relative = _relative(power_drift.get("output_change"), power_drift.get("output_first"))
    faded = relative is not None and relative <= -_OUTPUT_HOLD
    return {
        "available": True,
        "faded": faded,
        "change_watts": power_drift.get("output_change"),
        "relative_change": _round(relative, 4),
        "source": "calculated",
        "note": "Power fade is a decline in power. It is separate from cardiovascular drift.",
    }


def _pace_economy(
    power_drift: dict[str, Any],
    speed_drift: dict[str, Any],
    gap_drift: dict[str, Any],
) -> dict[str, Any]:
    return {
        "speed_versus_power": _economy_pair(speed_drift, power_drift),
        "grade_adjusted_speed_versus_power": _economy_pair(gap_drift, power_drift),
        "note": (
            "Pace change is compared with power change. Grade-adjusted speed is used "
            "only when the chart measured it. This is not an efficiency grade."
        ),
    }


def _economy_pair(pace: dict[str, Any], power: dict[str, Any]) -> dict[str, Any]:
    if not pace["available"] or not power["available"]:
        return {"available": False, "source": "calculated"}
    pace_relative = _relative(pace.get("output_change"), pace.get("output_first"))
    power_relative = _relative(power.get("output_change"), power.get("output_first"))
    if pace_relative is None or power_relative is None:
        return {"available": False, "source": "calculated"}
    return {
        "available": True,
        "pace_relative_change": round(pace_relative, 4),
        "power_relative_change": round(power_relative, 4),
        "difference": round(pace_relative - power_relative, 4),
        "source": "calculated",
    }


def _relative(change: Any, baseline: Any) -> float | None:
    if not _num(change) or not _num(baseline) or float(baseline) == 0:
        return None
    return float(change) / float(baseline)


def _power(samples: list[dict[str, Any]]) -> dict[str, Any]:
    average, count = _mean(samples, "power_watts")
    values = _values(samples, "power_watts")
    first, second = _halves(samples)
    first_mean, first_count = _mean(first, "power_watts")
    second_mean, second_count = _mean(second, "power_watts")
    climbing = _climbing(samples)
    climbing_mean, climbing_count = _mean(climbing, "power_watts")
    heart, heart_count = _mean(samples, "heart_rate_bpm")
    return {
        "average_watts": _round(average),
        "maximum_watts": max(values) if values else None,
        "sample_count": count,
        "source": "garmin_measurement",
        "source_field": "directPower",
        "first_half_mean_watts": _round(first_mean) if first_count else None,
        "second_half_mean_watts": _round(second_mean) if second_count else None,
        "half_change_watts": _change(first_mean, second_mean, first_count, second_count),
        "climbing_mean_watts": _round(climbing_mean) if climbing_count else None,
        "climbing_sample_count": climbing_count,
        "watts_per_heart_rate": _watts_per_heart(average, heart, heart_count),
        "climbing_note": _climbing_note(climbing_count),
        "trend_source": "calculated",
    }


def _cadence(samples: list[dict[str, Any]]) -> dict[str, Any]:
    first, second = _halves(samples)
    climbing = _climbing(samples)
    return {
        "run_cadence": _cadence_field(
            samples, first, second, climbing, "run_cadence_spm", "directRunCadence"
        ),
        "step_cadence": _cadence_field(
            samples, first, second, climbing, "step_cadence_spm", "directDoubleCadence"
        ),
        "note": (
            "directRunCadence is stored as run cadence. On the checked trail, "
            "directDoubleCadence was about twice that and is stored as step cadence."
        ),
    }


def _cadence_field(
    samples: list[dict[str, Any]],
    first: list[dict[str, Any]],
    second: list[dict[str, Any]],
    climbing: list[dict[str, Any]],
    field: str,
    source_field: str,
) -> dict[str, Any]:
    average, count = _mean(samples, field)
    first_mean, first_count = _mean(first, field)
    second_mean, second_count = _mean(second, field)
    climbing_mean, climbing_count = _mean(climbing, field)
    return {
        "average_spm": _round(average),
        "sample_count": count,
        "source": "garmin_measurement",
        "source_field": source_field,
        "first_half_mean_spm": _round(first_mean) if first_count else None,
        "second_half_mean_spm": _round(second_mean) if second_count else None,
        "change_spm": _change(first_mean, second_mean, first_count, second_count),
        "climbing_mean_spm": _round(climbing_mean) if climbing_count else None,
        "climbing_sample_count": climbing_count,
        "change_source": "calculated",
        "climbing_note": _climbing_note(climbing_count),
    }


def _stamina(samples: list[dict[str, Any]]) -> dict[str, Any]:
    heart, _heart_count = _mean(samples, "heart_rate_bpm")
    power, _power_count = _mean(samples, "power_watts")
    return {
        "potential": _stamina_field(samples, "potential_stamina", "directPotentialStamina"),
        "available": _stamina_field(samples, "available_stamina", "directAvailableStamina"),
        "mean_heart_rate_bpm": _round(heart),
        "mean_power_watts": _round(power),
        "context_source": "garmin_measurement",
        "note": (
            "Depletion is the first stored sample minus the last. "
            "It is calculated, not a Garmin field, and not a cause."
        ),
    }


def _stamina_field(samples: list[dict[str, Any]], field: str, source_field: str) -> dict[str, Any]:
    points = [
        (float(sample["elapsed_seconds"]), float(sample[field]))
        for sample in samples
        if _num(sample.get("elapsed_seconds")) and _num(sample.get(field))
    ]
    if len(points) < 2:
        return {"available": False, "source_field": source_field, "sample_count": len(points)}
    points.sort()
    start = points[0][1]
    end = points[-1][1]
    hours = (points[-1][0] - points[0][0]) / 3600
    depletion = start - end
    return {
        "available": True,
        "source": "garmin_measurement",
        "source_field": source_field,
        "sample_count": len(points),
        "start": round(start, 2),
        "end": round(end, 2),
        "depletion": round(depletion, 2),
        "depletion_per_hour": round(depletion / hours, 2) if hours > 0 else None,
        "depletion_source": "calculated",
    }


def _prepare(samples: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered = [sample for sample in samples if _num(sample.get("elapsed_seconds"))]
    ordered.sort(key=lambda sample: float(sample["elapsed_seconds"]))
    moving = 0.0
    previous: float | None = None
    resume_until: float | None = None
    prepared: list[dict[str, Any]] = []
    for sample in ordered:
        elapsed = float(sample["elapsed_seconds"])
        gap = 0.0 if previous is None else max(elapsed - previous, 0.0)
        paused = previous is not None and gap > _PAUSE_SECONDS
        if not paused:
            moving += gap
        if paused:
            resume_until = moving + _POST_PAUSE_SECONDS
        suppressed = resume_until is not None and moving < resume_until
        prepared.append({**sample, "moving_seconds": moving, "suppressed_after_pause": suppressed})
        previous = elapsed
    return prepared


def _halves(samples: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    prepared = samples if samples and "moving_seconds" in samples[0] else _prepare(samples)
    usable = [sample for sample in prepared if not sample.get("suppressed_after_pause")]
    moving = [
        float(sample["moving_seconds"])
        for sample in usable
        if _num(sample.get("moving_seconds"))
    ]
    if not moving:
        return [], []
    midpoint = (min(moving) + max(moving)) / 2
    first = [sample for sample in usable if float(sample["moving_seconds"]) <= midpoint]
    second = [sample for sample in usable if float(sample["moving_seconds"]) > midpoint]
    return first, second


def _paired(
    samples: list[dict[str, Any]],
    output_key: str,
) -> tuple[float | None, float | None, int]:
    pairs = [
        (float(sample["heart_rate_bpm"]), float(sample[output_key]))
        for sample in samples
        if _num(sample.get("heart_rate_bpm")) and _num(sample.get(output_key))
    ]
    if not pairs:
        return None, None, 0
    heart = sum(pair[0] for pair in pairs) / len(pairs)
    output = sum(pair[1] for pair in pairs) / len(pairs)
    return heart, output, len(pairs)


def _terrain_changed(samples: list[dict[str, Any]]) -> bool:
    first, second = _halves(samples)
    first_rate = _climb_rate(first)
    second_rate = _climb_rate(second)
    if first_rate is None or second_rate is None:
        return False
    difference = abs(second_rate - first_rate)
    baseline = max(abs(first_rate), 1.0)
    return difference >= _TERRAIN_METERS_PER_HOUR and difference / baseline >= _TERRAIN_FRACTION


def _climb_rate(samples: list[dict[str, Any]]) -> float | None:
    ordered = [
        sample
        for sample in samples
        if _num(sample.get("elapsed_seconds")) and _num(sample.get("elevation_meters"))
    ]
    ordered.sort(key=lambda sample: float(sample["elapsed_seconds"]))
    if len(ordered) < 2:
        return None
    gain = 0.0
    moving = 0.0
    for previous, current in zip(ordered, ordered[1:], strict=False):
        gap = float(current["elapsed_seconds"]) - float(previous["elapsed_seconds"])
        if gap <= 0 or gap > _PAUSE_SECONDS:
            continue
        moving += gap
        delta = float(current["elevation_meters"]) - float(previous["elevation_meters"])
        if delta > 0:
            gain += delta
    if moving <= 0:
        return None
    return gain / (moving / 3600.0)


def _climbing(samples: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered = [
        sample
        for sample in samples
        if isinstance(sample.get("elapsed_seconds"), (int, float))
        and isinstance(sample.get("elevation_meters"), (int, float))
    ]
    ordered.sort(key=lambda sample: float(sample["elapsed_seconds"]))
    climbing: list[dict[str, Any]] = []
    for previous, current in zip(ordered, ordered[1:], strict=False):
        if float(current["elevation_meters"]) > float(previous["elevation_meters"]):
            climbing.append(current)
    return climbing


def _climbing_note(count: int) -> str:
    if count:
        return "Climbing samples are chart rows whose elevation is higher than the previous row."
    return "Climbing split is unavailable because the elevation series is missing."


def _mean(samples: list[dict[str, Any]], field: str) -> tuple[float | None, int]:
    values = _values(samples, field)
    if not values:
        return None, 0
    return sum(values) / len(values), len(values)


def _values(samples: list[dict[str, Any]], field: str) -> list[float]:
    return [float(sample[field]) for sample in samples if _num(sample.get(field))]


def _change(
    first: float | None,
    second: float | None,
    first_count: int,
    second_count: int,
) -> float | None:
    if first is None or second is None or first_count < _MIN_HALF or second_count < _MIN_HALF:
        return None
    return round(second - first, 3)


def _watts_per_heart(average: float | None, heart: float | None, heart_count: int) -> float | None:
    if not average or not heart or not heart_count:
        return None
    return _round(average / heart, 4)


def _round(value: float | None, digits: int = 2) -> float | None:
    if value is None:
        return None
    return round(value, digits)


def _similar(target: dict[str, Any], other: dict[str, Any]) -> bool:
    target_distance = target.get("distance_meters")
    other_distance = other.get("distance_meters")
    target_elevation = target.get("elevation_gain_meters")
    other_elevation = other.get("elevation_gain_meters")
    if not all(isinstance(value, (int, float)) for value in (target_distance, other_distance)):
        return False
    if float(target_distance) <= 0:
        return False
    if abs(float(other_distance) - float(target_distance)) / float(target_distance) > 0.15:
        return False
    elevations = (target_elevation, other_elevation)
    if not all(_num(value) and float(value) > 0 for value in elevations):
        return False
    return abs(float(other_elevation) - float(target_elevation)) / float(target_elevation) <= 0.25


def _pair(target: dict[str, Any], other: dict[str, Any]) -> dict[str, Any]:
    target_gap = _gap_available(target)
    other_gap = _gap_available(other)
    return {
        "provider_activity_id": other.get("provider_activity_id"),
        "distance_meters": other.get("distance_meters"),
        "elevation_gain_meters": other.get("elevation_gain_meters"),
        "duration_seconds": other.get("duration_seconds"),
        "heart_rate_change_bpm": _drift_value(other, "heart_rate_change_bpm"),
        "target_heart_rate_change_bpm": _drift_value(target, "heart_rate_change_bpm"),
        "stamina_depletion": _depletion(other),
        "target_stamina_depletion": _depletion(target),
        "grade_adjusted_speed": "compared" if target_gap and other_gap else "unavailable",
        "grade_adjusted_note": (
            None
            if target_gap and other_gap
            else "Grade-adjusted speed is missing on one activity. Actual pace was not substituted."
        ),
        **_effort_review(target, other),
    }


def _grade_meters_per_km(row: dict[str, Any]) -> float | None:
    distance = row.get("distance_meters")
    elevation = row.get("elevation_gain_meters")
    if not _num(distance) or not _num(elevation) or float(distance) <= 0:
        return None
    return float(elevation) / (float(distance) / 1000.0)


def _effort_review(target: dict[str, Any], other: dict[str, Any]) -> dict[str, Any]:
    target_duration = target.get("duration_seconds")
    other_duration = other.get("duration_seconds")
    duration_close = False
    if _num(target_duration) and _num(other_duration) and float(target_duration) > 0:
        gap = abs(float(other_duration) - float(target_duration))
        duration_close = gap / float(target_duration) <= 0.20
    target_grade = _grade_meters_per_km(target)
    other_grade = _grade_meters_per_km(other)
    grade_close = False
    if target_grade and other_grade:
        grade_close = abs(other_grade - target_grade) / target_grade <= 0.25
    aligned = duration_close and grade_close
    return {
        "duration_within_20_percent": duration_close,
        "grade_within_25_percent": grade_close,
        "target_grade_meters_per_km": _round(target_grade, 1),
        "grade_meters_per_km": _round(other_grade, 1),
        "effort_review": "aligned" if aligned else "gates_match_but_effort_differs",
    }


def _gap_available(row: dict[str, Any]) -> bool:
    analysis = row.get("analysis")
    if not isinstance(analysis, dict):
        return False
    drift = analysis.get("cardiovascular_drift")
    if not isinstance(drift, dict):
        return False
    gap = drift.get("grade_adjusted_speed")
    return isinstance(gap, dict) and bool(gap.get("available"))


def _drift_value(row: dict[str, Any], field: str) -> float | None:
    analysis = row.get("analysis")
    if not isinstance(analysis, dict):
        return None
    drift = analysis.get("cardiovascular_drift")
    if not isinstance(drift, dict) or not drift.get("available"):
        return None
    value = drift.get(field)
    return float(value) if isinstance(value, (int, float)) else None


def _depletion(row: dict[str, Any]) -> float | None:
    analysis = row.get("analysis")
    if not isinstance(analysis, dict):
        return None
    stamina = analysis.get("stamina")
    if not isinstance(stamina, dict):
        return None
    potential = stamina.get("potential")
    if not isinstance(potential, dict) or not potential.get("available"):
        return None
    value = potential.get("depletion")
    return float(value) if isinstance(value, (int, float)) else None
