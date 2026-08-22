"""Sample weekly rollups from a backfill window."""

from __future__ import annotations

import asyncio
import json
from datetime import date

from sqlalchemy import text

from endurance_coach.analytics.repositories import AnalyticsDataRepository
from endurance_coach.analytics.weekly import build_weekly_aggregate_row, group_by_week, iter_week_starts, week_end
from endurance_coach.collector.repositories import SqlAlchemyUserRepository
from endurance_coach.di.container import create_container


async def main() -> None:
    container = create_container()
    async with container.session_factory() as session:
        user = await SqlAlchemyUserRepository(session).get_or_create_default(
            container.settings.default_user_email
        )
        repo = AnalyticsDataRepository(session)

        as_of = date(2022, 3, 20)
        starts = iter_week_starts(as_of, weeks=3)

        range_start, range_end = starts[0], week_end(starts[-1])

        activities = await repo.get_activities_between(user.id, range_start, range_end)
        hrv = await repo.get_hrv_between(user.id, range_start, range_end)
        sleep = await repo.get_sleep_records_in_window(user.id, range_start, range_end)
        steps = await repo.get_steps_in_window(user.id, range_start, range_end)
        stress = await repo.get_stress_in_window(user.id, range_start, range_end)
        body_battery = await repo.get_body_battery_in_window(user.id, range_start, range_end)
        readiness = await repo.get_readiness_in_window(user.id, range_start, range_end)
        daily_loads = await repo.get_daily_activity_loads(user.id, range_end)

        activity_groups = group_by_week(activities, lambda record: record.started_at.date())
        sleep_groups = group_by_week(sleep, lambda record: record.sleep_date)
        step_groups = group_by_week(steps, lambda record: record.step_date)
        hrv_groups = group_by_week(hrv, lambda record: record.recorded_at.date())
        stress_groups = group_by_week(stress, lambda record: record.recorded_at.date())
        battery_groups = group_by_week(body_battery, lambda record: record.recorded_at.date())
        readiness_groups = group_by_week(readiness, lambda record: record.recorded_at.date())

        rows = []
        for week_start in starts:
            week_steps = step_groups.get(week_start, [])
            week_sleep = sleep_groups.get(week_start, [])
            week_hrv = hrv_groups.get(week_start, [])
            aggregate = build_weekly_aggregate_row(
                week_start,
                activities=activity_groups.get(week_start, []),
                hrv=week_hrv,
                sleep=week_sleep,
                steps=week_steps,
                stress=stress_groups.get(week_start, []),
                body_battery=battery_groups.get(week_start, []),
                readiness=readiness_groups.get(week_start, []),
                daily_loads=daily_loads,
            )
            rows.append(
                {
                    "week": f"{aggregate['week_start']} to {aggregate['week_end']}",
                    "running_mi": aggregate["running"]["distance_mi"],
                    "running_count": aggregate["running"]["count"],
                    "all_activities": aggregate["activities"]["count"],
                    "steps_days": len(week_steps),
                    "avg_steps": round(sum(item.total_steps for item in week_steps) / len(week_steps))
                    if week_steps
                    else None,
                    "sleep_nights": len(week_sleep),
                    "avg_sleep_h": round(
                        sum(item.total_sleep_seconds for item in week_sleep) / len(week_sleep) / 3600,
                        1,
                    )
                    if week_sleep
                    else None,
                    "hrv_readings": len(week_hrv),
                    "avg_hrv_ms": round(sum(item.hrv_ms for item in week_hrv) / len(week_hrv), 1)
                    if week_hrv
                    else None,
                    "avg_stress": aggregate["health"].get("avg_stress"),
                }
            )

        mix = await session.execute(
            text(
                """
                SELECT provider, COUNT(*)
                FROM activities
                WHERE started_at >= :start AND started_at <= :end
                GROUP BY provider
                ORDER BY provider
                """
            ),
            {"start": range_start, "end": range_end},
        )
        print(
            json.dumps(
                {"weeks": rows, "activity_providers": [list(row) for row in mix.fetchall()]},
                indent=2,
            )
        )

    await container.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
