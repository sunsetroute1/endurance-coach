# Garmin Authentication (including 2FA)

Sign in with `python scripts/garmin_auth.py` on the server, or from the phone link in a sync alert. The password is used for that sign-in only and is not stored. Tokens are saved to `~/.garminconnect` (or `GARMIN_TOKEN_PATH`). Scheduled sync and the API read those tokens afterward.

Accounts with 2FA are supported. Garmin asks for a verification code during that same sign-in.

---

## Sign in from your phone

When Garmin rejects the saved token, the sync alert includes a sign-in link. Open it on your phone, enter the Garmin email and password, then the verification code if Garmin asks for one. Leave the server VPN off until the page says you are signed in.

The link stays valid for 12 hours. The desktop shortcut **Garmin Login** starts `scripts/garmin_auth.py` when you are at the server.

## Sign in at the server

Run this in a real terminal, not inside the API or MCP container:

```bash
python scripts/garmin_auth.py
```

You will be prompted for:

- Email
- Password
- Verification code, if Garmin asks for one

## Token refresh

When tokens expire or you change your Garmin password, use the phone link or:

```bash
python scripts/garmin_auth.py
```

## Docker

`docker-compose.yml` bind-mounts the host token directory:

- The API container mounts `${USERPROFILE}/.garminconnect` writable, so a phone sign-in can save a new token.
- The MCP container mounts the same directory read-only.

Both containers mount `${USERPROFILE}/.endurance-coach` writable. That directory holds the sync pause and the one-time phone sign-in grant. It does not hold the Garmin password.

## Check status and sync

```bash
curl https://example.duckdns.org/api/v1/providers/garmin/status
curl -X POST https://example.duckdns.org/api/v1/sync/garmin
```

Use the bearer token from `API_SECRET_KEY`.

---

## Troubleshooting

| Problem | Solution |
|---------|------------|
| Saved token rejected | Open the phone link from the alert, or run `python scripts/garmin_auth.py` on the server with the VPN off |
| Garmin rate-limits login (429) | Wait 15 minutes with the VPN off, then try the sign-in page again |
| Sync works on the host but not in Docker | Confirm the API container can read `~/.garminconnect` at `/root/.garminconnect` |

---

## Security Notes

- **Never** put the Garmin email or password in `.env` or Docker Compose
- Tokens in `~/.garminconnect` are the credential — treat them like a password
- The API container can write `~/.garminconnect` so a phone sign-in can save a new token. The MCP container still mounts that directory read-only.
- This app stores **no** Garmin passwords in PostgreSQL
- The phone sign-in posts are accepted only with the API bearer token or the one-time grant from the alert. The sign-in page itself is public so the phone can load the form.

## What we deliberately don't build

The phone page and `scripts/garmin_auth.py` both use the installed `garminconnect` login. The app does not store the Garmin password and does not implement its own OAuth server.
