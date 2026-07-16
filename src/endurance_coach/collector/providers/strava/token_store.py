"""Strava OAuth token storage and refresh."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

import httpx

from endurance_coach.collector.providers.strava.setup import strava_setup_instructions
from endurance_coach.domain.enums import DataProviderType
from endurance_coach.domain.models import ProviderSetupInstructions, TokenReference

STRAVA_TOKEN_FILENAME = "strava_tokens.json"
STRAVA_TOKEN_URL = "https://www.strava.com/oauth/token"


@dataclass(frozen=True)
class StravaTokenData:
    access_token: str
    refresh_token: str
    expires_at: int
    athlete_id: int | None = None

    def is_expired(self, *, buffer_seconds: int = 300) -> bool:
        return int(time.time()) >= (self.expires_at - buffer_seconds)

    def to_dict(self) -> dict[str, object]:
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_at": self.expires_at,
            "athlete_id": self.athlete_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> StravaTokenData:
        return cls(
            access_token=str(data["access_token"]),
            refresh_token=str(data["refresh_token"]),
            expires_at=int(data["expires_at"]),
            athlete_id=int(data["athlete_id"]) if data.get("athlete_id") is not None else None,
        )

    @classmethod
    def from_oauth_response(cls, payload: dict[str, object]) -> StravaTokenData:
        expires_at = int(time.time()) + int(payload.get("expires_in", 0))
        athlete = payload.get("athlete")
        athlete_id = None
        if isinstance(athlete, dict) and athlete.get("id") is not None:
            athlete_id = int(athlete["id"])
        return cls(
            access_token=str(payload["access_token"]),
            refresh_token=str(payload["refresh_token"]),
            expires_at=expires_at,
            athlete_id=athlete_id,
        )


class StravaTokenStore:
    """Manages Strava OAuth tokens on disk — never stores client secret here."""

    def __init__(
        self,
        token_path: Path,
        *,
        client_id: str,
        client_secret: str,
    ) -> None:
        self._token_path = token_path.expanduser()
        self._client_id = client_id
        self._client_secret = client_secret

    @property
    def token_path(self) -> Path:
        return self._token_path

    @property
    def token_file(self) -> Path:
        if self._token_path.is_dir():
            return self._token_path / STRAVA_TOKEN_FILENAME
        return self._token_path

    def token_file_exists(self) -> bool:
        return self.token_file.exists()

    def load_tokens(self) -> StravaTokenData | None:
        if not self.token_file_exists():
            return None
        data = json.loads(self.token_file.read_text(encoding="utf-8"))
        return StravaTokenData.from_dict(data)

    def save_tokens(self, tokens: StravaTokenData) -> None:
        self.token_file.parent.mkdir(parents=True, exist_ok=True)
        self.token_file.write_text(
            json.dumps(tokens.to_dict(), indent=2),
            encoding="utf-8",
        )

    async def exchange_code(self, code: str) -> StravaTokenData:
        payload = await self._token_request(
            {
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "code": code,
                "grant_type": "authorization_code",
            }
        )
        tokens = StravaTokenData.from_oauth_response(payload)
        self.save_tokens(tokens)
        return tokens

    async def refresh_tokens(self, tokens: StravaTokenData) -> StravaTokenData:
        payload = await self._token_request(
            {
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "refresh_token": tokens.refresh_token,
                "grant_type": "refresh_token",
            }
        )
        refreshed = StravaTokenData.from_oauth_response(payload)
        self.save_tokens(refreshed)
        return refreshed

    async def get_valid_tokens(self) -> StravaTokenData | None:
        tokens = self.load_tokens()
        if tokens is None:
            return None
        if tokens.is_expired():
            if not self._client_id or not self._client_secret:
                return None
            tokens = await self.refresh_tokens(tokens)
        return tokens

    async def get_reference(
        self,
        user_id: UUID,
        provider: DataProviderType,
    ) -> TokenReference | None:
        if provider != DataProviderType.STRAVA or not self.token_file_exists():
            return None
        return TokenReference(
            provider=provider,
            reference_path=str(self.token_file),
            metadata={
                "athlete_id": str(tokens.athlete_id)
                if (tokens := self.load_tokens()) and tokens.athlete_id is not None
                else ""
            },
        )

    async def is_authenticated(
        self,
        user_id: UUID,
        provider: DataProviderType,
    ) -> bool:
        if provider != DataProviderType.STRAVA:
            return False
        valid, _ = await self.validate_tokens()
        return valid

    def get_setup_instructions(
        self,
        provider: DataProviderType,
    ) -> ProviderSetupInstructions:
        return strava_setup_instructions()

    async def validate_tokens(self) -> tuple[bool, str]:
        if not self._client_id or not self._client_secret:
            return False, "STRAVA_CLIENT_ID and STRAVA_CLIENT_SECRET are required"
        if not self.token_file_exists():
            return False, f"Token file not found: {self.token_file}"

        try:
            tokens = await self.get_valid_tokens()
            if tokens is None:
                return False, "Unable to load or refresh Strava tokens"
            return True, ""
        except httpx.HTTPStatusError as exc:
            return False, f"Strava token refresh failed: {exc.response.status_code}"
        except Exception as exc:
            return False, f"Strava token validation failed: {str(exc).split(':')[0]}"

    async def _token_request(self, data: dict[str, str]) -> dict[str, object]:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(STRAVA_TOKEN_URL, data=data)
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("Unexpected Strava token response")
            return payload
