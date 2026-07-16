"""Garmin-specific normalizers."""

from __future__ import annotations

from datetime import UTC, datetime, time
from typing import Any

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
    RawPayload,
)
from endurance_coach.garmin.body_battery_parsing import extract_body_battery_day_stats
from endurance_coach.processor.parsing import (
    as_float,
    as_int,
    dig,
    pace_from_distance_duration,
    pace_sec_per_km_from_speed_mps,
    parse_date,
    parse_datetime,
)


class GarminActivityNormalizer:
    def supports(self, provider: DataProviderType) -> bool:
        return provider == DataProviderType.GARMIN

    async def normalize(self, payload: RawPayload) -> NormalizedActivity:
        root = payload.payload
        summary = root.get("summary", root)
        detail = root.get("detail", {})
        dto = detail.get("summaryDTO", detail) if isinstance(detail, dict) else {}
        merged: dict[str, Any] = {**summary, **dto}

        started_at = (
            parse_datetime(merged.get("startTimeLocal"))
            or parse_datetime(merged.get("startTimeGMT"))
            or parse_datetime(merged.get("beginTimestamp"))
        )
        if started_at is None:
            raise ValueError("Activity payload missing start time")

        duration_seconds = as_int(merged.get("duration")) or 0
        distance_meters = as_float(merged.get("distance"))
        avg_speed = as_float(merged.get("averageSpeed"))
        pace = pace_sec_per_km_from_speed_mps(avg_speed) or pace_from_distance_duration(
            distance_meters,
            duration_seconds,
        )

        activity_type = (
            dig(merged, "activityType", "typeKey")
            or dig(merged, "activityTypeDTO", "typeKey")
            or str(merged.get("activityType", "unknown"))
        )

        if payload.id is None:
            raise ValueError("Raw payload id is required for normalization")

        return NormalizedActivity(
            user_id=payload.user_id,
            provider=payload.provider,
            provider_record_id=payload.provider_record_id,
            name=str(merged.get("activityName") or "Untitled Activity"),
            activity_type=str(activity_type),
            started_at=started_at,
            duration_seconds=duration_seconds,
            distance_meters=distance_meters,
            avg_heart_rate=as_int(merged.get("averageHR")),
            max_heart_rate=as_int(merged.get("maxHR")),
            avg_pace_sec_per_km=pace,
            elevation_gain_meters=as_float(merged.get("elevationGain")),
            training_load=as_float(
                merged.get("activityTrainingLoad") or merged.get("trainingLoad")
            ),
            source_payload_id=payload.id,
        )

    def extract_running_dynamics(
        self,
        payload: RawPayload,
        activity_id: Any,
    ) -> NormalizedRunningDynamics | None:
        detail = payload.payload.get("detail", {})
        if not isinstance(detail, dict):
            return None

        dto = detail.get("summaryDTO", detail)
        cadence = as_float(dto.get("averageRunCadence") or dto.get("avgCadence"))
        vertical_osc = as_float(
            dto.get("avgVerticalOscillation") or dto.get("averageVerticalOscillation")
        )
        gct = as_float(dto.get("avgGroundContactTime") or dto.get("averageGroundContactTime"))
        stride = as_float(dto.get("avgStrideLength") or dto.get("averageStrideLength"))

        if all(v is None for v in (cadence, vertical_osc, gct, stride)):
            return None

        if payload.id is None:
            return None

        return NormalizedRunningDynamics(
            user_id=payload.user_id,
            provider=payload.provider,
            activity_id=activity_id,
            avg_cadence=cadence,
            avg_vertical_oscillation_mm=vertical_osc,
            avg_ground_contact_time_ms=gct,
            avg_stride_length_m=stride,
            source_payload_id=payload.id,
        )


class GarminSleepNormalizer:
    def supports(self, provider: DataProviderType) -> bool:
        return provider == DataProviderType.GARMIN

    async def normalize(self, payload: RawPayload) -> NormalizedSleep:
        root = payload.payload
        data = root.get("data", root)
        sleep_date = parse_date(root.get("date")) or parse_date(payload.provider_record_id)
        if sleep_date is None:
            raise ValueError("Sleep payload missing date")

        daily = data.get("dailySleepDTO", data) if isinstance(data, dict) else {}
        total_sleep = (
            as_int(dig(data, "sleepTimeSeconds"))
            or as_int(dig(daily, "sleepTimeSeconds"))
            or 0
        )
        if total_sleep <= 0 and isinstance(daily, dict):
            deep = as_int(dig(daily, "deepSleepSeconds")) or 0
            rem = as_int(dig(daily, "remSleepSeconds")) or 0
            light = as_int(dig(daily, "lightSleepSeconds")) or 0
            stage_sum = deep + rem + light
            if stage_sum > 0:
                total_sleep = stage_sum

        if payload.id is None:
            raise ValueError("Raw payload id is required for normalization")

        return NormalizedSleep(
            user_id=payload.user_id,
            provider=payload.provider,
            sleep_date=sleep_date,
            total_sleep_seconds=total_sleep,
            deep_sleep_seconds=as_int(
                dig(data, "deepSleepSeconds") or dig(daily, "deepSleepSeconds")
            ),
            rem_sleep_seconds=as_int(dig(data, "remSleepSeconds") or dig(daily, "remSleepSeconds")),
            light_sleep_seconds=as_int(
                dig(data, "lightSleepSeconds") or dig(daily, "lightSleepSeconds")
            ),
            awake_seconds=as_int(dig(data, "awakeSleepSeconds") or dig(daily, "awakeSleepSeconds")),
            sleep_score=as_int(dig(data, "sleepScores", "overall", "value"))
            or as_int(dig(daily, "sleepScores", "overall", "value")),
            source_payload_id=payload.id,
        )


class GarminHRVNormalizer:
    def supports(self, provider: DataProviderType) -> bool:
        return provider == DataProviderType.GARMIN

    @staticmethod
    def _first_hrv_reading(data: Any) -> float | None:
        readings = data.get("hrvReadings") if isinstance(data, dict) else None
        if isinstance(readings, list) and readings:
            first = readings[0]
            if isinstance(first, dict):
                return as_float(first.get("hrvValue"))
        return None

    async def normalize(self, payload: RawPayload) -> NormalizedHRV:
        root = payload.payload
        data = root.get("data", root)
        sleep_date = parse_date(root.get("date")) or parse_date(payload.provider_record_id)
        if sleep_date is None:
            raise ValueError("HRV payload missing date")

        hrv_ms = (
            as_float(dig(data, "lastNightAvg"))
            or as_float(dig(data, "weeklyAvg"))
            or as_float(dig(data, "hrvSummary", "lastNightAvg"))
            or self._first_hrv_reading(data)
        )
        if hrv_ms is None:
            raise ValueError("HRV payload missing hrv value")

        if payload.id is None:
            raise ValueError("Raw payload id is required for normalization")

        return NormalizedHRV(
            user_id=payload.user_id,
            provider=payload.provider,
            recorded_at=datetime.combine(sleep_date, time.min, tzinfo=UTC),
            hrv_ms=hrv_ms,
            resting_heart_rate=as_int(dig(data, "restingHeartRate"))
            or as_int(dig(data, "hrvSummary", "restingHeartRate")),
            baseline_ms=as_float(dig(data, "hrvSummary", "baseline", "balancedLow"))
            or as_float(dig(data, "baseline", "balancedLow"))
            or as_float(dig(data, "baselineLowUpper")),
            source_payload_id=payload.id,
        )


class GarminReadinessNormalizer:
    def supports(self, provider: DataProviderType) -> bool:
        return provider == DataProviderType.GARMIN

    async def normalize(self, payload: RawPayload) -> NormalizedReadiness:
        root = payload.payload
        data = root.get("data", root)
        sleep_date = parse_date(root.get("date")) or parse_date(payload.provider_record_id)
        if sleep_date is None:
            raise ValueError("Readiness payload missing date")

        entries = data if isinstance(data, list) else [data]
        entry = next(
            (item for item in entries if isinstance(item, dict) and item.get("score")),
            None,
        )
        if entry is None and isinstance(data, dict):
            entry = data
        if not isinstance(entry, dict):
            raise ValueError("Readiness payload missing score entry")

        score = as_int(entry.get("score") or entry.get("readinessScore"))
        if score is None:
            raise ValueError("Readiness payload missing score")

        if payload.id is None:
            raise ValueError("Raw payload id is required for normalization")

        return NormalizedReadiness(
            user_id=payload.user_id,
            provider=payload.provider,
            recorded_at=datetime.combine(sleep_date, time.min, tzinfo=UTC),
            readiness_score=score,
            hrv_component=as_int(entry.get("hrvFactor") or entry.get("hrvFactorPercent")),
            sleep_component=as_int(entry.get("sleepFactor") or entry.get("sleepFactorPercent")),
            recovery_component=as_int(
                entry.get("recoveryFactor") or entry.get("recoveryFactorPercent")
            ),
            source_payload_id=payload.id,
        )


class GarminBodyBatteryNormalizer:
    def supports(self, provider: DataProviderType) -> bool:
        return provider == DataProviderType.GARMIN

    async def normalize(self, payload: RawPayload) -> NormalizedBodyBattery:
        root = payload.payload
        data = root.get("data", root)
        sleep_date = parse_date(root.get("date")) or parse_date(payload.provider_record_id)

        if isinstance(data, list) and data and isinstance(data[0], dict):
            entry_date = parse_date(data[0].get("date"))
            if entry_date is not None:
                sleep_date = entry_date

        if sleep_date is None:
            raise ValueError("Body battery payload missing date")

        level, charged, drained, _levels = extract_body_battery_day_stats(data)
        if level is None:
            raise ValueError("Body battery payload missing level")

        if payload.id is None:
            raise ValueError("Raw payload id is required for normalization")

        return NormalizedBodyBattery(
            user_id=payload.user_id,
            provider=payload.provider,
            recorded_at=datetime.combine(sleep_date, time.min, tzinfo=UTC),
            level=level,
            charged=charged,
            drained=drained,
            source_payload_id=payload.id,
        )


class GarminStressNormalizer:
    def supports(self, provider: DataProviderType) -> bool:
        return provider == DataProviderType.GARMIN

    async def normalize(self, payload: RawPayload) -> NormalizedStress:
        root = payload.payload
        data = root.get("data", root)
        sleep_date = parse_date(root.get("date")) or parse_date(payload.provider_record_id)
        if sleep_date is None:
            raise ValueError("Stress payload missing date")

        avg_stress = as_int(
            dig(data, "avgStressLevel")
            or dig(data, "averageStressLevel")
            or dig(data, "overallStressLevel")
        )
        if avg_stress is None:
            raise ValueError("Stress payload missing average stress")

        if payload.id is None:
            raise ValueError("Raw payload id is required for normalization")

        return NormalizedStress(
            user_id=payload.user_id,
            provider=payload.provider,
            recorded_at=datetime.combine(sleep_date, time.min, tzinfo=UTC),
            avg_stress=avg_stress,
            max_stress=as_int(dig(data, "maxStressLevel") or dig(data, "maxStress")),
            source_payload_id=payload.id,
        )


class GarminStepsNormalizer:
    def supports(self, provider: DataProviderType) -> bool:
        return provider == DataProviderType.GARMIN

    async def normalize(self, payload: RawPayload) -> NormalizedSteps:
        root = payload.payload
        data = root.get("data", root)
        step_date = parse_date(root.get("date")) or parse_date(payload.provider_record_id)
        if step_date is None and isinstance(data, dict):
            step_date = parse_date(data.get("calendarDate"))
        if step_date is None:
            raise ValueError("Steps payload missing date")

        if not isinstance(data, dict):
            raise ValueError("Steps payload missing stats data")

        total_steps = as_int(data.get("totalSteps"))
        if total_steps is None:
            raise ValueError("Steps payload missing totalSteps")

        if payload.id is None:
            raise ValueError("Raw payload id is required for normalization")

        return NormalizedSteps(
            user_id=payload.user_id,
            provider=payload.provider,
            step_date=step_date,
            total_steps=total_steps,
            step_goal=as_int(data.get("dailyStepGoal")),
            distance_meters=as_float(data.get("totalDistanceMeters")),
            source_payload_id=payload.id,
        )
