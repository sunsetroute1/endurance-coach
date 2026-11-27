"""Phone Garmin sign-in page and one-time alert link."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from endurance_coach.api.main import app
from endurance_coach.config import get_settings
from endurance_coach.garmin.phone_login import (
    LoginResult,
    grant_is_valid,
    grant_path,
    reset_phone_login_state,
    start_phone_login,
    submit_phone_code,
)


class _Dump:
    def __init__(self, calls: list[str]) -> None:
        self._calls = calls

    def dump(self, path: str) -> None:
        self._calls.append(path)
        Path(path, "garmin_tokens.json").write_text("{}", encoding="utf-8")


class _Client:
    def __init__(self, email: str, password: str) -> None:
        self.email = email
        self.password = password
        self.full_name = "Ada Lovelace"
        self.client = _Dump([])
        self.codes: list[str] = []

    def login(self) -> tuple[str, dict[str, str]]:
        return "needs_mfa", {"flow": "widget"}

    def resume_login(self, state: dict[str, str], code: str) -> tuple[None, None]:
        self.codes.append(code)
        if code != "123456":
            from garminconnect.exceptions import GarminConnectAuthenticationError

            raise GarminConnectAuthenticationError("bad code")
        return None, None

    def get_full_name(self) -> str:
        return self.full_name


def _pause_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("GARMIN_AUTH_PAUSE_PATH", str(tmp_path / "garmin-auth.paused"))


def test_grant_rejects_a_missing_or_expired_token(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _pause_env(monkeypatch, tmp_path)
    assert grant_is_valid("anything") is False
    grant_path().write_text(
        json.dumps(
            {
                "token": "abc",
                "expires_at": (datetime.now(UTC) - timedelta(minutes=1)).isoformat(),
            }
        ),
        encoding="utf-8",
    )
    assert grant_is_valid("abc") is False
    grant_path().write_text(
        json.dumps(
            {
                "token": "abc",
                "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
            }
        ),
        encoding="utf-8",
    )
    assert grant_is_valid("abc") is True
    assert grant_is_valid("nope") is False


def test_code_saves_token_and_clears_the_pause(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _pause_env(monkeypatch, tmp_path)
    pause = tmp_path / "garmin-auth.paused"
    pause.write_text("paused\n", encoding="utf-8")
    (tmp_path / "garmin-auth.retry").write_text("last_attempt=x\n", encoding="utf-8")
    grant_path().write_text(
        json.dumps({"token": "grant", "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat()}),
        encoding="utf-8",
    )
    reset_phone_login_state()
    started = start_phone_login(
        "ada@example.com",
        "secret",
        tmp_path / "tokens",
        client_factory=_Client,
    )
    assert started.status == "needs_mfa"
    assert started.login_id
    with pytest.raises(Exception, match="verification code"):
        submit_phone_code(started.login_id, "000000", tmp_path / "tokens")
    finished = submit_phone_code(started.login_id, "123456", tmp_path / "tokens")
    assert finished.name == "Ada Lovelace"
    assert (tmp_path / "tokens" / "garmin_tokens.json").is_file()
    assert not pause.exists()
    assert not (tmp_path / "garmin-auth.retry").exists()
    assert not grant_path().exists()
    reset_phone_login_state()


def test_login_page_is_public_and_posts_require_the_alert_grant(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _pause_env(monkeypatch, tmp_path)
    monkeypatch.setenv("API_SECRET_KEY", "test-secret")
    get_settings.cache_clear()
    grant_path().write_text(
        json.dumps({"token": "phone-grant", "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat()}),
        encoding="utf-8",
    )

    def fake_start(email: str, password: str, token_dir: Path) -> LoginResult:
        assert email == "ada@example.com"
        assert password == "secret"
        return LoginResult(status="needs_mfa", login_id="login-1", message="Enter the code.")

    monkeypatch.setattr("endurance_coach.api.routes.garmin.start_phone_login", fake_start)

    with TestClient(app) as client:
        page = client.get("/api/v1/garmin/login")
        assert page.status_code == 200
        assert "Garmin sign-in" in page.text
        assert "phone-grant" not in page.text

        denied = client.post(
            "/api/v1/garmin/login",
            json={"email": "ada@example.com", "password": "secret"},
        )
        assert denied.status_code == 401

        accepted = client.post(
            "/api/v1/garmin/login",
            headers={"X-Garmin-Login-Grant": "phone-grant"},
            json={"email": "ada@example.com", "password": "secret"},
        )
        assert accepted.status_code == 200
        assert accepted.json()["status"] == "needs_mfa"
        assert accepted.json()["login_id"] == "login-1"

    get_settings.cache_clear()
