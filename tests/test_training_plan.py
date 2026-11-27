"""Projection of a Garmin Coach adaptive plan."""

from datetime import date

from endurance_coach.collector.providers.garmin.provider import _plan_still_relevant
from endurance_coach.garmin.training_plan import project_training_plan


def test_scheduled_plan_is_kept_before_its_start_date() -> None:
    plan = {
        "trainingStatus": {"statusKey": "Scheduled"},
        "endDate": "2027-03-07T00:00:00.0",
    }
    assert _plan_still_relevant(plan, date(2026, 11, 15)) is True


def test_project_open_loop_running_plan() -> None:
    projected = project_training_plan(
        {
            "trainingPlanId": 48670196,
            "name": "2027 Fitness Plan",
            "trainingStatus": {"statusKey": "Scheduled"},
            "trainingType": {"typeKey": "Running"},
            "trainingSubType": {"subTypeKey": "GarminRunningCoachOpenLoop"},
            "trainingLevel": {"levelKey": "Intermediate"},
            "trainingPlanCategory": "FBT_ADAPTIVE",
            "startDate": "2026-11-16T00:00:00.0",
            "endDate": "2027-03-07T00:00:00.0",
            "durationInWeeks": 16,
            "avgWeeklyWorkouts": 7,
            "supplementalSports": ["STRENGTH_TRAINING_GYM"],
            "taskList": [
                {
                    "calendarDate": "2026-11-16",
                    "keyWorkout": True,
                    "longWkt": False,
                    "taskWorkout": {
                        "workoutName": "Sprint",
                        "sportType": {"sportTypeKey": "running"},
                        "estimatedDurationInSecs": 2640,
                        "estimatedDistanceInMeters": 6082,
                        "workoutPhrase": "ANAEROBIC_SPEED",
                        "trainingEffectLabel": "SPEED",
                        "adaptiveCoachingWorkoutStatus": "NOT_COMPLETE",
                        "restDay": False,
                    },
                }
            ],
        }
    )

    assert projected["name"] == "2027 Fitness Plan"
    assert projected["sport"] == "Running"
    assert projected["plan_type"] == "GarminRunningCoachOpenLoop"
    assert projected["start_date"] == "2026-11-16"
    workout = projected["workouts"][0]
    assert workout["name"] == "Sprint"
    assert workout["sport"] == "running"
    assert workout["duration_minutes"] == 44
    assert workout["distance_meters"] == 6082
    assert workout["key_workout"] is True
    assert workout["status"] == "NOT_COMPLETE"
