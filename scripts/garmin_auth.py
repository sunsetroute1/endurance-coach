#!/usr/bin/env python3
"""Interactive Garmin Connect login — saves OAuth tokens for endurance-coach.

Equivalent to garmin-mcp-auth using the already-installed garminconnect library.
Run in a real terminal (MFA prompt requires keyboard input).
"""

from __future__ import annotations

import getpass
import os
import sys
from pathlib import Path


def _token_dir() -> Path:
    raw = os.environ.get("GARMIN_TOKEN_PATH", "~/.garminconnect")
    return Path(raw).expanduser()


def _prompt_mfa() -> str:
    print("\nGarmin 2FA required. Check your authenticator app or email.")
    return input("Enter MFA code: ").strip()


def main() -> int:
    token_dir = _token_dir()
    token_dir.mkdir(parents=True, exist_ok=True)
    token_path = str(token_dir)

    print(f"Garmin token directory: {token_dir}")
    print("Credentials are sent to Garmin only — not stored by endurance-coach.\n")

    email = os.environ.get("GARMIN_EMAIL") or input("Garmin email: ").strip()
    password = os.environ.get("GARMIN_PASSWORD") or getpass.getpass("Garmin password: ")

    if not email or not password:
        print("Email and password are required.", file=sys.stderr)
        return 1

    from garminconnect import Garmin

    client = Garmin(email=email, password=password, prompt_mfa=_prompt_mfa)
    print("\nLogging in (this may take a minute if Garmin rate-limits)...")

    try:
        status, _ = client.login(tokenstore=token_path)
        if status == "needs_mfa":
            print("MFA still required — re-run and enter the code when prompted.", file=sys.stderr)
            return 1
        name = client.get_full_name()
        print(f"\nSuccess. Logged in as: {name}")
        print(f"Tokens saved to: {token_dir / 'garmin_tokens.json'}")
        print("\nNext steps:")
        print("  curl http://localhost:8000/api/v1/providers/garmin/status")
        print("  curl -X POST http://localhost:8000/api/v1/sync/garmin")
        return 0
    except Exception as exc:
        print(f"\nLogin failed: {exc}", file=sys.stderr)
        print("\nTips:")
        print("  - Run this in PowerShell/WSL, not inside a background Docker container")
        print("  - If rate-limited (429), wait 15-30 min or try a different network")
        print("  - Re-run after fixing: python scripts/garmin_auth.py")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
