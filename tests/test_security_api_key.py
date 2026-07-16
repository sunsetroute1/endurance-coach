"""Tests for API key security."""

import pytest

from endurance_coach.security.api_key import StaticBearerTokenVerifier, verify_bearer_token


@pytest.mark.asyncio
async def test_static_bearer_token_verifier_accepts_valid_key() -> None:
    verifier = StaticBearerTokenVerifier("secret-token")
    result = await verifier.verify_token("secret-token")
    assert result is not None
    assert result.client_id == "endurance-coach"


@pytest.mark.asyncio
async def test_static_bearer_token_verifier_rejects_invalid_key() -> None:
    verifier = StaticBearerTokenVerifier("secret-token")
    result = await verifier.verify_token("wrong-token")
    assert result is None


def test_verify_bearer_token_without_configured_key() -> None:
    assert verify_bearer_token(None, None) is True
    assert verify_bearer_token("Bearer anything", None) is True


def test_verify_bearer_token_with_configured_key() -> None:
    assert verify_bearer_token("Bearer good-key", "good-key") is True
    assert verify_bearer_token("Bearer bad-key", "good-key") is False
    assert verify_bearer_token(None, "good-key") is False
