# Garmin Authentication (including 2FA)

Sign in with `python scripts/garmin_auth.py` on the server, or from the phone link in a sync alert. The password is used for that sign-in only and is not stored. Tokens are saved to `~/.garminconnect` (or `GARMIN_TOKEN_PATH`). Scheduled sync and the API read those tokens afterward.

Accounts with 2FA are supported. Garmin asks for a verification code during that same sign-in.

---

## Sign in from your phone

When Garmin rejects the saved token, the scheduled sync sends one alert. The default service is [ntfy.sh](https://ntfy.sh), which is free. Install the ntfy app and subscribe to `GARMIN_ALERT_NTFY_TOPIC`. An optional ntfy access token also emails that alert to the address on the ntfy account. The installer can switch the alert to your own SMTP server, or to an HTTPS webhook for an SMS provider or another service. More than one can be listed in `GARMIN_ALERT_PROVIDER`, for example `ntfy,email`. `none` turns alerts off.

The alert does not contain the Garmin password. Its link opens `PUBLIC_BASE_URL/api/v1/garmin/login`, a page hosted by this server. The page has to run on this computer because the Garmin login call is made from here. You type the email, password, and verification code on that page. The password is used only for that sign-in. It is not saved, not written to disk, and not sent to ntfy, email, or the webhook.

The link stays valid for 12 hours. Leave the server VPN off until the page says you are signed in. The desktop shortcut **Garmin Login** starts `scripts/garmin_auth.py` when you are at the server. That script asks for the same password in the terminal, uses it only for that sign-in, and does not save it.

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
