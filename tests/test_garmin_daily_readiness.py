"""Tests for daily Garmin readiness assembly."""

from datetime import UTC, date, datetime, time, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from tests.fixtures.garmin_payloads import body_battery_payload

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
    metric_source_date,
    morning_cutoff_applies,
    morning_sync_cutoff,
    morning_sync_fetched_before,
    readiness_source_date,
)


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


def test_morning_cutoff_applies_only_after_901_on_report_day(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tz = "America/Denver"
    report = date(2026, 7, 16)
    monkeypatch.setattr(
        "endurance_coach.garmin.readiness_dates.today_local",
        lambda _timezone: report,
    )
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


def test_midnight_utc_label_is_not_shifted_into_the_previous_local_day() -> None:
    label = datetime(2026, 11, 12, 0, 0, tzinfo=UTC)
    assert local_date_from_timestamp(label, "America/Denver") == date(2026, 11, 11)
    assert metric_source_date(label, "America/Denver") == date(2026, 11, 12)


def test_real_utc_instant_uses_the_denver_calendar_date() -> None:
    # 05:00 UTC on Nov 12 is 22:00 MST on Nov 11.
    instant = datetime(2026, 11, 12, 5, 0, tzinfo=UTC)
    assert metric_source_date(instant, "America/Denver") == date(2026, 11, 11)
    assert local_date_from_timestamp(instant, "America/Denver") == date(2026, 11, 11)


def test_parse_weekly_hrv_from_payload() -> None:
    payload = {
        "date": "2026-07-14",
        "data": {"hrvSummary": {"weeklyAvg": 53, "lastNightAvg": 18}},
    }
    assert parse_weekly_hrv(payload) == 53


def test_parse_body_battery_levels_from_payload() -> None:
    assert _parse_body_battery_levels(body_battery_payload().payload) == (45, 58)


def test_assess_morning_readiness_rejects_prior_day_sleep() -> None:
    from endurance_coach.garmin.daily_readiness import LastActivityReadiness

    report_date = date(2026, 7, 15)
    status, missing, latest = assess_morning_readiness(
        report_date=report_date,
        overnight_hrv=18,
        morning_rhr=51,
        seven_day_hrv=53,
        sleep_date=date(2026, 7, 14),
        sleep_seconds=23580,
        last_activity=LastActivityReadiness(
            date="2026-07-15",
            started_at="2026-07-15T08:00:00+00:00",
            distance_miles=5.08,
            avg_hr=132,
        ),
        metric_timestamps=[datetime(2026, 7, 14, 0, 0, tzinfo=UTC)],
    )
    assert status == ReadinessCompletionStatus.PARTIAL
    assert missing == ["sleep"]
    assert latest is None


def test_assess_morning_readiness_complete_with_wake_day_sleep() -> None:
    from endurance_coach.garmin.daily_readiness import LastActivityReadiness

    report_date = date(2026, 7, 16)
    status, missing, latest = assess_morning_readiness(
        report_date=report_date,
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
    def __init__(
        self,
        sleep_date: date,
        *,
        total_sleep_seconds: int = 27000,
        sleep_score: int = 82,
    ) -> None:
        self.sleep_date = sleep_date
        self.provider = "garmin"
        self.total_sleep_seconds = total_sleep_seconds
        self.deep_sleep_seconds = None
        self.rem_sleep_seconds = None
        self.light_sleep_seconds = None
        self.awake_seconds = None
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
                "data": {
                    "hrvSummary": {
                        "weeklyAvg": 53,
                        "lastNightAvg": 18,
                        "restingHeartRate": 51,
                    }
                },
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

    async def get_latest_hrv(self, user_id, as_of):
        return self.hrv

    async def get_sleep_for_date(self, user_id, sleep_date):
        if sleep_date == self.report_date:
            return None
        return self.sleep if sleep_date == self.source_date else None

    async def get_latest_meaningful_sleep(self, user_id, as_of):
        return self.sleep

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
async def test_july_15_prior_night_does_not_complete_the_report() -> None:
    service = DailyGarminReadinessService(July15CompleteRepo())
    response = await service.get_daily_readiness(
        uuid4(),
        timezone="America/Denver",
        target_date=date(2026, 7, 15),
        require_complete=False,
    )

    assert response.status == ReadinessCompletionStatus.PARTIAL
    assert response.date == "2026-07-15"
    assert "sleep" in response.missing_fields
    assert "overnight_hrv" in response.missing_fields
    assert "sleep" in response.stale_fields
    assert "overnight_hrv" in response.stale_fields
    assert response.sleep.sleep_date is None
    assert response.sleep.total_sleep_seconds is None
    assert response.sleep.duration_hours is None
    assert response.sleep.source_date == "2026-07-14"
    assert response.hrv.overnight_hrv is None
    assert response.hrv.seven_day_hrv is None
    assert response.hrv.source_date == "2026-07-14"
    assert response.source_dates.sleep == "2026-07-14"
    assert response.source_dates.hrv == "2026-07-14"
    assert response.last_activity.source_date == "2026-07-15"
    assert response.last_successful_metric_timestamp is None


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

    partial = await service.get_daily_readiness(
        uuid4(),
        timezone="America/Denver",
        target_date=date(2026, 7, 16),
        require_complete=False,
    )
    assert partial.sleep.sleep_date is None
    assert partial.sleep.total_sleep_seconds is None
    assert partial.sleep.duration_hours is None


@pytest.mark.asyncio
async def test_rest_and_mcp_share_same_readiness_status_shape() -> None:
    service = DailyGarminReadinessService(July15CompleteRepo())
    user_id = uuid4()
    rest = await service.get_daily_readiness(
        user_id,
        timezone="America/Denver",
        target_date=date(2026, 7, 15),
        require_complete=False,
    )
    status = await service.get_morning_readiness_status(
        user_id,
        timezone="America/Denver",
        target_date=date(2026, 7, 15),
    )
    assert rest.status == status.status == ReadinessCompletionStatus.PARTIAL
    assert rest.date == status.date == "2026-07-15"
    assert status.missing_fields == rest.missing_fields
    assert status.stale_fields == rest.stale_fields
    assert status.source_dates == rest.source_dates
    assert "sleep" in status.missing_fields


class _DatedActivity:
    def __init__(self, started_at: datetime) -> None:
        self.started_at = started_at
        self.distance_meters = 5000.0
        self.elevation_gain_meters = 12.0
        self.avg_heart_rate = 140
        self.training_load = 40.0


class CalendarDateRepo:
    """Sleep keyed by sleep_date. HRV may be a UTC-midnight label or a real instant."""

    def __init__(
        self,
        *,
        hrv_at: datetime,
        sleep_by_date: dict[date, tuple[int, int]],
        resting_heart_rate: int | None = None,
        hide_target_sleep_when_fetched_before: bool = False,
    ) -> None:
        self.hrv_at = hrv_at
        self.sleep_by_date = sleep_by_date
        self.resting_heart_rate = resting_heart_rate
        self.hide_target_sleep_when_fetched_before = hide_target_sleep_when_fetched_before
        self.hrv_id = uuid4()
        self.sleep_ids = {day: uuid4() for day in sleep_by_date}
        self.sleep_lookups: list[tuple[date, datetime | None]] = []
        self.activity = _DatedActivity(datetime(2026, 11, 12, 15, 0, tzinfo=UTC))

    def _sleep(self, day: date) -> StubSleep | None:
        row = self.sleep_by_date.get(day)
        if row is None:
            return None
        seconds, score = row
        sleep = StubSleep(day, total_sleep_seconds=seconds, sleep_score=score)
        sleep.source_payload_id = self.sleep_ids[day]
        return sleep

    async def get_hrv_for_date(self, user_id, target_date):
        if self.hrv_at.astimezone(UTC).date() != target_date:
            return None
        return StubHRV(
            self.hrv_at,
            self.hrv_id,
            hrv_ms=62.0,
            resting_heart_rate=self.resting_heart_rate,
        )

    async def get_latest_hrv(self, user_id, as_of):
        return await self.get_hrv_for_date(user_id, self.hrv_at.astimezone(UTC).date())

    async def get_sleep_for_date(self, user_id, sleep_date, fetched_before=None):
        self.sleep_lookups.append((sleep_date, fetched_before))
        if (
            self.hide_target_sleep_when_fetched_before
            and fetched_before is not None
            and sleep_date == date(2026, 11, 12)
        ):
            return None
        return self._sleep(sleep_date)

    async def get_latest_meaningful_sleep(self, user_id, as_of):
        earlier = [
            day
            for day, (seconds, _score) in self.sleep_by_date.items()
            if day <= as_of and seconds > 0
        ]
        if not earlier:
            return None
        return self._sleep(max(earlier))

    async def get_sleep_by_date(self, user_id, end_date, *, window_days: int = 14):
        start = end_date - timedelta(days=window_days)
        return {
            day: seconds
            for day, (seconds, _score) in self.sleep_by_date.items()
            if start <= day <= end_date
        }

    async def get_latest_body_battery(self, user_id, as_of):
        return None

    async def get_latest_stress(self, user_id, as_of):
        return None

    async def get_steps_for_date(self, user_id, step_date):
        return None

    async def get_recent_activities(self, user_id, limit: int = 10):
        return [self.activity]

    async def get_raw_payload(self, payload_id):
        if payload_id == self.hrv_id:
            return {
                "date": "2026-11-12",
                "data": {"hrvSummary": {"weeklyAvg": 71, "lastNightAvg": 62}},
            }
        for day, sleep_id in self.sleep_ids.items():
            if payload_id == sleep_id:
                heart_rate = 49 if day == date(2026, 11, 12) else 51
                return {"date": day.isoformat(), "data": {"restingHeartRate": heart_rate}}
        return None


class _NoSnapshots:
    async def get_latest_snapshot(self, user_id, family):
        return None


def _assert_tools_share_sleep(summary: dict[str, object], readiness: dict[str, object]) -> None:
    sleep = summary["sleep"]
    ready = readiness["sleep"]
    assert isinstance(ready, dict)
    if sleep is None:
        assert ready["sleep_date"] is None
        assert ready["total_sleep_seconds"] is None
        assert ready["sleep_score"] is None
        return
    assert isinstance(sleep, dict)
    assert ready["sleep_date"] == sleep["sleep_date"]
    assert ready["total_sleep_seconds"] == sleep["total_sleep_seconds"]
    assert ready["sleep_score"] == sleep["sleep_score"]


def _nov12_repo() -> CalendarDateRepo:
    return CalendarDateRepo(
        hrv_at=datetime(2026, 11, 12, 0, 0, tzinfo=UTC),
        sleep_by_date={
            date(2026, 11, 11): (27240, 90),
            date(2026, 11, 12): (24660, 87),
        },
        hide_target_sleep_when_fetched_before=True,
    )


@pytest.mark.asyncio
async def test_nov12_readiness_uses_the_same_sleep_as_sleep_summary() -> None:
    from endurance_coach.mcp.service import CoachMCPService

    repo = _nov12_repo()
    user_id = uuid4()
    target = date(2026, 11, 12)
    mcp = CoachMCPService(repo, _NoSnapshots(), None, app_timezone="America/Denver")  # type: ignore[arg-type]

    summary = await mcp.get_sleep_summary(user_id, target)
    readiness = await mcp.get_daily_garmin_readiness(user_id, target)

    assert summary["sleep"]["total_sleep_seconds"] == 24660
    assert summary["sleep"]["sleep_score"] == 87
    assert summary["sleep"]["sleep_date"] == "2026-11-12"
    _assert_tools_share_sleep(summary, readiness)
    assert readiness["status"] == "complete"
    assert readiness["sleep"]["quality"] == "excellent"
    assert readiness["sleep"]["source_date"] == "2026-11-12"
    assert readiness["sleep"]["total_sleep_seconds"] != 27240
    assert readiness["hrv"]["source_date"] == "2026-11-12"
    assert readiness["hrv"]["overnight_hrv"] == 62
    assert readiness["hrv"]["seven_day_hrv"] == 71
    assert readiness["hrv"]["morning_rhr"] == 49
    assert readiness["source_dates"]["sleep"] == "2026-11-12"
    assert readiness["source_dates"]["hrv"] == "2026-11-12"
    assert readiness["missing_fields"] == []
    assert "sleep" not in readiness["stale_fields"]
    assert all(fetched_before is None for _day, fetched_before in repo.sleep_lookups)


@pytest.mark.asyncio
async def test_mixed_dates_do_not_embed_prior_night_sleep() -> None:
    from endurance_coach.mcp.service import CoachMCPService

    repo = CalendarDateRepo(
        hrv_at=datetime(2026, 11, 12, 0, 0, tzinfo=UTC),
        sleep_by_date={date(2026, 11, 11): (27240, 90)},
        resting_heart_rate=49,
    )
    user_id = uuid4()
    target = date(2026, 11, 12)
    mcp = CoachMCPService(repo, _NoSnapshots(), None, app_timezone="America/Denver")  # type: ignore[arg-type]

    summary = await mcp.get_sleep_summary(user_id, target)
    readiness = await mcp.get_daily_garmin_readiness(user_id, target)

    assert summary["sleep"] is None
    _assert_tools_share_sleep(summary, readiness)
    assert readiness["status"] == "partial"
    assert "sleep" in readiness["missing_fields"]
    assert "sleep" in readiness["stale_fields"]
    assert readiness["sleep"]["source_date"] == "2026-11-11"
    assert readiness["sleep"]["duration_hours"] is None
    assert readiness["sleep"]["total_sleep_seconds"] is None
    assert readiness["hrv"]["source_date"] == "2026-11-12"
    assert readiness["hrv"]["overnight_hrv"] == 62
    assert readiness["source_dates"]["hrv"] == "2026-11-12"


@pytest.mark.asyncio
async def test_missing_current_day_sleep_is_incomplete_without_a_stale_row() -> None:
    repo = CalendarDateRepo(
        hrv_at=datetime(2026, 11, 12, 0, 0, tzinfo=UTC),
        sleep_by_date={},
        resting_heart_rate=49,
    )
    response = await DailyGarminReadinessService(repo).get_daily_readiness(
        uuid4(),
        timezone="America/Denver",
        target_date=date(2026, 11, 12),
        require_complete=False,
    )

    assert response.status == ReadinessCompletionStatus.PARTIAL
    assert response.missing_fields == ["sleep"]
    assert response.stale_fields == []
    assert response.sleep.source_date is None
    assert response.sleep.total_sleep_seconds is None
    assert response.hrv.source_date == "2026-11-12"
    assert response.hrv.overnight_hrv == 62


@pytest.mark.asyncio
async def test_sleep_date_wins_over_a_midnight_utc_instant() -> None:
    repo = _nov12_repo()
    response = await DailyGarminReadinessService(repo).get_daily_readiness(
        uuid4(),
        timezone="America/Denver",
        target_date=date(2026, 11, 12),
        require_complete=False,
    )

    midnight_utc = datetime(2026, 11, 12, 0, 0, tzinfo=UTC)
    assert local_date_from_timestamp(midnight_utc, "America/Denver") == date(2026, 11, 11)
    assert response.sleep.sleep_date == "2026-11-12"
    assert response.sleep.total_sleep_seconds == 24660
    assert response.sleep.source_date == "2026-11-12"


@pytest.mark.asyncio
async def test_real_utc_instant_is_not_treated_as_the_denver_day() -> None:
    repo = CalendarDateRepo(
        hrv_at=datetime(2026, 11, 12, 5, 0, tzinfo=UTC),
        sleep_by_date={date(2026, 11, 12): (24660, 87)},
    )
    response = await DailyGarminReadinessService(repo).get_daily_readiness(
        uuid4(),
        timezone="America/Denver",
        target_date=date(2026, 11, 12),
        require_complete=False,
    )

    assert metric_source_date(repo.hrv_at, "America/Denver") == date(2026, 11, 11)
    assert response.hrv.overnight_hrv is None
    assert response.hrv.source_date == "2026-11-11"
    assert "overnight_hrv" in response.missing_fields
    assert "overnight_hrv" in response.stale_fields
    assert response.sleep.total_sleep_seconds == 24660
    assert response.sleep.source_date == "2026-11-12"
    assert response.status == ReadinessCompletionStatus.PARTIAL
