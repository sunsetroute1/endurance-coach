"""Drain unprocessed Garmin raw payloads."""

from __future__ import annotations

import asyncio

from sqlalchemy import text

from endurance_coach.collector.repositories import SqlAlchemyRawPayloadRepository
from endurance_coach.config import get_settings
from endurance_coach.db.session import create_engine, create_session_factory
from endurance_coach.processor.pipeline import DefaultProcessorPipeline
from endurance_coach.processor.repositories import SqlAlchemyNormalizedRecordRepository


async def main() -> None:
    settings = get_settings()
    engine = create_engine(settings)
    session_factory = create_session_factory(engine)
    totals: dict[str, int] = {}

    async with session_factory() as session:
        user_id = (await session.execute(text("SELECT id FROM users LIMIT 1"))).scalar_one()

    for _ in range(20):
        async with session_factory() as session:
            pipeline = DefaultProcessorPipeline(
                SqlAlchemyRawPayloadRepository(session),
                SqlAlchemyNormalizedRecordRepository(session),
            )
            results = await pipeline.process_all_pending(user_id, limit_per_type=500)
            await session.commit()
            if not results:
                break
            for key, value in results.items():
                totals[key.value] = totals.get(key.value, 0) + value

    async with engine.connect() as conn:
        body_battery = (await conn.execute(text("SELECT COUNT(*) FROM body_battery_records"))).scalar_one()
        unprocessed = (
            await conn.execute(text("SELECT COUNT(*) FROM raw_payloads WHERE processed_at IS NULL"))
        ).scalar_one()

    await engine.dispose()
    print(f"processed_batches={totals}")
    print(f"body_battery_records={body_battery}")
    print(f"unprocessed_remaining={unprocessed}")


if __name__ == "__main__":
    asyncio.run(main())
