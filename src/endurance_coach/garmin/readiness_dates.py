"""Readiness report date semantics for Garmin morning metrics."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

from endurance_coach.timezone_util import resolve_timezone, today_local

# Local time after the 9:00 AM automated sync when the morning snapshot freezes.
MORNING_SYNC_CUTOFF_HOUR = 9
MORNING_SYNC_CUTOFF_MINUTE = 1


def readiness_source_date(report_date: date, timezone: str = "America/Denver") -> date:
    """Return the prior local calendar date that holds overnight sleep/HRV for a report."""
    _ = timezone  # report_date is already the athlete-local decision date
    return report_date - timedelta(days=1)


def morning_sync_cutoff(report_date: date, timezone: str) -> datetime:
    """UTC instant for the last moment same-day morning sync data counts (9:01 AM local)."""
    tz = resolve_timezone(timezone)
    local_cutoff = datetime.combine(
        report_date,
        time(hour=MORNING_SYNC_CUTOFF_HOUR, minute=MORNING_SYNC_CUTOFF_MINUTE),
        tzinfo=tz,
    )
    return local_cutoff.astimezone(UTC)


def morning_cutoff_applies(
    report_date: date,
    timezone: str,
    *,
    now: datetime | None = None,
) -> bool:
    """Freeze today's morning readiness after 9:01 AM local; ignore later syncs."""
    today = today_local(timezone)
    if report_date != today:
        return False

    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)

    cutoff = morning_sync_cutoff(report_date, timezone)
    return current >= cutoff


def morning_sync_fetched_before(
    report_date: date,
    timezone: str,
    *,
    now: datetime | None = None,
) -> datetime | None:
    """Return payload fetched_at ceiling when the morning cutoff is active."""
    if not morning_cutoff_applies(report_date, timezone, now=now):
        return None
    return morning_sync_cutoff(report_date, timezone)


def local_date_from_timestamp(value: datetime, timezone: str) -> date:
    """Map a real UTC instant to the athlete's local calendar date."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(resolve_timezone(timezone)).date()


def metric_source_date(recorded_at: datetime, timezone: str) -> date:
    """Calendar date a stored wellness row belongs to.

    Garmin daily rows are written at 00:00 UTC on the payload's local calendar
    date. That stamp is a date label: converting it to America/Denver lands on
    the previous evening, so an exact UTC midnight keeps the UTC date.

    Any other timestamp is a real instant. Its calendar date is the local date
    in ``timezone``, not the UTC date of the clock reading.
    """
    if recorded_at.tzinfo is None:
        recorded_at = recorded_at.replace(tzinfo=UTC)
    utc = recorded_at.astimezone(UTC)
    if utc.hour == utc.minute == utc.second == utc.microsecond == 0:
        return utc.date()
    return local_date_from_timestamp(utc, timezone)


def in_morning_sync_window(timezone: str, *, now: datetime | None = None) -> bool:
    """True during the 9:00-9:01 AM local window for post-manual-sync polling."""
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    local_now = current.astimezone(resolve_timezone(timezone))
    return (
        local_now.hour == MORNING_SYNC_CUTOFF_HOUR
        and local_now.minute <= MORNING_SYNC_CUTOFF_MINUTE
    )
