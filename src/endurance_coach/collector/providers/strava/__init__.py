"""Strava provider package."""

from endurance_coach.collector.providers.strava.provider import SUPPORTED_RESOURCES, StravaDataProvider
from endurance_coach.collector.providers.strava.setup import strava_authorize_url, strava_setup_instructions
from endurance_coach.collector.providers.strava.token_store import StravaTokenStore

__all__ = [
    "SUPPORTED_RESOURCES",
    "StravaDataProvider",
    "StravaTokenStore",
    "strava_authorize_url",
    "strava_setup_instructions",
]
