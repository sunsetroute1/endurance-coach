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
    ENDURANCE_SCORE = "endurance_score"
    HILL_SCORE = "hill_score"
    RUNNING_TOLERANCE = "running_tolerance"
    TRAINING_STATUS = "training_status"
    RACE_PREDICTIONS = "race_predictions"
    VO2_MAX = "vo2_max"
    HEAT_ACCLIMATION = "heat_acclimation"
    RUNNING_ECONOMY = "running_economy"
    STAMINA_CURVE = "stamina_curve"
    POWER_CURVE = "power_curve"
    LACTATE_THRESHOLD = "lactate_threshold"
    RESPIRATION = "respiration"
    SPO2_ACCLIMATION = "spo2_acclimation"
    HEART_RATE = "heart_rate"
    WEIGHT = "weight"
    DEVICES = "devices"
    SOLAR_GAIN = "solar_gain"
    TRAINING_PLAN = "training_plan"
    RUNNING_DYNAMICS = "running_dynamics"
    ACTIVITY_DETAILS = "activity_details"
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
