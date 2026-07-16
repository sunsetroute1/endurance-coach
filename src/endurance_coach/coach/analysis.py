"""Deterministic metric analysis — no LLM arithmetic."""

from __future__ import annotations

from datetime import datetime

from endurance_coach.coach.briefings import training_focus
from endurance_coach.coach.metrics import (
    injury_risk_factors_from_snapshot,
    injury_risk_level_from_snapshot,
    metric_value,
    snapshot_to_dict,
)
from endurance_coach.domain.enums import MetricFamily
from endurance_coach.domain.models import MetricSnapshot


def _snapshot_by_family(
    snapshots: tuple[MetricSnapshot, ...],
    family: MetricFamily,
) -> MetricSnapshot | None:
    for snapshot in snapshots:
        if snapshot.family == family:
            return snapshot
    return None


def analyze_metric_context(
    *,
    intent: str,
    as_of: datetime,
    snapshots: tuple[MetricSnapshot, ...],
    activity_summary: dict[str, object] | None = None,
) -> dict[str, object]:
    load = _snapshot_by_family(snapshots, MetricFamily.LOAD)
    recovery = _snapshot_by_family(snapshots, MetricFamily.RECOVERY)
    risk = _snapshot_by_family(snapshots, MetricFamily.RISK)

    tsb = metric_value(load, "tsb")
    recovery_score = metric_value(recovery, "recovery_score")
    injury_level = injury_risk_level_from_snapshot(risk)
    focus, focus_action, citations = training_focus(
        tsb=tsb,
        recovery_score=recovery_score,
        injury_level=injury_level,
    )

    flags: list[str] = []
    acwr = metric_value(load, "acwr")
    sleep_debt = metric_value(recovery, "sleep_debt_hours")
    if acwr > 1.5:
        flags.append("elevated_acwr")
    if sleep_debt >= 3:
        flags.append("sleep_debt")
    if tsb < -20:
        flags.append("accumulated_fatigue")
    if injury_level in {"high", "critical"}:
        flags.append("elevated_injury_risk")

    metric_values = {
        "ctl": metric_value(load, "ctl"),
        "atl": metric_value(load, "atl"),
        "tsb": tsb,
        "acwr": acwr,
        "weekly_load": metric_value(load, "weekly_load"),
        "weekly_load_progression": metric_value(load, "weekly_load_progression"),
        "recovery_score": recovery_score,
        "fatigue_score": metric_value(recovery, "fatigue_score"),
        "sleep_debt_hours": sleep_debt,
        "hrv_deviation_pct": metric_value(recovery, "hrv_deviation_pct"),
        "injury_risk_score": metric_value(risk, "injury_risk_score"),
    }

    return {
        "intent": intent,
        "as_of": as_of.isoformat(),
        "metric_values": metric_values,
        "training_focus": focus,
        "training_action": focus_action,
        "metric_citations": list(citations),
        "injury_level": injury_level,
        "injury_factors": list(injury_risk_factors_from_snapshot(risk)),
        "flags": flags,
        "snapshots": {
            "load": snapshot_to_dict(load),
            "recovery": snapshot_to_dict(recovery),
            "risk": snapshot_to_dict(risk),
        },
        "activity_summary": activity_summary or {},
    }
