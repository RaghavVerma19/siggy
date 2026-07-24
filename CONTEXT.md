# AI-Powered Observability Memory System — Project Context

## Status

This file reflects the project state as of **Friday, July 24, 2026**.

The project is no longer just an incident similarity engine. It is now an **AI-powered Observability Memory System** built on top of SigNoz with four active product layers:

1. **Knowledge Memory** via Qdrant
2. **Operational Experience** via structured experience records and pattern aggregation
3. **Organizational Knowledge Graph** via a local graph abstraction designed to be replaceable with Neo4j later
4. **Judge-facing Product UI and Evaluation Layer** via a served frontend, benchmark suite, and supporting docs

The current direction is:

Telemetry  
→ Knowledge  
→ Experience  
→ Graph Context  
→ Explainable Recommendation  
→ Feedback / Evaluation

## What The System Does

The backend ingests incidents or telemetry, normalizes them into structured `KnowledgeObject`s, retrieves similar operational knowledge from vector memory, ranks recommendations using historical outcomes, expands context through a graph of operational relationships, and returns explainable recommendations.

The goal is not to build another dashboard or chatbot. The goal is to make the AI behave more like a senior SRE with memory of past incidents, successful fixes, and recurring operational patterns.

## Current Architecture

```text
User's Application
        |
        v
siggy instrument --service <name> <command>
        |
        v
OTel Auto-Instrumentation (child process)
        |
        v
Traces / Logs / Metrics → OTLP Collector → SigNoz
        |
        v
SigNoz detects anomaly → fires alert
        |
        v
siggy watch (polls MCP signoz_list_alerts)
        |
        v
Alert → InvestigatorAgent → Knowledge Pipeline → Memory-Enriched Recommendation
        |
        v
Dashboard: SigNoz UI (iframe) + Memory Panel (overlay)
```

## Implemented Milestones

### Day 1

- FastAPI backend
- Fake incident dataset
- Embeddings
- Qdrant similarity search
- Basic incident retrieval

### Day 2

- Incident analysis agent
- Metadata-aware retrieval hints
- Explainable LLM recommendation flow

### Day 3

- SigNoz and MCP integration
- Investigator agent for logs, traces, and metrics
- Telemetry investigation endpoints

### Day 4

- `KnowledgeObject` schema
- Canonical taxonomy for failures, fixes, symptoms, severity, environment
- Structured normalization
- Metadata-aware retrieval over knowledge objects
- Explainable recommendation object

### Day 5

- `experience/` package added
- Structured experience store in SQLite
- Stable recommendation IDs
- Recommendation statistics engine
- Experience-aware ranking
- Operational pattern aggregation
- Experience APIs

### Day 6

- `graph/` package added
- Minimal graph schema:
  - `Service`
  - `Component`
  - `FailureType`
  - `Recommendation`
  - `OperationalPattern`
- Automatic graph sync from knowledge objects and operational patterns
- Graph neighbor, pattern, recommendation, and natural-language query APIs
- Hybrid retrieval context:
  - Qdrant for similarity
  - Experience for ranking
  - Graph for neighborhood expansion

### Day 7

- Product-style frontend served directly from FastAPI
- Simplified non-technical dashboard copy and cleaner relationship map
- Repo-level documentation package:
  - `README.md`
  - `docs/demo-script.md`
  - `docs/evaluation.md`
  - `docs/judge-faq.md`
- Automated benchmark suite in `backend/evaluate.py`
- 30-case benchmark dataset in `backend/data/benchmark_incidents.json`
- Isolated local benchmark mode for vector memory and report generation

### Day 8

- **Normalization 2.0** engine in `backend/knowledge/normalization_v2.py`
  - Deterministic alias dictionaries for service, component, failure type, fix type, severity, symptom phrases
  - Regex-first normalization rules for common production patterns:
    - Redis pool exhaustion
    - Redis failover storm
    - Kafka disk pressure
    - Query overload / missing index
    - Certificate expiry / TLS errors
    - OOM failures
    - Infinite retry loops / CPU saturation
  - 23 failure types (up from 15), 21 fix types (up from 15), 18 symptom types (up from 12)
  - Per-field normalization confidence scoring
  - `NormalizationReport` with method tracking (regex-first / alias-lookup / heuristic)
- Expanded taxonomy in `backend/knowledge/taxonomy.py`:
  - New failure types: `kafka_disk_pressure`, `redis_failover_storm`, `ssl_tls_handshake_failure`, `database_connection_exhaustion`, `pod_crash_loop`, `replication_lag`, `disk_io_saturation`, `garbage_collection_storm`
  - New fix types: `add_index`, `increase_connection_timeout`, `scale_vertically`, `rebalance_partitions`, `optimize_query_plan`, `upgrade_oom_limits`
  - New symptom types: `connection_pool_exhausted`, `disk_pressure`, `certificate_errors`, `retry_storm`, `gc_pause_spike`, `replication_delay`
- Field-level normalization reporting and confusion-style summaries in `backend/evaluate.py`:
  - Per-case confusion tracking (expected vs. predicted for each field)
  - Top-5 confusion pairs per field in markdown report
  - Normalization method distribution tracking
- **Hidden holdout benchmark** in `backend/data/holdout_incidents.json`:
  - 20 cases across 10 failure scenarios
  - Separate from the 30-case development benchmark
  - Accessed via `--holdout` or `--holdout-only` flags
- **Benchmark scorecard exposed in frontend**:
  - New `GET /api/v1/benchmark/scorecard` API endpoint
  - Scorecard section in the dashboard UI with all key metrics
  - Per-field normalization accuracy chips
  - Returns `available: false` with empty metrics when no report exists (no hardcoded values)
- Updated fallbacks (`backend/utils/fallbacks.py`) to delegate to Normalization 2.0 engine
- Updated `backend/knowledge/normalizer.py` to use Normalization 2.0 as fallback

### Day 9

- **Self-hosted SigNoz via Foundry** (replacing old hand-written `docker-compose.yml`):
  - Installed `foundryctl` (v0.9.0, Windows amd64)
  - Created `casting.yaml` with `deployment.flavor: compose`, `deployment.mode: docker`, `mcp.spec.enabled: true`
  - Generated `casting.yaml.lock` via `foundryctl cast` (668 lines, full deployment manifest)
  - Removed old hand-written `docker-compose.yml` — all SigNoz infra now defined declaratively via Foundry
  - SigNoz stack deployed: ClickHouse, ClickHouse Keeper, Postgres, OTel Collector, SigNoz UI, MCP server
  - MCP server confirmed healthy on `http://localhost:8000/mcp` (v0.9.0, HTTP transport mode)
- **Benchmark auto-run on server startup**:
  - Added `_run_benchmark_on_startup()` to `main.py` lifespan
  - Server runs `evaluate.py` automatically on first boot if no cached report exists
  - Scorecard endpoint returns `available: false` with empty metrics until a real benchmark has been run
- **Removed all hardcoded benchmark values**:
  - `main.py` scorecard endpoint: no longer returns fake metrics as fallback
  - `index.html` scorecard section: all metric values default to `—` (em-dash)
  - `app.js`: fixed `sc-evaluation-date` → `sc-eval-date` ID mismatch
- **Lifespan error handling hardened**:
  - MCP connect/disconnect wrapped in `except BaseException` to catch `asyncio.CancelledError`
  - Server now starts cleanly even when MCP is temporarily unreachable
- Updated `.env`: `SIGNOZ_MCP_URL` changed from `http://localhost:8081/mcp` to `http://localhost:8000/mcp` to match Foundry-deployed MCP

### Day 10

- **Siggy CLI** — production observability with memory:
  - `backend/cli/` package added with Click-based CLI
  - 5 commands: `siggy init`, `siggy instrument`, `siggy watch`, `siggy investigate`, `siggy dashboard`
  - `siggy init` creates `.siggy.yaml`, tests SigNoz/MCP/backend connections, seeds baseline services
  - `siggy instrument --service <name> <command>` wraps any Python app with OTel auto-instrumentation
  - `siggy watch` polls SigNoz alerts via MCP and enriches with memory layer
  - `siggy investigate "query"` runs manual investigation through the knowledge pipeline
  - `siggy dashboard` starts the FastAPI backend with alert watcher
  - `backend/cli/config.py` — YAML config reader/writer for `.siggy.yaml`
- **OTel auto-instrumentation wrapper**:
  - `backend/otel/instrument.py` — builds child process environment with OTel env vars
  - Uses `opentelemetry-instrument` CLI wrapper to instrument any Python app without code changes
  - Session ID attached as OTel resource attribute (`siggy.session_id`)
  - Process supervision with graceful Ctrl+C shutdown
  - Framework detection (Flask, FastAPI, Django, generic Python)
- **SigNoz alert consumption**:
  - `backend/telemetry/signoz_mcp.py` — added 4 new MCP tool wrappers:
    - `list_alerts()` — fetches firing alert instances from SigNoz
    - `list_alert_rules()` — lists configured alert rules
    - `create_alert_rule()` — creates new alert rules via MCP
    - `get_alert_history()` — fetches rule firing history
  - `backend/alerts/consumer.py` — polls MCP for alerts every 30s, stores enriched incidents in SQLite
  - `backend/alerts/enricher.py` — takes alert → InvestigatorAgent → Knowledge Pipeline → memory-enriched recommendation
  - `backend/data/siggy_incidents.db` — separate SQLite store for detected incidents
- **Backend OTel self-instrumentation**:
  - `main.py` now configures OpenTelemetry for Siggy's own API calls
  - Siggy's traces show up in SigNoz — the dogfooding loop is complete
- **Demo app**:
  - `demo/app.py` — Flask app with `/health`, `/fast`, `/slow`, `/error`, `/flaky`, `/load` endpoints
  - `demo/requirements.txt` — Flask + OTel dependencies
  - `demo/run.sh` — wrapper script using `siggy instrument` or manual OTel setup
- **Updated dependencies** in `backend/requirements.txt`:
  - Added: `click`, `pyyaml`, `opentelemetry-api`, `opentelemetry-sdk`, `opentelemetry-exporter-otlp`, `opentelemetry-instrumentation-fastapi`

### Day 11

- **SigNoz dashboard + saved views auto-creation**:
  - `backend/signoz/__init__.py` — new package
  - `backend/signoz/dashboards.py` — auto-creates dashboard and saved views in SigNoz on server startup
  - **Dashboard**: "Siggy - Memory Layer" with 4 panels (Recent Recommendations, Recommendations by Service, Confidence Distribution, Top Failure Types)
  - **Saved views**: "Siggy Recommendations" and "Siggy Low Confidence" in traces explorer
  - **Direct REST API** (not MCP) — uses `SIGNOZ-API-KEY` header auth against `http://localhost:8080`
  - **MCP HTTP mode limitation discovered**: SigNoz MCP server v0.9.0 in HTTP mode does not forward `SIGNOZ_API_KEY` to SigNoz API — all MCP write tools return 401. Solution: bypass MCP for dashboard/view operations.
  - **SigNoz v5 API format** (captured from UI):
    - Dashboard create: `POST /api/v1/dashboards` with `{title, description}` → returns ID
    - Dashboard update: `PUT /api/v1/dashboards/{id}` with `{title, description, widgets, layout}`
    - View create: `POST /api/v1/explorer/views` with `{name, sourcePage, compositeQuery, extraData}`
    - View `compositeQuery` uses expression-based `filter.expression` (not items array)
  - **Idempotent**: detects existing dashboard/views before creating, skips if already present
  - `backend/main.py` lifespan calls `setup_siggy_in_signoz()` on startup
- **SigNoz API key**: Service account `siggy` with role `signoz-admin`. API key now lives in `.siggy.yaml` only (not in compose files). `siggy init` prompts interactively with step-by-step instructions.
- **Frontend/saved-views removal**: `backend/frontend/` and `backend/dashboard/` directories deleted — SigNoz UI is the product surface

### Day 12

- **User-friendly API key flow** — no more manual compose file editing:
  - Removed `SIGNOZ_API_KEY` from `compose.yaml` and `casting.yaml.lock` MCP sections — Siggy no longer modifies the user's SigNoz deployment
  - `backend/signoz/dashboards.py` rewritten: `setup_siggy_in_signoz(api_key, signoz_url)` now takes parameters instead of reading module-level env vars. Added `validate_api_key(api_key, signoz_url)` for pre-flight validation
  - `backend/main.py` lifespan: loads `SiggyConfig` early, passes `config.signoz.api_key` and `config.signoz.url` to `setup_siggy_in_signoz()`. Dashboard setup moved outside MCP connect block (no longer depends on MCP)
  - `backend/cli/main.py`: `siggy init` now interactively prompts for API key when SigNoz is detected but no key is set. Shows clear step-by-step instructions (open URL → create service account → paste key). Validates the key against `GET /api/v2/rules` before storing. Key stored in `.siggy.yaml` via `SiggyConfig`
  - `_quickstart_check_signoz()` also prompts for API key interactively when SigNoz is reachable
  - `_check_signoz()` now returns `bool` (was `None`)
  - `backend/.env.example` updated: comment clarifies key is optional, for dashboard integration
  - **Degradation model**: No API key → Siggy works fine (CLI, OTel write-back, alert watching). Invalid key → same, logged warning. Valid key → dashboard + views auto-created on startup
- **Verified**: all files compile, `setup_siggy_in_signoz()` with correct key returns `already_exists` for all resources, `validate_api_key()` correctly identifies valid/invalid keys, config save/load round-trips correctly

## Current Backend Structure

```text
.
├── README.md
├── CONTEXT.md
├── casting.yaml
├── casting.yaml.lock
├── .siggy.yaml                    ← NEW (after siggy init)
├── foundry_windows_amd64/
├── demo/                          ← NEW
│   ├── app.py
│   ├── requirements.txt
│   └── run.sh
├── docs/
│   ├── demo-script.md
│   ├── evaluation.md
│   └── judge-faq.md
└── backend/
    ├── main.py
    ├── requirements.txt
    ├── .env
    ├── evaluate.py
    ├── cli/                       ← NEW
    │   ├── __init__.py
    │   ├── __main__.py
    │   ├── main.py
    │   └── config.py
    ├── otel/                      ← NEW
    │   ├── __init__.py
    │   └── instrument.py
    ├── alerts/                    ← NEW
    │   ├── __init__.py
    │   ├── consumer.py
    │   └── enricher.py
    ├── signoz/                    ← NEW
    │   ├── __init__.py
    │   └── dashboards.py
    ├── frontend/                  ← REWRITTEN
    │   ├── index.html
    │   ├── styles.css
    │   └── app.js
    ├── agents/
    ├── experience/
    ├── graph/
    ├── knowledge/
    ├── llm/
    ├── memory/
    ├── models/
    ├── rules/
    └── telemetry/
```

## Frontend Structure

```text
backend/
└── frontend/
    ├── index.html
    ├── styles.css
    └── app.js
```

The frontend lives inside `backend/frontend/` intentionally so the FastAPI app can serve the demo UI directly from `/` during judging.

## Core Data Models

### KnowledgeObject

Structured operational memory unit used for retrieval and graph sync.

Key fields:

- `service`
- `component`
- `failure_type`
- `symptoms`
- `severity`
- `environment`
- `root_cause`
- `fix`
- `fix_type`
- `confidence`

### ExperienceRecord

Represents the result of a recommendation, not another incident.

Key fields:

- `recommendation_id`
- `recommendation`
- `accepted`
- `worked`
- `resolution_time_seconds`
- `engineer_feedback`
- `service`
- `component`
- `failure_type`
- `symptoms`

### OperationalPattern

Derived artifact computed from experiences.

Key fields:

- `failure_type`
- `services`
- `components`
- `total_occurrences`
- `best_recommendation_id`
- `success_rate`
- `avg_resolution_time_seconds`

## Active Retrieval Strategy

Current recommendation generation is hybrid:

1. Normalize the current incident or telemetry into a `KnowledgeObject`
2. Search Qdrant for top similar knowledge objects
3. Rank candidate fixes using:
   - similarity
   - historical success rate
   - average resolution time
   - confidence
   - operational metadata alignment
4. Expand graph context around service, component, failure, and pattern relationships
5. Return an explainable recommendation with evidence

## Product Layer

The backend now serves a product-style demo UI from the FastAPI app root:

- `/` returns `backend/frontend/index.html`
- `/app/assets` serves the frontend assets
- `/api/v1/dashboard/summary` provides headline product metrics
- `/api/v1/experience/history` powers recent recommendation history in the UI

The current UI is a clean two-panel layout:

- **Left panel**: Memory Layer — active incidents with recommendations, operational patterns, stats
- **Right panel**: SigNoz UI embedded via iframe — real dashboards, traces, logs, metrics
- **Bottom bar**: Manual investigation input with results

The frontend auto-refreshes every 10s with real data from the backend.

## Graph Design

### Nodes

- `Service`
- `Component`
- `FailureType`
- `Recommendation`
- `OperationalPattern`

### Relationships

- `DEPENDS_ON`
- `FAILS_WITH`
- `RESOLVED_BY`
- `OBSERVED_PATTERN`
- `DESCRIBES_FAILURE`
- `USES_RECOMMENDATION`
- `INVOLVES_COMPONENT`

### Current Graph Backend

The current graph is implemented in SQLite behind a graph client abstraction. This is intentional.

It allows:

- fast local iteration
- easier debugging of graph sync and retrieval logic
- later replacement of the storage layer with Neo4j without rewriting the graph-facing parts of the backend

Neo4j is the planned next storage backend, but it is **not yet connected**.

## API Surface

### Core

- `GET /api/v1/health`
- `GET /api/v1/incidents`
- `POST /api/v1/incidents/seed`
- `POST /api/v1/incidents/search`
- `POST /api/v1/incidents/recommend`
- `POST /api/v1/incidents/store`

### Knowledge

- `POST /api/v1/knowledge/analyze`
- `POST /api/v1/knowledge/store`

### Telemetry

- `GET /api/v1/telemetry/health`
- `POST /api/v1/telemetry/investigate`
- `POST /api/v1/telemetry/full-analysis`

### Experience

- `POST /api/v1/experience/record`
- `GET /api/v1/experience/stats`
- `GET /api/v1/experience/statistics`
- `GET /api/v1/experience/patterns`
- `GET /api/v1/experience/recommendations`
- `GET /api/v1/experience/recommendation/{recommendation_id}`

### Graph

- `POST /api/v1/graph/sync`
- `GET /api/v1/graph/neighbors/{service}`
- `GET /api/v1/graph/pattern/{failure}`
- `GET /api/v1/graph/recommendation/{recommendation_id}`
- `POST /api/v1/graph/query`

### Product / Dashboard

- `GET /`
- `GET /api/v1/dashboard/summary`
- `GET /api/v1/dashboard/incidents`
- `POST /api/v1/dashboard/incidents/{id}/resolve`
- `GET /api/v1/dashboard/services`
- `GET /api/v1/dashboard/patterns`
- `POST /api/v1/dashboard/investigate`
- `GET /api/v1/dashboard/stats`
- `GET /api/v1/experience/history`

### Benchmark

- `GET /api/v1/benchmark/scorecard`

## Evaluation Layer

An automated benchmark suite now exists in `backend/evaluate.py`.

It:

1. seeds reference memory from synthetic incidents
2. seeds synthetic experience history
3. builds graph context and operational patterns
4. evaluates 30 benchmark incidents
5. writes a JSON report and Markdown scorecard

The benchmark dataset is:

- `backend/data/benchmark_incidents.json`

A hidden holdout benchmark exists separately:

- `backend/data/holdout_incidents.json` (20 cases across 10 failure scenarios)

The benchmark supports isolated local storage for repeatable evaluation runs:

- local Qdrant path mode
- local graph SQLite database
- local experience SQLite database
- configurable report output directory via `EVALUATION_REPORT_DIR`

Field-level normalization confusion tracking is included in both JSON and Markdown reports.

## Validation Results

### Local code validation

These passed:

- `test_experience_engine.py`
- `test_graph_engine.py`
- live benchmark execution in `backend/evaluate.py`

### Live HTTP end-to-end check

A fresh app instance was started on `http://127.0.0.1:8010` on **Wednesday, July 23, 2026** and exercised over HTTP.

Working in that run:

- `GET /api/v1/health` — returns `{"status":"ok","incident_count":20}`
- `GET /api/v1/benchmark/scorecard` — returns `{"available":false,...}` (no hardcoded values)
- SigNoz UI accessible at `http://localhost:8080`
- MCP server healthy at `http://localhost:8000/mcp`

### Frontend validation

The scorecard section now shows `—` placeholders until a real benchmark runs:

- All metric elements default to em-dash (`&mdash;`)
- `refreshScorecard()` in `app.js` populates real values from API when available
- Fixed `sc-evaluation-date` → `sc-eval-date` ID mismatch in `app.js`

### Benchmark snapshot

The scorecard now returns **only real, measured data** — no hardcoded fallback values.

When no benchmark report exists:

- `available: false`
- All metric fields are empty `{}`

When a benchmark has been run (auto-run on first server startup):

- `available: true`
- All metrics populated from `backend/data/evaluation_report.json`

## Important Limitations

1. The graph backend is still local SQLite, not Neo4j.
2. Live telemetry and knowledge analysis no longer hard-fail without external inference, but fallback outputs are less precise than the intended LLM-backed behavior.
3. The old Day 1/Day 2 agent path is still present, but it is not yet aligned with the newer graph-aware recommendation flow.
4. Some seeded knowledge objects still produce sparse graph nodes when normalized fields such as `failure_type` are empty.
5. The current benchmark shows experience-aware ranking underperforming the raw retrieval baseline on the synthetic suite.
6. The SigNoz alert integration depends on the MCP server exposing `signoz_list_alerts` and related tools — if the MCP version doesn't support them, the alert watcher silently degrades.

## Immediate Next Steps

1. Test the full integration flow: `siggy init` → `siggy serve` → `siggy instrument` → alerts appearing in dashboard.
2. Improve graph hygiene for older seeded data so blank failure nodes are not created.
3. Replace the local graph storage backend with Neo4j once the graph semantics are stable.
4. Improve fallback quality for telemetry summarization and normalization when the external LLM path is unavailable.
5. Tune recommendation ranking against the benchmark until it beats the raw retrieval baseline.
6. Extend the graph later with richer entities like:
   - deployments
   - pull requests
   - commits
   - engineers

## What We Did So Far (Summary)

1. **Backend core**: FastAPI backend with Qdrant vector memory, knowledge normalization, experience ranking, knowledge graph, and automated benchmark suite.
2. **SigNoz integration**: MCP-based alert consumption, OTel auto-instrumentation, dashboard + saved views auto-creation via direct SigNoz REST API (bypassing MCP auth limitation).
3. **CLI**: Click-based CLI with 5 commands (`init`, `instrument`, `watch`, `investigate`, `dashboard`).
4. **Evaluation**: 30-case benchmark + 20-case holdout, field-level normalization confusion tracking, auto-runs on first server boot.
5. **SigNoz UI surface**: Dashboard "Siggy - Memory Layer" with 4 panels, 2 saved views (Recommendations + Low Confidence), all auto-created idempotently on server startup.
6. **User-friendly installation**: API key lives in `.siggy.yaml` only (never in compose files), `siggy init` prompts interactively with step-by-step instructions, validates key before storing, graceful degradation without key.

## Design Principles

1. Structured schemas over free-form LLM output
2. Retrieval should combine semantics, metadata, experience, and relationships
3. Recommendations must be explainable with evidence
4. Experience should improve future recommendations
5. Every new feature should increase future decision quality, not just present nicer output
