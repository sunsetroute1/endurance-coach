"""Backfill Garmin activities since a date directly (bypasses API timeout)."""
from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime

from endurance_coach.analytics.engine import DefaultMetricEngine
from endurance_coach.analytics.repositories import AnalyticsDataRepository
from endurance_coach.collector.providers.garmin import GarminDataProvider, GarminTokenStore
from endurance_coach.collector.repositories import (
    SqlAlchemyProviderConnectionRepository,
    SqlAlchemyRawPayloadRepository,
    SqlAlchemySyncJobRepository,
    SqlAlchemyUserRepository,
)
from endurance_coach.collector.sync_orchestrator import DefaultSyncOrchestrator
from endurance_coach.config import get_settings
from endurance_coach.di.container import create_container
from endurance_coach.domain.enums import DataProviderType, ResourceType
from endurance_coach.domain.models import SyncRequest
from endurance_coach.processor.pipeline import DefaultProcessorPipeline
from endurance_coach.processor.repositories import SqlAlchemyNormalizedRecordRepository


async def main() -> None:
    since = datetime(2021, 1, 1, tzinfo=UTC)
    if len(sys.argv) > 1:
        since = datetime.fromisoformat(sys.argv[1]).replace(tzinfo=UTC)

    container = create_container()
    settings = get_settings()
    try:
        async with container.session_factory() as session:
            token_store = GarminTokenStore(settings.garmin_token_path)
            raw_repo = SqlAlchemyRawPayloadRepository(session)
            sync_job_repo = SqlAlchemySyncJobRepository(session)
            connection_repo = SqlAlchemyProviderConnectionRepository(session)
            garmin_provider = GarminDataProvider(
                token_store=token_store,
                raw_payload_repo=raw_repo,
                sync_job_repo=sync_job_repo,
                connection_repo=connection_repo,
                sync_days=settings.garmin_sync_days,
                timezone=settings.app_timezone,
            )
            orchestrator = DefaultSyncOrchestrator(
                providers={garmin_provider.provider_type: garmin_provider}
            )
            processor = DefaultProcessorPipeline(
                raw_payload_repo=raw_repo,
                normalized_repo=SqlAlchemyNormalizedRecordRepository(session),
            )
            metric_engine = DefaultMetricEngine(AnalyticsDataRepository(session))
            user_repo = SqlAlchemyUserRepository(session)
            user = await user_repo.get_or_create_default(settings.default_user_email)

            print(f"Backfilling Garmin activities since {since.date()}...")
            result = await orchestrator.run_sync(
                SyncRequest(
                    user_id=user.id,
                    provider=DataProviderType.GARMIN,
                    resource_types=(ResourceType.ACTIVITIES,),
                    since=since,
                    full_sync=False,
                )
            )
            print(f"Sync status={result.status} synced={result.resources_synced}")
            if result.errors:
                print(f"errors={list(result.errors)}")

            processed = await processor.process_pending(user.id, ResourceType.ACTIVITIES, limit=1000)
            print(f"Processed activities={processed}")

            snapshots = await metric_engine.compute_all(user.id)
            print(f"Analytics snapshots={len(snapshots)}")
            await session.commit()
    finally:
        await container.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
