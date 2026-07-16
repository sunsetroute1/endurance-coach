"""Tests for deterministic coach briefings."""

from datetime import UTC, datetime
from uuid import uuid4

from endurance_coach.coach.briefings import (
    build_daily_training_plan,
    build_explain_today,
    build_weekly_summary,
)
from endurance_coach.domain.enums import MetricFamily
from endurance_coach.domain.models import MetricSnapshot, MetricValue


def _snapshot(family: MetricFamily, metrics: dict[str, float]) -> MetricSnapshot:
    as_of = datetime.now(UTC)
    return MetricSnapshot(
        user_id=uuid4(),
        family=family,
        as_of=as_of,
        metrics=tuple(
            MetricValue(key=key, value=value, unit="x", computed_at=as_of)
            for key, value in metrics.items()
        ),
    )


def test_explain_today_recommends_recovery_when_fatigued() -> None:
    load = _snapshot(MetricFamily.LOAD, {"ctl": 70, "atl": 90, "tsb": -20, "acwr": 1.3})
    recovery = _snapshot(
        MetricFamily.RECOVERY,
        {"recovery_score": 40, "fatigue_score": 70, "sleep_debt_hours": 4},
    )
    risk = _snapshot(
        MetricFamily.RISK,
        {"injury_risk_score": 55, "injury_risk_level": 2, "injury_risk_factors": 1},
    )

    response = build_explain_today(
        as_of=datetime.now(UTC),
        load=load,
        recovery=recovery,
        risk=risk,
    )

    assert "Recovery score is 40" in response.explanation
    assert any(rec.category == "recovery" for rec in response.recommendations)
    assert response.confidence >= 0.5


def test_daily_training_plan_quality_when_fresh() -> None:
    load = _snapshot(MetricFamily.LOAD, {"ctl": 65, "atl": 50, "tsb": 15, "acwr": 0.9})
    recovery = _snapshot(
        MetricFamily.RECOVERY,
        {"recovery_score": 80, "fatigue_score": 20, "sleep_debt_hours": 0.5},
    )

    response = build_daily_training_plan(
        as_of=datetime.now(UTC),
        load=load,
        recovery=recovery,
        risk=None,
    )

    assert "Quality session" in response.explanation
    assert response.recommendations[0].category == "session"


def test_weekly_summary_includes_activity_totals() -> None:
    load = _snapshot(
        MetricFamily.LOAD,
        {"weekly_load": 420, "weekly_load_progression": 8, "tsb": -5},
    )
    recovery = _snapshot(MetricFamily.RECOVERY, {"recovery_score": 60})

    response = build_weekly_summary(
        week_end=datetime.now(UTC).date(),
        activity_count=5,
        total_duration_seconds=5 * 3600,
        load=load,
        recovery=recovery,
        risk=None,
        avg_sleep_hours=7.2,
        hrv_trend_pct=-3.5,
    )

    assert "5 sessions" in response.explanation
    assert "Average sleep was 7.2h" in response.explanation
    assert "HRV trend" in response.explanation
