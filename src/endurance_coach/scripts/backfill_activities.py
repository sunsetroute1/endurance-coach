"""CLI entrypoint for throttled Garmin activity backfill."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from endurance_coach.collector.providers.garmin.activity_backfill import GarminActivityBackfillService
from endurance_coach.collector.providers.garmin.client import GarminClient
from endurance_coach.collector.providers.garmin.token_store import GarminTokenStore
from endurance_coach.collector.repositories import SqlAlchemyUserRepository
from endurance_coach.config import get_settings
from endurance_coach.di.container import create_container
from endurance_coach.domain.enums import DataProviderType


def _configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)


async def _run(args: argparse.Namespace) -> int:
    settings = get_settings()
    container = create_container()
    token_store = GarminTokenStore(settings.garmin_token_path)

    try:
        async with container.session_factory() as session:
            user = await SqlAlchemyUserRepository(session).get_or_create_default(
                settings.default_user_email
            )
            if not await token_store.is_authenticated(user.id, DataProviderType.GARMIN):
                logging.error("Garmin tokens not available at %s", settings.garmin_token_path)
                return 1

            client = await GarminClient.from_token_path(settings.garmin_token_path)
            service = GarminActivityBackfillService(
                session,
                client,
                delay_seconds=args.delay,
                batch_size=args.batch_size,
            )
            result = await service.backfill(
                user.id,
                limit=args.limit,
                full_refresh=args.full,
                dry_run=args.dry_run,
            )

        logging.info(
            "Backfill complete: candidates=%s updated=%s skipped=%s failed=%s",
            result.total_candidates,
            result.updated,
            result.skipped,
            result.failed,
        )
        if result.errors:
            for error in result.errors[:10]:
                logging.error("%s", error)
            if len(result.errors) > 10:
                logging.error("... and %s more errors", len(result.errors) - 10)
        return 0 if result.failed == 0 else 2
    finally:
        await container.shutdown()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Backfill Garmin activity lap splits safely.")
    parser.add_argument("--limit", type=int, default=None, help="Max activities to process")
    parser.add_argument(
        "--delay",
        type=float,
        default=get_settings().garmin_backfill_delay_seconds,
        help="Seconds to wait between activities (default: 1.5)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=get_settings().garmin_backfill_batch_size,
        help="Commit after this many updates (default: 10)",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Re-fetch full activity detail in addition to lap splits",
    )
    parser.add_argument("--dry-run", action="store_true", help="Log actions without writing")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging")
    args = parser.parse_args(argv)

    _configure_logging(args.verbose)
    return asyncio.run(_run(args))


if __name__ == "__main__":
    sys.exit(main())
