"""Garmin provider package."""

from endurance_coach.collector.providers.garmin.client import GarminClient
from endurance_coach.collector.providers.garmin.provider import GarminDataProvider
from endurance_coach.collector.providers.garmin.setup import (
    GARMIN_MCP_AUTH_COMMAND,
    GARMIN_MCP_FORCE_REAUTH_COMMAND,
    GARMIN_MCP_VERIFY_COMMAND,
    garmin_setup_instructions,
)
from endurance_coach.collector.providers.garmin.token_store import GarminTokenStore

__all__ = [
    "GARMIN_MCP_AUTH_COMMAND",
    "GARMIN_MCP_FORCE_REAUTH_COMMAND",
    "GARMIN_MCP_VERIFY_COMMAND",
    "GarminClient",
    "GarminDataProvider",
    "GarminTokenStore",
    "garmin_setup_instructions",
]
