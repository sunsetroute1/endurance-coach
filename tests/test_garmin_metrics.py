"""Tests for splitting verified Garmin metric responses into raw records."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from endurance_coach.collector.providers.garmin.metrics import (
    HEART_RATE_SPAN_DAYS,
    chunk_dates,
    device_inventory_record,
    endurance_records,
    heart_rate_records,
    hill_records,
    hrv_range_records,
    is_missing_garmin_feature,
    is_unsupported_power_sport,
    power_curve_record,
    solar_records,
    stamina_record,
    training_status_records,
    vo2_records,
)


def test_heart_rate_chunks_stay_inside_verified_limit() -> None:
    start = date(2026, 10, 1)
    end = date(2026, 11, 9)
    chunks = chunk_dates(start, end, HEART_RATE_SPAN_DAYS)
    assert chunks[0] == (date(2026, 10, 1), date(2026, 10, 28))
    assert chunks[-1][1] == end
    assert all(
        (chunk_end - chunk_start).days <= HEART_RATE_SPAN_DAYS
        for chunk_start, chunk_end in chunks
    )
    assert chunk_dates(end, start, HEART_RATE_SPAN_DAYS) == []


def test_endurance_records_keep_daily_groups_and_current_score() -> None:
    payload = {
        "avg": 40,
        "groupMap": {
            "2026-11-08": {"groupAverage": 38, "groupMax": 40},
            "2026-11-09": {"groupAverage": 41, "groupMax": 44},
        },
        "enduranceScoreDTO": {"calendarDate": "2026-11-09", "overallScore": 44},
    }
    records = dict(endurance_records(payload))
    assert set(records) == {"2026-11-08", "2026-11-09"}
    assert "enduranceScoreDTO" not in records["2026-11-08"]
    assert records["2026-11-09"]["enduranceScoreDTO"]["overallScore"] == 44
    assert records["2026-11-09"]["groupAverage"] == 41


def test_null_hill_scores_are_not_stored() -> None:
    payload = {
        "hillScoreDTOList": [
            {"calendarDate": "2026-11-09", "overallScore": None, "deviceId": 1},
        ]
    }
    assert hill_records(payload) == []


def test_training_status_groups_devices_by_day() -> None:
    weekly = {
        "reportData": {
            "11": [
                {"calendarDate": "2026-11-09", "weeklyTrainingLoad": 420, "deviceId": 11},
            ]
        }
    }
    snapshot = {"mostRecentTrainingLoadBalance": {"monthlyLoadAerobicLow": 100}}
    records = training_status_records(weekly, snapshot)
    assert records[0][0] == "2026-11-09"
    assert records[0][1]["devices"][0]["weeklyTrainingLoad"] == 420
    assert records[0][1]["trainingLoadBalance"]["monthlyLoadAerobicLow"] == 100


def test_vo2_latest_is_kept_when_range_is_empty() -> None:
    latest = {
        "generic": {"calendarDate": "2026-11-09", "vo2MaxValue": 52},
        "cycling": None,
    }
    records = dict(vo2_records(latest, []))
    assert records["2026-11-09"]["generic"]["vo2MaxValue"] == 52


def test_empty_stamina_and_power_curves_are_skipped() -> None:
    assert stamina_record(date(2026, 11, 9), {}) == []
    assert power_curve_record("cycling", date(2026, 11, 9), {"entries": []}) == []
    stored = power_curve_record(
        "cycling",
        date(2026, 11, 9),
        {"entries": [{"power": 250}]},
    )
    assert stored[0][0] == "cycling:2026-11-09"


def test_solar_records_are_keyed_by_device_and_day() -> None:
    payload = {
        "solarGainDailyDetailDTOList": [
            {"localConnectDate": "2026-11-09", "totalActivityTimeGainedMs": 1200},
        ]
    }
    records = solar_records("99", payload)
    assert records == [
        (
            "99:2026-11-09",
            {
                "deviceId": "99",
                "localConnectDate": "2026-11-09",
                "totalActivityTimeGainedMs": 1200,
            },
        )
    ]


def test_device_inventory_keeps_the_raw_device_document() -> None:
    records = device_inventory_record(
        [{"deviceId": 7, "applicationKey": "enduro3"}],
        {"PrimaryTrainingDevice": {"deviceId": 7}},
        None,
    )
    assert records[0][0] == "inventory"
    assert records[0][1]["registeredDevices"][0]["applicationKey"] == "enduro3"
    assert "lastUsed" not in records[0][1]


def test_heart_rate_rows_keep_garmin_value_names() -> None:
    rows = heart_rate_records(
        [{"calendarDate": "2026-11-09", "values": {"restingHR": 48, "wellnessMaxAvgHR": 140}}]
    )
    assert rows[0][1]["values"]["restingHR"] == 48


@pytest.mark.parametrize(
    ("message", "missing", "bad_sport"),
    [
        ("API Error 404 - not found", True, True),
        ("API Error 400 - Invalid activity type: running", False, True),
        ("API Error 400 - Invalid Dates", False, False),
        ("API Error 429 - rate limit", False, False),
    ],
)
def test_http_status_classification(message: str, missing: bool, bad_sport: bool) -> None:
    exc = RuntimeError(message)
    assert is_missing_garmin_feature(exc) is missing
    assert is_unsupported_power_sport(exc) is bad_sport


def test_chunk_dates_cover_the_window_without_overlap() -> None:
    start = date(2026, 1, 1)
    end = start + timedelta(days=60)
    chunks = chunk_dates(start, end, 28)
    assert chunks[0][0] == start
    assert chunks[-1][1] == end
    for previous, current in zip(chunks, chunks[1:], strict=False):
        assert current[0] == previous[1] + timedelta(days=1)


def test_hrv_range_records_keep_the_daily_wrapper() -> None:
    records = hrv_range_records(
        {
            "userProfilePk": 9,
            "hrvSummaries": [
                {"calendarDate": "2026-09-12", "lastNightAvg": 48},
                {"calendarDate": "2026-09-13", "weeklyAvg": None},
            ],
        }
    )
    assert len(records) == 1
    assert records[0][0] == "2026-09-12"
    assert records[0][1]["date"] == "2026-09-12"
    assert records[0][1]["data"]["lastNightAvg"] == 48
