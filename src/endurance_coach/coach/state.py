"""LangGraph state for the coach workflow."""

from __future__ import annotations

from typing import TypedDict

from endurance_coach.domain.models import CoachRequest, CoachResponse, MetricSnapshot


class CoachState(TypedDict, total=False):
    request: CoachRequest
    snapshots: tuple[MetricSnapshot, ...]
    activity_summary: dict[str, object]
    analysis: dict[str, object]
    response: CoachResponse
