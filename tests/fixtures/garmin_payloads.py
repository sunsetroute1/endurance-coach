"""Sample Garmin raw payloads for processor tests."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from endurance_coach.domain.enums import DataProviderType, ResourceType
from endurance_coach.domain.models import RawPayload

PAYLOAD_ID = uuid4()
USER_ID = uuid4()
FETCHED_AT = datetime(2026, 7, 14, 8, 0, tzinfo=UTC)


def activity_payload() -> RawPayload:
    return RawPayload(
        id=PAYLOAD_ID,
        user_id=USER_ID,
        provider=DataProviderType.GARMIN,
        resource_type=ResourceType.ACTIVITIES,
        provider_record_id="101",
        content_hash="activity-hash",
        fetched_at=FETCHED_AT,
        payload={
            "summary": {
                "activityId": 101,
                "activityName": "Treadmill Running",
                "activityType": {"typeKey": "treadmill_running"},
                "startTimeLocal": "2026-07-15T08:20:26",
                "duration": 3000.0,
                "distance": 8170.6,
                "averageHR": 123,
                "maxHR": 150,
                "averageSpeed": 2.72,
                "elevationGain": 0.0,
                "activityTrainingLoad": 32.0,
                "aerobicTrainingEffect": 1.2,
                "anaerobicTrainingEffect": 0.0,
                "trainingEffectLabel": "AEROBIC_BASE",
                "averageRunningCadenceInStepsPerMinute": 153.0,
                "avgVerticalRatio": 8.5,
                "avgVerticalOscillation": 8.2,
                "avgGroundContactTime": 298.0,
                "avgStrideLength": 98.0,
                "hrTimeInZone_1": 1200.0,
                "hrTimeInZone_2": 1500.0,
                "hrTimeInZone_3": 300.0,
                "hrTimeInZone_4": 0.0,
                "hrTimeInZone_5": 0.0,
            },
            "detail": {
                "summaryDTO": {
                    "maxRunCadence": 185.0,
                    "averageRunCadence": 153.0,
                    "avgVerticalOscillation": 8.2,
                    "avgVerticalRatio": 8.5,
                    "avgGroundContactTime": 298.0,
                    "avgStrideLength": 98.0,
                    "aerobicTrainingEffect": 1.2,
                    "anaerobicTrainingEffect": 0.0,
                    "trainingEffectLabel": "AEROBIC_BASE",
                    "maxHR": 150,
                    "hrTimeInZone_1": 1200.0,
                    "hrTimeInZone_2": 1500.0,
                    "hrTimeInZone_3": 300.0,
                    "hrTimeInZone_4": 0.0,
                    "hrTimeInZone_5": 0.0,
                },
                "lapDTOs": [
                    {"lapIndex": 1, "duration": 600.0, "averageHR": 115},
                    {"lapIndex": 2, "duration": 570.0, "averageHR": 125},
                ],
            },
        },
    )


def sleep_payload() -> RawPayload:
    return RawPayload(
        id=uuid4(),
        user_id=USER_ID,
        provider=DataProviderType.GARMIN,
        resource_type=ResourceType.SLEEP,
        provider_record_id="2026-07-14",
        content_hash="sleep-hash",
        fetched_at=FETCHED_AT,
        payload={
            "date": "2026-07-14",
            "data": {
                "sleepTimeSeconds": 28800,
                "deepSleepSeconds": 5400,
                "remSleepSeconds": 7200,
                "lightSleepSeconds": 14400,
                "awakeSleepSeconds": 1800,
                "sleepScores": {"overall": {"value": 82}},
            },
        },
    )


def hrv_payload() -> RawPayload:
    return RawPayload(
        id=uuid4(),
        user_id=USER_ID,
        provider=DataProviderType.GARMIN,
        resource_type=ResourceType.HRV,
        provider_record_id="2026-07-14",
        content_hash="hrv-hash",
        fetched_at=FETCHED_AT,
        payload={
            "date": "2026-07-14",
            "data": {"lastNightAvg": 48.0, "restingHeartRate": 52, "baselineLowUpper": 50.0},
        },
    )


def readiness_payload() -> RawPayload:
    return RawPayload(
        id=uuid4(),
        user_id=USER_ID,
        provider=DataProviderType.GARMIN,
        resource_type=ResourceType.TRAINING_READINESS,
        provider_record_id="2026-07-14",
        content_hash="readiness-hash",
        fetched_at=FETCHED_AT,
        payload={
            "date": "2026-07-14",
            "data": [{"score": 78, "hrvFactor": 80, "sleepFactor": 75, "recoveryFactor": 70}],
        },
    )


def body_battery_payload() -> RawPayload:
    return RawPayload(
        id=uuid4(),
        user_id=USER_ID,
        provider=DataProviderType.GARMIN,
        resource_type=ResourceType.BODY_BATTERY,
        provider_record_id="2026-07-14",
        content_hash="battery-hash",
        fetched_at=FETCHED_AT,
        payload={
            "date": "2026-07-14",
            "data": [[0, 45], [60, 62], [120, 58]],
        },
    )


def stress_payload() -> RawPayload:
    return RawPayload(
        id=uuid4(),
        user_id=USER_ID,
        provider=DataProviderType.GARMIN,
        resource_type=ResourceType.STRESS,
        provider_record_id="2026-07-14",
        content_hash="stress-hash",
        fetched_at=FETCHED_AT,
        payload={
            "date": "2026-07-14",
            "data": {"avgStressLevel": 28, "maxStressLevel": 65},
        },
    )


def steps_payload() -> RawPayload:
    return RawPayload(
        id=uuid4(),
        user_id=USER_ID,
        provider=DataProviderType.GARMIN,
        resource_type=ResourceType.STEPS,
        provider_record_id="2026-07-14",
        content_hash="steps-hash",
        fetched_at=FETCHED_AT,
        payload={
            "date": "2026-07-14",
            "data": {
                "calendarDate": "2026-07-14",
                "totalSteps": 4207,
                "dailyStepGoal": 20000,
                "totalDistanceMeters": 3218.5,
            },
        },
    )
