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

    async def get_activity_details(
        self,
        activity_id: str,
        *,
        maxchart: int = 20000,
    ) -> dict[str, Any]:
        result = await self._call(self._client.get_activity_details, activity_id, maxchart, 0)
        return result if isinstance(result, dict) else {}

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

    async def get_hrv_data_range(self, start: date, end: date) -> dict[str, Any] | None:
        return await self._call(
            self._client.get_hrv_data_range,
            start.isoformat(),
            end.isoformat(),
        )

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

    async def get_endurance_score(self, start: date, end: date) -> Any:
        return await self._call(
            self._client.get_endurance_score,
            start.isoformat(),
            end.isoformat(),
            "daily",
        )

    async def get_hill_score(self, start: date, end: date) -> Any:
        return await self._call(self._client.get_hill_score, start.isoformat(), end.isoformat())

    async def get_running_tolerance(self, start: date, end: date) -> Any:
        return await self._call(
            self._client.get_running_tolerance,
            start.isoformat(),
            end.isoformat(),
            "daily",
        )

    async def get_weekly_training_status(self, start: date, end: date) -> Any:
        return await self._call(
            self._client.get_weekly_training_status,
            start.isoformat(),
            end.isoformat(),
        )

    async def get_training_status(self, day: date) -> Any:
        return await self._call(self._client.get_training_status, day.isoformat())

    async def get_race_predictions(self, start: date, end: date) -> Any:
        return await self._call(
            self._client.get_race_predictions,
            start.isoformat(),
            end.isoformat(),
            "daily",
        )

    async def get_max_metrics_latest(self, day: date) -> Any:
        return await self._call(self._client.get_max_metrics_latest, day.isoformat())

    async def get_max_metrics_range(self, start: date, end: date) -> Any:
        return await self._call(
            self._client.get_max_metrics_range,
            start.isoformat(),
            end.isoformat(),
        )

    async def get_heat_altitude_acclimation(self, start: date, end: date) -> Any:
        return await self._call(
            self._client.get_heat_altitude_acclimation_range,
            start.isoformat(),
            end.isoformat(),
        )

    async def get_running_economy(self, start: date, end: date) -> Any:
        return await self._call(
            self._client.get_running_economy_range,
            start.isoformat(),
            end.isoformat(),
        )

    async def get_stamina_curve(self, day: date) -> Any:
        return await self._call(self._client.get_stamina_curve, day.isoformat(), "running")

    async def get_power_curve(self, start: date, end: date, sport: str) -> Any:
        return await self._call(
            self._client.get_power_curve,
            start.isoformat(),
            end.isoformat(),
            sport,
        )

    async def get_lactate_threshold_latest(self) -> Any:
        return await self._call(self._client.get_lactate_threshold, latest=True)

    async def get_lactate_threshold_range(self, start: date, end: date) -> Any:
        return await self._call(
            self._client.get_lactate_threshold,
            latest=False,
            start_date=start.isoformat(),
            end_date=end.isoformat(),
        )

    async def get_respiration_stats(self, start: date, end: date) -> Any:
        return await self._call(
            self._client.get_daily_respiration_stats,
            start.isoformat(),
            end.isoformat(),
        )

    async def get_spo2_acclimation(self, day: date) -> Any:
        return await self._call(self._client.get_spo2_acclimation_data, day.isoformat())

    async def get_heart_rate_stats(self, start: date, end: date) -> Any:
        return await self._call(
            self._client.get_daily_heart_rate_stats,
            start.isoformat(),
            end.isoformat(),
        )

    async def get_weight_snapshot(self, start: date, end: date) -> Any:
        return await self._call(
            self._client.get_weight_snapshot,
            start.isoformat(),
            end.isoformat(),
        )

    async def get_devices(self) -> Any:
        return await self._call(self._client.get_devices)

    async def get_primary_training_device(self) -> Any:
        return await self._call(self._client.get_primary_training_device)

    async def get_device_last_used(self) -> Any:
        return await self._call(self._client.get_device_last_used)

    async def get_device_solar_gain(self, device_id: str, start: date, end: date) -> Any:
        return await self._call(
            self._client.get_device_solar_gain,
            device_id,
            start.isoformat(),
            end.isoformat(),
        )

    async def get_active_training_plans(self, day: date) -> Any:
        return await self._call(self._client.get_active_training_plans, day.isoformat())

    async def get_training_plans(self, *, limit: int = 20) -> Any:
        return await self._call(self._client.get_training_plans, limit)

    async def get_adaptive_training_plan(self, plan_id: int | str) -> Any:
        return await self._call(self._client.get_adaptive_training_plan_by_id, plan_id)

    async def get_training_plan(self, plan_id: int | str) -> Any:
        return await self._call(self._client.get_training_plan_by_id, plan_id)

    async def get_user_timezone(self) -> str | None:
        """IANA timezone from the Garmin profile, such as ``America/Denver``."""
        result = await self._call(self._client.get_user_timezone)
        return result if isinstance(result, str) and result.strip() else None

    def iter_dates(self, start: date, end: date) -> list[date]:
        days: list[date] = []
        current = start
        while current <= end:
            days.append(current)
            current += timedelta(days=1)
        return days
