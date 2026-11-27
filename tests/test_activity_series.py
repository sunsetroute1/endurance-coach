"""Activity-detail chart parsing."""

from datetime import UTC, datetime

from endurance_coach.garmin.activity_series import decimate_samples, parse_activity_detail_chart


def _descriptor(index: int, key: str, unit: str, factor: float) -> dict:
    return {"metricsIndex": index, "key": key, "unit": {"unitKey": unit, "factor": factor}}


def _payload(rows: list[list]) -> dict:
    keys = [
        ("directTimestamp", "gmt", 0),
        ("sumDuration", "second", 1000),
        ("directHeartRate", "bpm", 1),
        ("directSpeed", "mps", 0.1),
        ("directPower", "watt", 1),
        ("directElevation", "meter", 100),
        ("directGradeAdjustedSpeed", "mps", 0.1),
    ]
    return {
        "metricDescriptors": [
            _descriptor(index, key, unit, factor)
            for index, (key, unit, factor) in enumerate(keys)
        ],
        "activityDetailMetrics": [{"metrics": row} for row in rows],
    }


def test_unit_name_may_be_key_instead_of_unit_key() -> None:
    payload = _payload([[1_700_000_000_000, 0, 140, 3.5, 200, 1500, 2.4]])
    payload["metricDescriptors"][4]["unit"] = {"id": 10, "key": "watt", "factor": 1.0}
    parsed = parse_activity_detail_chart(payload)
    assert parsed["units"]["directPower"] == "watt"
    assert parsed["samples"][0]["power_watts"] == 200


def test_chart_values_keep_unit_and_nulls() -> None:
    parsed = parse_activity_detail_chart(
        _payload(
            [
                [1_700_000_000_000, 0, 140, 3.5, 200, 1500, None],
                [1_700_000_001_000, 1, None, 3.5, 210, 1502, 2.4],
                "skip",
            ]
        )
    )
    assert parsed["factors_applied"] is False
    assert len(parsed["samples"]) == 2
    first = parsed["samples"][0]
    assert first["speed_mps"] == 3.5
    assert first["elevation_meters"] == 1500
    assert first["grade_adjusted_speed_mps"] is None
    assert first["recorded_at"] == datetime(2023, 11, 14, 22, 13, 20, tzinfo=UTC)
    assert parsed["samples"][1]["heart_rate_bpm"] is None
    assert parsed["sampling"]["median_interval_seconds"] == 1


def test_short_metric_row_leaves_missing_fields_null() -> None:
    parsed = parse_activity_detail_chart(_payload([[1_700_000_000_000, 0]]))
    sample = parsed["samples"][0]
    assert sample["heart_rate_bpm"] is None
    assert sample["power_watts"] is None
    assert parsed["priority_fields_present"] is False


def test_decimate_keeps_every_kth_sample() -> None:
    samples = [{"sample_index": index, "recorded_at": None} for index in range(10)]
    reduced = decimate_samples(samples, limit=4)
    assert reduced["decimated"] is True
    assert [sample["sample_index"] for sample in reduced["samples"]] == [0, 3, 6, 9]
