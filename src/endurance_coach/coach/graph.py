"""LangGraph coach workflow."""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from endurance_coach.analytics.engine import DefaultMetricEngine
from endurance_coach.analytics.repositories import AnalyticsDataRepository
from endurance_coach.coach.context import DefaultCoachContextFetcher
from endurance_coach.coach.llm import ChatModelFactory
from endurance_coach.coach.nodes import (
    analyze_metrics,
    make_fetch_context,
    make_generate_response,
)
from endurance_coach.coach.state import CoachState
from endurance_coach.config import Settings


def build_coach_graph(
    *,
    data_repo: AnalyticsDataRepository,
    metric_engine: DefaultMetricEngine,
    settings: Settings,
    llm_factory: ChatModelFactory | None = None,
) -> Any:
    from endurance_coach.coach.llm import create_chat_model_factory

    factory = llm_factory or create_chat_model_factory(settings)
    llm = factory.create()
    fetcher = DefaultCoachContextFetcher(data_repo, metric_engine)

    graph = StateGraph(CoachState)
    graph.add_node("fetch_context", make_fetch_context(fetcher))
    graph.add_node("analyze_metrics", analyze_metrics)
    graph.add_node("generate_response", make_generate_response(llm))
    graph.add_edge(START, "fetch_context")
    graph.add_edge("fetch_context", "analyze_metrics")
    graph.add_edge("analyze_metrics", "generate_response")
    graph.add_edge("generate_response", END)
    return graph.compile()
