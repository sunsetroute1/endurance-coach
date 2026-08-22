"""Tests for Garmin daily recap parsing."""

from endurance_coach.garmin.daily_recap import parse_daily_recap, synthesize_recap_message


def test_parse_stressful_day_recap() -> None:
    data = {
        "stressQualifier": "VERY_STRESSFUL_AWAKE",
        "averageStressLevel": 68,
        "maxStressLevel": 98,
        "stressDuration": 40800,
        "restStressDuration": 1200,
        "totalSteps": 12610,
        "totalKilocalories": 2450.0,
        "activeKilocalories": 420.0,
        "activeSeconds": 2016,
        "bodyBatteryDynamicFeedbackEvent": {
            "bodyBatteryLevel": "VERY_LOW",
            "feedbackShortType": "DAY_STRESSFUL_AND_INACTIVE",
            "feedbackLongType": "DAY_STRESSFUL_AND_INACTIVE_AND_BB_LOW",
            "eventTimestampGmt": "2026-07-14T20:15:12.0",
        },
        "endOfDayBodyBatteryDynamicFeedbackEvent": {
            "bodyBatteryLevel": "VERY_LOW",
            "feedbackShortType": "SLEEP_TIME_PASSED_STRESSFUL_AND_INACTIVE",
            "feedbackLongType": "SLEEP_TIME_PASSED_STRESSFUL_AND_INACTIVE_AND_BB_LOW",
            "eventTimestampGmt": "2026-07-15T05:30:13.0",
        },
    }

    parsed = parse_daily_recap(data)

    assert parsed["stress_qualifier"] == "VERY_STRESSFUL_AWAKE"
    assert parsed["average_stress_level"] == 68
    assert parsed["stress_duration_min"] == 680
    assert parsed["total_steps"] == 12610
    assert parsed["is_day_complete"] is True
    assert parsed["recap_message"] is not None
    assert "stressful" in parsed["recap_message"].lower()
    assert parsed["body_battery_feedback"] is not None
    assert parsed["body_battery_feedback"].feedback_short == "DAY_STRESSFUL_AND_INACTIVE"


def test_in_progress_day_marks_incomplete() -> None:
    parsed = parse_daily_recap(
        {
            "stressQualifier": "UNKNOWN",
            "averageStressLevel": 66,
            "bodyBatteryDynamicFeedbackEvent": {
                "feedbackShortType": "DAY_NOT_STRESS_DATA_AND_INACTIVE",
            },
        }
    )

    assert parsed["is_day_complete"] is False
    assert parsed["recap_message"] is not None
    assert "inactive" in parsed["recap_message"].lower()


def test_wellness_description_preferred() -> None:
    message = synthesize_recap_message(
        stress_qualifier="CALM",
        wellness_description="You had a stressful day, but your workout helped you recover.",
        body_battery_feedback=None,
        end_of_day_feedback=None,
    )
    assert message == "You had a stressful day, but your workout helped you recover."
