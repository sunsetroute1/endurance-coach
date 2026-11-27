"""Read normalized data and persist computed metric snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import Float, cast, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from endurance_coach.analytics.activity_selection import select_primary_activity
from endurance_coach.db.models import (
    ActivityRecord,
    BodyBatteryRecord,
    ComputedMetricRecord,
    HRVRecord,
    RawPayloadRecord,
    SleepRecord,
    StepsRecord,
    StressRecord,
    SyncJob,
    TrainingReadinessRecord,
)
from endurance_coach.domain.enums import DataProviderType, MetricFamily
from endurance_coach.domain.models import MetricSnapshot, MetricValue
from endurance_coach.timezone_util import as_local, local_range_bounds


@dataclass(frozen=True)
class StoredRawPayload:
    payload: dict
    fetched_at: datetime | None


class AnalyticsDataRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @property
    def session(self) -> AsyncSession:
        return self._session

    async def get_daily_activity_loads(
        self,
        user_id: UUID,
        end_date: date,
        *,
        history_days: int = 120,
        timezone: str = "America/Denver",
    ) -> dict[date, float]:
        from endurance_coach.analytics.math import estimate_activity_load

        start, end = local_range_bounds(
            end_date - timedelta(days=history_days),
            end_date,
            timezone,
        )

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
            day = as_local(activity.started_at, timezone).date()
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
            .order_by(HRVRecord.recorded_at.desc(), HRVRecord.created_at.desc())
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
            .order_by(
                TrainingReadinessRecord.recorded_at.desc(),
                TrainingReadinessRecord.created_at.desc(),
            )
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_latest_sleep_score(
        self,
        user_id: UUID,
        as_of: date,
    ) -> int | None:
        row = await self.get_latest_meaningful_sleep(user_id, as_of)
        return row.sleep_score if row else None

    async def get_activities_since(
        self,
        user_id: UUID,
        since: date,
        *,
        limit: int = 100,
    ) -> list[ActivityRecord]:
        activities, _total = await self.list_activities(
            user_id,
            since=since,
            start=0,
            limit=limit,
        )
        return activities

    async def list_activities(
        self,
        user_id: UUID,
        *,
        since: date | None = None,
        activity_type: str | None = None,
        start: int = 0,
        limit: int = 50,
        max_limit: int = 100,
        timezone: str = "America/Denver",
    ) -> tuple[list[ActivityRecord], int]:
        query = select(ActivityRecord).where(ActivityRecord.user_id == user_id)
        if since is not None:
            since_dt, _end = local_range_bounds(since, since, timezone)
            query = query.where(ActivityRecord.started_at >= since_dt)
        if activity_type:
            needle = activity_type.strip().lower()
            if needle:
                query = query.where(func.lower(ActivityRecord.activity_type).contains(needle))

        count_result = await self._session.execute(
            select(func.count()).select_from(query.subquery())
        )
        total = int(count_result.scalar_one())

        offset = max(start, 0)
        cap = max(max_limit, 1)
        page_size = max(min(limit, cap), 1)
        result = await self._session.execute(
            query.order_by(ActivityRecord.started_at.desc())
            .offset(offset)
            .limit(page_size)
        )
        return list(result.scalars().all()), total

    async def get_activities_between(
        self,
        user_id: UUID,
        start_date: date,
        end_date: date,
        *,
        timezone: str = "America/Denver",
    ) -> list[ActivityRecord]:
        start_dt, end_dt = local_range_bounds(start_date, end_date, timezone)
        result = await self._session.execute(
            select(ActivityRecord)
            .where(
                ActivityRecord.user_id == user_id,
                ActivityRecord.started_at >= start_dt,
                ActivityRecord.started_at <= end_dt,
            )
            .order_by(ActivityRecord.started_at.asc())
        )
        return list(result.scalars().all())

    async def list_activity_trend_points(
        self,
        user_id: UUID,
        start_date: date,
        end_date: date,
        *,
        timezone: str = "America/Denver",
        provider: str | None = None,
    ) -> list[dict[str, object]]:
        """Activity fields used for trends, including grade-adjusted speed and stamina."""
        tz = ZoneInfo(timezone)
        utc_start = datetime.combine(start_date, datetime.min.time(), tzinfo=tz).astimezone(UTC)
        utc_end = datetime.combine(end_date, datetime.max.time(), tzinfo=tz).astimezone(UTC)
        gap_speed = func.coalesce(
            cast(RawPayloadRecord.payload["summary"]["avgGradeAdjustedSpeed"].astext, Float),
            cast(
                RawPayloadRecord.payload["detail"]["summaryDTO"]["avgGradeAdjustedSpeed"].astext,
                Float,
            ),
        )
        stamina_begin = func.coalesce(
            cast(RawPayloadRecord.payload["summary"]["beginPotentialStamina"].astext, Float),
            cast(
                RawPayloadRecord.payload["detail"]["summaryDTO"]["beginPotentialStamina"].astext,
                Float,
            ),
        )
        stamina_end = func.coalesce(
            cast(RawPayloadRecord.payload["summary"]["endPotentialStamina"].astext, Float),
            cast(
                RawPayloadRecord.payload["detail"]["summaryDTO"]["endPotentialStamina"].astext,
                Float,
            ),
        )
        filters = [
            ActivityRecord.user_id == user_id,
            ActivityRecord.started_at >= utc_start,
            ActivityRecord.started_at <= utc_end,
        ]
        if provider is not None:
            filters.append(ActivityRecord.provider == provider)
        result = await self._session.execute(
            select(
                ActivityRecord.started_at,
                ActivityRecord.activity_type,
                ActivityRecord.duration_seconds,
                ActivityRecord.distance_meters,
                ActivityRecord.avg_heart_rate,
                ActivityRecord.avg_pace_sec_per_km,
                ActivityRecord.elevation_gain_meters,
                ActivityRecord.training_load,
                gap_speed.label("grade_adjusted_speed_mps"),
                stamina_begin.label("stamina_begin"),
                stamina_end.label("stamina_end"),
            )
            .join(RawPayloadRecord, ActivityRecord.source_payload_id == RawPayloadRecord.id)
            .where(*filters)
            .order_by(ActivityRecord.started_at.asc())
        )
        return [dict(row) for row in result.mappings()]

    async def get_sleep_records_in_window(
        self,
        user_id: UUID,
        start_date: date,
        end_date: date,
    ) -> list[SleepRecord]:
        result = await self._session.execute(
            select(SleepRecord)
            .where(
                SleepRecord.user_id == user_id,
                SleepRecord.sleep_date >= start_date,
                SleepRecord.sleep_date <= end_date,
            )
            .order_by(SleepRecord.sleep_date.asc())
        )
        return list(result.scalars().all())

    async def get_steps_in_window(
        self,
        user_id: UUID,
        start_date: date,
        end_date: date,
    ) -> list[StepsRecord]:
        result = await self._session.execute(
            select(StepsRecord)
            .where(
                StepsRecord.user_id == user_id,
                StepsRecord.step_date >= start_date,
                StepsRecord.step_date <= end_date,
            )
            .order_by(StepsRecord.step_date.asc())
        )
        return list(result.scalars().all())

    async def get_stress_in_window(
        self,
        user_id: UUID,
        start_date: date,
        end_date: date,
    ) -> list[StressRecord]:
        start_dt = datetime.combine(start_date, datetime.min.time(), tzinfo=UTC)
        end_dt = datetime.combine(end_date, datetime.max.time(), tzinfo=UTC)
        result = await self._session.execute(
            select(StressRecord)
            .where(
                StressRecord.user_id == user_id,
                StressRecord.recorded_at >= start_dt,
                StressRecord.recorded_at <= end_dt,
            )
            .order_by(StressRecord.recorded_at.asc())
        )
        return list(result.scalars().all())

    async def get_body_battery_in_window(
        self,
        user_id: UUID,
        start_date: date,
        end_date: date,
    ) -> list[BodyBatteryRecord]:
        start_dt = datetime.combine(start_date, datetime.min.time(), tzinfo=UTC)
        end_dt = datetime.combine(end_date, datetime.max.time(), tzinfo=UTC)
        result = await self._session.execute(
            select(BodyBatteryRecord)
            .where(
                BodyBatteryRecord.user_id == user_id,
                BodyBatteryRecord.recorded_at >= start_dt,
                BodyBatteryRecord.recorded_at <= end_dt,
            )
            .order_by(BodyBatteryRecord.recorded_at.asc())
        )
        return list(result.scalars().all())

    async def get_readiness_in_window(
        self,
        user_id: UUID,
        start_date: date,
        end_date: date,
    ) -> list[TrainingReadinessRecord]:
        start_dt = datetime.combine(start_date, datetime.min.time(), tzinfo=UTC)
        end_dt = datetime.combine(end_date, datetime.max.time(), tzinfo=UTC)
        result = await self._session.execute(
            select(TrainingReadinessRecord)
            .where(
                TrainingReadinessRecord.user_id == user_id,
                TrainingReadinessRecord.recorded_at >= start_dt,
                TrainingReadinessRecord.recorded_at <= end_dt,
            )
            .order_by(TrainingReadinessRecord.recorded_at.asc())
        )
        return list(result.scalars().all())

    async def get_hrv_between(
        self,
        user_id: UUID,
        start_date: date,
        end_date: date,
    ) -> list[HRVRecord]:
        start_dt = datetime.combine(start_date, datetime.min.time(), tzinfo=UTC)
        end_dt = datetime.combine(end_date, datetime.max.time(), tzinfo=UTC)
        result = await self._session.execute(
            select(HRVRecord)
            .where(
                HRVRecord.user_id == user_id,
                HRVRecord.recorded_at >= start_dt,
                HRVRecord.recorded_at <= end_dt,
            )
            .order_by(HRVRecord.recorded_at.asc())
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

    async def get_activity_by_id(
        self,
        user_id: UUID,
        activity_id: UUID,
    ) -> ActivityRecord | None:
        result = await self._session.execute(
            select(ActivityRecord).where(
                ActivityRecord.user_id == user_id,
                ActivityRecord.id == activity_id,
            )
        )
        return result.scalar_one_or_none()

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
        *,
        timezone: str = "America/Denver",
    ) -> ActivityRecord | None:
        tz = ZoneInfo(timezone)
        local_start = datetime.combine(target_date, datetime.min.time(), tzinfo=tz)
        local_end = datetime.combine(target_date, datetime.max.time(), tzinfo=tz)
        utc_start = local_start.astimezone(UTC)
        utc_end = local_end.astimezone(UTC)
        result = await self._session.execute(
            select(ActivityRecord)
            .where(
                ActivityRecord.user_id == user_id,
                ActivityRecord.started_at >= utc_start,
                ActivityRecord.started_at <= utc_end,
            )
            .order_by(ActivityRecord.started_at.asc())
        )
        activities = list(result.scalars().all())
        return select_primary_activity(activities, target_date, timezone=timezone)

    async def list_recent_garmin_raw(
        self,
        user_id: UUID,
        resource_types: tuple[str, ...],
        *,
        limit: int = 800,
    ) -> list[RawPayloadRecord]:
        if not resource_types:
            return []
        result = await self._session.execute(
            select(RawPayloadRecord)
            .where(
                RawPayloadRecord.user_id == user_id,
                RawPayloadRecord.provider == "garmin",
                RawPayloadRecord.resource_type.in_(resource_types),
            )
            .order_by(RawPayloadRecord.fetched_at.desc())
            .limit(limit)
        )
        rows = list(result.scalars().all())
        newest: dict[tuple[str, str], RawPayloadRecord] = {}
        for row in rows:
            key = (row.resource_type, row.provider_record_id)
            if key not in newest:
                newest[key] = row
        return list(newest.values())

    async def get_raw_payload(self, payload_id: UUID) -> dict | None:
        result = await self._session.execute(
            select(RawPayloadRecord).where(RawPayloadRecord.id == payload_id)
        )
        row = result.scalar_one_or_none()
        return row.payload if row else None

    async def get_activity_payload(self, payload_id: UUID) -> dict | None:
        return await self.get_raw_payload(payload_id)

    async def get_latest_raw_payload_by_record(
        self,
        user_id: UUID,
        *,
        resource_type: str,
        provider_record_id: str,
    ) -> StoredRawPayload | None:
        result = await self._session.execute(
            select(RawPayloadRecord)
            .where(
                RawPayloadRecord.user_id == user_id,
                RawPayloadRecord.resource_type == resource_type,
                RawPayloadRecord.provider_record_id == provider_record_id,
            )
            .order_by(RawPayloadRecord.fetched_at.desc())
            .limit(1)
        )
        row = result.scalar_one_or_none()
        if row is None:
            return None
        return StoredRawPayload(payload=row.payload, fetched_at=row.fetched_at)

    async def list_latest_raw_payloads_by_type(
        self,
        user_id: UUID,
        resource_type: str,
        *,
        limit: int = 10,
    ) -> list[StoredRawPayload]:
        result = await self._session.execute(
            select(RawPayloadRecord)
            .where(
                RawPayloadRecord.user_id == user_id,
                RawPayloadRecord.provider == DataProviderType.GARMIN.value,
                RawPayloadRecord.resource_type == resource_type,
            )
            .order_by(RawPayloadRecord.fetched_at.desc())
            .limit(limit)
        )
        return [
            StoredRawPayload(payload=row.payload, fetched_at=row.fetched_at)
            for row in result.scalars().all()
        ]

    async def get_raw_payloads_by_ids(self, payload_ids: list[UUID]) -> dict[UUID, dict]:
        if not payload_ids:
            return {}
        result = await self._session.execute(
            select(RawPayloadRecord).where(RawPayloadRecord.id.in_(payload_ids))
        )
        rows = result.scalars().all()
        return {row.id: row.payload for row in rows}

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
            .order_by(BodyBatteryRecord.recorded_at.desc(), BodyBatteryRecord.created_at.desc())
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
            .order_by(StressRecord.recorded_at.desc(), StressRecord.created_at.desc())
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

    async def garmin_metric_days(self, user_id: UUID) -> list[dict[str, object]]:
        result = await self._session.execute(
            select(
                RawPayloadRecord.resource_type,
                RawPayloadRecord.provider_record_id,
            ).where(
                RawPayloadRecord.user_id == user_id,
                RawPayloadRecord.provider == "garmin",
            )
        )
        grouped: dict[str, list[date]] = {}
        duplicates: dict[str, int] = {}
        seen: dict[str, set[str]] = {}
        for resource_type, record_id in result.all():
            seen.setdefault(resource_type, set())
            if record_id in seen[resource_type]:
                duplicates[resource_type] = duplicates.get(resource_type, 0) + 1
            seen[resource_type].add(record_id)
            day = _record_day(record_id)
            if day is not None:
                grouped.setdefault(resource_type, []).append(day)
        names = set(grouped) | set(seen)
        return [
            {
                "metric": name,
                "days": grouped.get(name, []),
                "duplicate_rows": duplicates.get(name, 0),
            }
            for name in sorted(names)
        ]

    async def garmin_activity_completeness(self, user_id: UUID) -> dict[str, int]:
        result = await self._session.execute(
            text(
                """
                SELECT count(*)::int AS activities,
                       count(a.elevation_gain_meters)::int AS elevation,
                       count(a.training_load)::int AS training_load,
                       count(a.avg_heart_rate)::int AS heart_rate,
                       count(a.avg_pace_sec_per_km)::int AS actual_pace,
                       count(COALESCE(
                           r.payload->'summary'->>'avgGradeAdjustedSpeed',
                           r.payload->'detail'->'summaryDTO'->>'avgGradeAdjustedSpeed'
                       ))::int AS grade_adjusted_speed,
                       count(COALESCE(
                           r.payload->'detail'->'summaryDTO'->>'beginPotentialStamina',
                           r.payload->'summary'->>'beginPotentialStamina'
                       ))::int AS stamina,
                       count(COALESCE(
                           r.payload->'summary'->>'avgPower',
                           r.payload->'detail'->'summaryDTO'->>'averagePower'
                       ))::int AS running_power,
                       count(COALESCE(
                           r.payload->'summary'->>'averageRunningCadenceInStepsPerMinute',
                           r.payload->'detail'->'summaryDTO'->>'averageRunCadence'
                       ))::int AS cadence,
                       count(COALESCE(
                           r.payload->'summary'->>'maxTemperature',
                           r.payload->'detail'->'summaryDTO'->>'averageTemperature'
                       ))::int AS temperature
                FROM activities a
                JOIN raw_payloads r ON r.id = a.source_payload_id
                WHERE a.user_id = :user_id AND a.provider = 'garmin'
                """
            ),
            {"user_id": user_id},
        )
        row = result.mappings().one()
        return {key: int(row[key] or 0) for key in row}

    async def garmin_hrv_integrity(self, user_id: UUID, timezone: str) -> dict[str, int]:
        result = await self._session.execute(
            text(
                """
                SELECT count(*)::int AS duplicate_dates,
                       count(*) FILTER (WHERE distinct_vals > 1)::int AS dates_with_different_values
                FROM (
                    SELECT count(DISTINCT hrv_ms) AS distinct_vals
                    FROM hrv_records
                    WHERE user_id = :user_id AND provider = 'garmin'
                    GROUP BY (recorded_at AT TIME ZONE :timezone)::date
                    HAVING count(*) > 1
                ) days
                """
            ),
            {"user_id": user_id, "timezone": timezone},
        )
        duplicates = result.mappings().one()
        totals = await self._session.execute(
            text(
                """
                SELECT count(*)::int AS rows,
                       count(DISTINCT timezone(:timezone, recorded_at)::date)::int
                           AS populated_days,
                       count(resting_heart_rate)::int AS resting_heart_rate_rows
                FROM hrv_records
                WHERE user_id = :user_id AND provider = 'garmin'
                """
            ),
            {"user_id": user_id, "timezone": timezone},
        )
        total_row = totals.mappings().one()
        return {
            "rows": int(total_row["rows"]),
            "populated_days": int(total_row["populated_days"]),
            "resting_heart_rate_rows": int(total_row["resting_heart_rate_rows"]),
            "duplicate_dates": int(duplicates["duplicate_dates"] or 0),
            "dates_with_different_values": int(duplicates["dates_with_different_values"] or 0),
        }

    async def latest_garmin_sync(self, user_id: UUID) -> dict[str, object] | None:
        result = await self._session.execute(
            select(SyncJob).where(
                SyncJob.user_id == user_id,
                SyncJob.provider == "garmin",
                SyncJob.status == "completed",
            )
            .order_by(SyncJob.completed_at.desc())
            .limit(1)
        )
        job = result.scalar_one_or_none()
        if job is None or job.completed_at is None:
            return None
        return {
            "completed_at": job.completed_at.isoformat(),
            "resource_types": list(job.resource_types or []),
            "resources_synced": job.resources_synced or {},
        }


def _record_day(value: object) -> date | None:
    text_value = str(value or "")
    if len(text_value) >= 10 and text_value[4:5] == "-" and text_value[7:8] == "-":
        try:
            return date.fromisoformat(text_value[:10])
        except ValueError:
            return None
    if ":" in text_value:
        return _record_day(text_value.rsplit(":", 1)[-1])
    return None
