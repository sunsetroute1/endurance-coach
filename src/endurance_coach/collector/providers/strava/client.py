"""Async Strava REST API client."""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Any

import httpx

from endurance_coach.collector.providers.strava.token_store import StravaTokenStore

STRAVA_API_BASE = "https://www.strava.com/api/v3"


class StravaClient:
    def __init__(self, access_token: str) -> None:
        self._access_token = access_token

    @classmethod
    async def from_token_store(cls, token_store: StravaTokenStore) -> StravaClient:
        tokens = await token_store.get_valid_tokens()
        if tokens is None:
            raise RuntimeError("Strava tokens are not available")
        return cls(tokens.access_token)

    async def get_activities(
        self,
        *,
        after_epoch: int | None = None,
        page: int = 1,
        per_page: int = 50,
    ) -> list[dict[str, Any]]:
        params: dict[str, int] = {"page": page, "per_page": per_page}
        if after_epoch is not None:
            params["after"] = after_epoch
        return await self._get_list("/athlete/activities", params=params)

    async def get_activity(self, activity_id: str) -> dict[str, Any]:
        return await self._get_json(f"/activities/{activity_id}")

    async def get_athlete(self) -> dict[str, Any]:
        return await self._get_json("/athlete")

    async def _get_list(
        self,
        path: str,
        *,
        params: dict[str, int] | None = None,
    ) -> list[dict[str, Any]]:
        payload = await self._get_json(path, params=params)
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        return []

    async def _get_json(
        self,
        path: str,
        *,
        params: dict[str, int] | None = None,
    ) -> Any:
        async with httpx.AsyncClient(
            base_url=STRAVA_API_BASE,
            timeout=30.0,
            headers={"Authorization": f"Bearer {self._access_token}"},
        ) as client:
            response = await client.get(path, params=params)
            response.raise_for_status()
            return response.json()


def date_to_epoch(day: date) -> int:
    return int(datetime.combine(day, time.min).timestamp())
