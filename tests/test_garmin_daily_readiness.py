"""Tests for daily Garmin readiness assembly."""

from datetime import UTC, date, datetime, time
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest

from endurance_coach.garmin.daily_readiness import (
    DailyGarminReadinessService,
    MorningReadinessIncompleteError,
    ReadinessCompletionStatus,
    _parse_body_battery_levels,
    assess_morning_readiness,
    sleep_quality_from_score,
)
from endurance_coach.garmin.payload_parsing import parse_weekly_hrv
from endurance_coach.garmin.readiness_dates import (
    in_morning_sync_window,
    local_date_from_timestamp,
    morning_cutoff_applies,
    morning_sync_cutoff,
    morning_sync_fetched_before,
    readiness_source_date,
)
from tests.fixtures.garmin_payloads import body_battery_payload


@pytest.mark.parametrize(
    ("score", "expected"),
    [
        (90, "excellent"),
        (75, "good"),
        (60, "fair"),
        (40, "poor"),
        (None, None),
    ],
)
def test_sleep_quality_from_score(score: int | None, expected: str | None) -> None:
    assert sleep_quality_from_score(score) == expected


def test_readiness_source_date_is_prior_local_day() -> None:
    assert readiness_source_date(date(2026, 7, 15), "America/Denver") == date(2026, 7, 14)


def test_morning_sync_cutoff_is_901_am_local() -> None:
    cutoff = morning_sync_cutoff(date(2026, 7, 16), "America/Denver")
    local = cutoff.astimezone(ZoneInfo("America/Denver"))
    assert local.hour == 9
    assert local.minute == 1


def test_morning_cutoff_applies_only_after_901_on_report_day() -> None:
    tz = "America/Denver"
    report = date(2026, 7, 16)
    before = datetime(2026, 7, 16, 14, 30, tzinfo=UTC)  # 8:30 AM MDT
    after = datetime(2026, 7, 16, 15, 2, tzinfo=UTC)  # 9:02 AM MDT
    assert morning_cutoff_applies(report, tz, now=before) is False
    assert morning_cutoff_applies(report, tz, now=after) is True
    assert morning_sync_fetched_before(report, tz, now=before) is None
    assert morning_sync_fetched_before(report, tz, now=after) == morning_sync_cutoff(report, tz)


def test_in_morning_sync_window_covers_900_to_901() -> None:
    tz = "America/Denver"
    at_900 = datetime(2026, 7, 16, 15, 0, tzinfo=UTC)
    at_901 = datetime(2026, 7, 16, 15, 1, tzinfo=UTC)
    at_902 = datetime(2026, 7, 16, 15, 2, tzinfo=UTC)
    assert in_morning_sync_window(tz, now=at_900) is True
    assert in_morning_sync_window(tz, now=at_901) is True
    assert in_morning_sync_window(tz, now=at_902) is False


def test_local_date_from_timestamp_uses_denver() -> None:
    # 2026-07-15 02:51 UTC is still 2026-07-14 evening in Denver (MDT, UTC-6).
    ts = datetime(2026, 7, 15, 2, 51, tzinfo=UTC)
    assert local_date_from_timestamp(ts, "America/Denver") == date(2026, 7, 14)


def test_parse_weekly_hrv_from_payload() -> None:
    payload = {
        "date": "2026-07-14",
        "data": {"hrvSummary": {"weeklyAvg": 53, "lastNightAvg": 18}},
    }
    assert parse_weekly_hrv(payload) == 53


def test_parse_body_battery_levels_from_payload() -> None:
    assert _parse_body_battery_levels(body_battery_payload().payload) == (45, 58)


def test_assess_morning_readiness_complete_with_source_date() -> None:
    from endurance_coach.garmin.daily_readiness import LastActivityReadiness

    report_date = date(2026, 7, 15)
    source_date = date(2026, 7, 14)
    status, missing, latest = assess_morning_readiness(
        report_date=report_date,
        source_date=source_date,
        overnight_hrv=18,
        morning_rhr=51,
        seven_day_hrv=53,
        sleep_date=source_date,
        sleep_seconds=23580,
        last_activity=LastActivityReadiness(
            date="2026-07-15",
            started_at="2026-07-15T08:00:00+00:00",
            distance_miles=5.08,
            avg_hr=132,
        ),
        metric_timestamps=[datetime(2026, 7, 14, 0, 0, tzinfo=UTC)],
    )
    assert status == ReadinessCompletionStatus.COMPLETE
    assert missing == []
    assert latest is not None


def test_assess_morning_readiness_complete_with_wake_day_sleep() -> None:
    from endurance_coach.garmin.daily_readiness import LastActivityReadiness

    report_date = date(2026, 7, 16)
    source_date = date(2026, 7, 15)
    status, missing, latest = assess_morning_readiness(
        report_date=report_date,
        source_date=source_date,
        overnight_hrv=20,
        morning_rhr=49,
        seven_day_hrv=55,
        sleep_date=report_date,
        sleep_seconds=22518,
        last_activity=LastActivityReadiness(
            date="2026-07-15",
            started_at="2026-07-15T08:00:00+00:00",
            distance_miles=5.08,
            avg_hr=132,
        ),
        metric_timestamps=[datetime(2026, 7, 16, 0, 0, tzinfo=UTC)],
    )
    assert status == ReadinessCompletionStatus.COMPLETE
    assert missing == []


def test_assess_morning_readiness_partial_when_source_sleep_missing() -> None:
    from endurance_coach.garmin.daily_readiness import LastActivityReadiness

    status, missing, latest = assess_morning_readiness(
        report_date=date(2026, 7, 16),
        source_date=date(2026, 7, 15),
        overnight_hrv=None,
        morning_rhr=None,
        seven_day_hrv=None,
        sleep_date=None,
        sleep_seconds=None,
        last_activity=LastActivityReadiness(
            date="2026-07-15",
            started_at="2026-07-15T08:00:00+00:00",
            distance_miles=5.08,
            avg_hr=132,
        ),
        metric_timestamps=[],
    )
    assert status == ReadinessCompletionStatus.PARTIAL
    assert "overnight_hrv" in missing
    assert "sleep" in missing
    assert latest is None


class StubSleep:
    def __init__(self, sleep_date: date, *, total_sleep_seconds: int = 27000, sleep_score: int = 82) -> None:
        self.sleep_date = sleep_date
        self.total_sleep_seconds = total_sleep_seconds
        self.sleep_score = sleep_score
        self.source_payload_id = uuid4()


class StubHRV:
    def __init__(
        self,
        recorded_at: datetime,
        source_payload_id,
        *,
        hrv_ms: float = 98.0,
        resting_heart_rate: int | None = 42,
    ) -> None:
        self.recorded_at = recorded_at
        self.hrv_ms = hrv_ms
        self.resting_heart_rate = resting_heart_rate
        self.source_payload_id = source_payload_id


class StubBodyBattery:
    def __init__(self, recorded_at: datetime, source_payload_id) -> None:
        self.recorded_at = recorded_at
        self.level = 58
        self.charged = 75
        self.drained = 30
        self.source_payload_id = source_payload_id


class StubStress:
    def __init__(self, recorded_at: datetime) -> None:
        self.recorded_at = recorded_at
        self.avg_stress = 18


class StubSteps:
    def __init__(self, step_date: date) -> None:
        self.step_date = step_date
        self.total_steps = 4207
        self.step_goal = 20000
        self.distance_meters = 3218.5


class StubActivity:
    def __init__(self) -> None:
        self.started_at = datetime(2026, 7, 15, 8, 0, tzinfo=UTC)
        self.distance_meters = 8169.0
        self.elevation_gain_meters = 0.0
        self.avg_heart_rate = 132
        self.training_load = 75.0


class July15CompleteRepo:
    """Backfilled overnight metrics stored on 2026-07-14 for report 2026-07-15."""

    def __init__(self) -> None:
        self.report_date = date(2026, 7, 15)
        self.source_date = date(2026, 7, 14)
        self.hrv_payload_id = uuid4()
        self.battery_payload_id = uuid4()
        self.sleep_payload_id = uuid4()
        self.hrv = StubHRV(
            datetime.combine(self.source_date, time.min, tzinfo=UTC),
            self.hrv_payload_id,
            hrv_ms=18.0,
            resting_heart_rate=51,
        )
        self.sleep = StubSleep(self.source_date, total_sleep_seconds=23580, sleep_score=40)
        self.sleep.source_payload_id = self.sleep_payload_id
        self.body_battery = StubBodyBattery(
            datetime.combine(self.source_date, time.min, tzinfo=UTC),
            self.battery_payload_id,
        )
        self.stress = StubStress(datetime.combine(self.source_date, time.min, tzinfo=UTC))
        self.steps = StubSteps(self.report_date)
        self.activity = StubActivity()
        self.payloads = {
            self.hrv_payload_id: {
                "date": "2026-07-14",
                "data": {"hrvSummary": {"weeklyAvg": 53, "lastNightAvg": 18, "restingHeartRate": 51}},
            },
            self.battery_payload_id: body_battery_payload().payload,
            self.sleep_payload_id: {
                "date": "2026-07-14",
                "data": {
                    "restingHeartRate": 51,
                    "dailySleepDTO": {
                        "deepSleepSeconds": 3600,
                        "remSleepSeconds": 5400,
                        "lightSleepSeconds": 14580,
                    },
                },
            },
        }

    async def get_hrv_for_date(self, user_id, target_date):
        if target_date == self.report_date:
            return None
        return self.hrv if target_date == self.source_date else None

    async def get_sleep_for_date(self, user_id, sleep_date):
        if sleep_date == self.report_date:
            return None
        return self.sleep if sleep_date == self.source_date else None

    async def get_latest_body_battery(self, user_id, as_of):
        return self.body_battery

    async def get_latest_stress(self, user_id, as_of):
        return self.stress

    async def get_steps_for_date(self, user_id, step_date):
        return self.steps if step_date == self.report_date else None

    async def get_recent_activities(self, user_id, limit: int = 10):
        return [self.activity]

    async def get_raw_payload(self, payload_id):
        return self.payloads.get(payload_id)


class PartialMorningRepo:
    """Report 2026-07-16 before overnight metrics exist on source date 2026-07-15."""

    def __init__(self) -> None:
        self.report_date = date(2026, 7, 16)
        self.source_date = date(2026, 7, 15)
        self.july14 = July15CompleteRepo()

    async def get_hrv_for_date(self, user_id, target_date):
        return None

    async def get_sleep_for_date(self, user_id, sleep_date):
        if sleep_date == self.source_date:
            return StubSleep(self.source_date, total_sleep_seconds=0, sleep_score=None)
        return None

    async def get_latest_body_battery(self, user_id, as_of):
        return None

    async def get_latest_stress(self, user_id, as_of):
        return None

    async def get_steps_for_date(self, user_id, step_date):
        return None

    async def get_recent_activities(self, user_id, limit: int = 10):
        return [self.july14.activity]

    async def get_raw_payload(self, payload_id):
        return None


@pytest.mark.asyncio
async def test_july_15_complete_acceptance_payload() -> None:
    service = DailyGarminReadinessService(July15CompleteRepo())
    response = await service.get_daily_readiness(
        uuid4(),
        timezone="America/Denver",
        target_date=date(2026, 7, 15),
    )

    assert response.status == ReadinessCompletionStatus.COMPLETE
    assert response.date == "2026-07-15"
    assert response.hrv.morning_rhr == 51
    assert response.hrv.overnight_hrv == 18
    assert response.hrv.seven_day_hrv == 53
    assert response.hrv.recorded_at == "2026-07-14T00:00:00+00:00"
    assert response.sleep.sleep_date == "2026-07-14"
    assert response.sleep.duration_hours == 6.5
    assert response.sleep.quality == "poor"
    assert response.last_activity.date == "2026-07-15"
    assert response.last_successful_metric_timestamp is not None


@pytest.mark.asyncio
async def test_july_16_partial_without_july_15_leakage() -> None:
    service = DailyGarminReadinessService(PartialMorningRepo())
    with pytest.raises(MorningReadinessIncompleteError) as exc_info:
        await service.get_daily_readiness(
            uuid4(),
            timezone="America/Denver",
            target_date=date(2026, 7, 16),
        )

    status = exc_info.value.status
    assert status.status == ReadinessCompletionStatus.PARTIAL
    assert "overnight_hrv" in status.missing_fields
    assert "sleep" in status.missing_fields
    assert status.last_successful_metric_timestamp is None


@pytest.mark.asyncio
async def test_rest_and_mcp_share_same_readiness_status_shape() -> None:
    service = DailyGarminReadinessService(July15CompleteRepo())
    user_id = uuid4()
    rest = await service.get_daily_readiness(
        user_id,
        timezone="America/Denver",
        target_date=date(2026, 7, 15),
    )
    status = await service.get_morning_readiness_status(
        user_id,
        timezone="America/Denver",
        target_date=date(2026, 7, 15),
    )
    assert rest.status == status.status == ReadinessCompletionStatus.COMPLETE
    assert rest.date == status.date == "2026-07-15"
    assert status.missing_fields == []
