"""Tests for trail effort ranking."""

from __future__ import annotations

from datetime import UTC, datetime

from endurance_coach.analytics.trail_efforts import (
    compute_rank_score,
    is_trail_activity,
    rank_trail_efforts,
)


class StubTrailActivity:
    def __init__(self, **kwargs: object) -> None:
        self.name = kwargs.get("name", "Trail Run")
        self.activity_type = kwargs.get("activity_type", "trail_running")
        self.started_at = kwargs.get("started_at", datetime(2026, 7, 10, 8, tzinfo=UTC))
        self.duration_seconds = kwargs.get("duration_seconds", 3600)
        self.distance_meters = kwargs.get("distance_meters", 10000.0)
        self.elevation_gain_meters = kwargs.get("elevation_gain_meters", 500.0)
        self.training_load = kwargs.get("training_load", 80.0)
        self.avg_heart_rate = kwargs.get("avg_heart_rate", 145)
        self.avg_pace_sec_per_km = kwargs.get("avg_pace_sec_per_km", 360.0)


def test_is_trail_activity() -> None:
    assert is_trail_activity(StubTrailActivity(activity_type="trail_running"))
    assert is_trail_activity(StubTrailActivity(name="Morning Trail", activity_type="running"))
    assert not is_trail_activity(StubTrailActivity(name="Road Run", activity_type="running"))


def test_rank_by_vert_duration() -> None:
    steep = StubTrailActivity(elevation_gain_meters=1000.0, duration_seconds=3600)
    flat = StubTrailActivity(elevation_gain_meters=200.0, duration_seconds=3600)
    assert compute_rank_score(steep, "vert_duration") > compute_rank_score(flat, "vert_duration")


def test_rank_by_training_load() -> None:
    hard = StubTrailActivity(training_load=120.0)
    easy = StubTrailActivity(training_load=40.0)
    assert compute_rank_score(hard, "training_load") > compute_rank_score(easy, "training_load")


def test_rank_trail_efforts_returns_top_n() -> None:
    activities = [
        StubTrailActivity(name="Easy trail", elevation_gain_meters=100.0, training_load=30.0),
        StubTrailActivity(name="Big vert", elevation_gain_meters=1500.0, training_load=95.0),
        StubTrailActivity(name="Road run", activity_type="running", elevation_gain_meters=2000.0),
    ]
    result = rank_trail_efforts(activities, rank_by="vert_duration", limit=1)
    assert len(result) == 1
    assert result[0]["name"] == "Big vert"
    assert result[0]["rank_by"] == "vert_duration"
    assert "rank_score" in result[0]
