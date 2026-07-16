"""Tests for coach analysis and parsing."""

from datetime import UTC, datetime
from uuid import uuid4

from endurance_coach.coach.analysis import analyze_metric_context
from endurance_coach.coach.parsing import parse_coach_response
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


def test_analyze_metric_context_flags_elevated_acwr() -> None:
    snapshots = (
        _snapshot(
            MetricFamily.LOAD,
            {"ctl": 60, "atl": 95, "tsb": -15, "acwr": 1.6, "weekly_load": 400},
        ),
        _snapshot(MetricFamily.RECOVERY, {"recovery_score": 55, "sleep_debt_hours": 1}),
        _snapshot(MetricFamily.RISK, {"injury_risk_score": 30, "injury_risk_level": 1}),
    )

    analysis = analyze_metric_context(
        intent="explain_today",
        as_of=datetime.now(UTC),
        snapshots=snapshots,
    )

    assert analysis["training_focus"] == "aerobic"
    assert "elevated_acwr" in analysis["flags"]
    assert analysis["metric_values"]["acwr"] == 1.6


def test_parse_coach_response_from_json() -> None:
    payload = """
    {
      "explanation": "You are carrying fatigue.",
      "recommendations": [
        {
          "category": "training",
          "action": "Keep it easy today.",
          "rationale": "TSB is negative.",
          "metric_citations": ["tsb"]
        }
      ],
      "metrics_used": ["tsb", "recovery_score"],
      "confidence": 0.9
    }
    """
    response = parse_coach_response(payload)
    assert response.explanation == "You are carrying fatigue."
    assert response.recommendations[0].metric_citations == ("tsb",)
    assert response.confidence == 0.9


def test_parse_coach_response_handles_markdown_fence() -> None:
    payload = """```json
    {
      "explanation": "Ready for quality work.",
      "recommendations": [],
      "metrics_used": ["tsb"],
      "confidence": 0.8
    }
    ```"""
    response = parse_coach_response(payload)
    assert response.explanation == "Ready for quality work."
