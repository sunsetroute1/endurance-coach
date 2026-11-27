# LLM Integration Guide

How to connect AI assistants and various LLM providers to your self-hosted Endurance Coach server, and how they consume your synced wearable data.

---

## Architecture Overview

Endurance Coach separates **data computation** from **language generation**:

```
Providers (Garmin, Strava, …)
        ↓ sync
   raw_payloads (immutable JSON)
        ↓ process
   normalized tables (activities, sleep, HRV, …)
        ↓ analytics/compute
   computed_metrics (CTL, ATL, TSB, ACWR, recovery, injury risk)
        ↓ coach graph / MCP tools
   LLM explains pre-computed facts (never calculates sports science)
```

The LLM layer only receives:
- Pre-computed `MetricSnapshot` values
- Deterministic analysis flags (training focus, elevated ACWR, etc.)
- Normalized activity summaries

It does **not** receive raw Garmin/Strava JSON and must **not** compute CTL, ATL, TSB, or ACWR itself.

---

## Step 1: Pull and Prepare Data

Run the full pipeline after connecting providers:

```bash
# Garmin (one-time sign-in on this machine)
python scripts/garmin_auth.py

# Strava (OAuth via browser)
# 1. Set STRAVA_CLIENT_ID / STRAVA_CLIENT_SECRET in .env
# 2. Visit https://YOUR_HOST/api/v1/providers/strava/connect

# Sync raw data
curl -X POST https://YOUR_HOST/api/v1/sync/garmin
curl -X POST https://YOUR_HOST/api/v1/sync/strava

# Normalize into canonical tables
curl -X POST https://YOUR_HOST/api/v1/process

# Compute deterministic metrics
curl -X POST https://YOUR_HOST/api/v1/analytics/compute
```

Verify metrics exist:

```bash
curl https://YOUR_HOST/api/v1/analytics/load
curl https://YOUR_HOST/api/v1/analytics/recovery
curl https://YOUR_HOST/api/v1/analytics/risk
```

Until `/analytics/compute` has run, coach tools and MCP tools return stale or empty snapshots.

---

## Step 2: Choose an LLM Provider

Set these in `.env`:

| Variable | Purpose |
|----------|---------|
| `COACH_LLM_PROVIDER` | `openai`, `anthropic`, `ollama`, or `openai_compatible` |
| `COACH_LLM_MODEL` | Model name for the selected provider |
| `COACH_LLM_BASE_URL` | Required for `ollama` and `openai_compatible` |
| `OPENAI_API_KEY` | OpenAI or compatible-server key |
| `ANTHROPIC_API_KEY` | Anthropic key |

If no API key is configured (or Ollama is unreachable), the coach falls back to **deterministic briefings** — structured advice without LLM narration.

---

## Provider Recipes

### OpenAI (default)

```env
COACH_LLM_PROVIDER=openai
COACH_LLM_MODEL=gpt-4o-mini
OPENAI_API_KEY=sk-...
```

Works with GPT-4o, GPT-4o-mini, o1, etc.

### Anthropic Claude

```env
COACH_LLM_PROVIDER=anthropic
COACH_LLM_MODEL=claude-sonnet-4-20250514
ANTHROPIC_API_KEY=sk-ant-...
```

Requires `langchain-anthropic` (included in project dependencies).

### Ollama (local)

Run Ollama locally, pull a model, then:

```env
COACH_LLM_PROVIDER=ollama
COACH_LLM_MODEL=llama3.1
COACH_LLM_BASE_URL=http://localhost:11434/v1
```

No API key needed. Ollama exposes an OpenAI-compatible `/v1` endpoint.

```bash
ollama pull llama3.1
ollama serve
```

### LM Studio / vLLM / LocalAI (OpenAI-compatible)

Any server exposing `POST /v1/chat/completions`:

```env
COACH_LLM_PROVIDER=openai_compatible
COACH_LLM_MODEL=your-local-model-name
COACH_LLM_BASE_URL=http://localhost:1234/v1
OPENAI_API_KEY=local
```

Examples:
- **LM Studio**: start server → use `http://localhost:1234/v1`
- **vLLM**: `http://localhost:8000/v1`
- **LocalAI**: `http://localhost:8080/v1`

### Azure OpenAI

Use the OpenAI provider with a custom base URL:

```env
COACH_LLM_PROVIDER=openai
COACH_LLM_MODEL=your-deployment-name
OPENAI_API_KEY=your-azure-key
COACH_LLM_BASE_URL=https://YOUR_RESOURCE.openai.azure.com/openai/deployments/YOUR_DEPLOYMENT
```

---

## Step 3: Consume Coaching via REST API

After configuring the LLM and computing metrics:

```bash
curl -X POST https://YOUR_HOST/api/v1/coach/explain-today
curl -X POST https://YOUR_HOST/api/v1/coach/daily-plan
curl -X POST https://YOUR_HOST/api/v1/coach/weekly-summary
```

Response shape:

```json
{
  "explanation": "Natural language summary citing pre-computed metrics",
  "recommendations": [
    {
      "category": "training",
      "action": "Easy aerobic session today.",
      "rationale": "TSB is -12 with elevated fatigue.",
      "metric_citations": ["tsb", "recovery_score"]
    }
  ],
  "metrics_used": ["ctl", "atl", "tsb", "recovery_score"],
  "confidence": 0.85
}
```

---

## Step 4: Connect any assistant

There are three ways to use the same Garmin pipeline. Pick the one the assistant already supports.

1. **MCP client.** Claude, Cursor, ChatGPT, Perplexity, LM Studio, a local agent, or any later app that speaks streamable HTTP MCP. Point it at `https://YOUR_HOST/mcp` (or `http://127.0.0.1:8080/mcp` on this machine) with `Authorization: Bearer API_SECRET_KEY`. The installer saves this as `config/mcp-client.json`. The assistant is the language model, so this server does not need that app's API key. The tools return the stored activities, sleep, load, recovery, and risk. `explain_today` uses the built-in model only when one is configured, and otherwise returns the deterministic briefing.
2. **REST.** An assistant, script, or shortcut that cannot speak MCP calls `POST /api/v1/coach/explain-today`, `/api/v1/coach/daily-plan`, or `/api/v1/coach/weekly-summary` with the same bearer token.
3. **Built-in narration.** Set `COACH_LLM_PROVIDER` so this server writes the briefing. `openai_compatible` covers any server with `POST /v1/chat/completions`, including ones that do not exist yet. A browser client whose site is rejected can be added to `MCP_ALLOWED_ORIGINS` without a code change.

The MCP server (`endurance-coach-mcp`) exposes coaching tools that read from your database.

### Run the MCP server

```bash
# stdio (Cursor, Claude Desktop)
uv run endurance-coach-mcp

# Or in Docker Compose (stdio)
docker compose up mcp
```

Ensure the MCP container shares:
- `DATABASE_URL` (PostgreSQL)
- LLM env vars (`OPENAI_API_KEY`, etc.)
- Same `.env` as the API

### Cursor configuration

Add to Cursor MCP settings (`~/.cursor/mcp.json` or Cursor Settings → MCP):

```json
{
  "mcpServers": {
    "endurance-coach": {
      "command": "uv",
      "args": ["run", "endurance-coach-mcp"],
      "cwd": "/path/to/endurance-coach",
      "env": {
        "DATABASE_URL": "postgresql+asyncpg://endurance:endurance@localhost:5432/endurance_coach",
        "OPENAI_API_KEY": "sk-...",
        "COACH_LLM_PROVIDER": "openai",
        "COACH_LLM_MODEL": "gpt-4o-mini"
      }
    }
  }
}
```

### Claude Desktop configuration

```json
{
  "mcpServers": {
    "endurance-coach": {
      "command": "uv",
      "args": ["run", "endurance-coach-mcp"],
      "cwd": "C:\\Users\\YOU\\Projects\\endurance-coach",
      "env": {
        "DATABASE_URL": "postgresql+asyncpg://endurance:endurance@localhost:5432/endurance_coach",
        "ANTHROPIC_API_KEY": "sk-ant-...",
        "COACH_LLM_PROVIDER": "anthropic",
        "COACH_LLM_MODEL": "claude-sonnet-4-20250514"
      }
    }
  }
}
```

### Available MCP tools

| Tool | What the LLM gets |
|------|-------------------|
| `get_recent_activities` | Paginated activities: `start`, `limit`, `activitytype`, `summary_only` (compact rows for long sweeps) |
| `get_sleep_summary` | Sleep stages, debt |
| `get_hrv_trend` | HRV readings + deviation |
| `get_training_readiness` | Garmin readiness score |
| `get_recovery_state` | Recovery/fatigue scores |
| `get_weekly_load` | CTL, ATL, TSB, ACWR |
| `get_injury_risk` | Risk level + factors |
| `explain_today` | Daily briefing (LLM or fallback) |
| `generate_daily_training_plan` | Structured plan |
| `summarize_last_week` | Weekly narrative |

A separate Garmin MCP server is not required. This server syncs Garmin with `scripts/garmin_auth.py` and exposes the coaching tools above.

---

## Step 5: How the Coach Graph Uses Data

LangGraph workflow (`coach/graph.py`):

1. **fetch_context** — loads latest `computed_metrics` snapshots + weekly activity counts
2. **analyze_metrics** — deterministic classification (training focus, risk flags) — no LLM
3. **generate_response** — LLM reads the analysis JSON and writes `CoachResponse`

The system prompt explicitly forbids arithmetic. If the LLM returns invalid JSON, the system falls back to deterministic briefings.

---

## Step 6: Docker Compose Deployment

```yaml
# docker-compose.yml already includes api, mcp, postgres
```

Set in `.env`:

```env
DATABASE_URL=postgresql+asyncpg://endurance:endurance@postgres:5432/endurance_coach
PUBLIC_BASE_URL=https://example.duckdns.org
OPENAI_API_KEY=sk-...
COACH_LLM_PROVIDER=openai
COACH_LLM_MODEL=gpt-4o-mini
```

Restart after changes:

```bash
docker compose up -d api mcp
```

For Ollama on the host from a Docker container:

```env
COACH_LLM_PROVIDER=ollama
COACH_LLM_BASE_URL=http://host.docker.internal:11434/v1
COACH_LLM_MODEL=llama3.1
```

---

## Extending with a Custom LLM Provider

A new host that already speaks `POST /v1/chat/completions` needs no code. Set `COACH_LLM_PROVIDER=openai_compatible`, `COACH_LLM_BASE_URL`, and `COACH_LLM_MODEL`.

A provider with a different API needs a small factory:

1. Create a factory in `coach/llm.py` implementing `ChatModelFactory`
2. Return a LangChain `BaseChatModel` from `.create()`
3. Register it in `create_chat_model_factory()` for your `COACH_LLM_PROVIDER` value
4. Set the corresponding env vars in `.env`

Example providers you can wrap:
- Google Gemini (`langchain-google-genai`)
- AWS Bedrock (`langchain-aws`)
- Mistral (`langchain-mistralai`)

The coach graph does not change — only the `generate_response` node's LLM backend changes.

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| Coach returns template text, not LLM prose | Set `OPENAI_API_KEY` (or provider key); check `COACH_LLM_PROVIDER` |
| Empty metrics in briefing | Run `POST /api/v1/analytics/compute` first |
| MCP tools fail to connect | Verify `DATABASE_URL` in MCP env matches API |
| Strava sync empty | Complete OAuth at `/api/v1/providers/strava/connect` |
| Garmin sync fails | Run `python scripts/garmin_auth.py` with the VPN off; check `GARMIN_TOKEN_PATH` |
| Ollama connection refused | Ensure `ollama serve` is running; set correct `COACH_LLM_BASE_URL` |
| Azure/OpenAI 404 | Verify `COACH_LLM_BASE_URL` includes deployment path |

---

## Quick Reference: Full Self-Hosted Setup

```bash
# 1. Environment
cp .env.example .env
# Edit: DATABASE_URL, PUBLIC_BASE_URL, provider keys, LLM keys

# 2. Start stack
docker compose up -d postgres api

# 3. Migrate
uv run alembic upgrade head

# 4. Auth providers
python scripts/garmin_auth.py
# Browser: https://YOUR_HOST/api/v1/providers/strava/connect

# 5. Pipeline
curl -X POST https://YOUR_HOST/api/v1/sync/garmin
curl -X POST https://YOUR_HOST/api/v1/sync/strava
curl -X POST https://YOUR_HOST/api/v1/process
curl -X POST https://YOUR_HOST/api/v1/analytics/compute

# 6. Coach
curl -X POST https://YOUR_HOST/api/v1/coach/explain-today

# 7. MCP (in Cursor/Claude Desktop)
uv run endurance-coach-mcp
```

Your LLM assistant can then call MCP tools or you can hit the REST coach endpoints directly. All coaching advice is grounded in data stored in your PostgreSQL instance — not live API calls at inference time.
