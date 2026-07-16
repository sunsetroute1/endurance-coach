"""Assemble detailed activity metrics from normalized records and raw payloads."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from pydantic import BaseModel, Field

from endurance_coach.analytics.repositories import AnalyticsDataRepository
from endurance_coach.db.models import ActivityRecord
from endurance_coach.garmin.activity_parsing import (
    format_activity_type_name,
    parse_activity_flags,
    parse_heart_rate_zones,
    parse_pace_splits,
    parse_running_dynamics,
    parse_training_effect,
    pace_min_per_mile,
    type_key_from_payload,
)
from endurance_coach.processor.parsing import as_float, as_int

METERS_TO_MILES = 0.000621371
METERS_TO_FEET = 3.28084


class TrainingEffectDetail(BaseModel):
    aerobic: float | None = None
    anaerobic: float | None = None
    primary_benefit: str | None = None


class RunningDynamicsDetail(BaseModel):
    avg_cadence_spm: int | None = None
    max_cadence_spm: int | None = None
    avg_stride_length_m: float | None = None
    avg_vertical_ratio_pct: float | None = None
    avg_vertical_oscillation_cm: float | None = None
    avg_ground_contact_time_ms: int | None = None


class HeartRateZonesDetail(BaseModel):
    z1_time_min: int = 0
    z2_time_min: int = 0
    z3_time_min: int = 0
    z4_time_min: int = 0
    z5_time_min: int = 0


class PaceSplitDetail(BaseModel):
    mile: int
    time_sec: int
    avg_hr: int | None = None


class DetailedActivityResponse(BaseModel):
    activity_id: str = Field(description="Garmin provider activity id.")
    date: str = Field(description="Calendar date (YYYY-MM-DD) when the activity started.")
    start_time: str = Field(description="Local start time (HH:MM:SS).")
    activity_type: str
    is_treadmill: bool = False
    is_trail: bool = False
    distance_miles: float | None = None
    duration_minutes: float | None = None
    avg_pace_min_per_mi: float | None = None
    avg_hr: int | None = None
    max_hr: int | None = None
    total_ascent_ft: int | None = None
    total_descent_ft: int | None = None
    exercise_load: int | None = None
    training_effect: TrainingEffectDetail = Field(default_factory=TrainingEffectDetail)
    running_dynamics: RunningDynamicsDetail = Field(default_factory=RunningDynamicsDetail)
    heart_rate_zones: HeartRateZonesDetail = Field(default_factory=HeartRateZonesDetail)
    pace_splits: list[PaceSplitDetail] = Field(default_factory=list)


class DetailedActivityService:
    def __init__(
        self,
        data_repo: AnalyticsDataRepository,
        *,
        timezone: str = "America/Denver",
        lap_fetcher: Any | None = None,
    ) -> None:
        self._data_repo = data_repo
        self._timezone = timezone
        self._lap_fetcher = lap_fetcher

    async def get_detailed_activity(
        self,
        user_id: UUID,
        *,
        target_date: date | None = None,
        activity_id: str | None = None,
    ) -> DetailedActivityResponse:
        activity = await self._resolve_activity(user_id, target_date=target_date, activity_id=activity_id)
        if activity is None:
            raise HTTPException(status_code=404, detail="Activity not found")

        payload = await self._data_repo.get_activity_payload(activity.source_payload_id)
        if payload is None:
            raise HTTPException(status_code=404, detail="Activity payload not found")

        detail = payload.get("detail", {})
        if not isinstance(detail, dict):
            detail = {}

        if not detail.get("lapDTOs") and self._lap_fetcher is not None:
            laps = await self._lap_fetcher(activity.provider_record_id)
            if laps:
                detail = {**detail, "lapDTOs": laps}

        merged = self._merged_summary(payload)
        type_key = type_key_from_payload(payload, merged)
        activity_type = format_activity_type_name(type_key, activity.name)
        is_treadmill, is_trail = parse_activity_flags(merged, activity.name, type_key)

        distance_miles = None
        if activity.distance_meters is not None:
            distance_miles = round(activity.distance_meters * METERS_TO_MILES, 2)

        duration_minutes = None
        if activity.duration_seconds:
            duration_minutes = round(activity.duration_seconds / 60.0, 1)

        total_ascent_ft = None
        if activity.elevation_gain_meters is not None:
            total_ascent_ft = round(activity.elevation_gain_meters * METERS_TO_FEET)

        elevation_loss = as_float(merged.get("elevationLoss"))
        total_descent_ft = round(elevation_loss * METERS_TO_FEET) if elevation_loss is not None else None

        exercise_load = None
        if activity.training_load is not None:
            exercise_load = round(activity.training_load)

        local_started = activity.started_at.astimezone(ZoneInfo(self._timezone))

        training_effect_data = parse_training_effect(merged)
        dynamics_data = parse_running_dynamics(merged, detail)
        zones_data = parse_heart_rate_zones(merged)
        splits_data = parse_pace_splits(detail)

        return DetailedActivityResponse(
            activity_id=activity.provider_record_id,
            date=local_started.date().isoformat(),
            start_time=local_started.strftime("%H:%M:%S"),
            activity_type=activity_type,
            is_treadmill=is_treadmill,
            is_trail=is_trail,
            distance_miles=distance_miles,
            duration_minutes=duration_minutes,
            avg_pace_min_per_mi=pace_min_per_mile(activity.distance_meters, activity.duration_seconds),
            avg_hr=activity.avg_heart_rate,
            max_hr=activity.max_heart_rate or as_int(merged.get("maxHR")),
            total_ascent_ft=total_ascent_ft,
            total_descent_ft=total_descent_ft,
            exercise_load=exercise_load,
            training_effect=TrainingEffectDetail(**training_effect_data),
            running_dynamics=RunningDynamicsDetail(**dynamics_data),
            heart_rate_zones=HeartRateZonesDetail(**zones_data),
            pace_splits=[PaceSplitDetail(**split) for split in splits_data],
        )

    async def _resolve_activity(
        self,
        user_id: UUID,
        *,
        target_date: date | None,
        activity_id: str | None,
    ) -> ActivityRecord | None:
        if activity_id:
            return await self._data_repo.get_activity_by_provider_record_id(user_id, activity_id)
        if target_date is not None:
            return await self._data_repo.get_activity_for_date(user_id, target_date)
        return await self._data_repo.get_most_recent_activity(user_id)

    @staticmethod
    def _merged_summary(payload: dict[str, Any]) -> dict[str, Any]:
        summary = payload.get("summary", payload)
        detail = payload.get("detail", {})
        dto = detail.get("summaryDTO", {}) if isinstance(detail, dict) else {}
        if not isinstance(summary, dict):
            summary = {}
        if not isinstance(dto, dict):
            dto = {}
        return {**summary, **dto}
