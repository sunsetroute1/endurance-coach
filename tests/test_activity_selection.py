"""Tests for primary activity selection."""

from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace
from uuid import uuid4

from endurance_coach.analytics.activity_selection import select_primary_activity


def _activity(
    *,
    name: str,
    started_at: datetime,
    duration_seconds: int,
    distance_meters: float,
    elevation_gain_meters: float | None = None,
    provider: str = "garmin",
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        name=name,
        started_at=started_at,
        duration_seconds=duration_seconds,
        distance_meters=distance_meters,
        elevation_gain_meters=elevation_gain_meters,
        provider=provider,
    )


def test_select_primary_activity_prefers_wheeler_peak_effort() -> None:
    target_date = date(2025, 11, 1)
    activities = [
        _activity(
            name="Running",
            started_at=datetime(2025, 11, 1, 22, 33, tzinfo=UTC),
            duration_seconds=900,
            distance_meters=2216.75,
        ),
        _activity(
            name="Taos County Trail Running",
            started_at=datetime(2025, 11, 1, 13, 2, 4, tzinfo=UTC),
            duration_seconds=7200,
            distance_meters=13055.0,
            elevation_gain_meters=750.0,
        ),
        _activity(
            name="Running",
            started_at=datetime(2025, 11, 1, 19, 2, 4, tzinfo=UTC),
            duration_seconds=7200,
            distance_meters=13055.0,
            elevation_gain_meters=750.0,
        ),
    ]

    selected = select_primary_activity(activities, target_date, timezone="America/Denver")

    assert selected is not None
    assert selected.name == "Taos County Trail Running"
    assert selected.distance_meters == 13055.0
    assert selected.elevation_gain_meters == 750.0


def test_select_primary_activity_uses_local_calendar_day() -> None:
    target_date = date(2025, 11, 1)
    activities = [
        _activity(
            name="Late Night Run",
            started_at=datetime(2025, 11, 2, 5, 30, tzinfo=UTC),
            duration_seconds=3600,
            distance_meters=10000.0,
        ),
        _activity(
            name="Evening Run",
            started_at=datetime(2025, 11, 2, 4, 30, tzinfo=UTC),
            duration_seconds=1800,
            distance_meters=5000.0,
        ),
    ]

    selected = select_primary_activity(activities, target_date, timezone="America/Denver")

    assert selected is not None
    assert selected.name == "Late Night Run"
