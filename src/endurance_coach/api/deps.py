"""FastAPI dependency injection helpers."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from dataclasses import dataclass

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from endurance_coach.analytics.engine import DefaultMetricEngine
from endurance_coach.analytics.repositories import AnalyticsDataRepository
from endurance_coach.analytics.repositories import AnalyticsDataRepository
from endurance_coach.coach.service import DefaultCoachService, build_coach_service
from endurance_coach.collector.providers.garmin import GarminDataProvider, GarminTokenStore
from endurance_coach.collector.providers.samsung import SamsungHealthDataProvider, SamsungHealthImportService
from endurance_coach.collector.providers.strava import StravaDataProvider, StravaTokenStore
from endurance_coach.collector.repositories import (
    SqlAlchemyProviderConnectionRepository,
    SqlAlchemyRawPayloadRepository,
    SqlAlchemySyncJobRepository,
    SqlAlchemyUserRepository,
)
from endurance_coach.collector.sync_orchestrator import DefaultSyncOrchestrator
from endurance_coach.di.container import Container
from endurance_coach.processor.pipeline import DefaultProcessorPipeline
from endurance_coach.processor.repositories import SqlAlchemyNormalizedRecordRepository


@dataclass
class RequestServices:
    session: AsyncSession
    user_repo: SqlAlchemyUserRepository
    connection_repo: SqlAlchemyProviderConnectionRepository
    sync_orchestrator: DefaultSyncOrchestrator
    processor_pipeline: DefaultProcessorPipeline
    analytics_repo: AnalyticsDataRepository
    metric_engine: DefaultMetricEngine
    coach_service: DefaultCoachService
    token_store: GarminTokenStore
    strava_token_store: StravaTokenStore
    samsung_import_service: SamsungHealthImportService
    samsung_provider: SamsungHealthDataProvider


def get_container(request: Request) -> Container:
    return request.app.state.container


def _build_strava_token_store(container: Container) -> StravaTokenStore:
    return StravaTokenStore(
        container.settings.strava_token_path,
        client_id=container.settings.strava_client_id,
        client_secret=container.settings.strava_client_secret,
    )


async def get_request_services(request: Request) -> AsyncGenerator[RequestServices, None]:
    container: Container = get_container(request)
    async with container.session_factory() as session:
        token_store = GarminTokenStore(container.settings.garmin_token_path)
        strava_token_store = _build_strava_token_store(container)
        raw_repo = SqlAlchemyRawPayloadRepository(session)
        sync_job_repo = SqlAlchemySyncJobRepository(session)
        connection_repo = SqlAlchemyProviderConnectionRepository(session)

        garmin_provider = GarminDataProvider(
            token_store=token_store,
            raw_payload_repo=raw_repo,
            sync_job_repo=sync_job_repo,
            connection_repo=connection_repo,
            sync_days=container.settings.garmin_sync_days,
        )
        strava_provider = StravaDataProvider(
            token_store=strava_token_store,
            raw_payload_repo=raw_repo,
            sync_job_repo=sync_job_repo,
            connection_repo=connection_repo,
            sync_days=container.settings.strava_sync_days,
        )
        samsung_import_service = SamsungHealthImportService(
            raw_payload_repo=raw_repo,
            sync_job_repo=sync_job_repo,
            connection_repo=connection_repo,
        )
        samsung_provider = SamsungHealthDataProvider(
            import_service=samsung_import_service,
            sync_job_repo=sync_job_repo,
            connection_repo=connection_repo,
            import_dir=container.settings.samsung_health_import_dir,
            public_base_url=container.settings.public_base_url,
        )

        orchestrator = DefaultSyncOrchestrator(
            providers={
                garmin_provider.provider_type: garmin_provider,
                strava_provider.provider_type: strava_provider,
                samsung_provider.provider_type: samsung_provider,
            }
        )
        processor_pipeline = DefaultProcessorPipeline(
            raw_payload_repo=raw_repo,
            normalized_repo=SqlAlchemyNormalizedRecordRepository(session),
        )
        analytics_repo = AnalyticsDataRepository(session)
        metric_engine = DefaultMetricEngine(analytics_repo)
        coach_service = build_coach_service(
            analytics_repo,
            metric_engine,
            container.settings,
        )

        yield RequestServices(
            session=session,
            user_repo=SqlAlchemyUserRepository(session),
            connection_repo=connection_repo,
            sync_orchestrator=orchestrator,
            processor_pipeline=processor_pipeline,
            analytics_repo=analytics_repo,
            metric_engine=metric_engine,
            coach_service=coach_service,
            token_store=token_store,
            strava_token_store=strava_token_store,
            samsung_import_service=samsung_import_service,
            samsung_provider=samsung_provider,
        )
        await session.commit()
