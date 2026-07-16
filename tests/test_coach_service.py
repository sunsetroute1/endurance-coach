"""Tests for LangGraph coach service."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage

from endurance_coach.coach.service import build_coach_service
from endurance_coach.config import Settings
from endurance_coach.domain.enums import MetricFamily
from endurance_coach.domain.models import CoachRequest, MetricSnapshot, MetricValue


class StubDataRepo:
    async def get_activities_since(self, user_id, since, *, limit: int = 100):
        return []

    async def get_sleep_by_date(self, user_id, end_date, *, window_days: int = 14):
        return {}

    async def get_hrv_in_window(self, user_id, end_date, *, window_days: int = 14):
        return []


class StubMetricEngine:
    def __init__(self, user_id) -> None:
        now = datetime.now(UTC)
        self._snapshots = {
            MetricFamily.LOAD: MetricSnapshot(
                user_id=user_id,
                family=MetricFamily.LOAD,
                as_of=now,
                metrics=(
                    MetricValue(key="ctl", value=60, unit="load", computed_at=now),
                    MetricValue(key="atl", value=70, unit="load", computed_at=now),
                    MetricValue(key="tsb", value=-10, unit="load", computed_at=now),
                    MetricValue(key="acwr", value=1.17, unit="ratio", computed_at=now),
                ),
            ),
            MetricFamily.RECOVERY: MetricSnapshot(
                user_id=user_id,
                family=MetricFamily.RECOVERY,
                as_of=now,
                metrics=(
                    MetricValue(key="recovery_score", value=65, unit="score", computed_at=now),
                    MetricValue(key="fatigue_score", value=45, unit="score", computed_at=now),
                    MetricValue(key="sleep_debt_hours", value=1.5, unit="hours", computed_at=now),
                ),
            ),
        }

    async def get_latest_snapshot(self, user_id, family):
        return self._snapshots.get(family)


class StubLLM:
    async def ainvoke(self, messages):
        return AIMessage(
            content="""
            {
              "explanation": "LLM-backed daily briefing.",
              "recommendations": [
                {
                  "category": "training",
                  "action": "Easy aerobic run.",
                  "rationale": "TSB is mildly negative.",
                  "metric_citations": ["tsb"]
                }
              ],
              "metrics_used": ["tsb", "recovery_score"],
              "confidence": 0.88
            }
            """
        )


class StubLLMFactory:
    def create(self):
        return StubLLM()


@pytest.mark.asyncio
async def test_coach_service_fallback_without_api_key() -> None:
    user_id = uuid4()
    settings = Settings(openai_api_key=None)
    service = build_coach_service(
        StubDataRepo(),  # type: ignore[arg-type]
        StubMetricEngine(user_id),  # type: ignore[arg-type]
        settings,
    )

    response = await service.explain_today(user_id)
    assert "TSB" in response.explanation
    assert response.recommendations


@pytest.mark.asyncio
async def test_coach_service_uses_llm_when_configured() -> None:
    user_id = uuid4()
    settings = Settings(openai_api_key="test-key")
    service = build_coach_service(
        StubDataRepo(),  # type: ignore[arg-type]
        StubMetricEngine(user_id),  # type: ignore[arg-type]
        settings,
        llm_factory=StubLLMFactory(),  # type: ignore[arg-type]
    )

    response = await service.respond(
        CoachRequest(user_id=user_id, intent="explain_today"),
    )
    assert response.explanation == "LLM-backed daily briefing."
    assert response.confidence == 0.88
