# Endurance Coach

Modular, self-hostable AI endurance coaching platform. Ingests wearable data from multiple providers, computes deterministic sports-science metrics, and exposes coaching context through an MCP server.

## Status

**Phase 7 (partial)** — Strava OAuth sync for activities. LangGraph coach with multi-provider LLM support.

Garmin sign-in uses `python scripts/garmin_auth.py` or the phone page linked from a sync alert. Strava uses OAuth2 via `/api/v1/providers/strava/connect`.

**LLM setup:** see [docs/LLM_INTEGRATION.md](docs/LLM_INTEGRATION.md) for connecting OpenAI, Anthropic, Ollama, LM Studio, and MCP clients.

## Quick Start

### Windows installer (recommended for self-hosting)

```powershell
powershell -ExecutionPolicy Bypass -File installer\Install-EnduranceCoach.ps1
```

See [INSTALL.md](INSTALL.md) for prerequisites, optional Caddy/DuckDNS, and post-install Garmin/Strava setup.

### Manual setup (uv + Docker)

#### Prerequisites

- Python 3.12
- [uv](https://docs.astral.sh/uv/) or pip + `requirements.txt`
- Docker & Docker Compose (for PostgreSQL)

#### Garmin Authentication (2FA supported)

Do not store the Garmin email or password in this project. **Accounts with 2FA are supported.** At the server, run the login script in a real terminal. When a saved token is rejected, the sync alert includes a phone link to the same sign-in page. The password is used for that sign-in only.

```bash
python scripts/garmin_auth.py
```

Tokens are saved to `~/.garminconnect` and referenced via `GARMIN_TOKEN_PATH` in `.env`. Sign in again when tokens expire, either with that script or from the phone link.

See [docs/GARMIN_AUTH.md](docs/GARMIN_AUTH.md) for the phone page, Docker mounts, and troubleshooting.

### Strava Authentication (OAuth2)

1. Create an app at https://www.strava.com/settings/api
2. Set **Authorization Callback Domain** to your public host (from `PUBLIC_BASE_URL` in `.env`)
3. Add to `.env`:

```env
STRAVA_CLIENT_ID=your_client_id
STRAVA_CLIENT_SECRET=your_client_secret
```

4. Authorize in browser:

```bash
# Local
open http://localhost:8000/api/v1/providers/strava/connect

# Production (set PUBLIC_BASE_URL in .env first)
open https://YOUR_HOST/api/v1/providers/strava/connect
```

5. Sync activities:

```bash
curl -X POST http://localhost:8000/api/v1/sync/strava
curl http://localhost:8000/api/v1/providers/strava/status
```

### Setup

```bash
cp .env.example .env
uv sync --all-extras
docker compose up -d postgres
uv run alembic upgrade head
uv run endurance-coach-api
```

### Trigger Garmin sync

```bash
curl -X POST http://localhost:8000/api/v1/sync/garmin
curl -X POST http://localhost:8000/api/v1/sync/strava
curl http://localhost:8000/api/v1/providers/garmin/status
curl -X POST http://localhost:8000/api/v1/process
curl -X POST http://localhost:8000/api/v1/analytics/compute
curl http://localhost:8000/api/v1/analytics/load
```

### MCP server (Cursor / Claude Desktop)

```bash
uv run endurance-coach-mcp
```

Coaching tools: `get_recent_activities`, `get_sleep_summary`, `get_hrv_trend`, `get_training_readiness`, `get_recovery_state`, `get_weekly_load`, `get_injury_risk`, `explain_today`, `generate_daily_training_plan`, `summarize_last_week`.

Set `OPENAI_API_KEY` (or another provider — see [docs/LLM_INTEGRATION.md](docs/LLM_INTEGRATION.md)) for LLM-backed coaching; without it, deterministic briefings are used.

```bash
curl -X POST http://localhost:8000/api/v1/coach/explain-today
curl -X POST http://localhost:8000/api/v1/coach/daily-plan
curl -X POST http://localhost:8000/api/v1/coach/weekly-summary
```

Set `MCP_TRANSPORT=streamable-http` and `MCP_PORT=8080` for HTTP mode in Docker.

### Development

```bash
uv run ruff check src tests
uv run pytest
uv run mypy
```

## Architecture

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for layer design and [docs/LLM_INTEGRATION.md](docs/LLM_INTEGRATION.md) for LLM/MCP setup.

## Project Structure

```
src/endurance_coach/
├── collector/     # Provider sync, token management, raw JSON storage
├── processor/     # Normalize activities, sleep, HRV, readiness, etc.
├── analytics/     # Deterministic CTL, ATL, TSB, ACWR, recovery, injury risk
├── coach/         # LangGraph-ready; LLM explains pre-computed metrics only
├── mcp/           # MCP tool exposure for AI assistants
├── api/           # FastAPI backend
├── db/            # SQLAlchemy models and session management
├── domain/        # Shared Pydantic types and enums
└── di/            # Dependency injection container
```

## License

MIT
