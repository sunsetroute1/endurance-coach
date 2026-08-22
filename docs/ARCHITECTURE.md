# Endurance Coach — Architecture

Modular, self-hostable AI endurance coaching platform. Ingests wearable data from multiple providers, normalizes it, computes deterministic sports-science metrics, and exposes coaching context through an MCP server for AI assistants.

**Phase 1 scope (this document):** folder structure, interfaces, database schema, and integration contracts. No Garmin-specific implementation yet.

---

## Ecosystem Evaluation

### Taxuspt/garmin_mcp — **Selected for Garmin authentication**

| Aspect | Assessment |
|--------|------------|
| Purpose | MCP server over `python-garminconnect`; 110+ tools for activities, health, training |
| Auth | `garmin-mcp-auth` CLI saves OAuth tokens to `~/.garminconnect`; MFA-aware; ~6-month token lifetime |
| Strengths | Battle-tested auth flow, no credentials in config, Docker volume support, active community (700+ stars) |
| Fit | **We delegate Garmin login entirely to this ecosystem.** Our collector reads the shared token store. |

**Integration contract:**

```bash
# One-time setup (documented for operators, not reimplemented)
uvx --python 3.12 --from git+https://github.com/Taxuspt/garmin_mcp garmin-mcp-auth
```

Our `GarminTokenStore` adapter resolves `GARMIN_TOKEN_PATH` (default `~/.garminconnect`) and verifies tokens via `garmin-mcp-auth --verify` or direct `garth` session resume. We never store Garmin passwords in our database or `.env`.

### bes-dev/garmy — Reference library, not auth source

| Aspect | Assessment |
|--------|------------|
| Purpose | Type-safe Garmin API client with optional MCP server and local SQLite sync |
| Auth | Own `AuthClient.login(email, password)` — reinvents credential handling |
| Strengths | Clean metric abstractions, async API, local DB patterns worth studying |
| Fit | **Reference for metric naming and normalizer field mapping.** Not used for auth. |

### leonzzz435/garmin-ai-coach — Reference for coach layer

| Aspect | Assessment |
|--------|------------|
| Purpose | LangGraph multi-agent CLI producing HTML training reports |
| Analytics | Computes CTL/ATL/ACWR/HRV in Python before LLM sees data |
| Strengths | Proves the "LLM explains, never computes" pattern; LangGraph workflow design |
| Fit | **Reference for coach graph topology and metric presentation.** Our analytics module owns the formulas. |

---

## Design Principles

1. **Garmin is one provider** — all ingestion flows through `DataProvider` protocol implementations.
2. **Raw before normalized** — collector stores immutable provider JSON; processor derives canonical records.
3. **Deterministic analytics** — CTL, ATL, TSB, ACWR, TRIMP, monotony, HR drift, decoupling, sleep debt, recovery, injury risk, weekly load, fatigue are computed in `analytics/`, never by the LLM.
4. **Coach receives facts** — `coach/` gets pre-computed `MetricSnapshot` objects and produces natural-language explanations and plans.
5. **LangGraph-ready** — coach layer exposes stateful graph nodes with typed inputs/outputs; no provider coupling.
6. **Self-hostable** — Docker Compose, PostgreSQL, no managed-service dependencies.
7. **Fully typed** — Pydantic v2 domain models, SQLAlchemy 2.0 mapped types, strict mypy.

---

## Layer Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│  MCP Server (mcp/)          FastAPI (api/)         LangGraph (coach/)   │
│  get_recent_activities()    REST admin/sync        explain_today()        │
│  get_sleep_summary()        health checks          generate_daily_plan() │
└───────────────────────────────┬─────────────────────────────────────────┘
                                │ reads computed metrics + normalized data
┌───────────────────────────────▼─────────────────────────────────────────┐
│  Analytics (analytics/)                                                  │
│  CTL · ATL · TSB · ACWR · TRIMP · Monotony · HR drift · Decoupling      │
│  Sleep debt · Recovery score · Injury risk · Weekly load · Fatigue      │
└───────────────────────────────┬─────────────────────────────────────────┘
                                │ reads normalized records
┌───────────────────────────────▼─────────────────────────────────────────┐
│  Processor (processor/)                                                  │
│  ActivityNormalizer · SleepNormalizer · HRVNormalizer · ReadinessNormalizer│
└───────────────────────────────┬─────────────────────────────────────────┘
                                │ reads raw_payloads
┌───────────────────────────────▼─────────────────────────────────────────┐
│  Collector (collector/)                                                  │
│  DataProvider protocol · TokenStore · SyncOrchestrator · RawPayloadRepo  │
│  ┌─────────┐ ┌──────────────┐ ┌──────┐ ┌───────┐ ┌───────┐ ┌─────────┐ │
│  │ Garmin  │ │Health Connect│ │ WHOOP│ │ Oura  │ │ Strava│ │  Coros  │ │
│  └─────────┘ └──────────────┘ └──────┘ └───────┘ └───────┘ └─────────┘ │
└───────────────────────────────┬─────────────────────────────────────────┘
                                │
┌───────────────────────────────▼─────────────────────────────────────────┐
│  PostgreSQL — raw_payloads, normalized tables, computed_metrics          │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Data Flow

```
Provider API
    │
    ▼
collector.DataProvider.sync()
    │  (uses TokenStore — Garmin: ~/.garminconnect via garmin_mcp)
    ▼
raw_payloads table (JSONB, content-hash dedup)
    │
    ▼
processor.*Normalizer.normalize()
    ▼
activities · sleep_records · hrv_records · readiness_records · ...
    │
    ▼
analytics.MetricEngine.compute()
    ▼
computed_metrics table (typed JSON per metric family)
    │
    ▼
coach.CoachService / mcp tools (read-only)
```

---

## Provider Interface Contract

### `DataProvider` (collector)

Every provider implements:

| Method | Responsibility |
|--------|----------------|
| `provider_type` | Returns `DataProviderType` enum value |
| `is_available(user_id)` | Checks `TokenStore` / connection health |
| `sync(request)` | Incremental or full sync; writes `RawPayload` rows |
| `supported_resource_types()` | e.g. `activities`, `sleep`, `hrv`, `readiness` |

### `TokenStore` (collector)

| Method | Responsibility |
|--------|----------------|
| `get_reference(user_id, provider)` | Returns opaque token path or OAuth metadata |
| `is_authenticated(user_id, provider)` | Boolean health check |
| `get_setup_instructions(provider)` | Human-readable setup (Garmin → `garmin-mcp-auth`) |

**Garmin implementation (Phase 2):** `GarminTokenStore` reads `GARMIN_TOKEN_PATH`, never handles passwords.

### Future providers

| Provider | Auth model (planned) | Notes |
|----------|---------------------|-------|
| Health Connect | Android app + local export API | Batch JSON export initially |
| WHOOP | OAuth2 API | Official API when available |
| Oura | OAuth2 v2 | Ring sleep/HRV rich |
| Strava | OAuth2 | Activities; limited wellness |
| Coros | API TBD | Activity-focused |
| Apple Health | iOS export XML / Health Auto Export | Batch import |

---

## Database Schema Overview

See `src/endurance_coach/db/models/` and Alembic migration `001_initial_schema`.

| Table | Purpose |
|-------|---------|
| `users` | Self-hosted user accounts |
| `provider_connections` | Per-user provider link + token reference (not secrets) |
| `sync_jobs` | Sync audit trail with status and cursor |
| `raw_payloads` | Immutable provider JSON with dedup hash |
| `activities` | Normalized activity records |
| `sleep_records` | Normalized sleep sessions |
| `hrv_records` | Normalized HRV readings |
| `body_battery_records` | Energy level time series |
| `training_readiness_records` | Readiness scores and components |
| `stress_records` | Stress level aggregates |
| `running_dynamics_records` | Cadence, vertical oscillation, GCT, etc. |
| `computed_metrics` | Versioned analytics output (JSONB) |

All normalized tables include `user_id`, `provider`, `provider_record_id`, `recorded_at`, and `source_payload_id` for lineage.

---

## Analytics Metrics (deterministic)

| Metric | Inputs | Module |
|--------|--------|--------|
| CTL | Daily TSS/TRIMP, 42-day EWMA | `analytics.load` |
| ATL | Daily TSS/TRIMP, 7-day EWMA | `analytics.load` |
| TSB | CTL − ATL | `analytics.load` |
| ACWR | ATL / CTL (or 7d/28d load ratio) | `analytics.load` |
| TRIMP | HR zones × duration | `analytics.load` |
| Monotony | Mean daily load / std dev (7d) | `analytics.load` |
| HR drift | HR rise at constant pace/power | `analytics.execution` |
| Pace/HR decoupling | Aerobic decoupling % | `analytics.execution` |
| Sleep debt | Rolling sleep need − actual | `analytics.recovery` |
| Recovery score | HRV + sleep + readiness composite | `analytics.recovery` |
| Injury risk | ACWR + monotony + load spike flags | `analytics.risk` |
| Weekly load progression | WoW volume/intensity delta | `analytics.load` |
| Fatigue score | TSB + HRV deviation + sleep debt | `analytics.recovery` |

Each calculator implements `MetricCalculator` protocol and returns typed `MetricResult`.

---

## MCP Tool Contracts

Our MCP server (`endurance-coach-mcp`) exposes **coaching-oriented** tools. It does not duplicate `garmin_mcp`'s 110+ raw Garmin tools — operators run both servers side by side if needed.

| Tool | Returns | Data source |
|------|---------|-------------|
| `get_recent_activities(days, start, limit, activitytype, summary_only)` | Paginated activity rows (`summary` or `full` mode) | `activities` |
| `get_sleep_summary(date)` | Sleep score, stages, debt | `sleep_records` + analytics |
| `get_hrv_trend(days)` | HRV baseline deviation | `hrv_records` + analytics |
| `get_training_readiness(date)` | Readiness score + components | `training_readiness_records` |
| `get_recovery_state()` | Recovery score, fatigue, sleep debt | `computed_metrics` |
| `get_weekly_load()` | Volume, intensity, CTL/ATL/TSB | `computed_metrics` |
| `get_injury_risk()` | Risk level + contributing factors | `computed_metrics` |
| `generate_daily_training_plan()` | Structured plan (coach graph) | analytics + coach |
| `explain_today()` | Natural language daily briefing | coach |
| `summarize_last_week()` | Weekly narrative summary | coach |

---

## Coach Layer (LangGraph-ready)

```
┌──────────────┐     ┌─────────────────┐     ┌──────────────────┐
│ fetch_context│ ──▶ │ analyze_metrics │ ──▶ │ generate_response│
│  (read-only) │     │  (no LLM math)  │     │  (LLM explains)  │
└──────────────┘     └─────────────────┘     └──────────────────┘
```

- **State:** `CoachState` with `MetricSnapshot`, `AthleteProfile`, `ConversationHistory`
- **Nodes receive** pre-computed numbers; prompts explicitly forbid arithmetic
- **Output:** `CoachResponse` with `explanation`, `recommendations`, `confidence`, `citations` (metric keys)

---

## Dependency Injection

`Container` in `endurance_coach/di/container.py` wires:

- `AsyncSession` factory
- Repository implementations
- Provider registry (`dict[DataProviderType, DataProvider]`)
- `MetricEngine` with calculator registry
- `CoachService` via LangGraph (`DefaultCoachService`); falls back to deterministic briefings without an API key

FastAPI and MCP entrypoints resolve services from the same container for consistent behavior.

---

## Deployment (Docker Compose)

| Service | Role |
|---------|------|
| `postgres` | Primary data store |
| `api` | FastAPI backend (sync triggers, health) |
| `mcp` | MCP server (stdio or SSE transport) |

Garmin auth is **operator-managed** outside the stack:

```bash
uvx --python 3.12 --from git+https://github.com/Taxuspt/garmin_mcp garmin-mcp-auth
# Mount ~/.garminconnect into collector container via volume
```

---

## Implementation Phases

| Phase | Deliverable |
|-------|-------------|
| **1 (current)** | Structure, interfaces, schema, docs |
| **2** | Garmin collector (token adapter + sync + raw storage) |
| **3** | Processor normalizers for Garmin payloads |
| **4** | Analytics calculators + unit tests with fixtures |
| **5** | MCP tool implementations |
| **6** | LangGraph coach graph |
| **7 (partial)** | Strava activities sync + processor; remaining providers planned |

---

## Technology Stack

| Component | Choice |
|-----------|--------|
| Runtime | Python 3.12 |
| API | FastAPI + uvicorn |
| Database | PostgreSQL 16 |
| ORM | SQLAlchemy 2.0 (async) |
| Migrations | Alembic |
| Validation | Pydantic v2 |
| Package manager | uv |
| Linting | Ruff |
| Testing | Pytest + pytest-asyncio |
| MCP | `mcp` SDK |
| Coach | LangGraph (Phase 6) |
