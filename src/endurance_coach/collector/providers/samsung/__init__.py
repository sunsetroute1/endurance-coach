"""Samsung Health import provider (Android SDK companion uploads)."""

from endurance_coach.collector.providers.samsung.import_service import SamsungHealthImportService
from endurance_coach.collector.providers.samsung.provider import (
    SUPPORTED_RESOURCES,
    SamsungHealthDataProvider,
)
from endurance_coach.collector.providers.samsung.setup import samsung_setup_instructions

__all__ = [
    "SUPPORTED_RESOURCES",
    "SamsungHealthDataProvider",
    "SamsungHealthImportService",
    "samsung_setup_instructions",
]
