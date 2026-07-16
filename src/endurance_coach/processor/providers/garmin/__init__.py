"""Garmin processor providers."""

from endurance_coach.processor.providers.garmin.normalizers import (
    GarminActivityNormalizer,
    GarminBodyBatteryNormalizer,
    GarminHRVNormalizer,
    GarminReadinessNormalizer,
    GarminSleepNormalizer,
    GarminStepsNormalizer,
    GarminStressNormalizer,
)

__all__ = [
    "GarminActivityNormalizer",
    "GarminBodyBatteryNormalizer",
    "GarminHRVNormalizer",
    "GarminReadinessNormalizer",
    "GarminSleepNormalizer",
    "GarminStepsNormalizer",
    "GarminStressNormalizer",
]
