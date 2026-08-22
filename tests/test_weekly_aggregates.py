"""Tests for Monday–Sunday weekly aggregate helpers."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from endurance_coach.analytics.weekly import (
    MAX_WEEKLY_AGGREGATES_WEEKS,
    aggregate_activity_week,
    aggregate_hrv_week,
    aggregate_running_week,
    aggregate_sleep_week,
    aggregate_training_week,
    build_weekly_aggregate_row,
    group_by_week,
    is_running_activity,
    iter_week_starts,
    iter_week_starts_between,
    monday_of,
    resolve_week_window,
    week_end,
)


class StubActivity:
    def __init__(
        self,
        *,
        started_at: datetime,
        activity_type: str = "running",
        duration_seconds: int = 3600,
        distance_meters: float = 10000.0,
        elevation_gain_meters: float = 100.0,
        training_load: float = 50.0,
        avg_heart_rate: int = 140,
    ) -> None:
        self.started_at = started_at
        self.activity_type = activity_type
        self.duration_seconds = duration_seconds
        self.distance_meters = distance_meters
        self.elevation_gain_meters = elevation_gain_meters
        self.training_load = training_load
        self.avg_heart_rate = avg_heart_rate


class StubHRV:
    def __init__(self, recorded_at: datetime, hrv_ms: float = 48.0, resting_heart_rate: int = 52) -> None:
        self.recorded_at = recorded_at
        self.hrv_ms = hrv_ms
        self.resting_heart_rate = resting_heart_rate


class StubSleep:
    def __init__(self, sleep_date: date, total_sleep_seconds: int = 7 * 3600, sleep_score: int = 82) -> None:
        self.sleep_date = sleep_date
        self.total_sleep_seconds = total_sleep_seconds
        self.sleep_score = sleep_score


def test_monday_of_and_week_end() -> None:
    assert monday_of(date(2026, 7, 17)) == date(2026, 7, 13)
    assert week_end(date(2026, 7, 13)) == date(2026, 7, 19)


def test_iter_week_starts() -> None:
    starts = iter_week_starts(date(2026, 7, 17), weeks=3)
    assert starts == [date(2026, 6, 29), date(2026, 7, 6), date(2026, 7, 13)]


def test_iter_week_starts_between() -> None:
    starts = iter_week_starts_between(date(2022, 3, 14), date(2022, 3, 20))
    assert starts == [date(2022, 3, 14)]


def test_resolve_week_window_by_date_range() -> None:
    week_starts, range_start, range_end, week_count = resolve_week_window(
        end_date=date(2022, 3, 20),
        start_date=date(2022, 3, 1),
    )
    assert week_count == 3
    assert range_start == date(2022, 2, 28)
    assert range_end == date(2022, 3, 20)
    assert week_starts == [date(2022, 2, 28), date(2022, 3, 7), date(2022, 3, 14)]


def test_resolve_week_window_caps_at_max_weeks() -> None:
    week_starts, _, _, week_count = resolve_week_window(
        end_date=date(2026, 7, 17),
        start_date=date(2016, 1, 1),
        max_weeks=4,
    )
    assert week_count == 4
    assert len(week_starts) == 4
    assert week_starts[0] == date(2015, 12, 28)
    assert MAX_WEEKLY_AGGREGATES_WEEKS == 520


def test_aggregate_activity_week_includes_total_fields() -> None:
    week_start = date(2026, 7, 13)
    activities = [
        StubActivity(started_at=datetime.combine(week_start, datetime.min.time(), tzinfo=UTC)),
        StubActivity(
            started_at=datetime.combine(week_start + timedelta(days=1), datetime.min.time(), tzinfo=UTC),
            duration_seconds=1800,
            distance_meters=5000.0,
            elevation_gain_meters=50.0,
            training_load=25.0,
            avg_heart_rate=150,
        ),
    ]
    result = aggregate_activity_week(activities)  # type: ignore[arg-type]
    assert result["count"] == 2
    assert result["duration_s"] == 5400
    assert result["duration_h"] == 1.5
    assert result["distance_m"] == 15000.0
    assert result["distance_mi"] == 9.32
    assert result["elevation_m"] == 150.0
    assert result["elevation_ft"] == 492.1
    assert result["training_load"] == 75.0
    assert result["avg_hr"] == 145


def test_aggregate_running_week_excludes_non_runs() -> None:
    week_start = date(2026, 7, 13)
    runs_and_rides = [
        StubActivity(
            started_at=datetime.combine(week_start, datetime.min.time(), tzinfo=UTC),
            activity_type="running",
            distance_meters=16093.4,
            elevation_gain_meters=328.0,
        ),
        StubActivity(
            started_at=datetime.combine(week_start + timedelta(days=1), datetime.min.time(), tzinfo=UTC),
            activity_type="cycling",
            distance_meters=5000.0,
        ),
    ]
    total = aggregate_activity_week(runs_and_rides)  # type: ignore[arg-type]
    running = aggregate_running_week(runs_and_rides)  # type: ignore[arg-type]
    assert running["count"] == 1
    assert running["distance_mi"] == 10.0
    assert running["duration_h"] == 1.0
    assert running["elevation_ft"] == 1076.1
    assert total["distance_mi"] > running["distance_mi"]
    assert is_running_activity("treadmill_running")
    assert not is_running_activity("cycling")


def test_aggregate_hrv_week_includes_rhr_min_and_avg() -> None:
    records = [
        StubHRV(datetime(2026, 7, 13, 6, tzinfo=UTC), hrv_ms=40.0, resting_heart_rate=55),
        StubHRV(datetime(2026, 7, 14, 6, tzinfo=UTC), hrv_ms=50.0, resting_heart_rate=49),
    ]
    result = aggregate_hrv_week(records)  # type: ignore[arg-type]
    assert result["readings"] == 2
    assert result["avg_ms"] == 45.0
    assert result["min_ms"] == 40.0
    assert result["max_ms"] == 50.0
    assert result["avg_rhr"] == 52
    assert result["min_rhr"] == 49


def test_aggregate_sleep_week() -> None:
    week_start = date(2026, 7, 13)
    records = [
        StubSleep(week_start, total_sleep_seconds=8 * 3600, sleep_score=80),
        StubSleep(week_start + timedelta(days=1), total_sleep_seconds=6 * 3600, sleep_score=70),
    ]
    result = aggregate_sleep_week(records)  # type: ignore[arg-type]
    assert result["nights"] == 2
    assert result["avg_hours"] == 7.0
    assert result["avg_score"] == 75.0


def test_aggregate_training_week_exposes_acute_and_chronic_load() -> None:
    week_start = date(2026, 7, 13)
    result = aggregate_training_week(
        [],
        {week_start + timedelta(days=offset): 10.0 for offset in range(7)},
        week_start,
    )
    assert result["weekly_load"] == 70.0
    assert result["chronic_load"] == result["ctl"]
    assert result["acute_load"] == result["atl"]
    assert "tsb" in result
    assert "acwr" in result


def test_group_by_week() -> None:
    activities = [
        StubActivity(started_at=datetime(2026, 7, 13, 8, tzinfo=UTC)),
        StubActivity(started_at=datetime(2026, 7, 20, 8, tzinfo=UTC)),
    ]
    grouped = group_by_week(activities, lambda record: record.started_at.date())
    assert len(grouped[date(2026, 7, 13)]) == 1
    assert len(grouped[date(2026, 7, 20)]) == 1


def test_build_weekly_aggregate_row_includes_all_blocks() -> None:
    week_start = date(2026, 7, 13)
    row = build_weekly_aggregate_row(
        week_start,
        activities=[],
        hrv=[],
        sleep=[],
        steps=[],
        stress=[],
        body_battery=[],
        readiness=[],
        daily_loads={week_start + timedelta(days=offset): 10.0 for offset in range(7)},
    )
    assert row["week_start"] == "2026-07-13"
    assert "running" in row
    assert "activities" in row
    assert row["sleep"]["nights"] == 0
    assert row["training"]["chronic_load"] == row["training"]["ctl"]
