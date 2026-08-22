import asyncio
from sqlalchemy import text
from endurance_coach.di.container import create_container


async def main() -> None:
    container = create_container()
    async with container.session_factory() as session:
        result = await session.execute(
            text(
                """
                SELECT activity_type, COUNT(*)
                FROM activities
                WHERE provider = 'samsung_health'
                GROUP BY activity_type
                ORDER BY COUNT(*) DESC
                LIMIT 10
                """
            )
        )
        print("samsung activity types:", result.fetchall())
    await container.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
