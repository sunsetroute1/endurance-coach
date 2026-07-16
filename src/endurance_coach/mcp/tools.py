"""MCP tool contracts."""

from __future__ import annotations

from datetime import date
from typing import Protocol
from uuid import UUID


class MCPToolRegistry(Protocol):
    """Registry of coaching-oriented MCP tools."""

    async def get_recent_activities(
        self,
        user_id: UUID,
        days: int = 7,
    ) -> dict[str, object]: ...

    async def get_sleep_summary(
        self,
        user_id: UUID,
        target_date: date | None = None,
    ) -> dict[str, object]: ...

    async def get_hrv_trend(
        self,
        user_id: UUID,
        days: int = 14,
    ) -> dict[str, object]: ...

    async def get_training_readiness(
        self,
        user_id: UUID,
        target_date: date | None = None,
    ) -> dict[str, object]: ...

    async def get_recovery_state(self, user_id: UUID) -> dict[str, object]: ...

    async def get_weekly_load(self, user_id: UUID) -> dict[str, object]: ...

    async def get_injury_risk(self, user_id: UUID) -> dict[str, object]: ...

    async def generate_daily_training_plan(self, user_id: UUID) -> dict[str, object]: ...

    async def explain_today(self, user_id: UUID) -> dict[str, object]: ...

    async def summarize_last_week(self, user_id: UUID) -> dict[str, object]: ...
