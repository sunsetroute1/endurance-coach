"""Garmin setup instructions and constants."""

from pathlib import Path

from endurance_coach.domain.enums import DataProviderType
from endurance_coach.domain.models import ProviderSetupInstructions

GARMIN_MCP_AUTH_COMMAND = (
    "uvx --python 3.12 --from git+https://github.com/Taxuspt/garmin_mcp garmin-mcp-auth"
)

GARMIN_MCP_VERIFY_COMMAND = (
    "uvx --python 3.12 --from git+https://github.com/Taxuspt/garmin_mcp garmin-mcp-auth --verify"
)

GARMIN_MCP_FORCE_REAUTH_COMMAND = (
    "uvx --python 3.12 --from git+https://github.com/Taxuspt/garmin_mcp "
    "garmin-mcp-auth --force-reauth"
)


def garmin_setup_instructions(token_path: Path | None = None) -> ProviderSetupInstructions:
    path = token_path or Path.home() / ".garminconnect"
    return ProviderSetupInstructions(
        provider=DataProviderType.GARMIN,
        summary=(
            "Authenticate with Taxuspt/garmin_mcp in an interactive terminal. "
            "2FA/MFA is handled during this one-time login — not by the API server."
        ),
        steps=(
            "Open a terminal on the host (not inside a background Docker service).",
            f"Run: {GARMIN_MCP_AUTH_COMMAND}",
            "Enter Garmin email, password, and MFA code when prompted (app or email).",
            f"Confirm tokens exist at {path}",
            f"Set GARMIN_TOKEN_PATH={path} in your .env file.",
            "Mount the token directory read-only into Docker containers.",
            "Re-run with --force-reauth when tokens expire (~6 months) or after a password change.",
        ),
        verify_command=GARMIN_MCP_VERIFY_COMMAND,
    )
