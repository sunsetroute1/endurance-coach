"""Strava provider setup instructions."""

from __future__ import annotations

from endurance_coach.domain.enums import DataProviderType
from endurance_coach.domain.models import ProviderSetupInstructions

STRAVA_OAUTH_SCOPES = "activity:read_all,read"


def strava_authorize_url(
    *,
    client_id: str,
    redirect_uri: str,
) -> str:
    from urllib.parse import urlencode

    params = urlencode(
        {
            "client_id": client_id,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "approval_prompt": "auto",
            "scope": STRAVA_OAUTH_SCOPES,
        }
    )
    return f"https://www.strava.com/oauth/authorize?{params}"


def strava_setup_instructions() -> ProviderSetupInstructions:
    return ProviderSetupInstructions(
        provider=DataProviderType.STRAVA,
        summary="Connect Strava via OAuth2 at /api/v1/providers/strava/connect.",
        steps=(
            "Create a Strava API application at https://www.strava.com/settings/api",
            "Set Authorization Callback Domain to your deployment host",
            "Set STRAVA_CLIENT_ID and STRAVA_CLIENT_SECRET in .env",
            "Visit GET /api/v1/providers/strava/connect to authorize",
            "Trigger POST /api/v1/sync/strava to pull activities",
        ),
        verify_command="GET /api/v1/providers/strava/status",
    )
