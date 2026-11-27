#!/usr/bin/env python3
"""Interactive Garmin Connect login — saves OAuth tokens for endurance-coach.

Equivalent to garmin-mcp-auth using the already-installed garminconnect library.
Run in a real terminal (MFA prompt requires keyboard input).
"""

from __future__ import annotations

import getpass
import logging
import os
import sys
from pathlib import Path


def _token_dir() -> Path:
    raw = os.environ.get("GARMIN_TOKEN_PATH", "~/.garminconnect")
    return Path(raw).expanduser()


def _prompt_mfa() -> str:
    print(
        "\nGarmin asked for a verification code and the login client has requested it."
    )
    print("Check text messages first, then email, including spam.")
    print(
        "If an authenticator app was set up for Garmin, use the current 6-digit code "
        "shown in that app. That code is not sent as a text or a push."
    )
    return input("Enter MFA code: ").strip()


def _retire_rejected_tokens(token_dir: Path) -> None:
    """Move a saved login Garmin has already rejected out of the way."""
    token_file = token_dir / "garmin_tokens.json"
    if not token_file.is_file():
        return
    retired = token_dir / "garmin_tokens.rejected.json"
    retired.unlink(missing_ok=True)
    token_file.replace(retired)
    print("Set aside the saved Garmin login. A fresh sign-in will replace it.")


def _stop_when_signin_page_returns(client) -> None:
    from endurance_coach.garmin.phone_login import stop_when_signin_page_returns

    stop_when_signin_page_returns(client)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    token_dir = _token_dir()
    token_dir.mkdir(parents=True, exist_ok=True)
    token_path = str(token_dir)

    print(f"Garmin token directory: {token_dir}")
    print("Credentials are sent to Garmin only — not stored by endurance-coach.\n")

    env_email = os.environ.get("GARMIN_EMAIL")
    env_password = os.environ.get("GARMIN_PASSWORD")
    if env_email or env_password:
        used = []
        if env_email:
            used.append("email from GARMIN_EMAIL")
        if env_password:
            used.append("password from GARMIN_PASSWORD")
        print("Using " + " and ".join(used) + ".")

    email = (env_email or input("Garmin email or username: ")).strip()
    password = env_password or getpass.getpass("Garmin password: ")

    if not email or not password:
        print("Email and password are required.", file=sys.stderr)
        return 1

    print(f"Signing in as: {email}")
    print(f"Password length: {len(password)} characters")

    _retire_rejected_tokens(token_dir)

    from garminconnect import Garmin

    client = Garmin(email=email, password=password, prompt_mfa=_prompt_mfa)
    _stop_when_signin_page_returns(client)
    print("\nLogging in...")

    try:
        status, _ = client.login(tokenstore=token_path)
        if status == "needs_mfa":
            print("MFA still required — re-run and enter the code when prompted.", file=sys.stderr)
            return 1
        name = client.get_full_name()
        state_dir = Path.home() / ".endurance-coach"
        pause = state_dir / "garmin-auth.paused"
        if pause.exists():
            pause.unlink()
            print(f"Cleared automatic-sync pause: {pause}")
        retry = state_dir / "garmin-auth.retry"
        if retry.exists():
            retry.unlink()
        print(f"\nSuccess. Logged in as: {name}")
        print(f"Tokens saved to: {token_dir / 'garmin_tokens.json'}")
        print("\nNext steps:")
        print("  curl http://localhost:8000/api/v1/providers/garmin/status")
        print("  curl -X POST http://localhost:8000/api/v1/sync/garmin")
        return 0
    except Exception as exc:
        print(f"\nLogin failed: {exc}", file=sys.stderr)
        message = str(exc)
        if (
            "Invalid Username or Password" in message
            or "were not accepted" in message
            or "authentication failed" in message.lower()
        ):
            print(
                f"Garmin rejected the sign-in for {email} "
                f"({len(password)} character password).",
                file=sys.stderr,
            )
            print(
                "Match that address and character count with the login that works "
                "at https://connect.garmin.com. Wait before trying again. "
                "Another attempt now extends the Cloudflare block.",
                file=sys.stderr,
            )
        print("\nTips:")
        print("  - Run this in PowerShell/WSL, not inside a background Docker container")
        print("  - If rate-limited (429), wait 15-30 min or try a different network")
        print("  - Re-run after fixing: python scripts/garmin_auth.py")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
