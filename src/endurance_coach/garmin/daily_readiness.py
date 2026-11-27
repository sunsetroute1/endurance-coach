"""Assemble daily Garmin readiness metrics from normalized records and raw payloads."""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from endurance_coach.analytics.repositories import AnalyticsDataRepository
from endurance_coach.api.schemas.temporal import (
    ResponseMeta,
    build_response_meta,
    format_recorded_at,
)
from endurance_coach.db.models import ActivityRecord
from endurance_coach.garmin.body_battery_parsing import extract_body_battery_day_stats
from endurance_coach.garmin.payload_parsing import (
    parse_resting_heart_rate,
    parse_sleep_seconds,
    parse_weekly_hrv,
)
from endurance_coach.garmin.readiness_dates import metric_source_date
from endurance_coach.garmin.sleep_selection import sleep_record_for_local_date
from endurance_coach.timezone_util import as_local, resolve_timezone, today_local

METERS_TO_MILES = 0.000621371
METERS_TO_FEET = 3.28084

REQUIRED_MORNING_FIELDS = (
    "overnight_hrv",
    "morning_rhr",
    "seven_day_hrv",
    "sleep",
    "last_activity",
)


class ReadinessCompletionStatus(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"


class MorningReadinessIncompleteError(Exception):
    """Raised when required morning readiness fields are not yet available."""

    def __init__(self, status: MorningReadinessStatusResponse) -> None:
        self.status = status
        super().__init__(f"Morning readiness is {status.status.value}")


class SleepReadiness(BaseModel):
    source_date: str | None = Field(
        default=None,
        description="Calendar date (YYYY-MM-DD) of the sleep row that was found.",
    )
    sleep_date: str | None = Field(
        default=None,
        description="Target-day sleep calendar date. Empty when the row is not that day.",
    )
    recorded_at: str | None = Field(
        default=None,
        description="Local midnight of the target-day sleep calendar date.",
    )
    duration_hours: float | None = None
    total_sleep_seconds: int | None = None
    sleep_score: int | None = None
    quality: str | None = None


class BodyBatteryReadiness(BaseModel):
    source_date: str | None = Field(
        default=None,
        description="Calendar date (YYYY-MM-DD) of the body battery row.",
    )
    recorded_at: str | None = Field(
        default=None,
        description="ISO-8601 timestamp for the body battery snapshot.",
    )
    start_value: int | None = None
    end_value: int | None = None


class StressReadiness(BaseModel):
    source_date: str | None = Field(
        default=None,
        description="Calendar date (YYYY-MM-DD) of the stress row.",
    )
    recorded_at: str | None = Field(
        default=None,
        description="ISO-8601 timestamp for the overnight stress average.",
    )
    average_overnight: int | None = None


class StepsReadiness(BaseModel):
    source_date: str | None = Field(
        default=None,
        description="Calendar date (YYYY-MM-DD) of the step row.",
    )
    step_date: str | None = Field(
        default=None,
        description="Calendar date (YYYY-MM-DD) for the step count.",
    )
    total_steps: int | None = None
    step_goal: int | None = None
    distance_miles: float | None = None


class HRVReadiness(BaseModel):
    source_date: str | None = Field(
        default=None,
        description="Calendar date (YYYY-MM-DD) of the HRV row.",
    )
    recorded_at: str | None = Field(
        default=None,
        description="ISO-8601 timestamp for the overnight HRV reading.",
    )
    overnight_hrv: int | None = None
    morning_rhr: int | None = None
    seven_day_hrv: int | None = None


class LastActivityReadiness(BaseModel):
    source_date: str | None = Field(
        default=None,
        description="Local calendar date (YYYY-MM-DD) when the activity started.",
    )
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


class MetricSourceDates(BaseModel):
    sleep: str | None = None
    hrv: str | None = None
    body_battery: str | None = None
    stress: str | None = None
    steps: str | None = None
    last_activity: str | None = None


class MorningReadinessStatusResponse(BaseModel):
    meta: ResponseMeta = Field(
        description="Explicit response timing so clients do not infer the current date.",
    )
    date: str = Field(description="Calendar date (YYYY-MM-DD) for this readiness snapshot.")
    status: ReadinessCompletionStatus
    missing_fields: list[str] = Field(default_factory=list)
    stale_fields: list[str] = Field(default_factory=list)
    source_dates: MetricSourceDates = Field(default_factory=MetricSourceDates)
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
    missing_fields: list[str] = Field(default_factory=list)
    stale_fields: list[str] = Field(default_factory=list)
    source_dates: MetricSourceDates = Field(default_factory=MetricSourceDates)
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


def _local_midnight_iso(day: date, timezone: str) -> str:
    return datetime.combine(day, time.min, tzinfo=resolve_timezone(timezone)).isoformat()


def _iso_date(value: date | None) -> str | None:
    return value.isoformat() if value is not None else None


async def _target_sleep(
    data_repo: AnalyticsDataRepository,
    user_id: UUID,
    target_date: date,
) -> tuple[Any | None, int | None, dict[str, Any] | None, Any | None]:
    """Sleep for the local target date, plus a different day's row when that is all we have.

    The selected row is the same one ``get_sleep_summary`` returns. A prior night
    is reported as context and is not used as the target night's duration.
    """
    sleep = await sleep_record_for_local_date(data_repo, user_id, target_date)
    if sleep is not None and sleep.sleep_date != target_date:
        return None, None, None, sleep

    if sleep is not None:
        seconds = sleep.total_sleep_seconds if sleep.total_sleep_seconds > 0 else None
        payload = await data_repo.get_raw_payload(sleep.source_payload_id)
        if seconds is None and payload is not None:
            seconds = parse_sleep_seconds(payload)
        if seconds is not None and seconds > 0:
            return sleep, seconds, payload, None
        return None, None, None, None

    finder = getattr(data_repo, "get_latest_meaningful_sleep", None)
    if finder is None:
        return None, None, None, None
    prior = await finder(user_id, target_date)
    if prior is None or prior.sleep_date == target_date or prior.total_sleep_seconds <= 0:
        return None, None, None, None
    return None, None, None, prior


async def _target_hrv(
    data_repo: AnalyticsDataRepository,
    user_id: UUID,
    target_date: date,
    timezone: str,
) -> tuple[Any | None, Any | None]:
    """HRV labeled for the local target date, and a different day's row if that is all we have."""
    hrv = await data_repo.get_hrv_for_date(user_id, target_date)
    if hrv is not None and metric_source_date(hrv.recorded_at, timezone) == target_date:
        return hrv, None

    stale = hrv if hrv is not None else None
    finder = getattr(data_repo, "get_latest_hrv", None)
    if finder is not None:
        latest = await finder(user_id, target_date)
        if latest is not None and metric_source_date(latest.recorded_at, timezone) != target_date:
            stale = latest
        elif (
            latest is not None
            and stale is None
            and metric_source_date(latest.recorded_at, timezone) == target_date
        ):
            return latest, None
    return None, stale


def _resolve_morning_rhr_for_date(
    hrv: Any | None,
    sleep_payload: dict[str, Any] | None,
) -> int | None:
    if hrv is not None and hrv.resting_heart_rate is not None:
        return int(hrv.resting_heart_rate)
    if sleep_payload is not None:
        parsed = parse_resting_heart_rate(sleep_payload)
        return int(parsed) if parsed is not None else None
    return None


def _activity_has_summary(activity: LastActivityReadiness) -> bool:
    return activity.started_at is not None and (
        activity.distance_miles is not None or activity.avg_hr is not None
    )


def assess_morning_readiness(
    *,
    report_date: date,
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
    if sleep_date != report_date or sleep_seconds is None or sleep_seconds <= 0:
        missing.append("sleep")
    if not _activity_has_summary(last_activity):
        missing.append("last_activity")

    if missing:
        return ReadinessCompletionStatus.PARTIAL, missing, None

    latest = max(metric_timestamps) if metric_timestamps else None
    return ReadinessCompletionStatus.COMPLETE, [], latest


def _activity_to_last_activity(
    activity: ActivityRecord,
    *,
    timezone: str,
) -> LastActivityReadiness:
    distance_miles = None
    if activity.distance_meters is not None:
        distance_miles = round(activity.distance_meters * METERS_TO_MILES, 2)

    total_ascent_ft = None
    if activity.elevation_gain_meters is not None:
        total_ascent_ft = round(activity.elevation_gain_meters * METERS_TO_FEET)

    exercise_load = None
    if activity.training_load is not None:
        exercise_load = round(activity.training_load)

    started = as_local(activity.started_at, timezone)
    local_date = started.date().isoformat()
    return LastActivityReadiness(
        source_date=local_date,
        date=local_date,
        started_at=started.isoformat(),
        distance_miles=distance_miles,
        total_ascent_ft=total_ascent_ft,
        avg_hr=activity.avg_heart_rate,
        exercise_load=exercise_load,
        rpe=None,
    )


def _status_from_response(response: DailyGarminReadinessResponse) -> MorningReadinessStatusResponse:
    return MorningReadinessStatusResponse(
        meta=response.meta,
        date=response.date,
        status=response.status,
        missing_fields=list(response.missing_fields),
        stale_fields=list(response.stale_fields),
        source_dates=response.source_dates,
        last_successful_metric_timestamp=response.last_successful_metric_timestamp,
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
        response = await self._assemble(user_id, timezone=timezone, target_date=target_date)
        return _status_from_response(response)

    async def get_daily_readiness(
        self,
        user_id: UUID,
        *,
        timezone: str,
        target_date: date | None = None,
        require_complete: bool = True,
    ) -> DailyGarminReadinessResponse:
        response = await self._assemble(user_id, timezone=timezone, target_date=target_date)
        if require_complete and response.status == ReadinessCompletionStatus.PARTIAL:
            raise MorningReadinessIncompleteError(_status_from_response(response))
        return response

    async def _assemble(
        self,
        user_id: UUID,
        *,
        timezone: str,
        target_date: date | None,
    ) -> DailyGarminReadinessResponse:
        as_of = target_date or today_local(timezone)
        sleep, sleep_seconds, sleep_payload, stale_sleep = await _target_sleep(
            self._data_repo,
            user_id,
            as_of,
        )
        hrv, stale_hrv = await _target_hrv(self._data_repo, user_id, as_of, timezone)

        weekly_hrv: int | None = None
        if hrv is not None:
            hrv_payload = await self._data_repo.get_raw_payload(hrv.source_payload_id)
            if hrv_payload is not None:
                weekly_hrv = parse_weekly_hrv(hrv_payload)

        overnight_hrv = round(hrv.hrv_ms) if hrv else None
        morning_rhr = _resolve_morning_rhr_for_date(hrv, sleep_payload)

        body_battery = await self._data_repo.get_latest_body_battery(user_id, as_of)
        stress = await self._data_repo.get_latest_stress(user_id, as_of)
        steps = await self._data_repo.get_steps_for_date(user_id, as_of)
        activities = await self._data_repo.get_recent_activities(user_id, limit=1)
        last_activity = (
            _activity_to_last_activity(activities[0], timezone=timezone)
            if activities
            else LastActivityReadiness()
        )

        battery_source = (
            metric_source_date(body_battery.recorded_at, timezone) if body_battery else None
        )
        battery_current = body_battery is not None and battery_source == as_of
        stress_source = metric_source_date(stress.recorded_at, timezone) if stress else None
        stress_current = stress is not None and stress_source == as_of
        steps_current = steps is not None and steps.step_date == as_of

        body_start: int | None = None
        body_end: int | None = None
        battery_recorded_at: str | None = None
        stress_recorded_at: str | None = None
        stress_average: int | None = None
        if battery_current and body_battery is not None:
            battery_recorded_at = format_recorded_at(body_battery.recorded_at)
            battery_payload = await self._data_repo.get_raw_payload(body_battery.source_payload_id)
            if battery_payload is not None:
                body_start, body_end = _parse_body_battery_levels(battery_payload)
            if body_end is None:
                body_end = body_battery.level
            if body_start is None and body_battery.charged is not None:
                body_start = body_battery.charged
        if stress_current and stress is not None:
            stress_recorded_at = format_recorded_at(stress.recorded_at)
            stress_average = stress.avg_stress

        metric_timestamps: list[datetime] = []
        if hrv is not None:
            metric_timestamps.append(hrv.recorded_at)
        if sleep is not None:
            metric_timestamps.append(datetime.combine(sleep.sleep_date, time.min, tzinfo=UTC))
        if activities:
            metric_timestamps.append(activities[0].started_at)

        status, missing, latest = assess_morning_readiness(
            report_date=as_of,
            overnight_hrv=overnight_hrv,
            morning_rhr=morning_rhr,
            seven_day_hrv=weekly_hrv,
            sleep_date=sleep.sleep_date if sleep else None,
            sleep_seconds=sleep_seconds,
            last_activity=last_activity,
            metric_timestamps=metric_timestamps,
        )

        stale: list[str] = []
        if stale_sleep is not None:
            stale.append("sleep")
        if stale_hrv is not None:
            stale.append("overnight_hrv")
            stale.append("seven_day_hrv")
        if morning_rhr is None and (stale_hrv is not None or stale_sleep is not None):
            stale.append("morning_rhr")
        if body_battery is not None and not battery_current:
            stale.append("body_battery")
        if stress is not None and not stress_current:
            stale.append("stress")
        if steps is not None and not steps_current:
            stale.append("steps")

        hrv_source: date | None = None
        if hrv is not None:
            hrv_source = metric_source_date(hrv.recorded_at, timezone)
        elif stale_hrv is not None:
            hrv_source = metric_source_date(stale_hrv.recorded_at, timezone)
        sleep_source: date | None = None
        if sleep is not None:
            sleep_source = sleep.sleep_date
        elif stale_sleep is not None:
            sleep_source = stale_sleep.sleep_date
        source_dates = MetricSourceDates(
            sleep=_iso_date(sleep_source),
            hrv=_iso_date(hrv_source),
            body_battery=_iso_date(battery_source),
            stress=_iso_date(stress_source),
            steps=_iso_date(steps.step_date) if steps is not None else None,
            last_activity=last_activity.source_date,
        )

        return DailyGarminReadinessResponse(
            meta=build_response_meta(timezone=timezone, data_date=as_of),
            date=as_of.isoformat(),
            status=status,
            missing_fields=missing,
            stale_fields=stale,
            source_dates=source_dates,
            last_successful_metric_timestamp=format_recorded_at(latest) if latest else None,
            hrv=HRVReadiness(
                source_date=_iso_date(hrv_source),
                recorded_at=format_recorded_at(hrv.recorded_at) if hrv else None,
                overnight_hrv=overnight_hrv,
                morning_rhr=morning_rhr,
                seven_day_hrv=weekly_hrv,
            ),
            morning_rhr=morning_rhr,
            overnight_hrv=overnight_hrv,
            seven_day_hrv=weekly_hrv,
            sleep=SleepReadiness(
                source_date=_iso_date(sleep_source),
                sleep_date=sleep.sleep_date.isoformat() if sleep else None,
                recorded_at=_local_midnight_iso(sleep.sleep_date, timezone) if sleep else None,
                duration_hours=_round_hours(sleep_seconds),
                total_sleep_seconds=sleep_seconds,
                sleep_score=sleep.sleep_score if sleep else None,
                quality=sleep_quality_from_score(sleep.sleep_score if sleep else None),
            ),
            body_battery=BodyBatteryReadiness(
                source_date=_iso_date(battery_source),
                recorded_at=battery_recorded_at,
                start_value=body_start,
                end_value=body_end,
            ),
            stress=StressReadiness(
                source_date=_iso_date(stress_source),
                recorded_at=stress_recorded_at,
                average_overnight=stress_average,
            ),
            steps=StepsReadiness(
                source_date=_iso_date(steps.step_date) if steps is not None else None,
                step_date=steps.step_date.isoformat() if steps_current and steps else None,
                total_steps=steps.total_steps if steps_current and steps else None,
                step_goal=steps.step_goal if steps_current and steps else None,
                distance_miles=round(steps.distance_meters * METERS_TO_MILES, 2)
                if steps_current and steps and steps.distance_meters is not None
                else None,
            ),
            last_activity=last_activity,
        )
