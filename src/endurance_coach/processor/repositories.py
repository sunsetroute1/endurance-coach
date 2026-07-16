"""Persist normalized records from the processor layer."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from endurance_coach.db.models import (
    ActivityRecord,
    BodyBatteryRecord,
    HRVRecord,
    RunningDynamicsRecord,
    SleepRecord,
    StepsRecord,
    StressRecord,
    TrainingReadinessRecord,
)
from endurance_coach.domain.enums import DataProviderType
from endurance_coach.domain.models import (
    NormalizedActivity,
    NormalizedBodyBattery,
    NormalizedHRV,
    NormalizedReadiness,
    NormalizedRunningDynamics,
    NormalizedSleep,
    NormalizedSteps,
    NormalizedStress,
)


class SqlAlchemyNormalizedRecordRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert_activity(self, record: NormalizedActivity) -> ActivityRecord:
        existing = await self._get_activity(
            record.user_id,
            record.provider,
            record.provider_record_id,
        )
        if existing is not None:
            existing.name = record.name
            existing.activity_type = record.activity_type
            existing.started_at = record.started_at
            existing.duration_seconds = record.duration_seconds
            existing.distance_meters = record.distance_meters
            existing.avg_heart_rate = record.avg_heart_rate
            existing.max_heart_rate = record.max_heart_rate
            existing.avg_pace_sec_per_km = record.avg_pace_sec_per_km
            existing.elevation_gain_meters = record.elevation_gain_meters
            existing.training_load = record.training_load
            existing.source_payload_id = record.source_payload_id
            await self._session.flush()
            return existing

        row = ActivityRecord(
            user_id=record.user_id,
            provider=record.provider,
            provider_record_id=record.provider_record_id,
            source_payload_id=record.source_payload_id,
            name=record.name,
            activity_type=record.activity_type,
            started_at=record.started_at,
            duration_seconds=record.duration_seconds,
            distance_meters=record.distance_meters,
            avg_heart_rate=record.avg_heart_rate,
            max_heart_rate=record.max_heart_rate,
            avg_pace_sec_per_km=record.avg_pace_sec_per_km,
            elevation_gain_meters=record.elevation_gain_meters,
            training_load=record.training_load,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def upsert_sleep(self, record: NormalizedSleep) -> SleepRecord:
        result = await self._session.execute(
            select(SleepRecord).where(
                SleepRecord.user_id == record.user_id,
                SleepRecord.provider == record.provider,
                SleepRecord.sleep_date == record.sleep_date,
            )
        )
        existing = result.scalar_one_or_none()
        if existing is not None:
            existing.total_sleep_seconds = record.total_sleep_seconds
            existing.deep_sleep_seconds = record.deep_sleep_seconds
            existing.rem_sleep_seconds = record.rem_sleep_seconds
            existing.light_sleep_seconds = record.light_sleep_seconds
            existing.awake_seconds = record.awake_seconds
            existing.sleep_score = record.sleep_score
            existing.source_payload_id = record.source_payload_id
            await self._session.flush()
            return existing

        row = SleepRecord(
            user_id=record.user_id,
            provider=record.provider,
            sleep_date=record.sleep_date,
            source_payload_id=record.source_payload_id,
            total_sleep_seconds=record.total_sleep_seconds,
            deep_sleep_seconds=record.deep_sleep_seconds,
            rem_sleep_seconds=record.rem_sleep_seconds,
            light_sleep_seconds=record.light_sleep_seconds,
            awake_seconds=record.awake_seconds,
            sleep_score=record.sleep_score,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def upsert_hrv(self, record: NormalizedHRV) -> HRVRecord:
        row = HRVRecord(
            user_id=record.user_id,
            provider=record.provider,
            recorded_at=record.recorded_at,
            source_payload_id=record.source_payload_id,
            hrv_ms=record.hrv_ms,
            resting_heart_rate=record.resting_heart_rate,
            baseline_ms=record.baseline_ms,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def upsert_readiness(self, record: NormalizedReadiness) -> TrainingReadinessRecord:
        row = TrainingReadinessRecord(
            user_id=record.user_id,
            provider=record.provider,
            recorded_at=record.recorded_at,
            source_payload_id=record.source_payload_id,
            readiness_score=record.readiness_score,
            hrv_component=record.hrv_component,
            sleep_component=record.sleep_component,
            recovery_component=record.recovery_component,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def upsert_body_battery(self, record: NormalizedBodyBattery) -> BodyBatteryRecord:
        row = BodyBatteryRecord(
            user_id=record.user_id,
            provider=record.provider,
            recorded_at=record.recorded_at,
            source_payload_id=record.source_payload_id,
            level=record.level,
            charged=record.charged,
            drained=record.drained,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def upsert_stress(self, record: NormalizedStress) -> StressRecord:
        row = StressRecord(
            user_id=record.user_id,
            provider=record.provider,
            recorded_at=record.recorded_at,
            source_payload_id=record.source_payload_id,
            avg_stress=record.avg_stress,
            max_stress=record.max_stress,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def upsert_steps(self, record: NormalizedSteps) -> StepsRecord:
        result = await self._session.execute(
            select(StepsRecord).where(
                StepsRecord.user_id == record.user_id,
                StepsRecord.provider == record.provider,
                StepsRecord.step_date == record.step_date,
            )
        )
        existing = result.scalar_one_or_none()
        if existing is not None:
            existing.total_steps = record.total_steps
            existing.step_goal = record.step_goal
            existing.distance_meters = record.distance_meters
            existing.source_payload_id = record.source_payload_id
            await self._session.flush()
            return existing

        row = StepsRecord(
            user_id=record.user_id,
            provider=record.provider,
            step_date=record.step_date,
            source_payload_id=record.source_payload_id,
            total_steps=record.total_steps,
            step_goal=record.step_goal,
            distance_meters=record.distance_meters,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def upsert_running_dynamics(
        self,
        record: NormalizedRunningDynamics,
    ) -> RunningDynamicsRecord:
        result = await self._session.execute(
            select(RunningDynamicsRecord).where(
                RunningDynamicsRecord.activity_id == record.activity_id,
            )
        )
        existing = result.scalar_one_or_none()
        if existing is not None:
            existing.avg_cadence = record.avg_cadence
            existing.avg_vertical_oscillation_mm = record.avg_vertical_oscillation_mm
            existing.avg_ground_contact_time_ms = record.avg_ground_contact_time_ms
            existing.avg_stride_length_m = record.avg_stride_length_m
            existing.source_payload_id = record.source_payload_id
            await self._session.flush()
            return existing

        row = RunningDynamicsRecord(
            user_id=record.user_id,
            provider=record.provider,
            activity_id=record.activity_id,
            source_payload_id=record.source_payload_id,
            avg_cadence=record.avg_cadence,
            avg_vertical_oscillation_mm=record.avg_vertical_oscillation_mm,
            avg_ground_contact_time_ms=record.avg_ground_contact_time_ms,
            avg_stride_length_m=record.avg_stride_length_m,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def _get_activity(
        self,
        user_id: UUID,
        provider: DataProviderType,
        provider_record_id: str,
    ) -> ActivityRecord | None:
        result = await self._session.execute(
            select(ActivityRecord).where(
                ActivityRecord.user_id == user_id,
                ActivityRecord.provider == provider,
                ActivityRecord.provider_record_id == provider_record_id,
            )
        )
        return result.scalar_one_or_none()
