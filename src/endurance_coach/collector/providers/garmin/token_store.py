"""Garmin token store — reads tokens created by garmin_mcp auth."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from uuid import UUID

from garminconnect import Garmin, GarminConnectConnectionError

from endurance_coach.collector.providers.garmin.setup import garmin_setup_instructions
from endurance_coach.domain.enums import DataProviderType
from endurance_coach.domain.models import ProviderSetupInstructions, TokenReference

GARMIN_TOKEN_FILE = "garmin_tokens.json"
GARMIN_AUTH_PAUSE_NAME = "garmin-auth.paused"


def garmin_auth_pause_path() -> Path:
    """Host and Docker share this file via the ~/.endurance-coach mount."""
    override = os.environ.get("GARMIN_AUTH_PAUSE_PATH")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".endurance-coach" / GARMIN_AUTH_PAUSE_NAME


def read_garmin_auth_pause() -> str | None:
    path = garmin_auth_pause_path()
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8-sig").strip()
    return text or "Garmin automatic sync is paused until an interactive login succeeds."


def write_garmin_auth_pause(reason: str) -> None:
    path = garmin_auth_pause_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(reason.strip() + "\n", encoding="utf-8")


def clear_garmin_auth_pause() -> bool:
    path = garmin_auth_pause_path()
    if not path.exists():
        return False
    path.unlink()
    return True


def _exception_text(exc: BaseException) -> str:
    parts: list[str] = []
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        parts.append(str(current))
        current = current.__cause__ or current.__context__
    return " ".join(parts)


def garmin_auth_pause_reason(exc: BaseException) -> str | None:
    """Why automatic Garmin logins must stop, or None if the call can be retried."""
    text = _exception_text(exc).lower()
    if "429" in text or "too many" in text or "rate limit" in text:
        return (
            "Garmin rate limited this IP (429). "
            "Automatic sync is paused until scripts/garmin_auth.py succeeds."
        )
    auth_markers = ("401", "unauthorized", "social profile", "authentication failed", "tokens expired")
    if any(marker in text for marker in auth_markers):
        return (
            "Garmin rejected the saved token (401). "
            "Automatic sync is paused until scripts/garmin_auth.py succeeds."
        )
    return None


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
        paused = read_garmin_auth_pause()
        if paused:
            return False, paused

        if not self.token_file_exists():
            return False, f"Token path not found: {self._token_path}"

        try:
            client = Garmin()
            client.login(str(self._token_path))
            client.get_full_name()
            return True, ""
        except FileNotFoundError:
            return False, f"Token files not found in: {self._token_path}"
        except Exception as exc:
            pause_reason = garmin_auth_pause_reason(exc)
            if pause_reason:
                write_garmin_auth_pause(pause_reason)
                return False, pause_reason
            message = _exception_text(exc)
            if "mfa" in message.lower():
                mfa = "MFA required — run garmin-mcp-auth in an interactive terminal on the host"
                write_garmin_auth_pause(mfa)
                return False, mfa
            if isinstance(exc, GarminConnectConnectionError):
                return False, f"Garmin connection error: {message.split(':')[0]}"
            return False, f"Token validation failed: {message.split(':')[0]}"
