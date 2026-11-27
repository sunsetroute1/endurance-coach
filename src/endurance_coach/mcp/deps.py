"""Build MCP services from the shared DI container."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from uuid import UUID

from mcp.server.fastmcp.exceptions import ToolError

from endurance_coach.analytics.engine import DefaultMetricEngine
from endurance_coach.analytics.repositories import AnalyticsDataRepository
from endurance_coach.coach.service import build_coach_service
from endurance_coach.collector.providers.garmin import GarminTokenStore
from endurance_coach.collector.providers.garmin.client import GarminClient
from endurance_coach.collector.repositories import (
    SqlAlchemyProviderConnectionRepository,
    SqlAlchemyUserRepository,
)
from endurance_coach.di.container import Container
from endurance_coach.domain.enums import DataProviderType
from endurance_coach.mcp.logging_utils import log_event, logger
from endurance_coach.mcp.service import CoachMCPService
from endurance_coach.timezone_util import usable_timezone


@dataclass
class MCPRequestScope:
    service: CoachMCPService
    user_id: UUID


@asynccontextmanager
async def mcp_request_scope(container: Container) -> AsyncGenerator[MCPRequestScope, None]:
    """Open a DB-backed request scope.

    Failures here become tool-level errors. They must never unregister tools or
    break initialize / tools/list (those paths do not enter this scope).
    """
    try:
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
            connection_repo = SqlAlchemyProviderConnectionRepository(session)
            connection = await connection_repo.get_connection(user.id, DataProviderType.GARMIN)
            stored_timezone = None
            if connection is not None and connection.metadata_json:
                stored_timezone = connection.metadata_json.get("timezone")
            app_timezone = usable_timezone(stored_timezone) or container.settings.app_timezone
            lap_fetcher = None
            try:
                if await token_store.is_authenticated(user.id, DataProviderType.GARMIN):
                    token_path = token_store.token_path

                    async def fetch_laps(activity_id: str) -> list[dict]:
                        client = await GarminClient.from_token_path(token_path)
                        return await client.get_activity_laps(activity_id)

                    lap_fetcher = fetch_laps
            except Exception as exc:
                # Garmin token/client issues must not block DB-backed tools.
                logger.warning("garmin_lap_fetcher_unavailable error=%s", exc)
                lap_fetcher = None

            service = CoachMCPService(
                analytics_repo,
                metric_engine,
                coach_service,
                app_timezone=app_timezone,
                lap_fetcher=lap_fetcher,
            )
            log_event("db_session_open", user_id=str(user.id))
            yield MCPRequestScope(service=service, user_id=user.id)
            await session.commit()
            log_event("db_session_commit", user_id=str(user.id))
    except ToolError:
        raise
    except Exception as exc:
        logger.exception("db_session_failed error=%s", exc)
        raise ToolError(
            f"Database unavailable: {exc}. The MCP tool registry is still active; "
            "retry after Postgres recovers."
        ) from exc
