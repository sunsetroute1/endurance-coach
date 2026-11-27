"""Tests for compact Garmin performance payload projections."""

from __future__ import annotations

from datetime import date

from endurance_coach.garmin.performance_metrics import project_performance_records


def _row(resource_type: str, provider_record_id: str, payload: dict) -> tuple[str, str, dict]:
    return resource_type, provider_record_id, payload


def test_endurance_projection_keeps_overall_score_and_drops_user_ids() -> None:
    start = date(2026, 11, 1)
    end = date(2026, 11, 9)
    rows = [
        _row(
            "endurance_score",
            "2026-11-09",
            {
                "calendarDate": "2026-11-09",
                "groupAverage": 41,
                "groupMax": 44,
                "userProfilePk": 9,
                "enduranceScoreDTO": {"overallScore": 44, "userId": 1},
            },
        )
    ]
    result = project_performance_records(rows, start=start, end=end)
    metric = result["metrics"]["endurance_score"][0]
    assert metric["overallScore"] == 44
    assert metric["groupAverage"] == 41
    assert "userProfilePk" not in metric
    assert "userId" not in metric


def test_null_hill_score_omitted() -> None:
    start = date(2026, 11, 1)
    end = date(2026, 11, 9)
    rows = [
        _row(
            "hill_score",
            "2026-11-09",
            {"calendarDate": "2026-11-09", "overallScore": None},
        )
    ]
    result = project_performance_records(rows, start=start, end=end)
    assert "hill_score" not in result["metrics"]


def test_device_inventory_keeps_keys_and_drops_serial() -> None:
    start = date(2026, 11, 1)
    end = date(2026, 11, 9)
    rows = [
        _row(
            "devices",
            "inventory",
            {
                "registeredDevices": [
                    {
                        "applicationKey": "enduro3",
                        "productDisplayName": "Enduro 3",
                        "staminaCurveCapable": False,
                        "serialNumber": "SECRET",
                        "deviceId": 7,
                    }
                ]
            },
        )
    ]
    result = project_performance_records(rows, start=start, end=end)
    device = result["metrics"]["devices"][0]["devices"][0]
    assert device["applicationKey"] == "enduro3"
    assert device["staminaCurveCapable"] is False
    assert "serialNumber" not in device
    assert "deviceId" not in device


def test_solar_drops_device_id() -> None:
    start = date(2026, 11, 1)
    end = date(2026, 11, 9)
    rows = [
        _row(
            "solar_gain",
            "99:2026-11-09",
            {
                "deviceId": "99",
                "localConnectDate": "2026-11-09",
                "totalActivityTimeGainedMs": 1200,
            },
        )
    ]
    result = project_performance_records(rows, start=start, end=end)
    solar = result["metrics"]["solar_gain"][0]
    assert solar["totalActivityTimeGainedMs"] == 1200
    assert "deviceId" not in solar


def test_date_outside_window_omitted() -> None:
    start = date(2026, 11, 1)
    end = date(2026, 11, 8)
    rows = [
        _row(
            "heart_rate",
            "2026-11-09",
            {
                "calendarDate": "2026-11-09",
                "values": {"restingHR": 48},
            },
        )
    ]
    result = project_performance_records(rows, start=start, end=end)
    assert "heart_rate" not in result["metrics"]


def test_empty_resources_absent_from_metrics() -> None:
    start = date(2026, 11, 1)
    end = date(2026, 11, 9)
    rows = [
        _row(
            "running_economy",
            "2026-11-09",
            {"calendarDate": "2026-11-09", "score": None},
        )
    ]
    result = project_performance_records(rows, start=start, end=end)
    assert result["metrics"] == {}
