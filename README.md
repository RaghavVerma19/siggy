# Siggy

**Operational memory for your infrastructure.**

Siggy is an AI-powered incident investigation CLI that sits alongside [SigNoz](https://signoz.io/) as a sidecar. It learns from every fix, builds a knowledge graph of your infrastructure, and returns explainable recommendations grounded in your operational history.

```
$ siggy investigate "Redis timeout in checkout"

  Root cause: Redis connection pool exhausted
  Confidence: 87%
  Similar incidents: 3 found

  Recommendation:
    Increase Redis pool size from 64 to 128.
    Set idle connection timeout to 30s.
```

## Features

- **Vector Memory** — retrieves similar past incidents from Qdrant
- **Knowledge Graph** — expands context through services, components, failure types
- **Experience Engine** — ranks fixes by historical success rates and resolution times
- **Auto-Instrumentation** — wraps any Python app with OpenTelemetry, zero code changes
- **Explainable Recommendations** — root cause, fix, confidence, and evidence
- **Graceful Degradation** — works without external LLMs, without Qdrant Docker, without a SigNoz API key

## Quick Start

```bash
pip install siggy-memory

# One-command setup (auto-detects Docker, Qdrant, SigNoz, GROQ)
siggy quickstart

# Or step by step
siggy init
siggy serve
```

## Commands

| Command | Description |
|---|---|
| `siggy quickstart` | One-command setup, auto-detects everything |
| `siggy init` | Connect to SigNoz, configure memory |
| `siggy instrument` | Auto-instrument any Python app with OTel |
| `siggy watch` | Sidecar mode, enriches alerts with memory |
| `siggy serve` | Start API server + sidecar |
| `siggy up` | All-in-one: server + sidecar + your app |
| `siggy investigate` | Manual investigation through memory pipeline |
| `siggy status` | System health and connection checks |
| `siggy demo` | Ready-to-go demo, no SigNoz needed |

## How It Works

```
Your App → OTel → SigNoz → Alert fires
                              ↓
                    siggy watch detects alert
                              ↓
                    Normalize → KnowledgeObject
                              ↓
                    Vector search (Qdrant) → similar past incidents
                              ↓
                    Graph expansion → related services, patterns
                              ↓
                    Experience ranking → historical outcomes
                              ↓
                    Explainable recommendation written to SigNoz
```

## Architecture

```text
backend/
├── cli/               # Click-based CLI (siggy commands)
├── agents/            # Investigator agent
├── knowledge/         # Normalization, taxonomy, pipeline
├── experience/        # Feedback store, ranking, patterns
├── graph/             # Knowledge graph (SQLite-backed)
├── memory/            # Embeddings, Qdrant vector store
├── incident/          # Alert enrichment, OTel write-back
├── signoz/            # Dashboard + saved view auto-creation
├── otel/              # Auto-instrumentation wrapper
├── telemetry/         # SigNoz MCP integration
├── llm/               # LLM prompt management
├── siggy_server/      # FastAPI server (main.py)
└── evaluate.py        # Benchmark suite
website/               # Marketing site
demo/                  # Demo Flask app
docs/                  # Documentation
```

## API

The backend exposes 20+ REST endpoints:

- `POST /api/v1/incidents/recommend` — get recommendation for an incident
- `POST /api/v1/telemetry/investigate` — investigate raw telemetry
- `POST /api/v1/experience/record` — record recommendation outcome
- `GET /api/v1/experience/patterns` — operational patterns
- `POST /api/v1/graph/sync` — sync knowledge to graph
- `GET /api/v1/graph/neighbors/{service}` — graph context
- `GET /api/v1/benchmark/scorecard` — evaluation metrics

## Evaluation

Run the benchmark suite:

```bash
cd backend
python evaluate.py
```

- 30-case benchmark dataset + 20-case hidden holdout
- Field-level normalization confusion tracking
- Measures retrieval accuracy, recommendation quality, and latency
- Auto-runs on first server boot

## Tech Stack

Python 3.10+ · FastAPI · Qdrant · SigNoz · OpenTelemetry · SQLite · GROQ · Click · Pydantic

## License

MIT
