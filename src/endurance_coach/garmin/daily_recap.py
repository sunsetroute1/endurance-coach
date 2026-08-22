"""Parse Garmin evening daily recap fields from stored daily summary payloads."""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from pydantic import BaseModel, Field

from endurance_coach.analytics.repositories import AnalyticsDataRepository
from endurance_coach.processor.parsing import as_float, as_int

STRESS_QUALIFIER_MESSAGES: dict[str, str] = {
    "CALM": "Your day was calm.",
    "BALANCED": "Your day was balanced.",
    "STRESSFUL": "You had a stressful day.",
    "VERY_STRESSFUL": "You had a very stressful day.",
    "STRESSFUL_AWAKE": "You had a stressful day while awake.",
    "VERY_STRESSFUL_AWAKE": "You had a very stressful day while awake.",
    "CALM_AWAKE": "Your waking hours were calm.",
    "BALANCED_AWAKE": "Your waking hours were balanced.",
}

BODY_BATTERY_FEEDBACK_HINTS: dict[str, str] = {
    "DAY_STRESSFUL": "Stress drained your body battery during the day.",
    "DAY_NOT_STRESS_DATA_AND_INACTIVE": "You were mostly inactive today with limited stress data.",
    "SLEEP_TIME_PASSED_STRESSFUL": "Your day ended with elevated stress levels.",
    "SLEEP_PREPARATION": "Your body battery suggested winding down for sleep.",
    "INTENSIVE_EXERCISE": "Hard training affected your recovery balance.",
    "INACTIVE": "Low activity levels stood out today.",
    "RECOVERING": "Your body was still recovering from recent training.",
}


class BodyBatteryFeedbackDetail(BaseModel):
    body_battery_level: str | None = None
    feedback_short: str | None = None
    feedback_long: str | None = None
    event_time_gmt: str | None = None
    hint: str | None = None


class DailyRecapResponse(BaseModel):
    date: str
    timezone: str
    synced_at: str | None = None
    is_day_complete: bool = False
    recap_message: str | None = Field(
        default=None,
        description="Human-readable recap synthesized from Garmin daily summary codes.",
    )
    wellness_description: str | None = Field(
        default=None,
        description="Garmin prose recap when the API provides wellnessDescription.",
    )
    stress_qualifier: str | None = None
    average_stress_level: int | None = None
    max_stress_level: int | None = None
    stress_duration_min: int | None = None
    rest_stress_duration_min: int | None = None
    total_steps: int | None = None
    total_calories: int | None = None
    active_calories: int | None = None
    active_minutes: int | None = None
    body_battery_feedback: BodyBatteryFeedbackDetail | None = None
    end_of_day_body_battery_feedback: BodyBatteryFeedbackDetail | None = None


def _feedback_hint(feedback_type: str | None) -> str | None:
    if not feedback_type:
        return None
    normalized = feedback_type.upper()
    for prefix, hint in BODY_BATTERY_FEEDBACK_HINTS.items():
        if prefix in normalized:
            return hint
    return None


def _parse_feedback(raw: dict[str, Any] | None) -> BodyBatteryFeedbackDetail | None:
    if not isinstance(raw, dict):
        return None
    short = raw.get("feedbackShortType")
    if isinstance(short, str):
        short = short.strip() or None
    long = raw.get("feedbackLongType")
    if isinstance(long, str):
        long = long.strip() or None
    if not any((short, long, raw.get("bodyBatteryLevel"))):
        return None
    return BodyBatteryFeedbackDetail(
        body_battery_level=raw.get("bodyBatteryLevel"),
        feedback_short=short,
        feedback_long=long,
        event_time_gmt=raw.get("eventTimestampGmt"),
        hint=_feedback_hint(short or long),
    )


def synthesize_recap_message(
    *,
    stress_qualifier: str | None,
    wellness_description: str | None,
    body_battery_feedback: BodyBatteryFeedbackDetail | None,
    end_of_day_feedback: BodyBatteryFeedbackDetail | None,
) -> str | None:
    if wellness_description:
        return wellness_description.strip()

    parts: list[str] = []
    if stress_qualifier and stress_qualifier.upper() != "UNKNOWN":
        parts.append(
            STRESS_QUALIFIER_MESSAGES.get(
                stress_qualifier.upper(),
                f"Garmin classified your day as {stress_qualifier.replace('_', ' ').lower()}.",
            )
        )

    for feedback in (end_of_day_feedback, body_battery_feedback):
        if feedback and feedback.hint and feedback.hint not in parts:
            parts.append(feedback.hint)

    if not parts:
        return None
    return " ".join(parts)


def parse_daily_recap(data: dict[str, Any]) -> dict[str, Any]:
    stress_duration = as_int(data.get("stressDuration"))
    rest_stress_duration = as_int(data.get("restStressDuration"))
    active_seconds = as_int(data.get("activeSeconds"))
    stress_qualifier = data.get("stressQualifier")
    if isinstance(stress_qualifier, str):
        stress_qualifier = stress_qualifier.strip() or None

    wellness_description = data.get("wellnessDescription")
    if isinstance(wellness_description, str):
        wellness_description = wellness_description.strip() or None

    body_battery_feedback = _parse_feedback(data.get("bodyBatteryDynamicFeedbackEvent"))
    end_of_day_feedback = _parse_feedback(data.get("endOfDayBodyBatteryDynamicFeedbackEvent"))

    return {
        "wellness_description": wellness_description,
        "stress_qualifier": stress_qualifier,
        "average_stress_level": as_int(data.get("averageStressLevel")),
        "max_stress_level": as_int(data.get("maxStressLevel")),
        "stress_duration_min": round(stress_duration / 60) if stress_duration else None,
        "rest_stress_duration_min": round(rest_stress_duration / 60)
        if rest_stress_duration
        else None,
        "total_steps": as_int(data.get("totalSteps")),
        "total_calories": as_int(as_float(data.get("totalKilocalories"))),
        "active_calories": as_int(as_float(data.get("activeKilocalories"))),
        "active_minutes": round(active_seconds / 60) if active_seconds else None,
        "body_battery_feedback": body_battery_feedback,
        "end_of_day_body_battery_feedback": end_of_day_feedback,
        "is_day_complete": bool(stress_qualifier and stress_qualifier.upper() != "UNKNOWN"),
        "recap_message": synthesize_recap_message(
            stress_qualifier=stress_qualifier,
            wellness_description=wellness_description,
            body_battery_feedback=body_battery_feedback,
            end_of_day_feedback=end_of_day_feedback,
        ),
    }


class DailyRecapService:
    def __init__(
        self,
        data_repo: AnalyticsDataRepository,
        *,
        timezone: str = "America/Denver",
    ) -> None:
        self._data_repo = data_repo
        self._timezone = timezone

    async def get_daily_recap(
        self,
        user_id: UUID,
        *,
        target_date: date | None = None,
    ) -> DailyRecapResponse:
        as_of = target_date or date.today()
        stored = await self._data_repo.get_latest_raw_payload_by_record(
            user_id,
            resource_type="steps",
            provider_record_id=as_of.isoformat(),
        )
        if stored is None:
            raise HTTPException(status_code=404, detail="Daily recap not found for date")

        payload = stored.payload
        data = payload.get("data", payload)
        if not isinstance(data, dict):
            raise HTTPException(status_code=404, detail="Daily recap payload invalid")

        parsed = parse_daily_recap(data)
        synced_at = None
        if stored.fetched_at is not None:
            synced_at = stored.fetched_at.astimezone(ZoneInfo(self._timezone)).isoformat()

        return DailyRecapResponse(
            date=as_of.isoformat(),
            timezone=self._timezone,
            synced_at=synced_at,
            **parsed,
        )
