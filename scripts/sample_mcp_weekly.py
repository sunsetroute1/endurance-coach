"""Sample MCP-style weekly aggregates over backfill window."""

from __future__ import annotations

import asyncio
import json

from endurance_coach.analytics.engine import DefaultMetricEngine
from endurance_coach.analytics.repositories import AnalyticsDataRepository
from endurance_coach.coach.service import build_coach_service
from endurance_coach.collector.repositories import SqlAlchemyUserRepository
from endurance_coach.di.container import create_container
from endurance_coach.mcp.service import CoachMCPService


async def main() -> None:
    container = create_container()
    async with container.session_factory() as session:
        user = await SqlAlchemyUserRepository(session).get_or_create_default(
            container.settings.default_user_email
        )
        repo = AnalyticsDataRepository(session)
        engine = DefaultMetricEngine(repo)
        service = CoachMCPService(
            repo,
            engine,
            build_coach_service(repo, engine, container.settings),
            app_timezone=container.settings.app_timezone,
        )
        result = await service.get_weekly_aggregates(user.id, weeks=52)
        sample = [
            week
            for week in result["aggregates"]
            if "2024-05-27" <= week["week_start"] <= "2024-06-16"
        ]
        payload = {
            "range_start": result["range_start"],
            "range_end": result["range_end"],
            "sample_weeks": [
                {
                    "week_start": week["week_start"],
                    "week_end": week["week_end"],
                    "all_activities": week["activities"]["count"],
                    "all_distance_mi": week["activities"]["distance_mi"],
                    "running_mi": week["running"]["distance_mi"],
                    "total_steps": week["health"]["total_steps"],
                    "avg_stress": week["health"]["avg_stress"],
                    "sleep_nights": week["sleep"]["nights"],
                    "avg_sleep_h": week["sleep"]["avg_hours"],
                    "hrv_avg": week["hrv"]["avg_hrv_ms"],
                }
                for week in sample
            ],
        }
        print(json.dumps(payload, indent=2))
    await container.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
