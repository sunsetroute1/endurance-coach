"""Shared metric snapshot helpers for coach and MCP layers."""

from __future__ import annotations

from endurance_coach.domain.enums import InjuryRiskLevel
from endurance_coach.domain.models import MetricSnapshot

_INJURY_RISK_LEVELS = (
    InjuryRiskLevel.LOW,
    InjuryRiskLevel.MODERATE,
    InjuryRiskLevel.HIGH,
    InjuryRiskLevel.CRITICAL,
)


def snapshot_metrics(snapshot: MetricSnapshot | None) -> dict[str, dict[str, object]]:
    if snapshot is None:
        return {}
    return {
        metric.key: {"value": metric.value, "unit": metric.unit}
        for metric in snapshot.metrics
    }


def snapshot_to_dict(snapshot: MetricSnapshot | None) -> dict[str, object]:
    if snapshot is None:
        return {}
    return {
        "as_of": snapshot.as_of.isoformat(),
        "family": snapshot.family.value,
        "metrics": snapshot_metrics(snapshot),
    }


def metric_value(snapshot: MetricSnapshot | None, key: str, default: float = 0.0) -> float:
    if snapshot is None:
        return default
    for metric in snapshot.metrics:
        if metric.key == key:
            return metric.value
    return default


def injury_risk_level_from_snapshot(snapshot: MetricSnapshot | None) -> str | None:
    if snapshot is None:
        return None
    metrics = snapshot_metrics(snapshot)
    level_metric = metrics.get("injury_risk_level")
    if level_metric is None:
        return None
    index = int(float(level_metric["value"]))
    if 0 <= index < len(_INJURY_RISK_LEVELS):
        return _INJURY_RISK_LEVELS[index].value
    return None


def injury_risk_factors_from_snapshot(snapshot: MetricSnapshot | None) -> tuple[str, ...]:
    if snapshot is None:
        return ()
    metrics = snapshot_metrics(snapshot)
    factors_metric = metrics.get("injury_risk_factors")
    if factors_metric is None:
        return ()
    unit = str(factors_metric.get("unit", ""))
    if not unit:
        return ()
    return tuple(part for part in unit.split(";") if part)
