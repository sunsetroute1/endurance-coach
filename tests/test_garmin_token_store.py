"""Tests for Garmin token store."""

from pathlib import Path

import pytest

from endurance_coach.collector.providers.garmin.token_store import (
    GARMIN_TOKEN_FILE,
    GarminTokenStore,
    garmin_auth_pause_reason,
)
from endurance_coach.domain.enums import DataProviderType


@pytest.mark.asyncio
async def test_token_store_missing_tokens(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GARMIN_AUTH_PAUSE_PATH", str(tmp_path / "missing-pause"))
    store = GarminTokenStore(tmp_path)
    assert store.token_file_exists() is False
    valid, error = await store.validate_tokens()
    assert valid is False
    assert "not found" in error.lower()


@pytest.mark.asyncio
async def test_token_store_detects_token_file(tmp_path: Path) -> None:
    token_dir = tmp_path / ".garminconnect"
    token_dir.mkdir()
    (token_dir / GARMIN_TOKEN_FILE).write_text("{}", encoding="utf-8")

    store = GarminTokenStore(token_dir)
    assert store.token_file_exists() is True

    reference = await store.get_reference(
        user_id=__import__("uuid").uuid4(),
        provider=DataProviderType.GARMIN,
    )
    assert reference is not None
    assert reference.reference_path == str(token_dir)


def test_auth_pause_reason_detects_chained_401() -> None:
    cause = Exception("API Error 401 -")
    outer = Exception("Failed to retrieve social profile")
    outer.__cause__ = cause

    reason = garmin_auth_pause_reason(outer)

    assert reason is not None
    assert "401" in reason


def test_auth_pause_reason_detects_rate_limit() -> None:
    reason = garmin_auth_pause_reason(Exception("Too many login attempts"))

    assert reason is not None
    assert "429" in reason


def test_auth_pause_reason_leaves_network_errors_retryable() -> None:
    assert garmin_auth_pause_reason(Exception("connection timed out")) is None


@pytest.mark.asyncio
async def test_pause_file_skips_garmin_login(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pause = tmp_path / "garmin-auth.paused"
    pause.write_text("Garmin rejected the saved token (401).\n", encoding="utf-8")
    monkeypatch.setenv("GARMIN_AUTH_PAUSE_PATH", str(pause))

    store = GarminTokenStore(tmp_path / "tokens")
    valid, error = await store.validate_tokens()

    assert valid is False
    assert "401" in error


def test_setup_instructions_reference_garmin_mcp() -> None:
    from endurance_coach.collector.providers.garmin import garmin_setup_instructions

    instructions = garmin_setup_instructions()
    assert instructions.provider == DataProviderType.GARMIN
    assert "garmin-mcp-auth" in (instructions.verify_command or "")
