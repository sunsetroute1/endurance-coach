"""Build MCP services from the shared DI container."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from uuid import UUID

from endurance_coach.analytics.engine import DefaultMetricEngine
from endurance_coach.analytics.repositories import AnalyticsDataRepository
from endurance_coach.coach.service import build_coach_service
from endurance_coach.collector.providers.garmin import GarminTokenStore
from endurance_coach.collector.providers.garmin.client import GarminClient
from endurance_coach.collector.repositories import SqlAlchemyUserRepository
from endurance_coach.di.container import Container
from endurance_coach.domain.enums import DataProviderType
from endurance_coach.mcp.service import CoachMCPService


@dataclass
class MCPRequestScope:
    service: CoachMCPService
    user_id: UUID


@asynccontextmanager
async def mcp_request_scope(container: Container) -> AsyncGenerator[MCPRequestScope, None]:
    async with container.session_factory() as session:
        user = await SqlAlchemyUserRepository(session).get_or_create_default(
            container.settings.default_user_email
        )
        analytics_repo = AnalyticsDataRepository(session)
        metric_engine = DefaultMetricEngine(analytics_repo)
        coach_service = build_coach_service(
            analytics_repo,
            metric_engine,
            container.settings,
        )
        token_store = GarminTokenStore(container.settings.garmin_token_path)
        lap_fetcher = None
        if await token_store.is_authenticated(user.id, DataProviderType.GARMIN):
            token_path = token_store.token_path

            async def fetch_laps(activity_id: str) -> list[dict]:
                client = await GarminClient.from_token_path(token_path)
                return await client.get_activity_laps(activity_id)

            lap_fetcher = fetch_laps

        service = CoachMCPService(
            analytics_repo,
            metric_engine,
            coach_service,
            app_timezone=container.settings.app_timezone,
            lap_fetcher=lap_fetcher,
        )
        yield MCPRequestScope(service=service, user_id=user.id)
        await session.commit()
