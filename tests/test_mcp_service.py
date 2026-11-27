"""Tests for MCP service tool implementations."""

from datetime import UTC, date, datetime, timedelta
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
        self.provider_record_id = kwargs.get("provider_record_id", "garmin-1")
        self.source_payload_id = kwargs.get("source_payload_id", uuid4())
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
        activities, _total = await self.list_activities(
            user_id,
            since=since,
            start=0,
            limit=limit,
        )
        return activities

    async def list_activities(
        self,
        user_id,
        *,
        since=None,
        activity_type=None,
        start: int = 0,
        limit: int = 50,
        max_limit: int = 100,
        timezone: str = "America/Denver",
    ):
        activities = list(self.activities)
        if since is not None:
            since_dt = datetime.combine(since, datetime.min.time(), tzinfo=UTC)
            activities = [activity for activity in activities if activity.started_at >= since_dt]
        if activity_type:
            needle = activity_type.strip().lower()
            activities = [
                activity
                for activity in activities
                if needle in activity.activity_type.lower()
            ]
        total = len(activities)
        cap = max(max_limit, 1)
        page_size = max(min(limit, cap), 1)
        offset = max(start, 0)
        activities = sorted(activities, key=lambda activity: activity.started_at, reverse=True)
        return activities[offset : offset + page_size], total

    async def get_sleep_for_date(self, user_id, sleep_date):
        return self.sleep.get(sleep_date)

    async def get_sleep_by_date(self, user_id, end_date, *, window_days: int = 14):
        return {day: record.total_sleep_seconds for day, record in self.sleep.items()}

    async def get_hrv_in_window(self, user_id, end_date, *, window_days: int = 14):
        return self.hrv

    async def get_latest_readiness(self, user_id, as_of):
        return self.readiness

    async def get_raw_payloads_by_ids(self, payload_ids):
        return {}

    async def get_activities_between(self, user_id, start_date, end_date, *, timezone: str = "America/Denver"):
        return [
            activity
            for activity in self.activities
            if start_date <= activity.started_at.date() <= end_date
        ]

    async def get_hrv_between(self, user_id, start_date, end_date):
        return [
            record
            for record in self.hrv
            if start_date <= record.recorded_at.date() <= end_date
        ]

    async def get_sleep_records_in_window(self, user_id, start_date, end_date):
        return [
            record
            for record in self.sleep.values()
            if start_date <= record.sleep_date <= end_date
        ]

    async def get_steps_in_window(self, user_id, start_date, end_date):
        return []

    async def get_stress_in_window(self, user_id, start_date, end_date):
        return []

    async def get_body_battery_in_window(self, user_id, start_date, end_date):
        return []

    async def get_readiness_in_window(self, user_id, start_date, end_date):
        if start_date <= self.readiness.recorded_at.date() <= end_date:
            return [self.readiness]
        return []

    async def get_daily_activity_loads(
        self,
        user_id,
        end_date,
        *,
        history_days: int = 120,
        timezone: str = "America/Denver",
    ):
        loads: dict[date, float] = {}
        for activity in self.activities:
            day = activity.started_at.date()
            loads[day] = loads.get(day, 0.0) + float(activity.training_load or 0.0)
        return loads


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
    result = await service.get_recent_activities(uuid4(), days=7, summary_only=False)
    assert result["mode"] == "full"
    assert result["count"] == 1
    assert result["total"] == 1
    assert result["start"] == 0
    assert result["limit"] == 50
    assert result["has_more"] is False
    assert result["activities"][0]["name"] == "Morning Run"


@pytest.mark.asyncio
async def test_get_recent_activities_summary_only() -> None:
    service = _make_service()
    result = await service.get_recent_activities(uuid4(), days=7, summary_only=True)
    assert result["mode"] == "summary"
    activity = result["activities"][0]
    assert set(activity) == {
        "id",
        "provider_activity_id",
        "name",
        "started_at",
        "date",
        "type",
        "duration_s",
        "distance_m",
        "avg_hr",
        "vert_m",
        "load",
    }
    assert activity["type"] == "running"
    assert activity["duration_s"] == 3600
    assert activity["id"]
    assert activity["provider_activity_id"] == "garmin-1"


@pytest.mark.asyncio
async def test_get_recent_activities_pagination_and_activitytype() -> None:
    now = datetime.now(UTC)
    data_repo = StubDataRepo()
    data_repo.activities = [
        StubActivity(
            name="Morning Run",
            activity_type="running",
            started_at=now - timedelta(hours=2),
        ),
        StubActivity(
            name="Evening Ride",
            activity_type="cycling",
            started_at=now - timedelta(hours=1),
        ),
        StubActivity(
            name="Treadmill",
            activity_type="treadmill_running",
            started_at=now,
        ),
    ]
    metric_engine = StubMetricEngine()
    coach_service = build_coach_service(
        data_repo,  # type: ignore[arg-type]
        metric_engine,  # type: ignore[arg-type]
        Settings(openai_api_key=None),
    )
    service = CoachMCPService(data_repo, metric_engine, coach_service)  # type: ignore[arg-type]

    page = await service.get_recent_activities(
        uuid4(),
        days=30,
        start=1,
        limit=1,
        activitytype="run",
        summary_only=False,
    )

    assert page["mode"] == "full"

    assert page["total"] == 2
    assert page["count"] == 1
    assert page["start"] == 1
    assert page["limit"] == 1
    assert page["activitytype"] == "run"
    assert page["activities"][0]["name"] == "Morning Run"


@pytest.mark.asyncio
async def test_get_weekly_aggregates() -> None:
    service = _make_service()
    result = await service.get_weekly_aggregates(uuid4(), weeks=2)
    assert result["rollup"] == "mon_sun"
    assert len(result["aggregates"]) == 2
    latest = result["aggregates"][-1]
    assert latest["activities"]["count"] >= 1
    assert "running" in latest
    assert latest["running"]["distance_mi"] >= 0
    assert latest["activities"]["distance_mi"] >= 0
    assert latest["training"]["acute_load"] == latest["training"]["atl"]
    assert latest["sleep"]["nights"] >= 0
    assert "training" in latest
    assert "hrv" in latest
    assert "health" in latest


@pytest.mark.asyncio
async def test_get_weekly_aggregates_by_date_range() -> None:
    service = _make_service()
    result = await service.get_weekly_aggregates(
        uuid4(),
        weeks=12,
        start_date=date(2022, 3, 1),
        end_date=date(2022, 3, 31),
    )
    assert result["rollup"] == "mon_sun"
    assert result["weeks"] == 5
    assert result["range_start"] == "2022-02-28"
    assert result["range_end"] == "2022-04-03"
    assert len(result["aggregates"]) == 5
    assert result["aggregates"][0]["week_start"] == "2022-02-28"


@pytest.mark.asyncio
async def test_get_hrv_trend_weekly_rollup() -> None:
    service = _make_service()
    result = await service.get_hrv_trend(uuid4(), days=14, rollup="weekly")
    assert result["rollup"] == "weekly"
    assert isinstance(result["readings"], list)
    assert result["readings"]


@pytest.mark.asyncio
async def test_get_top_trail_efforts() -> None:
    # Fixed dates avoid UTC-vs-app-timezone flakiness near midnight.
    day = date(2026, 6, 15)
    data_repo = StubDataRepo()
    data_repo.activities = [
        StubActivity(
            name="Flat trail",
            activity_type="trail_running",
            started_at=datetime(2026, 6, 15, 12, 0, tzinfo=UTC),
            elevation_gain_meters=200.0,
            training_load=40.0,
        ),
        StubActivity(
            name="Alpine trail",
            activity_type="trail_running",
            started_at=datetime(2026, 6, 14, 12, 0, tzinfo=UTC),
            elevation_gain_meters=1200.0,
            training_load=90.0,
        ),
    ]
    metric_engine = StubMetricEngine()
    coach_service = build_coach_service(
        data_repo,  # type: ignore[arg-type]
        metric_engine,  # type: ignore[arg-type]
        Settings(openai_api_key=None),
    )
    service = CoachMCPService(data_repo, metric_engine, coach_service)  # type: ignore[arg-type]

    result = await service.get_top_trail_efforts(
        uuid4(),
        start_date=date(2026, 6, 1),
        end_date=day,
        limit=5,
        rank_by="vert_duration",
    )
    assert result["count"] == 2
    assert result["efforts"][0]["name"] == "Alpine trail"
    assert result["rank_by"] == "vert_duration"
    assert result["efforts"][0]["provider_activity_id"]


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
