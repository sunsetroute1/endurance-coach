# Garmin Authentication (including 2FA)

Endurance Coach **does not** implement Garmin login itself. Garmin auth — including two-factor authentication — is delegated to [Taxuspt/garmin_mcp](https://github.com/Taxuspt/garmin_mcp).

The API server only reads **saved OAuth tokens** from disk. It never prompts for passwords or MFA codes.

---

## How 2FA Works

Garmin accounts with 2FA enabled require an interactive login **once** (or when tokens expire). The flow:

1. You run `garmin-mcp-auth` in a **real terminal** on the host
2. Enter email + password
3. Enter your **MFA code** (authenticator app or email)
4. OAuth tokens are saved to `~/.garminconnect` (or `GARMIN_TOKEN_PATH`)
5. The API/MCP server uses those tokens for months without re-entering MFA

```
┌─────────────────────┐     one-time, interactive      ┌──────────────────┐
│  You + terminal     │ ─────────────────────────────▶ │ ~/.garminconnect │
│  garmin-mcp-auth    │   email, password, MFA code    │  OAuth tokens    │
└─────────────────────┘                                └────────┬─────────┘
                                                                │ read-only
                                                                ▼
                                                       ┌──────────────────┐
                                                       │ endurance-coach  │
                                                       │  sync / API / MCP│
                                                       └──────────────────┘
```

**Why not in the API?** MCP servers and Docker containers run headless. Garmin MFA requires an interactive prompt — that cannot happen inside a background API process.

---

## Setup (2FA-enabled account)

### 1. Run auth on the host (Windows PowerShell or WSL)

**Option A — project script (no uvx required):**

```bash
cd C:\Users\<you>\Projects\endurance-coach
python scripts/garmin_auth.py
```

**Option B — garmin_mcp CLI (if uvx is installed):**

```bash
uvx --python 3.12 --from git+https://github.com/Taxuspt/garmin_mcp garmin-mcp-auth
```

You will be prompted for:

- Email (or set `GARMIN_EMAIL`)
- Password (or set `GARMIN_PASSWORD`)
- **MFA code** — from your authenticator app or Garmin email

### 2. Verify tokens

```bash
uvx --python 3.12 --from git+https://github.com/Taxuspt/garmin_mcp garmin-mcp-auth --verify
```

### 3. Point endurance-coach at the token directory

In `.env`:

```env
GARMIN_TOKEN_PATH=~/.garminconnect
```

### 4. Mount tokens into Docker (production)

The `docker-compose.yml` already mounts `garmin_tokens:/root/.garminconnect:ro`. Populate that volume by running `garmin-mcp-auth` on the host, then copy or bind-mount the tokens.

### 5. Check status via API

```bash
curl https://example.duckdns.org/api/v1/providers/garmin/status
```

Response includes `mfa_note`, `setup_command`, `verify_command`, and `reauth_command`.

### 6. Sync

```bash
curl -X POST https://example.duckdns.org/api/v1/sync/garmin
```

The extra performance, device, and solar reads are described in [GARMIN_METRICS.md](GARMIN_METRICS.md).

---

## Sign in from your phone

When Garmin rejects the saved token, the sync alert includes a sign-in link. Open it on your phone, enter the Garmin email and password, then the verification code if Garmin asks for one. The password is sent only for that sign-in and is not stored. Leave the server VPN off until the page says you are signed in.

The link stays valid for 12 hours. The desktop shortcut **Garmin Login** does the same sign-in when you are at the server.

## Token Refresh (~6 months)

When tokens expire or you change your Garmin password, use the phone link above or:

```bash
python scripts/garmin_auth.py
```

Enter MFA again when prompted. No endurance-coach code changes needed.

---

## Docker + 2FA

Do **not** run `garmin-mcp-auth` inside the long-running `api` or `mcp` containers. Instead:

1. Run auth on the **host** (or a one-off setup container with `-it` and a TTY)
2. Copy tokens into the `garmin_tokens` volume
3. Start `docker compose up api`

Example one-off auth container:

```bash
docker compose run --rm -it api bash
# inside container (if Garmin creds available):
uvx --python 3.12 --from git+https://github.com/Taxuspt/garmin_mcp garmin-mcp-auth
```

Prefer host-side auth and volume mount — simpler and MFA-friendly.

---

## Troubleshooting

| Problem | Solution |
|---------|------------|
| `MFA authentication required but no interactive terminal available` | Run `garmin-mcp-auth` on the host, not in a background service |
| `Tokens expired or invalid` | Run `garmin-mcp-auth --force-reauth` and enter MFA |
| Email MFA hangs / no code prompt | Known upstream issue with some Garmin email-MFA page titles. Try: different network (mobile hotspot), latest `garmin_mcp`, or TOTP app instead of email MFA |
| Garmin rate-limits login (429) | Wait 15–30 min, try different IP/VPN, or auth from another machine |
| Sync works locally but not in Docker | Check `GARMIN_TOKEN_PATH` mount; tokens must exist inside container at mounted path |

---

## Security Notes

- **Never** put `GARMIN_PASSWORD` in `.env` or Docker Compose for production
- Tokens in `~/.garminconnect` are the credential — treat like a password
- The API container can write `~/.garminconnect` so a phone sign-in can save a new token. The MCP container still mounts that directory read-only.
- This app stores **no** Garmin passwords in PostgreSQL

---

## What We Deliberately Don't Build

The phone page and `scripts/garmin_auth.py` both use the installed `garminconnect` login. The app does not store the Garmin password and does not implement its own OAuth server.
