# Endurance Coach

A self-hosted coaching server for Garmin. It syncs your activities, sleep, and recovery, computes the training numbers on your machine, and exposes them through MCP so any assistant can coach from your own data instead of guessing.

## What it does

- **Syncs Garmin on a schedule.** Activities, sleep, HRV, and readiness land in your database. The first sign-in of a local day looks back 30 days. Later runs that day look back 3 days.
- **Computes the training numbers itself.** Chronic load (CTL), acute load (ATL), form (TSB), acute-to-chronic ratio, recovery, and injury risk are calculated here. The assistant is told those results. It is not asked to do the math.
- **Decides the day from readiness.** A high injury risk, a very negative TSB, or a low recovery score becomes rest or easy movement. A fresh day with a positive TSB can be a quality session.
- **Answers through MCP or plain HTTP.** Connect Claude, Cursor, ChatGPT, Perplexity, LM Studio, or any other MCP client. An assistant that cannot speak MCP can call the same coach over HTTP with the bearer token.
- **Keeps the Garmin password off disk.** You type it on a page hosted by this server, or in `scripts/garmin_auth.py` on this computer. It is used for that sign-in only. It is not saved, and it is not included in the expiration alert.

## What this repo does not include

Strava is not part of this project. There is no nutrition planner and no medical diagnosis. The server does not store your Garmin password, and it does not send that password to the alert service.

The language model does not invent training numbers. If Garmin data is missing, the honest result is that it is missing.

## Setup

The fastest path on Windows is the installer. It asks for your database, timezone, public address, API secret, and how you want token-expiration alerts. The default alert is the free ntfy.sh service. Email and an HTTPS webhook are the other choices.

```powershell
powershell -ExecutionPolicy Bypass -File installer\Install-EnduranceCoach.ps1
```

Then sign in to Garmin in a terminal on that computer:

```powershell
.venv\Scripts\python.exe scripts\garmin_auth.py
```

The installer writes `config/mcp-client.json`. Paste that into any MCP client. Full steps, including Docker and a manual install, are in [INSTALL.md](INSTALL.md). Garmin sign-in, the phone page, and alerts are in [docs/GARMIN_AUTH.md](docs/GARMIN_AUTH.md). Connecting an assistant or a local model is in [docs/LLM_INTEGRATION.md](docs/LLM_INTEGRATION.md).

### Prerequisites

- Windows, for the installer and the scheduled sync
- Python 3.12
- Docker, or PostgreSQL 16
- A Garmin account

### Manual setup

```bash
cp .env.example .env
uv sync --all-extras
docker compose up -d postgres
uv run alembic upgrade head
uv run endurance-coach-api
```

```bash
curl -X POST http://localhost:8000/api/v1/sync/garmin
curl -X POST http://localhost:8000/api/v1/process
curl -X POST http://localhost:8000/api/v1/analytics/compute
curl -X POST http://localhost:8000/api/v1/coach/explain-today
```

## A note on data privacy

This server keeps your Garmin history in a database you run. When an assistant calls the MCP tools, the activity, sleep, and recovery facts you synced are sent to that assistant's provider. You choose which assistant, and you can skip any detail you do not want to share.

The Garmin password never goes into that conversation. It is typed into the sign-in page or the local script, used once, and discarded.

## Repo structure

```
endurance-coach/
  README.md
  INSTALL.md                         setup, alerts, and the MCP client file
  docs/GARMIN_AUTH.md                sign-in page, password rules, token alerts
  docs/LLM_INTEGRATION.md            any MCP client, or a local model
  installer/Install-EnduranceCoach.ps1
  src/endurance_coach/
    collector/                       Garmin sync and saved tokens
    processor/                       activities, sleep, HRV, readiness
    analytics/                       CTL, ATL, TSB, ACWR, recovery, injury risk
    coach/                           explains those numbers; does not recalculate them
    mcp/                             tools for any MCP assistant
    api/                             HTTP coach and Garmin sign-in page
```

## Feedback

If you install it and something is missing or wrong, open an issue.

## Disclaimer

This is not a physician and it is not a substitute for a coach. Chest pain, fainting, or pain that is getting worse needs a person qualified to evaluate it. The readiness rules can turn a planned hard day into easy movement or rest. They cannot diagnose an injury.
