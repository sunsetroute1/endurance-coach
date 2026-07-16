"""LangGraph nodes for the coach workflow."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from endurance_coach.coach.analysis import analyze_metric_context
from endurance_coach.coach.briefings import (
    build_daily_training_plan,
    build_explain_today,
    build_weekly_summary,
    current_as_of,
)
from endurance_coach.coach.context import DefaultCoachContextFetcher
from endurance_coach.coach.parsing import parse_coach_response
from endurance_coach.coach.prompts import SYSTEM_PROMPT, build_user_prompt
from endurance_coach.coach.state import CoachState
from endurance_coach.domain.enums import MetricFamily
from endurance_coach.domain.models import CoachResponse, MetricSnapshot


def _snapshot_by_family(
    snapshots: tuple[MetricSnapshot, ...],
    family: MetricFamily,
) -> MetricSnapshot | None:
    for snapshot in snapshots:
        if snapshot.family == family:
            return snapshot
    return None


def make_fetch_context(fetcher: DefaultCoachContextFetcher):
    async def fetch_context(state: CoachState) -> dict[str, object]:
        request = state["request"]
        as_of = request.context_date or datetime.now(UTC).date()
        snapshots = await fetcher.fetch_metric_snapshots(request.user_id, as_of)
        activity_summary: dict[str, object] = {}
        if request.intent == "summarize_last_week":
            activity_summary = await fetcher.fetch_activity_summary(request.user_id)
        return {
            "snapshots": snapshots,
            "activity_summary": activity_summary,
        }

    return fetch_context


def analyze_metrics(state: CoachState) -> dict[str, object]:
    request = state["request"]
    snapshots = state.get("snapshots", ())
    activity_summary = state.get("activity_summary", {})
    as_of = datetime.combine(
        request.context_date or datetime.now(UTC).date(),
        datetime.min.time(),
        tzinfo=UTC,
    )
    analysis = analyze_metric_context(
        intent=request.intent,
        as_of=as_of,
        snapshots=snapshots,
        activity_summary=activity_summary,
    )
    return {"analysis": analysis}


def _fallback_response(state: CoachState) -> CoachResponse:
    request = state["request"]
    snapshots = state.get("snapshots", ())
    activity_summary = state.get("activity_summary", {})
    as_of = current_as_of()
    load = _snapshot_by_family(snapshots, MetricFamily.LOAD)
    recovery = _snapshot_by_family(snapshots, MetricFamily.RECOVERY)
    risk = _snapshot_by_family(snapshots, MetricFamily.RISK)

    if request.intent == "generate_daily_training_plan":
        return build_daily_training_plan(
            as_of=as_of,
            load=load,
            recovery=recovery,
            risk=risk,
        )
    if request.intent == "summarize_last_week":
        week_end = datetime.now(UTC).date()
        return build_weekly_summary(
            week_end=week_end,
            activity_count=int(activity_summary.get("activity_count", 0)),
            total_duration_seconds=int(activity_summary.get("total_duration_seconds", 0)),
            load=load,
            recovery=recovery,
            risk=risk,
            avg_sleep_hours=activity_summary.get("avg_sleep_hours"),  # type: ignore[arg-type]
            hrv_trend_pct=activity_summary.get("hrv_trend_pct"),  # type: ignore[arg-type]
        )
    return build_explain_today(
        as_of=as_of,
        load=load,
        recovery=recovery,
        risk=risk,
    )


def make_generate_response(llm: BaseChatModel | None):
    async def generate_response(state: CoachState) -> dict[str, object]:
        if llm is None:
            return {"response": _fallback_response(state)}

        analysis = state.get("analysis", {})
        try:
            result = await llm.ainvoke(
                [
                    SystemMessage(content=SYSTEM_PROMPT),
                    HumanMessage(content=build_user_prompt(analysis)),
                ]
            )
            content = str(result.content)
            response = parse_coach_response(content)
        except (ValueError, KeyError, TypeError, json.JSONDecodeError):
            response = _fallback_response(state)
        return {"response": response}

    return generate_response
