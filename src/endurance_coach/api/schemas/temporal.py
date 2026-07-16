"""Explicit date/time fields for API responses."""

from __future__ import annotations

from datetime import UTC, date, datetime

from pydantic import BaseModel, Field

from endurance_coach.timezone_util import now_local


class ResponseMeta(BaseModel):
    """When the response was built, in the user's configured local timezone."""

    response_generated_at: datetime = Field(
        description="ISO-8601 timestamp in the configured local timezone.",
    )
    timezone: str = Field(
        description="IANA timezone used for response_generated_at and data_date.",
    )
    data_date: str | None = Field(
        default=None,
        description="Calendar date (YYYY-MM-DD) in the configured local timezone.",
    )


def build_response_meta(*, timezone: str, data_date: date | None = None) -> ResponseMeta:
    local_now = now_local(timezone)
    resolved_date = data_date or local_now.date()
    return ResponseMeta(
        response_generated_at=local_now,
        timezone=timezone,
        data_date=resolved_date.isoformat(),
    )


def format_recorded_at(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.isoformat()
