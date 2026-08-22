# Windows Installation Guide

Endurance Coach ships with a first-run installer for self-hosted Windows deployments.

## Quick install (new user)

```powershell
cd C:\path\to\endurance-coach
powershell -ExecutionPolicy Bypass -File installer\Install-EnduranceCoach.ps1
```

The installer runs an **interactive setup wizard** that prompts for database URL, athlete email, timezone, public URL, API secret (auto-generated or paste your own), and optional Strava/LLM keys. At the end it prints your **API secret** and a ready-to-copy **Perplexity MCP JSON** block — no need to open `.env` manually.

```powershell
cd C:\path\to\endurance-coach
powershell -ExecutionPolicy Bypass -File installer\Install-EnduranceCoach.ps1
```

The installer will:

1. Create `.venv` and install all Python dependencies (`requirements.txt` + editable package)
2. Walk through the setup wizard and write values into `.env`
3. Generate or accept your `API_SECRET_KEY` and display it on screen
4. Run `alembic upgrade head` (if PostgreSQL is reachable)
5. Register hidden scheduled tasks (API, MCP, Garmin sync, watchdog)
6. Print Perplexity/MCP connector JSON at the end

### Non-interactive (CI / scripted)

```powershell
powershell -ExecutionPolicy Bypass -File installer\Install-EnduranceCoach.ps1 -NonInteractive
```

### With Caddy reverse proxy (admin PowerShell)

```powershell
powershell -ExecutionPolicy Bypass -File installer\Install-EnduranceCoach.ps1 -WithCaddy
```

## Prerequisites

| Component | Required | Install |
|-----------|----------|---------|
| Python 3.12+ | Yes | Installer can `winget install Python.Python.3.12` |
| PostgreSQL 16 | Yes | `winget install PostgreSQL.PostgreSQL.16` or `docker compose up -d postgres` |
| Caddy | Optional | Download `caddy.exe` to `CADDY_ROOT` (default `C:\Caddy`) |
| Garmin account | For sync | `python scripts/garmin_auth.py` after install |

## Configuration (`.env`)

The installer wizard fills `.env` for you. You can rerun the installer to fill empty fields, or edit `.env` directly later.

| Variable | Set in wizard |
|----------|----------------|
| `API_SECRET_KEY` | Auto-generated or paste your own — **shown on screen at end** |
| `PUBLIC_BASE_URL` | Your public HTTPS URL, or blank for local-only |
| `DEFAULT_USER_EMAIL` | Your email |
| `DATABASE_URL` | PostgreSQL connection string |
| `STRAVA_CLIENT_ID` / `STRAVA_CLIENT_SECRET` | Optional — paste during wizard |
| `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` | Optional — paste during wizard |
| `GARMIN_*` passwords | **Never** in `.env — use `scripts/garmin_auth.py` after install |

## Post-install steps

### 1. Garmin authentication (2FA supported)

```powershell
.venv\Scripts\python.exe scripts\garmin_auth.py
```

Tokens saved to `~/.garminconnect`.

### 2. Start services

```powershell
powershell -File scripts\restart_app_services.ps1
```

### 3. Verify

```powershell
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/api/v1/server
```

### 4. Strava (optional)

1. Create app at https://www.strava.com/settings/api
2. Set callback domain to your `PUBLIC_BASE_URL` host
3. Add `STRAVA_CLIENT_ID` and `STRAVA_CLIENT_SECRET` to `.env`
4. Visit `/api/v1/providers/strava/connect`

### 5. MCP client (Cursor / Claude)

```json
{
  "url": "https://YOUR_HOST/mcp",
  "transport": "streamable-http",
  "headers": { "Authorization": "Bearer YOUR_API_SECRET_KEY" }
}
```

## Scheduled tasks

| Task | Schedule |
|------|----------|
| `EnduranceCoachAPI` | At startup (+30s) |
| `EnduranceCoachMCP` | At startup (+45s) |
| `EnduranceCoachGarminSync` | Every hour on the hour |
| `EnduranceCoachWatchdog` | Every 5 min |
| `MusicIngestWatcher` | At startup (+90s) |
| `MusicIngestFallbackScan` | Every 30 min |
| `Slskd` | At startup (+60s) |
| `DuckDNS Updater` | Every 5 min (optional) |

Re-register tasks:

```powershell
powershell -File scripts\install_all_services.ps1
```

Repair API, MCP, tasks, and run a Garmin sync catch-up:

```powershell
powershell -File scripts\fix_endurance_services.ps1
```

Watchboard / automation fix (re-register tasks + repair + sync):

```powershell
powershell -File scripts\fix_endurance_services.ps1
```

Silent elevated update for slskd, Navidrome, beets, Caddy, and Python deps:

```powershell
powershell -File scripts\update_tools_suite.ps1
```

From watchboard / fix flow (updates first, then repairs services):

```powershell
powershell -File scripts\fix_endurance_services.ps1 -UpdateTools
```

Automation Watchboard (`automation-watchboard`) shows an **Update** button on each supported app (slskd, Navidrome, Caddy, beets, Jellyfin, *arr, Endurance Coach). Use **Update All** in the toolbar for the full suite. Updates run hidden and self-elevate via UAC when needed.

Logs: `logs\update-tools.log` and `logs\update-tools-last.json`

## Optional: Caddy + DuckDNS

1. Copy `installer/local.json.example` → `installer/local.json`
2. Fill in `duckdns_token`, `duckdns_domain`, `lan_bind_ip`
3. Set `PUBLIC_BASE_URL` in `.env`
4. Place `caddy.exe` in `CADDY_ROOT`
5. Run elevated:

```powershell
powershell -File installer\caddy\Install-CaddyService.ps1
powershell -File installer\caddy\Install-DuckDNSTask.ps1
```

## Linux / Docker

```bash
cp .env.example .env
docker compose up -d postgres
pip install -r requirements.txt && pip install -e .
alembic upgrade head
uvicorn endurance_coach.api.main:app --host 127.0.0.1 --port 8000
```

## Troubleshooting

- **Migrations fail:** PostgreSQL not running or `DATABASE_URL` mismatch
- **401 on API:** Set `Authorization: Bearer <API_SECRET_KEY>` header
- **Garmin sync empty:** Run `scripts/garmin_auth.py` first
- **Logs:** `logs/api.log`, `logs/mcp.log`, `logs/sync-pipeline.log`
