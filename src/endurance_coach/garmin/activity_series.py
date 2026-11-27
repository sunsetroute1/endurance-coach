"""Parse Garmin activity-detail charts without scaling or filling gaps."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

# Live charts already use unitKey. Descriptor factors (speed 0.1, elevation 100,
# duration 1000) did not match the stored activity totals, so they are not applied.
CHART_FIELDS: dict[str, str] = {
    "directTimestamp": "timestamp_ms",
    "sumDuration": "elapsed_seconds",
    "directHeartRate": "heart_rate_bpm",
    "directPower": "power_watts",
    "directRunCadence": "run_cadence_spm",
    "directDoubleCadence": "step_cadence_spm",
    "directPotentialStamina": "potential_stamina",
    "directAvailableStamina": "available_stamina",
    "directElevation": "elevation_meters",
    "directSpeed": "speed_mps",
    "directGradeAdjustedSpeed": "grade_adjusted_speed_mps",
}

PRIORITY_FIELDS: tuple[str, ...] = (
    "heart_rate_bpm",
    "power_watts",
    "run_cadence_spm",
    "potential_stamina",
    "available_stamina",
)

SOURCE_FIELDS: dict[str, str] = {value: key for key, value in CHART_FIELDS.items()}


def parse_activity_detail_chart(payload: dict[str, Any]) -> dict[str, Any]:
    """Align one chart row to one sample. Missing metrics stay null."""
    indexes, units = _descriptors(payload)
    samples: list[dict[str, Any]] = []
    for row in payload.get("activityDetailMetrics") or []:
        if not isinstance(row, dict):
            continue
        metrics = row.get("metrics")
        if not isinstance(metrics, list):
            continue
        sample = _sample(metrics, indexes)
        sample["sample_index"] = len(samples)
        samples.append(sample)
    present = {
        field: sum(sample.get(field) is not None for sample in samples)
        for field in CHART_FIELDS.values()
    }
    return {
        "samples": samples,
        "units": units,
        "fields_present": present,
        "priority_fields_present": any(present.get(field, 0) for field in PRIORITY_FIELDS),
        "factors_applied": False,
        "sampling": sampling_summary(samples),
        "note": (
            "Each chart row is one sample. Nulls are kept. "
            "Values are stored in the descriptor unit without applying its factor. "
            "Nothing is interpolated."
        ),
    }


def sampling_summary(samples: list[dict[str, Any]]) -> dict[str, Any]:
    stamps = [
        sample["timestamp_ms"]
        for sample in samples
        if isinstance(sample.get("timestamp_ms"), (int, float))
    ]
    deltas = [
        right - left
        for left, right in zip(stamps, stamps[1:], strict=False)
        if right >= left
    ]
    short = [delta for delta in deltas if delta <= 30_000]
    chosen = short or deltas
    median = _median(chosen)
    return {
        "sample_count": len(samples),
        "median_interval_seconds": round(median / 1000, 3) if median is not None else None,
        "max_interval_seconds": round(max(deltas) / 1000, 3) if deltas else None,
    }


def decimate_samples(samples: list[dict[str, Any]], limit: int = 120) -> dict[str, Any]:
    """Keep every kth stored sample. This does not invent points between them."""
    if limit < 1:
        limit = 1
    if len(samples) <= limit:
        step = 1
        chosen = samples
    else:
        step = (len(samples) + limit - 1) // limit
        chosen = samples[::step]
    return {
        "decimated": step > 1,
        "decimation_step": step,
        "returned_count": len(chosen),
        "samples": [_public_sample(sample) for sample in chosen],
        "note": "Every kth stored sample is returned. Missing samples are not interpolated.",
    }


def _descriptors(payload: dict[str, Any]) -> tuple[dict[str, int], dict[str, str]]:
    indexes: dict[str, int] = {}
    units: dict[str, str] = {}
    for descriptor in payload.get("metricDescriptors") or []:
        if not isinstance(descriptor, dict):
            continue
        key = descriptor.get("key")
        index = descriptor.get("metricsIndex")
        if not isinstance(key, str) or not isinstance(index, int):
            continue
        if key in CHART_FIELDS:
            indexes[key] = index
        unit = descriptor.get("unit")
        if isinstance(unit, dict):
            unit_name = unit.get("unitKey") or unit.get("key")
            if isinstance(unit_name, str):
                units[key] = unit_name
    return indexes, units


def _sample(metrics: list[Any], indexes: dict[str, int]) -> dict[str, Any]:
    values = {field: None for field in CHART_FIELDS.values()}
    for key, index in indexes.items():
        number = _number(metrics[index]) if index < len(metrics) else None
        values[CHART_FIELDS[key]] = number
    recorded_at = _recorded_at(values.get("timestamp_ms"))
    return {**values, "recorded_at": recorded_at}


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _recorded_at(timestamp_ms: Any) -> datetime | None:
    if not isinstance(timestamp_ms, (int, float)) or isinstance(timestamp_ms, bool):
        return None
    seconds = timestamp_ms / 1000 if timestamp_ms > 10_000_000_000 else timestamp_ms
    return datetime.fromtimestamp(seconds, tz=UTC)


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[len(ordered) // 2]


def _public_sample(sample: dict[str, Any]) -> dict[str, Any]:
    recorded_at = sample.get("recorded_at")
    return {
        "sample_index": sample.get("sample_index"),
        "recorded_at": recorded_at.isoformat() if isinstance(recorded_at, datetime) else None,
        "elapsed_seconds": sample.get("elapsed_seconds"),
        "heart_rate_bpm": sample.get("heart_rate_bpm"),
        "power_watts": sample.get("power_watts"),
        "run_cadence_spm": sample.get("run_cadence_spm"),
        "step_cadence_spm": sample.get("step_cadence_spm"),
        "potential_stamina": sample.get("potential_stamina"),
        "available_stamina": sample.get("available_stamina"),
        "elevation_meters": sample.get("elevation_meters"),
        "speed_mps": sample.get("speed_mps"),
        "grade_adjusted_speed_mps": sample.get("grade_adjusted_speed_mps"),
    }
