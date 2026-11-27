"""Project a stored Garmin Coach / adaptive training plan into coach fields."""

from __future__ import annotations

from typing import Any


def project_training_plan(payload: dict[str, Any]) -> dict[str, Any]:
    """Compact view of one stored plan.

    Garmin Coach open-loop plans return the current week in ``taskList``.
    Workout steps are not on that object, and these workouts often have no
    integer workout id to fetch separately.
    """
    plan = payload.get("data", payload) if isinstance(payload, dict) else {}
    if not isinstance(plan, dict):
        plan = {}

    return {
        "training_plan_id": plan.get("trainingPlanId"),
        "name": plan.get("name"),
        "status": _key(plan.get("trainingStatus"), "statusKey"),
        "sport": _key(plan.get("trainingType"), "typeKey"),
        "plan_type": _key(plan.get("trainingSubType"), "subTypeKey"),
        "level": _key(plan.get("trainingLevel"), "levelKey"),
        "category": plan.get("trainingPlanCategory"),
        "start_date": _day(plan.get("startDate")),
        "end_date": _day(plan.get("endDate")),
        "duration_weeks": plan.get("durationInWeeks"),
        "workouts_per_week": plan.get("avgWeeklyWorkouts"),
        "supplemental_sports": plan.get("supplementalSports") or [],
        "workouts": [_workout(task) for task in _tasks(plan)],
    }


def _tasks(plan: dict[str, Any]) -> list[dict[str, Any]]:
    tasks = plan.get("taskList") or []
    if not isinstance(tasks, list):
        return []
    return [task for task in tasks if isinstance(task, dict)]


def _workout(task: dict[str, Any]) -> dict[str, Any]:
    workout = task.get("taskWorkout")
    if not isinstance(workout, dict):
        workout = {}
    sport = workout.get("sportType")
    duration = workout.get("estimatedDurationInSecs")
    minutes = round(duration / 60) if isinstance(duration, (int, float)) else None
    return {
        "date": _day(task.get("calendarDate") or workout.get("scheduledDate")),
        "name": workout.get("workoutName"),
        "sport": _key(sport, "sportTypeKey"),
        "duration_minutes": minutes,
        "distance_meters": workout.get("estimatedDistanceInMeters"),
        "phrase": workout.get("workoutPhrase"),
        "training_effect": workout.get("trainingEffectLabel"),
        "status": workout.get("adaptiveCoachingWorkoutStatus"),
        "key_workout": bool(task.get("keyWorkout")),
        "long_workout": bool(task.get("longWkt")),
        "rest_day": bool(workout.get("restDay")),
    }


def _key(value: Any, field: str) -> Any:
    if isinstance(value, dict):
        return value.get(field)
    return value


def _day(value: Any) -> str | None:
    if not isinstance(value, str) or len(value) < 10:
        return None
    return value[:10]
