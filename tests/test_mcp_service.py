"""Tests for MCP service tool implementations."""

from datetime import UTC, date, datetime
from uuid import uuid4

import pytest

from endurance_coach.coach.service import build_coach_service
from endurance_coach.config import Settings
from endurance_coach.domain.enums import MetricFamily
from endurance_coach.domain.models import MetricSnapshot, MetricValue
from endurance_coach.mcp.service import CoachMCPService


class StubActivity:
    def __init__(self, **kwargs: object) -> None:
        self.id = kwargs.get("id", uuid4())
        self.provider = kwargs.get("provider", "garmin")
        self.name = kwargs.get("name", "Morning Run")
        self.activity_type = kwargs.get("activity_type", "running")
        self.started_at = kwargs.get("started_at", datetime.now(UTC))
        self.duration_seconds = kwargs.get("duration_seconds", 3600)
        self.distance_meters = kwargs.get("distance_meters", 10000.0)
        self.avg_heart_rate = kwargs.get("avg_heart_rate", 145)
        self.max_heart_rate = kwargs.get("max_heart_rate", 165)
        self.avg_pace_sec_per_km = kwargs.get("avg_pace_sec_per_km", 360.0)
        self.elevation_gain_meters = kwargs.get("elevation_gain_meters", 120.0)
        self.training_load = kwargs.get("training_load", 85.0)


class StubSleep:
    def __init__(self, sleep_date: date) -> None:
        self.sleep_date = sleep_date
        self.provider = "garmin"
        self.total_sleep_seconds = 7 * 3600
        self.deep_sleep_seconds = 3600
        self.rem_sleep_seconds = 5400
        self.light_sleep_seconds = 14400
        self.awake_seconds = 1800
        self.sleep_score = 82


class StubHRV:
    def __init__(self, recorded_at: datetime) -> None:
        self.recorded_at = recorded_at
        self.provider = "garmin"
        self.hrv_ms = 48.0
        self.resting_heart_rate = 52
        self.baseline_ms = 50.0


class StubReadiness:
    def __init__(self, recorded_at: datetime) -> None:
        self.recorded_at = recorded_at
        self.provider = "garmin"
        self.readiness_score = 74
        self.hrv_component = 78
        self.sleep_component = 70
        self.recovery_component = 75


class StubDataRepo:
    def __init__(self) -> None:
        self.activities = [StubActivity()]
        self.sleep = {date.today(): StubSleep(date.today())}
        self.hrv = [StubHRV(datetime.now(UTC))]
        self.readiness = StubReadiness(datetime.now(UTC))

    async def get_activities_since(self, user_id, since, *, limit: int = 100):
        return self.activities

    async def get_sleep_for_date(self, user_id, sleep_date):
        return self.sleep.get(sleep_date)

    async def get_sleep_by_date(self, user_id, end_date, *, window_days: int = 14):
        return {day: record.total_sleep_seconds for day, record in self.sleep.items()}

    async def get_hrv_in_window(self, user_id, end_date, *, window_days: int = 14):
        return self.hrv

    async def get_latest_readiness(self, user_id, as_of):
        return self.readiness


class StubMetricEngine:
    def __init__(self) -> None:
        self._snapshots: dict[MetricFamily, MetricSnapshot] = {}
        now = datetime.now(UTC)
        user_id = uuid4()
        self._snapshots[MetricFamily.LOAD] = MetricSnapshot(
            user_id=user_id,
            family=MetricFamily.LOAD,
            as_of=now,
            metrics=(
                MetricValue(key="ctl", value=60, unit="load", computed_at=now),
                MetricValue(key="atl", value=70, unit="load", computed_at=now),
                MetricValue(key="tsb", value=-10, unit="load", computed_at=now),
                MetricValue(key="acwr", value=1.17, unit="ratio", computed_at=now),
                MetricValue(key="weekly_load", value=350, unit="load", computed_at=now),
                MetricValue(
                    key="weekly_load_progression",
                    value=5,
                    unit="percent",
                    computed_at=now,
                ),
                MetricValue(key="monotony", value=1.2, unit="ratio", computed_at=now),
                MetricValue(key="strain", value=420, unit="load", computed_at=now),
            ),
        )
        self._snapshots[MetricFamily.RECOVERY] = MetricSnapshot(
            user_id=user_id,
            family=MetricFamily.RECOVERY,
            as_of=now,
            metrics=(
                MetricValue(key="recovery_score", value=65, unit="score", computed_at=now),
                MetricValue(key="fatigue_score", value=45, unit="score", computed_at=now),
                MetricValue(key="sleep_debt_hours", value=1.5, unit="hours", computed_at=now),
                MetricValue(key="hrv_deviation_pct", value=-4, unit="percent", computed_at=now),
            ),
        )
        self._snapshots[MetricFamily.RISK] = MetricSnapshot(
            user_id=user_id,
            family=MetricFamily.RISK,
            as_of=now,
            metrics=(
                MetricValue(key="injury_risk_score", value=30, unit="score", computed_at=now),
                MetricValue(key="injury_risk_level", value=1, unit="level", computed_at=now),
                MetricValue(
                    key="injury_risk_factors",
                    value=1,
                    unit="Elevated ACWR",
                    computed_at=now,
                ),
            ),
        )

    async def get_latest_snapshot(self, user_id, family):
        return self._snapshots.get(family)


def _make_service() -> CoachMCPService:
    data_repo = StubDataRepo()
    metric_engine = StubMetricEngine()
    coach_service = build_coach_service(
        data_repo,  # type: ignore[arg-type]
        metric_engine,  # type: ignore[arg-type]
        Settings(openai_api_key=None),
    )
    return CoachMCPService(data_repo, metric_engine, coach_service)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_get_recent_activities() -> None:
    service = _make_service()
    result = await service.get_recent_activities(uuid4(), days=7)
    assert result["count"] == 1
    assert result["activities"][0]["name"] == "Morning Run"


@pytest.mark.asyncio
async def test_get_recovery_state() -> None:
    service = _make_service()
    result = await service.get_recovery_state(uuid4())
    assert result["recovery_score"] == 65
    assert result["sleep_debt_hours"] == 1.5


@pytest.mark.asyncio
async def test_get_injury_risk() -> None:
    service = _make_service()
    result = await service.get_injury_risk(uuid4())
    assert result["level"] == "moderate"
    assert result["factors"] == ["Elevated ACWR"]


@pytest.mark.asyncio
async def test_explain_today_returns_briefing() -> None:
    service = _make_service()
    result = await service.explain_today(uuid4())
    assert "explanation" in result
    assert result["recommendations"]
    assert "tsb" in result["metrics_used"]
