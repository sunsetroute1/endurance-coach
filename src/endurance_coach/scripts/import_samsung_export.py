"""Import Samsung Health personal data export into PostgreSQL."""

from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import date
from pathlib import Path

from sqlalchemy import select

from endurance_coach.collector.providers.samsung.export_parser import parse_export_records
from endurance_coach.collector.providers.samsung.import_service import SamsungHealthImportService
from endurance_coach.collector.repositories import (
    SqlAlchemyProviderConnectionRepository,
    SqlAlchemyRawPayloadRepository,
    SqlAlchemySyncJobRepository,
    SqlAlchemyUserRepository,
)
from endurance_coach.config import get_settings
from endurance_coach.di.container import create_container
from endurance_coach.domain.enums import DataProviderType, ResourceType, SyncStatus
from endurance_coach.domain.models import SyncRequest
from endurance_coach.processor.pipeline import DefaultProcessorPipeline
from endurance_coach.processor.repositories import SqlAlchemyNormalizedRecordRepository
from endurance_coach.db.models import SleepRecord, StepsRecord, StressRecord

logger = logging.getLogger(__name__)

BATCH_SIZE = 250


async def _existing_dates(session, user_id, start: date, end: date) -> tuple[set[date], set[date], set[date]]:
    sleep = await session.execute(
        select(SleepRecord.sleep_date).where(
            SleepRecord.user_id == user_id,
            SleepRecord.provider == DataProviderType.SAMSUNG_HEALTH.value,
            SleepRecord.sleep_date >= start,
            SleepRecord.sleep_date <= end,
        )
    )
    steps = await session.execute(
        select(StepsRecord.step_date).where(
            StepsRecord.user_id == user_id,
            StepsRecord.provider == DataProviderType.SAMSUNG_HEALTH.value,
            StepsRecord.step_date >= start,
            StepsRecord.step_date <= end,
        )
    )
    stress = await session.execute(
        select(StressRecord.recorded_at).where(
            StressRecord.user_id == user_id,
            StressRecord.provider == DataProviderType.SAMSUNG_HEALTH.value,
            StressRecord.recorded_at >= start,
            StressRecord.recorded_at <= end,
        )
    )
    return (
        set(sleep.scalars().all()),
        set(steps.scalars().all()),
        {value.date() for value in stress.scalars().all()},
    )


def _filter_existing(
    records,
    *,
    sleep_dates: set[date],
    step_dates: set[date],
    stress_dates: set[date],
) -> list:
    filtered = []
    for record in records:
        if record.resource_type == ResourceType.ACTIVITIES:
            filtered.append(record)
            continue
        if record.resource_type == ResourceType.HRV:
            filtered.append(record)
            continue
        day = date.fromisoformat(record.provider_record_id[:10])
        if record.resource_type == ResourceType.SLEEP and day in sleep_dates:
            continue
        if record.resource_type == ResourceType.STEPS and day in step_dates:
            continue
        if record.resource_type == ResourceType.STRESS and day in stress_dates:
            continue
        filtered.append(record)
    return filtered


async def run_import(
    export_dir: Path,
    *,
    start_date: date,
    end_date: date,
    skip_existing: bool,
    process: bool,
) -> None:
    settings = get_settings()
    container = create_container()
    try:
        records = parse_export_records(export_dir, start_date=start_date, end_date=end_date)
        logger.info("Parsed %s Samsung export records (%s to %s)", len(records), start_date, end_date)

        async with container.session_factory() as session:
            user = await SqlAlchemyUserRepository(session).get_or_create_default(
                settings.default_user_email
            )
            if skip_existing:
                sleep_dates, step_dates, stress_dates = await _existing_dates(
                    session,
                    user.id,
                    start_date,
                    end_date,
                )
                before = len(records)
                records = _filter_existing(
                    records,
                    sleep_dates=sleep_dates,
                    step_dates=step_dates,
                    stress_dates=stress_dates,
                )
                logger.info(
                    "Skipped %s records that already exist for sleep/steps/stress dates",
                    before - len(records),
                )

            raw_repo = SqlAlchemyRawPayloadRepository(session)
            sync_repo = SqlAlchemySyncJobRepository(session)
            connection_repo = SqlAlchemyProviderConnectionRepository(session)
            import_service = SamsungHealthImportService(raw_repo, sync_repo, connection_repo)
            pipeline = DefaultProcessorPipeline(
                raw_repo,
                SqlAlchemyNormalizedRecordRepository(session),
            )

            resource_types = tuple({record.resource_type for record in records})
            request = SyncRequest(
                user_id=user.id,
                provider=DataProviderType.SAMSUNG_HEALTH,
                resource_types=resource_types,
            )

            imported = 0
            for offset in range(0, len(records), BATCH_SIZE):
                batch = records[offset : offset + BATCH_SIZE]
                result = await import_service.import_records(
                    request,
                    batch,
                    device_id="samsung-export",
                )
                imported += sum(result.resources_synced.values())
                if result.status == SyncStatus.FAILED and result.errors:
                    logger.warning("Batch %s errors: %s", offset // BATCH_SIZE, result.errors[:3])

            if process:
                processed = await pipeline.process_all_pending(user.id, limit_per_type=10000)
                logger.info("Processed pending payloads: %s", processed)

            await session.commit()
            logger.info("Import complete: %s raw records saved", imported)
    finally:
        await container.shutdown()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--export-dir",
        type=Path,
        default=Path("data/samsung_export"),
        help="Directory containing extracted Samsung Health export",
    )
    parser.add_argument("--start-date", type=date.fromisoformat, default=date(2021, 1, 1))
    parser.add_argument("--end-date", type=date.fromisoformat, default=date(2025, 11, 30))
    parser.add_argument(
        "--skip-existing",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Skip Samsung sleep/steps/stress dates already imported from Samsung",
    )
    parser.add_argument(
        "--process",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Normalize imported raw payloads after import",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    asyncio.run(
        run_import(
            args.export_dir,
            start_date=args.start_date,
            end_date=args.end_date,
            skip_existing=args.skip_existing,
            process=args.process,
        )
    )


if __name__ == "__main__":
    main()
