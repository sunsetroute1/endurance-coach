"""Dependency injection container."""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from endurance_coach.analytics.interfaces import MetricEngine
from endurance_coach.coach.interfaces import CoachService
from endurance_coach.collector.interfaces import DataProvider, SyncOrchestrator, TokenStore
from endurance_coach.config import Settings, get_settings
from endurance_coach.db.session import create_engine, create_session_factory
from endurance_coach.domain.enums import DataProviderType
from endurance_coach.mcp.tools import MCPToolRegistry


@dataclass
class Container:
    """Wires application services for API, MCP, and background jobs."""

    settings: Settings = field(default_factory=get_settings)
    engine: AsyncEngine = field(init=False)
    session_factory: async_sessionmaker[AsyncSession] = field(init=False)

    token_store: TokenStore | None = None
    providers: dict[DataProviderType, DataProvider] = field(default_factory=dict)
    sync_orchestrator: SyncOrchestrator | None = None
    metric_engine: MetricEngine | None = None
    coach_service: CoachService | None = None
    mcp_tools: MCPToolRegistry | None = None

    def __post_init__(self) -> None:
        self.engine = create_engine(self.settings)
        self.session_factory = create_session_factory(self.engine)

    def register_provider(self, provider: DataProvider) -> None:
        self.providers[provider.provider_type] = provider

    async def shutdown(self) -> None:
        await self.engine.dispose()


def create_container() -> Container:
    return Container()
