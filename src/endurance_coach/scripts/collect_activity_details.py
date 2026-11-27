"""Collect Garmin activity charts for a bounded set of outdoor runs."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from endurance_coach.collector.providers.garmin.activity_detail_sync import (
    GarminActivityDetailCollector,
    SqlActivityDetailStore,
)
from endurance_coach.collector.providers.garmin.client import GarminClient
from endurance_coach.collector.providers.garmin.token_store import GarminTokenStore
from endurance_coach.collector.repositories import SqlAlchemyUserRepository
from endurance_coach.config import get_settings
from endurance_coach.di.container import create_container
from endurance_coach.domain.enums import DataProviderType


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine.Engine").setLevel(logging.WARNING)


async def _run(args: argparse.Namespace) -> int:
    settings = get_settings()
    container = create_container()
    container.engine.echo = False
    token_store = GarminTokenStore(settings.garmin_token_path)
    try:
        async with container.session_factory() as session:
            user = await SqlAlchemyUserRepository(session).get_or_create_default(
                settings.default_user_email
            )
            if not await token_store.is_authenticated(user.id, DataProviderType.GARMIN):
                logging.error("Garmin tokens are not available")
                return 1
            logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
            logging.getLogger("sqlalchemy.engine.Engine").setLevel(logging.WARNING)
            store = SqlActivityDetailStore(session)
            ids = [item.strip() for item in args.activity_ids.split(",") if item.strip()] or None
            jobs = await store.outdoor_jobs(user.id, limit=args.limit, provider_activity_ids=ids)
            client = await GarminClient.from_token_path(settings.garmin_token_path)
            collector = GarminActivityDetailCollector(
                client,
                store,
                maxchart=settings.garmin_activity_detail_maxchart,
                pause_seconds=args.pause,
            )

            async def _commit() -> None:
                await session.commit()

            result = await collector.collect(jobs)
            await _commit()
        logging.info(
            "requested=%s collected=%s skipped=%s unsupported=%s failed=%s downloaded=%s",
            result.requested,
            result.collected,
            result.skipped,
            result.unsupported,
            result.failed,
            result.downloaded,
        )
        if result.stopped_reason:
            logging.error("%s", result.stopped_reason)
        return 0 if result.failed == 0 else 2
    finally:
        await container.shutdown()


def main(argv: list[str] | None = None) -> int:
    settings = get_settings()
    parser = argparse.ArgumentParser(description="Collect a bounded set of Garmin activity charts.")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--activity-ids", default="", help="Comma-separated Garmin activity ids.")
    parser.add_argument(
        "--pause",
        type=float,
        default=settings.garmin_activity_detail_pause_seconds,
    )
    return asyncio.run(_run(parser.parse_args(argv)))


if __name__ == "__main__":
    _configure_logging()
    sys.exit(main())
