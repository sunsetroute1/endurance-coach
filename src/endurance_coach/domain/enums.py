"""Shared domain enums."""

from enum import StrEnum


class DataProviderType(StrEnum):
    GARMIN = "garmin"
    SAMSUNG_HEALTH = "samsung_health"
    HEALTH_CONNECT = "health_connect"
    WHOOP = "whoop"
    OURA = "oura"
    STRAVA = "strava"
    COROS = "coros"
    APPLE_HEALTH = "apple_health"


class ResourceType(StrEnum):
    ACTIVITIES = "activities"
    SLEEP = "sleep"
    HRV = "hrv"
    BODY_BATTERY = "body_battery"
    TRAINING_READINESS = "training_readiness"
    STRESS = "stress"
    STEPS = "steps"
    RUNNING_DYNAMICS = "running_dynamics"
    DAILY_SUMMARY = "daily_summary"


class SyncStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class MetricFamily(StrEnum):
    LOAD = "load"
    EXECUTION = "execution"
    RECOVERY = "recovery"
    RISK = "risk"


class InjuryRiskLevel(StrEnum):
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"
    CRITICAL = "critical"
