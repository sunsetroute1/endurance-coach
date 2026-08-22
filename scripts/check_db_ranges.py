import asyncio
from sqlalchemy import text
from endurance_coach.di.container import create_container


async def main() -> None:
    container = create_container()
    async with container.session_factory() as session:
        for table, col in [
            ("sleep_records", "sleep_date"),
            ("steps_records", "step_date"),
            ("activities", "started_at"),
            ("hrv_records", "recorded_at"),
            ("stress_records", "recorded_at"),
        ]:
            result = await session.execute(
                text(
                    f"SELECT provider, MIN({col}), MAX({col}), COUNT(*) "
                    f"FROM {table} GROUP BY provider ORDER BY provider"
                )
            )
            print(table, result.fetchall())
    await container.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
