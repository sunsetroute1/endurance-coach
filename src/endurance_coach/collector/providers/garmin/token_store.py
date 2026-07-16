"""Garmin token store — reads tokens created by garmin_mcp auth."""

from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import UUID

from garminconnect import Garmin, GarminConnectConnectionError

from endurance_coach.collector.providers.garmin.setup import garmin_setup_instructions
from endurance_coach.domain.enums import DataProviderType
from endurance_coach.domain.models import ProviderSetupInstructions, TokenReference

GARMIN_TOKEN_FILE = "garmin_tokens.json"


class GarminTokenStore:
    """Resolves and validates the shared garmin_mcp token directory."""

    def __init__(self, token_path: Path) -> None:
        self._token_path = token_path.expanduser()

    @property
    def token_path(self) -> Path:
        return self._token_path

    def token_file_exists(self) -> bool:
        return self._token_path.exists() and (
            (self._token_path / GARMIN_TOKEN_FILE).exists() or self._token_path.is_file()
        )

    async def get_reference(
        self,
        user_id: UUID,
        provider: DataProviderType,
    ) -> TokenReference | None:
        if provider != DataProviderType.GARMIN or not self.token_file_exists():
            return None

        return TokenReference(
            provider=provider,
            reference_path=str(self._token_path),
            metadata={"token_file": GARMIN_TOKEN_FILE},
        )

    async def is_authenticated(
        self,
        user_id: UUID,
        provider: DataProviderType,
    ) -> bool:
        if provider != DataProviderType.GARMIN:
            return False
        valid, _ = await self.validate_tokens()
        return valid

    def get_setup_instructions(
        self,
        provider: DataProviderType,
    ) -> ProviderSetupInstructions:
        return garmin_setup_instructions(self._token_path)

    async def validate_tokens(self) -> tuple[bool, str]:
        return await asyncio.to_thread(self._validate_tokens_sync)

    def _validate_tokens_sync(self) -> tuple[bool, str]:
        if not self.token_file_exists():
            return False, f"Token path not found: {self._token_path}"

        try:
            client = Garmin()
            client.login(str(self._token_path))
            client.get_full_name()
            return True, ""
        except FileNotFoundError:
            return False, f"Token files not found in: {self._token_path}"
        except GarminConnectConnectionError as exc:
            message = str(exc)
            if "401" in message or "Unauthorized" in message:
                return False, "Tokens expired or invalid — re-run garmin-mcp-auth --force-reauth"
            if "mfa" in message.lower():
                return (
                    False,
                    "MFA required — run garmin-mcp-auth in an interactive terminal on the host",
                )
            return False, f"Garmin connection error: {message.split(':')[0]}"
        except Exception as exc:
            message = str(exc)
            if "401" in message:
                return False, "Tokens expired or invalid — re-run garmin-mcp-auth --force-reauth"
            if "mfa" in message.lower():
                return (
                    False,
                    "MFA required — run garmin-mcp-auth in an interactive terminal on the host",
                )
            return False, f"Token validation failed: {message.split(':')[0]}"
