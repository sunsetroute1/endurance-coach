"""Phone sign-in for a rejected Garmin token.

The password is used for one Garmin login call and is not written to disk.
A verification code, when Garmin asks for one, completes that same login.
"""

from __future__ import annotations

import json
import logging
import secrets
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from endurance_coach.collector.providers.garmin.token_store import (
    clear_garmin_auth_pause,
    garmin_auth_pause_path,
)

logger = logging.getLogger(__name__)

GRANT_NAME = "garmin-login-grant.json"
RETRY_NAME = "garmin-auth.retry"
GRANT_HEADER = "x-garmin-login-grant"
MFA_TTL = timedelta(minutes=10)

_pending_lock = threading.Lock()
_call_lock = threading.Lock()
_pending: dict[str, PendingLogin] = {}


class PhoneLoginError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


@dataclass
class PendingLogin:
    client: Any
    state: Any
    created_at: datetime


@dataclass(frozen=True)
class LoginResult:
    status: str
    message: str
    login_id: str | None = None
    name: str | None = None


def grant_path() -> Path:
    return garmin_auth_pause_path().parent / GRANT_NAME


def grant_is_valid(token: str | None) -> bool:
    if not token:
        return False
    path = grant_path()
    if not path.is_file():
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        expected = str(payload["token"])
        expires = datetime.fromisoformat(str(payload["expires_at"]))
    except (OSError, ValueError, KeyError, TypeError):
        return False
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    if expires < datetime.now(UTC):
        return False
    return secrets.compare_digest(token, expected)


def stop_when_signin_page_returns(client: Any) -> None:
    """Stop when Garmin shows the sign-in form again instead of a code prompt."""
    from garminconnect.exceptions import (
        GarminConnectAuthenticationError,
        GarminConnectConnectionError,
    )

    original = client.client._widget_web_login

    def _widget_web_login(email: str, password: str) -> None:
        try:
            original(email, password)
        except GarminConnectConnectionError as exc:
            if "unexpected title 'GARMIN Authentication Application'" in str(exc):
                raise GarminConnectAuthenticationError(
                    "Garmin showed the sign-in page again and did not send a "
                    "verification code. The username and password were not accepted."
                ) from exc
            raise

    client.client._widget_web_login = _widget_web_login


def start_phone_login(
    email: str,
    password: str,
    token_dir: Path,
    client_factory: Any = None,
) -> LoginResult:
    email = email.strip()
    if not email or not password:
        raise PhoneLoginError("Email and password are required.", 400)

    if client_factory is None:
        from garminconnect import Garmin

        client = Garmin(email=email, password=password, return_on_mfa=True)
        stop_when_signin_page_returns(client)
    else:
        client = client_factory(email, password)
    with _call_lock:
        try:
            status, state = client.login()
        except Exception as exc:
            raise _as_phone_error(exc, mfa=False) from exc
        finally:
            client.password = None
        if status == "needs_mfa":
            login_id = secrets.token_urlsafe(18)
            with _pending_lock:
                _pending.clear()
                _pending[login_id] = PendingLogin(
                    client=client,
                    state=state,
                    created_at=datetime.now(UTC),
                )
            return LoginResult(
                status="needs_mfa",
                login_id=login_id,
                message=(
                    "Garmin sent a verification code. Check your text messages "
                    "first, then email. If you use an authenticator app, enter "
                    "the current code from that app."
                ),
            )
        name = _save_and_finish(client, token_dir)
    return LoginResult(
        status="ok",
        name=name,
        message=f"Signed in as {name}. Sync will resume on the next run.",
    )


def submit_phone_code(login_id: str, code: str, token_dir: Path) -> LoginResult:
    code = code.strip()
    if not code:
        raise PhoneLoginError("Enter the verification code.", 400)
    with _pending_lock:
        pending = _pending.get(login_id)
    if pending is None or datetime.now(UTC) - pending.created_at > MFA_TTL:
        with _pending_lock:
            _pending.pop(login_id, None)
        raise PhoneLoginError(
            "That sign-in session expired. Enter your email and password again.",
            410,
        )
    with _call_lock:
        try:
            pending.client.resume_login(pending.state, code)
        except Exception as exc:
            raise _as_phone_error(exc, mfa=True) from exc
        name = _save_and_finish(pending.client, token_dir)
        with _pending_lock:
            _pending.pop(login_id, None)
    return LoginResult(
        status="ok",
        name=name,
        message=f"Signed in as {name}. Sync will resume on the next run.",
    )


def reset_phone_login_state() -> None:
    with _pending_lock:
        _pending.clear()


def _save_and_finish(client: Any, token_dir: Path) -> str:
    directory = token_dir.expanduser()
    try:
        directory.mkdir(parents=True, exist_ok=True)
        client.client.dump(str(directory))
    except OSError as exc:
        raise PhoneLoginError(
            "The server could not save the new Garmin token.",
            500,
        ) from exc
    clear_garmin_auth_pause()
    retry = garmin_auth_pause_path().parent / RETRY_NAME
    retry.unlink(missing_ok=True)
    grant_path().unlink(missing_ok=True)
    name = client.get_full_name()
    return name or "your Garmin account"


def _as_phone_error(exc: Exception, *, mfa: bool) -> PhoneLoginError:
    from garminconnect.exceptions import (
        GarminConnectAuthenticationError,
        GarminConnectTooManyRequestsError,
    )

    if isinstance(exc, PhoneLoginError):
        return exc
    text = str(exc)
    logger.warning("Garmin phone login failed: %s", text.splitlines()[0][:300])
    if isinstance(exc, GarminConnectTooManyRequestsError) or "429" in text or "427" in text:
        return PhoneLoginError(
            "Garmin is limiting login attempts. Wait 15 minutes, with the VPN off, and try again.",
            429,
        )
    if isinstance(exc, GarminConnectAuthenticationError):
        if mfa and "were not accepted" not in text and "Invalid Username" not in text:
            return PhoneLoginError(
                "That verification code was not accepted. Enter the current code.",
                401,
            )
        if "were not accepted" in text:
            return PhoneLoginError(text, 401)
        return PhoneLoginError("Garmin did not accept that email and password.", 401)
    return PhoneLoginError(
        "Garmin login failed. Wait a few minutes, with the VPN off, and try again.",
        502,
    )
