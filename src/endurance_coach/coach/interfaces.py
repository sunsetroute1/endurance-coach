"""Coach service interfaces — LLM explains, never computes metrics."""

from __future__ import annotations

from datetime import date
from typing import Protocol
from uuid import UUID

from endurance_coach.domain.models import CoachRequest, CoachResponse, MetricSnapshot


class CoachContextFetcher(Protocol):
    """Read-only context assembly for coach nodes."""

    async def fetch_metric_snapshots(
        self,
        user_id: UUID,
        as_of: date,
    ) -> tuple[MetricSnapshot, ...]: ...


class CoachService(Protocol):
    """High-level coaching API consumed by MCP tools and API routes."""

    async def explain_today(self, user_id: UUID) -> CoachResponse: ...

    async def summarize_last_week(self, user_id: UUID) -> CoachResponse: ...

    async def generate_daily_training_plan(self, user_id: UUID) -> CoachResponse: ...

    async def respond(self, request: CoachRequest) -> CoachResponse: ...


class CoachGraph(Protocol):
    """LangGraph workflow contract (implemented in Phase 6)."""

    async def invoke(self, request: CoachRequest) -> CoachResponse: ...
