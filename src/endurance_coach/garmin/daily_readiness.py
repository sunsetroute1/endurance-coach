"""Assemble daily Garmin readiness metrics from normalized records and raw payloads."""

from __future__ import annotations

from datetime import UTC, date, datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from endurance_coach.analytics.repositories import AnalyticsDataRepository
from endurance_coach.api.schemas.temporal import ResponseMeta, build_response_meta, format_recorded_at
from endurance_coach.db.models import ActivityRecord
from endurance_coach.garmin.body_battery_parsing import extract_body_battery_day_stats
from endurance_coach.garmin.payload_parsing import (
    parse_resting_heart_rate,
    parse_sleep_seconds,
    parse_weekly_hrv,
)
from endurance_coach.garmin.readiness_dates import (
    morning_sync_fetched_before,
    readiness_source_date,
)
from endurance_coach.timezone_util import today_local

METERS_TO_MILES = 0.000621371
METERS_TO_FEET = 3.28084

REQUIRED_MORNING_FIELDS = (
    "overnight_hrv",
    "morning_rhr",
    "seven_day_hrv",
    "sleep",
    "last_activity",
)


class ReadinessCompletionStatus(str, Enum):
    COMPLETE = "complete"
    PARTIAL = "partial"


class MorningReadinessIncompleteError(Exception):
    """Raised when required morning readiness fields are not yet available."""

    def __init__(self, status: MorningReadinessStatusResponse) -> None:
        self.status = status
        super().__init__(f"Morning readiness is {status.status.value}")


class SleepReadiness(BaseModel):
    sleep_date: str | None = Field(
        default=None,
        description="Calendar date (YYYY-MM-DD) for the sleep record.",
    )
    recorded_at: str | None = Field(
        default=None,
        description="ISO-8601 timestamp when this sleep record was stored.",
    )
    duration_hours: float | None = None
    quality: str | None = None


class BodyBatteryReadiness(BaseModel):
    recorded_at: str | None = Field(
        default=None,
        description="ISO-8601 timestamp for the body battery snapshot.",
    )
    start_value: int | None = None
    end_value: int | None = None


class StressReadiness(BaseModel):
    recorded_at: str | None = Field(
        default=None,
        description="ISO-8601 timestamp for the overnight stress average.",
    )
    average_overnight: int | None = None


class StepsReadiness(BaseModel):
    step_date: str | None = Field(
        default=None,
        description="Calendar date (YYYY-MM-DD) for the step count.",
    )
    total_steps: int | None = None
    step_goal: int | None = None
    distance_miles: float | None = None


class HRVReadiness(BaseModel):
    recorded_at: str | None = Field(
        default=None,
        description="ISO-8601 timestamp for the overnight HRV reading.",
    )
    overnight_hrv: int | None = None
    morning_rhr: int | None = None
    seven_day_hrv: int | None = None


class LastActivityReadiness(BaseModel):
    date: str | None = Field(
        default=None,
        description="Calendar date (YYYY-MM-DD) when the activity started.",
    )
    started_at: str | None = Field(
        default=None,
        description="ISO-8601 timestamp when the activity started.",
    )
    distance_miles: float | None = None
    total_ascent_ft: float | None = None
    avg_hr: int | None = None
    exercise_load: float | None = None
    rpe: int | None = None


class MorningReadinessStatusResponse(BaseModel):
    meta: ResponseMeta = Field(
        description="Explicit response timing so clients do not infer the current date.",
    )
    date: str = Field(description="Calendar date (YYYY-MM-DD) for this readiness snapshot.")
    status: ReadinessCompletionStatus
    missing_fields: list[str] = Field(default_factory=list)
    last_successful_metric_timestamp: str | None = Field(
        default=None,
        description="ISO-8601 timestamp of the newest required metric when status is complete.",
    )


class DailyGarminReadinessResponse(BaseModel):
    meta: ResponseMeta = Field(
        description="Explicit response timing so clients do not infer the current date.",
    )
    date: str = Field(description="Calendar date (YYYY-MM-DD) for this readiness snapshot.")
    status: ReadinessCompletionStatus = ReadinessCompletionStatus.COMPLETE
    last_successful_metric_timestamp: str | None = None
    hrv: HRVReadiness = Field(default_factory=HRVReadiness)
    sleep: SleepReadiness = Field(default_factory=SleepReadiness)
    body_battery: BodyBatteryReadiness = Field(default_factory=BodyBatteryReadiness)
    stress: StressReadiness = Field(default_factory=StressReadiness)
    steps: StepsReadiness = Field(default_factory=StepsReadiness)
    last_activity: LastActivityReadiness = Field(default_factory=LastActivityReadiness)

    # Deprecated top-level fields kept for backward compatibility.
    morning_rhr: int | None = None
    overnight_hrv: int | None = None
    seven_day_hrv: int | None = None


def sleep_quality_from_score(score: int | None) -> str | None:
    if score is None:
        return None
    if score >= 85:
        return "excellent"
    if score >= 70:
        return "good"
    if score >= 50:
        return "fair"
    return "poor"


def _round_hours(seconds: int | None) -> float | None:
    if seconds is None:
        return None
    return round(seconds / 3600, 1)


def _parse_body_battery_levels(payload: dict[str, Any]) -> tuple[int | None, int | None]:
    data = payload.get("data", payload)
    _end_level, _charged, _drained, levels = extract_body_battery_day_stats(data)
    if not levels:
        return None, None
    return levels[0], levels[-1]


async def _resolve_sleep_for_report(
    data_repo: AnalyticsDataRepository,
    user_id: UUID,
    report_date: date,
    timezone: str,
    *,
    fetched_before: datetime | None = None,
) -> tuple[Any | None, int | None, dict[str, Any] | None]:
    sleep, sleep_seconds, sleep_payload = await _resolve_sleep_for_date(
        data_repo,
        user_id,
        report_date,
        fetched_before=fetched_before,
    )
    if sleep is not None and sleep_seconds is not None and sleep_seconds > 0:
        return sleep, sleep_seconds, sleep_payload

    source_date = readiness_source_date(report_date, timezone)
    return await _resolve_sleep_for_date(
        data_repo,
        user_id,
        source_date,
        fetched_before=fetched_before,
    )


async def _resolve_hrv_for_report(
    data_repo: AnalyticsDataRepository,
    user_id: UUID,
    report_date: date,
    timezone: str,
    *,
    fetched_before: datetime | None = None,
):
    hrv = await data_repo.get_hrv_for_date(
        user_id,
        report_date,
        fetched_before=fetched_before,
    )
    if hrv is not None:
        return hrv
    source_date = readiness_source_date(report_date, timezone)
    return await data_repo.get_hrv_for_date(
        user_id,
        source_date,
        fetched_before=fetched_before,
    )


async def _resolve_sleep_for_date(
    data_repo: AnalyticsDataRepository,
    user_id: UUID,
    target_date: date,
    *,
    fetched_before: datetime | None = None,
) -> tuple[Any | None, int | None, dict[str, Any] | None]:
    sleep = await data_repo.get_sleep_for_date(
        user_id,
        target_date,
        fetched_before=fetched_before,
    )
    if sleep is None:
        return None, None, None

    sleep_seconds = sleep.total_sleep_seconds if sleep.total_sleep_seconds > 0 else None
    sleep_payload = await data_repo.get_raw_payload(sleep.source_payload_id)
    if sleep_seconds is None and sleep_payload is not None:
        sleep_seconds = parse_sleep_seconds(sleep_payload)

    return sleep, sleep_seconds, sleep_payload


def _resolve_morning_rhr_for_date(
    hrv,
    sleep_payload: dict[str, Any] | None,
) -> int | None:
    if hrv is not None and hrv.resting_heart_rate is not None:
        return hrv.resting_heart_rate
    if sleep_payload is not None:
        return parse_resting_heart_rate(sleep_payload)
    return None


def _activity_has_summary(activity: LastActivityReadiness) -> bool:
    return activity.started_at is not None and (
        activity.distance_miles is not None or activity.avg_hr is not None
    )


def assess_morning_readiness(
    *,
    report_date: date,
    source_date: date,
    overnight_hrv: int | None,
    morning_rhr: int | None,
    seven_day_hrv: int | None,
    sleep_date: date | None,
    sleep_seconds: int | None,
    last_activity: LastActivityReadiness,
    metric_timestamps: list[datetime],
) -> tuple[ReadinessCompletionStatus, list[str], datetime | None]:
    missing: list[str] = []

    if overnight_hrv is None:
        missing.append("overnight_hrv")
    if morning_rhr is None:
        missing.append("morning_rhr")
    if seven_day_hrv is None:
        missing.append("seven_day_hrv")
    if (
        sleep_date not in (source_date, report_date)
        or sleep_seconds is None
        or sleep_seconds <= 0
    ):
        missing.append("sleep")
    if not _activity_has_summary(last_activity):
        missing.append("last_activity")

    if missing:
        return ReadinessCompletionStatus.PARTIAL, missing, None

    latest = max(metric_timestamps) if metric_timestamps else None
    return ReadinessCompletionStatus.COMPLETE, [], latest


def _activity_to_last_activity(activity: ActivityRecord) -> LastActivityReadiness:
    distance_miles = None
    if activity.distance_meters is not None:
        distance_miles = round(activity.distance_meters * METERS_TO_MILES, 2)

    total_ascent_ft = None
    if activity.elevation_gain_meters is not None:
        total_ascent_ft = round(activity.elevation_gain_meters * METERS_TO_FEET)

    exercise_load = None
    if activity.training_load is not None:
        exercise_load = round(activity.training_load)

    return LastActivityReadiness(
        date=activity.started_at.date().isoformat(),
        started_at=format_recorded_at(activity.started_at),
        distance_miles=distance_miles,
        total_ascent_ft=total_ascent_ft,
        avg_hr=activity.avg_heart_rate,
        exercise_load=exercise_load,
        rpe=None,
    )


class DailyGarminReadinessService:
    def __init__(self, data_repo: AnalyticsDataRepository) -> None:
        self._data_repo = data_repo

    async def get_morning_readiness_status(
        self,
        user_id: UUID,
        *,
        timezone: str,
        target_date: date | None = None,
    ) -> MorningReadinessStatusResponse:
        as_of = target_date or today_local(timezone)
        status, missing, latest = await self._assess_for_date(user_id, as_of, timezone=timezone)
        return MorningReadinessStatusResponse(
            meta=build_response_meta(timezone=timezone, data_date=as_of),
            date=as_of.isoformat(),
            status=status,
            missing_fields=missing,
            last_successful_metric_timestamp=format_recorded_at(latest) if latest else None,
        )

    async def get_daily_readiness(
        self,
        user_id: UUID,
        *,
        timezone: str,
        target_date: date | None = None,
        require_complete: bool = True,
    ) -> DailyGarminReadinessResponse:
        as_of = target_date or today_local(timezone)
        status, missing, latest = await self._assess_for_date(user_id, as_of, timezone=timezone)
        if require_complete and status == ReadinessCompletionStatus.PARTIAL:
            raise MorningReadinessIncompleteError(
                MorningReadinessStatusResponse(
                    meta=build_response_meta(timezone=timezone, data_date=as_of),
                    date=as_of.isoformat(),
                    status=status,
                    missing_fields=missing,
                    last_successful_metric_timestamp=None,
                )
            )

        return await self._build_daily_readiness_response(
            user_id,
            timezone=timezone,
            as_of=as_of,
            status=status,
            last_successful_metric_timestamp=latest,
        )

    async def _assess_for_date(
        self,
        user_id: UUID,
        as_of: date,
        *,
        timezone: str,
    ) -> tuple[ReadinessCompletionStatus, list[str], datetime | None]:
        source_date = readiness_source_date(as_of, timezone)
        fetched_before = morning_sync_fetched_before(as_of, timezone)
        hrv = await _resolve_hrv_for_report(
            self._data_repo,
            user_id,
            as_of,
            timezone,
            fetched_before=fetched_before,
        )
        sleep, sleep_seconds, sleep_payload = await _resolve_sleep_for_report(
            self._data_repo,
            user_id,
            as_of,
            timezone,
            fetched_before=fetched_before,
        )

        weekly_hrv: int | None = None
        if hrv is not None:
            hrv_payload = await self._data_repo.get_raw_payload(hrv.source_payload_id)
            if hrv_payload is not None:
                weekly_hrv = parse_weekly_hrv(hrv_payload)

        overnight_hrv = round(hrv.hrv_ms) if hrv else None
        morning_rhr = _resolve_morning_rhr_for_date(hrv, sleep_payload)

        activities = await self._data_repo.get_recent_activities(user_id, limit=1)
        last_activity = (
            _activity_to_last_activity(activities[0]) if activities else LastActivityReadiness()
        )

        metric_timestamps: list[datetime] = []
        if hrv is not None:
            metric_timestamps.append(hrv.recorded_at)
        if sleep is not None:
            metric_timestamps.append(
                datetime.combine(sleep.sleep_date, datetime.min.time(), tzinfo=UTC)
            )
        if activities:
            metric_timestamps.append(activities[0].started_at)

        return assess_morning_readiness(
            report_date=as_of,
            source_date=source_date,
            overnight_hrv=overnight_hrv,
            morning_rhr=morning_rhr,
            seven_day_hrv=weekly_hrv,
            sleep_date=sleep.sleep_date if sleep else None,
            sleep_seconds=sleep_seconds,
            last_activity=last_activity,
            metric_timestamps=metric_timestamps,
        )

    async def _build_daily_readiness_response(
        self,
        user_id: UUID,
        *,
        timezone: str,
        as_of: date,
        status: ReadinessCompletionStatus,
        last_successful_metric_timestamp: datetime | None,
    ) -> DailyGarminReadinessResponse:
        fetched_before = morning_sync_fetched_before(as_of, timezone)
        hrv = await _resolve_hrv_for_report(
            self._data_repo,
            user_id,
            as_of,
            timezone,
            fetched_before=fetched_before,
        )
        sleep, sleep_seconds, sleep_payload = await _resolve_sleep_for_report(
            self._data_repo,
            user_id,
            as_of,
            timezone,
            fetched_before=fetched_before,
        )

        body_battery = await self._data_repo.get_latest_body_battery(user_id, as_of)
        stress = await self._data_repo.get_latest_stress(user_id, as_of)
        steps = await self._data_repo.get_steps_for_date(user_id, as_of)
        activities = await self._data_repo.get_recent_activities(user_id, limit=1)

        weekly_hrv: int | None = None
        if hrv is not None:
            hrv_payload = await self._data_repo.get_raw_payload(hrv.source_payload_id)
            if hrv_payload is not None:
                weekly_hrv = parse_weekly_hrv(hrv_payload)

        body_start: int | None = None
        body_end: int | None = None
        if body_battery is not None:
            battery_payload = await self._data_repo.get_raw_payload(body_battery.source_payload_id)
            if battery_payload is not None:
                body_start, body_end = _parse_body_battery_levels(battery_payload)
            if body_end is None:
                body_end = body_battery.level
            if body_start is None and body_battery.charged is not None:
                body_start = body_battery.charged

        overnight_hrv = round(hrv.hrv_ms) if hrv else None
        morning_rhr = _resolve_morning_rhr_for_date(hrv, sleep_payload)

        return DailyGarminReadinessResponse(
            meta=build_response_meta(timezone=timezone, data_date=as_of),
            date=as_of.isoformat(),
            status=status,
            last_successful_metric_timestamp=format_recorded_at(last_successful_metric_timestamp)
            if last_successful_metric_timestamp
            else None,
            hrv=HRVReadiness(
                recorded_at=format_recorded_at(hrv.recorded_at) if hrv else None,
                overnight_hrv=overnight_hrv,
                morning_rhr=morning_rhr,
                seven_day_hrv=weekly_hrv,
            ),
            morning_rhr=morning_rhr,
            overnight_hrv=overnight_hrv,
            seven_day_hrv=weekly_hrv,
            sleep=SleepReadiness(
                sleep_date=sleep.sleep_date.isoformat() if sleep else None,
                recorded_at=format_recorded_at(
                    datetime.combine(sleep.sleep_date, datetime.min.time(), tzinfo=UTC)
                )
                if sleep
                else None,
                duration_hours=_round_hours(sleep_seconds),
                quality=sleep_quality_from_score(sleep.sleep_score if sleep else None),
            ),
            body_battery=BodyBatteryReadiness(
                recorded_at=format_recorded_at(body_battery.recorded_at) if body_battery else None,
                start_value=body_start,
                end_value=body_end,
            ),
            stress=StressReadiness(
                recorded_at=format_recorded_at(stress.recorded_at) if stress else None,
                average_overnight=stress.avg_stress if stress else None,
            ),
            steps=StepsReadiness(
                step_date=steps.step_date.isoformat() if steps else None,
                total_steps=steps.total_steps if steps else None,
                step_goal=steps.step_goal if steps else None,
                distance_miles=round(steps.distance_meters * METERS_TO_MILES, 2)
                if steps and steps.distance_meters is not None
                else None,
            ),
            last_activity=_activity_to_last_activity(activities[0])
            if activities
            else LastActivityReadiness(),
        )
