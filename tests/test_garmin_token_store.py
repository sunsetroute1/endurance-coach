"""Tests for Garmin token store."""

from pathlib import Path

import pytest

from endurance_coach.collector.providers.garmin.token_store import (
    GARMIN_TOKEN_FILE,
    GarminTokenStore,
)
from endurance_coach.domain.enums import DataProviderType


@pytest.mark.asyncio
async def test_token_store_missing_tokens(tmp_path: Path) -> None:
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


def test_setup_instructions_reference_garmin_mcp() -> None:
    from endurance_coach.collector.providers.garmin import garmin_setup_instructions

    instructions = garmin_setup_instructions()
    assert instructions.provider == DataProviderType.GARMIN
    assert "garmin-mcp-auth" in (instructions.verify_command or "")
