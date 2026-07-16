"""Async wrapper around the synchronous garminconnect client."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path
from typing import Any, TypeVar

from garminconnect import Garmin

T = TypeVar("T")


class GarminClient:
    """Thin async facade over python-garminconnect using garmin_mcp token storage."""

    def __init__(self, client: Garmin) -> None:
        self._client = client

    @classmethod
    async def from_token_path(cls, token_path: Path) -> GarminClient:
        return await asyncio.to_thread(cls._connect_sync, token_path)

    @staticmethod
    def _connect_sync(token_path: Path) -> GarminClient:
        client = Garmin()
        client.login(str(token_path.expanduser()))
        return GarminClient(client)

    async def _call(self, method: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        return await asyncio.to_thread(method, *args, **kwargs)

    async def get_activities(self, start: int = 0, limit: int = 50) -> list[dict[str, Any]]:
        result = await self._call(self._client.get_activities, start, limit)
        if isinstance(result, list):
            return result
        if isinstance(result, dict):
            return result.get("activities", [])
        return []

    async def get_activity(self, activity_id: str) -> dict[str, Any]:
        return await self._call(self._client.get_activity, activity_id)

    async def get_activity_laps(self, activity_id: str) -> list[dict[str, Any]]:
        result = await self._call(self._client.get_activity_splits, activity_id)
        if isinstance(result, dict):
            laps = result.get("lapDTOs", [])
            return laps if isinstance(laps, list) else []
        if isinstance(result, list):
            return result
        return []

    async def get_sleep_data(self, day: date) -> dict[str, Any]:
        return await self._call(self._client.get_sleep_data, day.isoformat())

    async def get_hrv_data(self, day: date) -> dict[str, Any] | None:
        return await self._call(self._client.get_hrv_data, day.isoformat())

    async def get_training_readiness(self, day: date) -> list[dict[str, Any]]:
        return await self._call(self._client.get_training_readiness, day.isoformat())

    async def get_body_battery(self, day: date) -> list[dict[str, Any]]:
        return await self._call(
            self._client.get_body_battery,
            day.isoformat(),
            day.isoformat(),
        )

    async def get_stress_data(self, day: date) -> dict[str, Any]:
        return await self._call(self._client.get_stress_data, day.isoformat())

    async def get_daily_stats(self, day: date) -> dict[str, Any]:
        return await self._call(self._client.get_stats, day.isoformat())

    def iter_dates(self, start: date, end: date) -> list[date]:
        days: list[date] = []
        current = start
        while current <= end:
            days.append(current)
            current += timedelta(days=1)
        return days
