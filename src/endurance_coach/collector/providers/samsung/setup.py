"""Samsung Health setup instructions for operators."""

from __future__ import annotations

from endurance_coach.domain.enums import DataProviderType
from endurance_coach.domain.models import ProviderSetupInstructions


def samsung_setup_instructions(import_dir: str, public_base_url: str) -> ProviderSetupInstructions:
    return ProviderSetupInstructions(
        provider=DataProviderType.SAMSUNG_HEALTH,
        summary=(
            "Samsung Health data is read on your Android phone via Samsung Health Data SDK "
            "and uploaded to this server."
        ),
        steps=(
            "Install the Endurance Coach Samsung Health Sync app on your Android phone "
            "(see docs/SAMSUNG_HEALTH.md).",
            "Enable Samsung Health Data SDK developer mode and grant read permissions in Samsung Health.",
            f"Set the sync app API URL to {public_base_url.rstrip('/')}/api/v1/sync/samsung/import "
            "and paste your API_SECRET_KEY.",
            "Run a historical sync from the phone app, then POST /api/v1/process on the server.",
            f"Optional: drop JSON batch files into {import_dir} and call POST /api/v1/sync/samsung.",
        ),
    )
