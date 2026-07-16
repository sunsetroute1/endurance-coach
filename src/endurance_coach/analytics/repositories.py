"""Read normalized data and persist computed metric snapshots."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from endurance_coach.db.models import (
    ActivityRecord,
    BodyBatteryRecord,
    ComputedMetricRecord,
    HRVRecord,
    RawPayloadRecord,
    SleepRecord,
    StepsRecord,
    StressRecord,
    TrainingReadinessRecord,
)
from endurance_coach.domain.enums import MetricFamily
from endurance_coach.domain.models import MetricSnapshot, MetricValue


class AnalyticsDataRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_daily_activity_loads(
        self,
        user_id: UUID,
        end_date: date,
        *,
        history_days: int = 120,
    ) -> dict[date, float]:
        from endurance_coach.analytics.math import estimate_activity_load

        start = datetime.combine(
            end_date - timedelta(days=history_days),
            datetime.min.time(),
            tzinfo=UTC,
        )
        end = datetime.combine(end_date, datetime.max.time(), tzinfo=UTC)

        result = await self._session.execute(
            select(ActivityRecord).where(
                ActivityRecord.user_id == user_id,
                ActivityRecord.started_at >= start,
                ActivityRecord.started_at <= end,
            )
        )
        activities = result.scalars().all()

        daily: dict[date, float] = {}
        for activity in activities:
            day = activity.started_at.date()
            load = estimate_activity_load(
                training_load=activity.training_load,
                duration_seconds=activity.duration_seconds,
                avg_heart_rate=activity.avg_heart_rate,
            )
            daily[day] = daily.get(day, 0.0) + load
        return daily

    async def get_sleep_by_date(
        self,
        user_id: UUID,
        end_date: date,
        *,
        window_days: int = 14,
    ) -> dict[date, int]:
        start = end_date - timedelta(days=window_days)
        result = await self._session.execute(
            select(SleepRecord).where(
                SleepRecord.user_id == user_id,
                SleepRecord.sleep_date >= start,
                SleepRecord.sleep_date <= end_date,
            )
        )
        return {row.sleep_date: row.total_sleep_seconds for row in result.scalars().all()}

    async def get_hrv_for_date(
        self,
        user_id: UUID,
        target_date: date,
        *,
        fetched_before: datetime | None = None,
    ) -> HRVRecord | None:
        start = datetime.combine(target_date, datetime.min.time(), tzinfo=UTC)
        end = datetime.combine(target_date, datetime.max.time(), tzinfo=UTC)
        query = (
            select(HRVRecord)
            .where(
                HRVRecord.user_id == user_id,
                HRVRecord.recorded_at >= start,
                HRVRecord.recorded_at <= end,
            )
            .order_by(HRVRecord.recorded_at.desc())
            .limit(1)
        )
        if fetched_before is not None:
            query = query.join(
                RawPayloadRecord,
                HRVRecord.source_payload_id == RawPayloadRecord.id,
            ).where(RawPayloadRecord.fetched_at <= fetched_before)
        result = await self._session.execute(query)
        return result.scalar_one_or_none()

    async def get_latest_hrv(
        self,
        user_id: UUID,
        as_of: date,
    ) -> HRVRecord | None:
        start = datetime.combine(as_of - timedelta(days=3), datetime.min.time(), tzinfo=UTC)
        end = datetime.combine(as_of, datetime.max.time(), tzinfo=UTC)
        result = await self._session.execute(
            select(HRVRecord)
            .where(
                HRVRecord.user_id == user_id,
                HRVRecord.recorded_at >= start,
                HRVRecord.recorded_at <= end,
            )
            .order_by(HRVRecord.recorded_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_latest_readiness(
        self,
        user_id: UUID,
        as_of: date,
    ) -> TrainingReadinessRecord | None:
        start = datetime.combine(as_of - timedelta(days=3), datetime.min.time(), tzinfo=UTC)
        end = datetime.combine(as_of, datetime.max.time(), tzinfo=UTC)
        result = await self._session.execute(
            select(TrainingReadinessRecord)
            .where(
                TrainingReadinessRecord.user_id == user_id,
                TrainingReadinessRecord.recorded_at >= start,
                TrainingReadinessRecord.recorded_at <= end,
            )
            .order_by(TrainingReadinessRecord.recorded_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_latest_sleep_score(
        self,
        user_id: UUID,
        as_of: date,
    ) -> int | None:
        result = await self._session.execute(
            select(SleepRecord)
            .where(
                SleepRecord.user_id == user_id,
                SleepRecord.sleep_date <= as_of,
            )
            .order_by(SleepRecord.sleep_date.desc())
            .limit(1)
        )
        row = result.scalar_one_or_none()
        return row.sleep_score if row else None

    async def get_activities_since(
        self,
        user_id: UUID,
        since: date,
        *,
        limit: int = 100,
    ) -> list[ActivityRecord]:
        start = datetime.combine(since, datetime.min.time(), tzinfo=UTC)
        result = await self._session.execute(
            select(ActivityRecord)
            .where(
                ActivityRecord.user_id == user_id,
                ActivityRecord.started_at >= start,
            )
            .order_by(ActivityRecord.started_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_sleep_for_date(
        self,
        user_id: UUID,
        sleep_date: date,
        *,
        fetched_before: datetime | None = None,
    ) -> SleepRecord | None:
        query = select(SleepRecord).where(
            SleepRecord.user_id == user_id,
            SleepRecord.sleep_date == sleep_date,
        )
        if fetched_before is not None:
            query = query.join(
                RawPayloadRecord,
                SleepRecord.source_payload_id == RawPayloadRecord.id,
            ).where(RawPayloadRecord.fetched_at <= fetched_before)
        result = await self._session.execute(query)
        return result.scalar_one_or_none()

    async def get_hrv_in_window(
        self,
        user_id: UUID,
        end_date: date,
        *,
        window_days: int = 14,
    ) -> list[HRVRecord]:
        start = datetime.combine(
            end_date - timedelta(days=window_days),
            datetime.min.time(),
            tzinfo=UTC,
        )
        end = datetime.combine(end_date, datetime.max.time(), tzinfo=UTC)
        result = await self._session.execute(
            select(HRVRecord)
            .where(
                HRVRecord.user_id == user_id,
                HRVRecord.recorded_at >= start,
                HRVRecord.recorded_at <= end,
            )
            .order_by(HRVRecord.recorded_at.asc())
        )
        return list(result.scalars().all())

    async def get_recent_activities(
        self,
        user_id: UUID,
        limit: int = 10,
    ) -> list[ActivityRecord]:
        result = await self._session.execute(
            select(ActivityRecord)
            .where(ActivityRecord.user_id == user_id)
            .order_by(ActivityRecord.started_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_most_recent_activity(self, user_id: UUID) -> ActivityRecord | None:
        activities = await self.get_recent_activities(user_id, limit=1)
        return activities[0] if activities else None

    async def get_activity_by_provider_record_id(
        self,
        user_id: UUID,
        provider_record_id: str,
    ) -> ActivityRecord | None:
        result = await self._session.execute(
            select(ActivityRecord).where(
                ActivityRecord.user_id == user_id,
                ActivityRecord.provider_record_id == provider_record_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_activity_for_date(
        self,
        user_id: UUID,
        target_date: date,
    ) -> ActivityRecord | None:
        start = datetime.combine(target_date, datetime.min.time(), tzinfo=UTC)
        end = datetime.combine(target_date, datetime.max.time(), tzinfo=UTC)
        result = await self._session.execute(
            select(ActivityRecord)
            .where(
                ActivityRecord.user_id == user_id,
                ActivityRecord.started_at >= start,
                ActivityRecord.started_at <= end,
            )
            .order_by(ActivityRecord.started_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_raw_payload(self, payload_id: UUID) -> dict | None:
        result = await self._session.execute(
            select(RawPayloadRecord).where(RawPayloadRecord.id == payload_id)
        )
        row = result.scalar_one_or_none()
        return row.payload if row else None

    async def get_activity_payload(self, payload_id: UUID) -> dict | None:
        return await self.get_raw_payload(payload_id)

    async def get_latest_sleep_record(
        self,
        user_id: UUID,
        as_of: date,
    ) -> SleepRecord | None:
        result = await self._session.execute(
            select(SleepRecord)
            .where(
                SleepRecord.user_id == user_id,
                SleepRecord.sleep_date <= as_of,
            )
            .order_by(SleepRecord.sleep_date.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_latest_meaningful_sleep(
        self,
        user_id: UUID,
        as_of: date,
    ) -> SleepRecord | None:
        result = await self._session.execute(
            select(SleepRecord)
            .where(
                SleepRecord.user_id == user_id,
                SleepRecord.sleep_date <= as_of,
                SleepRecord.total_sleep_seconds > 0,
            )
            .order_by(SleepRecord.sleep_date.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_latest_body_battery(
        self,
        user_id: UUID,
        as_of: date,
    ) -> BodyBatteryRecord | None:
        start = datetime.combine(as_of - timedelta(days=3), datetime.min.time(), tzinfo=UTC)
        end = datetime.combine(as_of, datetime.max.time(), tzinfo=UTC)
        result = await self._session.execute(
            select(BodyBatteryRecord)
            .where(
                BodyBatteryRecord.user_id == user_id,
                BodyBatteryRecord.recorded_at >= start,
                BodyBatteryRecord.recorded_at <= end,
            )
            .order_by(BodyBatteryRecord.recorded_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_latest_stress(
        self,
        user_id: UUID,
        as_of: date,
    ) -> StressRecord | None:
        start = datetime.combine(as_of - timedelta(days=3), datetime.min.time(), tzinfo=UTC)
        end = datetime.combine(as_of, datetime.max.time(), tzinfo=UTC)
        result = await self._session.execute(
            select(StressRecord)
            .where(
                StressRecord.user_id == user_id,
                StressRecord.recorded_at >= start,
                StressRecord.recorded_at <= end,
            )
            .order_by(StressRecord.recorded_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_steps_for_date(
        self,
        user_id: UUID,
        step_date: date,
    ) -> StepsRecord | None:
        result = await self._session.execute(
            select(StepsRecord)
            .where(
                StepsRecord.user_id == user_id,
                StepsRecord.step_date == step_date,
            )
            .order_by(StepsRecord.step_date.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def save_snapshot(self, snapshot: MetricSnapshot) -> ComputedMetricRecord:
        metrics_dict = {
            metric.key: {"value": metric.value, "unit": metric.unit}
            for metric in snapshot.metrics
        }
        row = ComputedMetricRecord(
            user_id=snapshot.user_id,
            family=snapshot.family,
            as_of=snapshot.as_of,
            metrics=metrics_dict,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def get_latest_snapshot(
        self,
        user_id: UUID,
        family: MetricFamily,
    ) -> MetricSnapshot | None:
        result = await self._session.execute(
            select(ComputedMetricRecord)
            .where(
                ComputedMetricRecord.user_id == user_id,
                ComputedMetricRecord.family == family,
            )
            .order_by(ComputedMetricRecord.as_of.desc())
            .limit(1)
        )
        row = result.scalar_one_or_none()
        if row is None:
            return None

        metrics = tuple(
            MetricValue(
                key=key,
                value=float(data["value"]),
                unit=str(data.get("unit", "")),
                computed_at=row.as_of,
            )
            for key, data in row.metrics.items()
        )
        return MetricSnapshot(
            user_id=user_id,
            family=MetricFamily(row.family),
            as_of=row.as_of,
            metrics=metrics,
        )
