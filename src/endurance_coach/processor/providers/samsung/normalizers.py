"""Samsung Health normalizers for companion-app payloads."""

from __future__ import annotations

from datetime import UTC, datetime, time

from endurance_coach.domain.enums import DataProviderType
from endurance_coach.domain.models import (
    NormalizedActivity,
    NormalizedHRV,
    NormalizedSleep,
    NormalizedSteps,
    NormalizedStress,
    RawPayload,
)
from endurance_coach.processor.parsing import as_float, as_int, parse_date, parse_datetime


def _int(value: object) -> int | None:
    if value is None or value == "":
        return None
    return as_int(value)


def _float(value: object) -> float | None:
    if value is None or value == "":
        return None
    return as_float(value)


class SamsungSleepNormalizer:
    def supports(self, provider: DataProviderType) -> bool:
        return provider == DataProviderType.SAMSUNG_HEALTH

    async def normalize(self, payload: RawPayload) -> NormalizedSleep:
        data = payload.payload
        sleep_date = parse_date(data.get("sleep_date")) or parse_date(payload.provider_record_id)
        if sleep_date is None:
            raise ValueError("Samsung sleep payload missing sleep_date")

        total_sleep = as_int(data.get("total_sleep_seconds"))
        if total_sleep is None:
            raise ValueError("Samsung sleep payload missing total_sleep_seconds")

        if payload.id is None:
            raise ValueError("Raw payload id is required for normalization")

        return NormalizedSleep(
            user_id=payload.user_id,
            provider=payload.provider,
            sleep_date=sleep_date,
            total_sleep_seconds=total_sleep,
            deep_sleep_seconds=as_int(data.get("deep_sleep_seconds")),
            rem_sleep_seconds=as_int(data.get("rem_sleep_seconds")),
            light_sleep_seconds=as_int(data.get("light_sleep_seconds")),
            awake_seconds=as_int(data.get("awake_seconds")),
            sleep_score=as_int(data.get("sleep_score")),
            source_payload_id=payload.id,
        )


class SamsungStepsNormalizer:
    def supports(self, provider: DataProviderType) -> bool:
        return provider == DataProviderType.SAMSUNG_HEALTH

    async def normalize(self, payload: RawPayload) -> NormalizedSteps:
        data = payload.payload
        step_date = parse_date(data.get("date")) or parse_date(payload.provider_record_id)
        if step_date is None:
            raise ValueError("Samsung steps payload missing date")

        total_steps = as_int(data.get("total_steps"))
        if total_steps is None:
            raise ValueError("Samsung steps payload missing total_steps")

        if payload.id is None:
            raise ValueError("Raw payload id is required for normalization")

        return NormalizedSteps(
            user_id=payload.user_id,
            provider=payload.provider,
            step_date=step_date,
            total_steps=total_steps,
            step_goal=as_int(data.get("step_goal")),
            distance_meters=as_float(data.get("distance_meters")),
            source_payload_id=payload.id,
        )


class SamsungActivityNormalizer:
    def supports(self, provider: DataProviderType) -> bool:
        return provider == DataProviderType.SAMSUNG_HEALTH

    async def normalize(self, payload: RawPayload) -> NormalizedActivity:
        data = payload.payload
        started_at = parse_datetime(data.get("start_time"))
        if started_at is None:
            raise ValueError("Samsung activity payload missing start_time")

        duration_seconds = as_int(data.get("duration_seconds")) or 0
        distance_meters = as_float(data.get("distance_meters"))
        avg_pace = None
        if distance_meters and distance_meters > 0 and duration_seconds > 0:
            avg_pace = duration_seconds / (distance_meters / 1000.0)

        if payload.id is None:
            raise ValueError("Raw payload id is required for normalization")

        return NormalizedActivity(
            user_id=payload.user_id,
            provider=payload.provider,
            provider_record_id=payload.provider_record_id,
            name=str(data.get("name") or "Samsung Health Activity"),
            activity_type=str(data.get("activity_type") or "exercise"),
            started_at=started_at,
            duration_seconds=duration_seconds,
            distance_meters=distance_meters,
            avg_heart_rate=as_int(data.get("avg_heart_rate")),
            max_heart_rate=as_int(data.get("max_heart_rate")),
            avg_pace_sec_per_km=avg_pace,
            elevation_gain_meters=as_float(data.get("elevation_gain_meters")),
            training_load=as_float(data.get("training_load")),
            source_payload_id=payload.id,
        )


class SamsungHRVNormalizer:
    def supports(self, provider: DataProviderType) -> bool:
        return provider == DataProviderType.SAMSUNG_HEALTH

    async def normalize(self, payload: RawPayload) -> NormalizedHRV:
        data = payload.payload
        recorded_at = parse_datetime(data.get("recorded_at"))
        if recorded_at is None:
            record_date = parse_date(data.get("date")) or parse_date(payload.provider_record_id)
            if record_date is None:
                raise ValueError("Samsung HRV payload missing recorded_at or date")
            recorded_at = datetime.combine(record_date, time.min, tzinfo=UTC)

        hrv_ms = as_float(data.get("hrv_ms"))
        if hrv_ms is None:
            raise ValueError("Samsung HRV payload missing hrv_ms")

        if payload.id is None:
            raise ValueError("Raw payload id is required for normalization")

        return NormalizedHRV(
            user_id=payload.user_id,
            provider=payload.provider,
            recorded_at=recorded_at,
            hrv_ms=hrv_ms,
            resting_heart_rate=as_int(data.get("resting_heart_rate")),
            baseline_ms=as_float(data.get("baseline_ms")),
            source_payload_id=payload.id,
        )


class SamsungStressNormalizer:
    def supports(self, provider: DataProviderType) -> bool:
        return provider == DataProviderType.SAMSUNG_HEALTH

    async def normalize(self, payload: RawPayload) -> NormalizedStress:
        data = payload.payload
        recorded_at = parse_datetime(data.get("recorded_at"))
        if recorded_at is None:
            record_date = parse_date(data.get("date")) or parse_date(payload.provider_record_id)
            if record_date is None:
                raise ValueError("Samsung stress payload missing date")
            recorded_at = datetime.combine(record_date, time.min, tzinfo=UTC)

        avg_stress = _float(data.get("avg_stress"))
        if avg_stress is None:
            raise ValueError("Samsung stress payload missing avg_stress")

        if payload.id is None:
            raise ValueError("Raw payload id is required for normalization")

        return NormalizedStress(
            user_id=payload.user_id,
            provider=payload.provider,
            recorded_at=recorded_at,
            avg_stress=int(round(avg_stress)),
            max_stress=int(round(v)) if (v := _float(data.get("max_stress"))) is not None else None,
            source_payload_id=payload.id,
        )
