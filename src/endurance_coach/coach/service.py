"""Coach service — LangGraph orchestration with deterministic fallback."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from endurance_coach.analytics.engine import DefaultMetricEngine
from endurance_coach.analytics.repositories import AnalyticsDataRepository
from endurance_coach.coach.graph import build_coach_graph
from endurance_coach.coach.llm import ChatModelFactory, create_chat_model_factory
from endurance_coach.config import Settings
from endurance_coach.domain.models import CoachRequest, CoachResponse


class DefaultCoachService:
    def __init__(self, graph: Any) -> None:
        self._graph = graph

    async def respond(self, request: CoachRequest) -> CoachResponse:
        result = await self._graph.ainvoke({"request": request})
        response = result.get("response")
        if response is None:
            raise RuntimeError("Coach graph did not produce a response")
        return response

    async def explain_today(self, user_id: UUID) -> CoachResponse:
        return await self.respond(
            CoachRequest(user_id=user_id, intent="explain_today"),
        )

    async def summarize_last_week(self, user_id: UUID) -> CoachResponse:
        return await self.respond(
            CoachRequest(user_id=user_id, intent="summarize_last_week"),
        )

    async def generate_daily_training_plan(self, user_id: UUID) -> CoachResponse:
        return await self.respond(
            CoachRequest(user_id=user_id, intent="generate_daily_training_plan"),
        )


def build_coach_service(
    data_repo: AnalyticsDataRepository,
    metric_engine: DefaultMetricEngine,
    settings: Settings,
    *,
    llm_factory: ChatModelFactory | None = None,
) -> DefaultCoachService:
    graph = build_coach_graph(
        data_repo=data_repo,
        metric_engine=metric_engine,
        settings=settings,
        llm_factory=llm_factory or create_chat_model_factory(settings),
    )
    return DefaultCoachService(graph)
