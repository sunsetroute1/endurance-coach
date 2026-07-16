"""Application configuration via environment variables."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "development"
    app_debug: bool = False
    log_level: str = "INFO"

    database_url: str = "postgresql+asyncpg://endurance:endurance@localhost:5432/endurance_coach"

    api_host: str = "127.0.0.1"
    api_port: int = 8000

    mcp_transport: str = "stdio"
    mcp_host: str = "127.0.0.1"
    mcp_port: int = 8080

    api_secret_key: str | None = None

    garmin_token_path: Path = Field(default=Path.home() / ".garminconnect")
    garmin_mcp_enabled: bool = True
    garmin_sync_days: int = 30
    garmin_backfill_delay_seconds: float = 1.5
    garmin_backfill_batch_size: int = 10

    strava_client_id: str = ""
    strava_client_secret: str = ""
    strava_token_path: Path = Field(
        default=Path.home() / ".endurance-coach" / "strava_tokens.json"
    )
    strava_sync_days: int = 30

    public_base_url: str = "http://127.0.0.1:8000"
    default_user_email: str = "athlete@localhost"
    app_timezone: str = "America/Denver"

    @field_validator("public_base_url", mode="before")
    @classmethod
    def _default_public_base_url(cls, value: object) -> str:
        if value is None or (isinstance(value, str) and not value.strip()):
            return "http://127.0.0.1:8000"
        return str(value).rstrip("/")

    coach_llm_provider: str = "openai"
    coach_llm_model: str = "gpt-4o-mini"
    coach_llm_base_url: str | None = None
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None

    @property
    def strava_redirect_uri(self) -> str:
        return f"{self.public_base_url.rstrip('/')}/api/v1/providers/strava/callback"


@lru_cache
def get_settings() -> Settings:
    return Settings()
