"""Siggy — AI-powered observability memory layer for SigNoz.

This is the core API server. The CLI (siggy watch, siggy investigate) is the
primary interface. This server exposes the knowledge pipeline, experience,
and graph endpoints for programmatic access.
"""

from __future__ import annotations

import asyncio
import json
import os
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from utils.paths import siggy_data_dir, siggy_env_path

_env_path = siggy_env_path()
if _env_path.exists():
    from dotenv import load_dotenv
    load_dotenv(_env_path, override=True)

from models.incident import (
    Incident,
    IncidentQuery,
    NormalizedIncident,
    RecommendationResponse,
    AgentAnalysisResponse,
    TelemetrySummary,
    InvestigationResponse,
    ExperienceRecord,
)
from knowledge.schema import KnowledgeObject, SearchFilters, ExplainableRecommendation
from knowledge.normalizer import normalize_to_knowledge
from knowledge.pipeline import (
    knowledge_pipeline,
    knowledge_pipeline_from_telemetry,
    store_knowledge_object,
    search_by_knowledge,
    build_explainable_recommendation,
)
from experience.store import get_experience_store
from experience.statistics import get_statistics_engine
from experience.aggregator import get_pattern_aggregator
from experience.models import ExperienceRecordCreate
from graph.builder import get_graph_builder
from graph.context_builder import get_graph_context_builder
from graph.queries import get_graph_queries
from agents.normalizer import normalize_incident, build_embedding_text
from agents.recommender import recommend_fix
from agents.incident_agent import IncidentAgent
from agents.investigator import InvestigatorAgent
from memory.embeddings import get_embedding
from memory.vector_store import get_store
from memory.search import get_search
from rules.engine import evaluate_rules
from telemetry.signoz_mcp import get_telemetry_provider
from telemetry.mcp_http import DEFAULT_MCP_URL

DATA_DIR = siggy_data_dir()
SIGNOZ_MCP_URL = os.getenv("SIGNOZ_MCP_URL", DEFAULT_MCP_URL)


def _setup_otel():
    """Configure OpenTelemetry self-instrumentation for Siggy."""
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")
        if not otlp_endpoint:
            return

        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

        provider = TracerProvider()
        exporter = OTLPSpanExporter(endpoint=otlp_endpoint)
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)
        print(f"OpenTelemetry enabled -> {otlp_endpoint}")
    except Exception as e:
        print(f"OpenTelemetry skipped: {e}")


_siggysidecar = None
_sidecar_task = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _siggysidecar, _sidecar_task

    from cli.config import SiggyConfig

    config = SiggyConfig.load()

    store = get_store()
    count = store.count()
    if count == 0:
        seed_incidents(store)

    _setup_otel()

    # Auto-create Siggy dashboard and saved views in SigNoz
    try:
        from signoz.dashboards import setup_siggy_in_signoz
        setup_result = setup_siggy_in_signoz(
            api_key=config.signoz.api_key,
            signoz_url=config.signoz.url,
        )
        if setup_result.get("errors"):
            for err in setup_result["errors"]:
                print(f"SigNoz setup: {err}")
        else:
            print("Siggy dashboard + views created in SigNoz")
    except Exception as e:
        print(f"SigNoz dashboard setup skipped: {e}")

    try:
        telemetry = get_telemetry_provider()
        await telemetry.connect()
        print("Connected to SigNoz MCP")
    except BaseException as e:
        print(f"Warning: SigNoz MCP unreachable: {e}")

    try:
        from incident.processor import SiggySidecar
        _siggysidecar = SiggySidecar(config)
        _sidecar_task = asyncio.create_task(
            _siggysidecar.start_polling(interval=30)
        )
        print("Siggy sidecar started (polling every 30s)")
    except Exception as e:
        print(f"Warning: Sidecar failed to start: {e}")

    asyncio.get_event_loop().run_in_executor(None, _run_benchmark_on_startup)

    yield

    if _sidecar_task:
        _sidecar_task.cancel()
        try:
            await _sidecar_task
        except asyncio.CancelledError:
            pass

    try:
        telemetry = get_telemetry_provider()
        await telemetry.disconnect()
    except BaseException:
        pass


def _run_benchmark_on_startup():
    report_path = DATA_DIR / "evaluation_report.json"
    if report_path.exists():
        print("Benchmark report found, skipping")
        return

    try:
        import importlib
        import sys
        evaluate = importlib.import_module("evaluate")
        print("Running benchmark (first boot)...")
        summary = evaluate.evaluate()
        metrics = summary.get("metrics", {})
        print(f"Benchmark: {summary['dataset_size']} cases, "
              f"retrieval_top1={metrics.get('incident_retrieval_top1_accuracy', 0)}%, "
              f"normalization={metrics.get('knowledge_normalization_accuracy', 0)}%")
    except Exception as e:
        print(f"Benchmark skipped: {e}")


app = FastAPI(
    title="Siggy — Memory Layer for SigNoz",
    version="0.5.1",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/v1/health")
def health():
    store = get_store()
    return {"status": "ok", "incident_count": store.count()}


@app.get("/api/v1/incidents")
def list_incidents():
    store = get_store()
    return {"incidents": store.get_all(), "count": store.count()}


@app.post("/api/v1/incidents/seed")
def seed():
    store = get_store()
    count = store.count()
    if count > 0:
        return {"message": f"Already seeded {count} incidents"}
    seed_incidents(store)
    return {"message": "Seeded incidents as knowledge objects"}


@app.post("/api/v1/incidents/search")
def search_incidents(query: IncidentQuery):
    result = knowledge_pipeline(
        title=query.title,
        summary=query.summary,
    )
    return {
        "knowledge_object": result["knowledge_object"],
        "similar_incidents": result["similar_incidents"],
    }


@app.post("/api/v1/incidents/recommend")
def get_recommendation(query: IncidentQuery):
    result = knowledge_pipeline(
        title=query.title,
        summary=query.summary,
        store_new=False,
    )
    return {
        "current_incident": query.model_dump(),
        "similar_incidents": result["similar_incidents"],
        "knowledge_object": result["knowledge_object"],
        "recommendation": result["recommendation"]["recommendation"],
        "recommendation_id": result["recommendation"]["recommendation_id"],
        "confidence": result["recommendation"]["confidence"],
        "evidence": result["recommendation"]["evidence"],
        "graph_context": result["recommendation"].get("graph_context"),
        "reasoning": result["recommendation"]["reasoning"],
    }


@app.post("/api/v1/incidents/store")
def store_incident(incident: Incident):
    ko = normalize_to_knowledge(
        title=incident.title,
        summary=incident.summary,
        incident_id=incident.id,
    )
    ko.root_cause = incident.root_cause
    ko.fix = incident.fix
    ko.severity = incident.severity
    if incident.affected_services:
        ko.service = incident.affected_services[0]

    point_id = store_knowledge_object(ko, incident.title)
    return {"id": point_id, "message": "Incident stored as KnowledgeObject"}


@app.post("/api/v1/knowledge/analyze")
def knowledge_analyze(query: IncidentQuery):
    try:
        result = knowledge_pipeline(
            title=query.title,
            summary=query.summary,
            store_new=False,
        )
        return {
            "current_incident": {"title": query.title, "summary": query.summary},
            "knowledge_object": result["knowledge_object"],
            "similar_incidents": result["similar_incidents"],
            "recommendation": result["recommendation"]["recommendation"],
            "recommendation_id": result["recommendation"]["recommendation_id"],
            "confidence": result["recommendation"]["confidence"],
            "evidence": result["recommendation"]["evidence"],
            "graph_context": result["recommendation"].get("graph_context"),
            "reasoning": result["recommendation"]["reasoning"],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v1/knowledge/store")
def store_knowledge(query: IncidentQuery):
    try:
        ko = normalize_to_knowledge(
            title=query.title,
            summary=query.summary,
        )
        point_id = store_knowledge_object(ko, query.title)
        return {
            "id": point_id,
            "knowledge_object": ko.model_dump(),
            "message": "KnowledgeObject stored successfully",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


agent = IncidentAgent()


@app.post("/api/v1/agent/analyze", response_model=AgentAnalysisResponse)
def analyze_incident(query: IncidentQuery):
    try:
        result = agent.analyze(query.title, query.summary)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


investigator = InvestigatorAgent()


@app.post("/api/v1/telemetry/investigate")
async def investigate(query: dict):
    try:
        summary = await investigator.investigate(query["query"])
        return InvestigationResponse(
            query=query["query"],
            telemetry_summary=TelemetrySummary(**summary),
        ).model_dump()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v1/telemetry/full-analysis")
async def full_telemetry_analysis(query: dict):
    try:
        summary = await investigator.investigate(query["query"])

        rule_result = evaluate_rules(summary)
        if rule_result:
            return {
                "source": "rule_engine",
                "telemetry_summary": summary,
                "analysis": rule_result,
            }

        result = knowledge_pipeline_from_telemetry(
            telemetry_summary=summary,
            store_new=False,
        )

        return {
            "source": "knowledge_pipeline",
            "telemetry_summary": summary,
            "knowledge_object": result["knowledge_object"],
            "similar_incidents": result["similar_incidents"],
            "recommendation": result["recommendation"]["recommendation"],
            "recommendation_id": result["recommendation"]["recommendation_id"],
            "confidence": result["recommendation"]["confidence"],
            "evidence": result["recommendation"]["evidence"],
            "graph_context": result["recommendation"].get("graph_context"),
            "reasoning": result["recommendation"]["reasoning"],
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v1/experience/record")
def record_experience(record: ExperienceRecord):
    store = get_experience_store()
    created = store.record_experience(record.to_experience_create())
    get_graph_builder().sync_operational_patterns()
    return {
        "experience": created.model_dump(),
        "message": "Experience recorded",
    }


@app.get("/api/v1/experience/stats")
def get_experience_stats(recommendation_id: str):
    statistics = get_statistics_engine().get_recommendation_statistics(recommendation_id)
    patterns = [
        pattern.model_dump()
        for pattern in get_pattern_aggregator().build_patterns()
        if pattern.best_recommendation_id == statistics.recommendation_id
    ]
    return {"statistics": statistics.model_dump(), "patterns": patterns}


@app.get("/api/v1/experience/statistics")
def get_experience_statistics(recommendation_id: str | None = None):
    statistics_engine = get_statistics_engine()
    if recommendation_id:
        return statistics_engine.get_recommendation_statistics(recommendation_id).model_dump()
    return {
        "recommendations": [
            item.model_dump() for item in statistics_engine.list_recommendation_statistics()
        ]
    }


@app.get("/api/v1/experience/patterns")
def get_experience_patterns(service: str | None = None, failure_type: str | None = None):
    patterns = get_pattern_aggregator().build_patterns(service=service, failure_type=failure_type)
    return {"patterns": [pattern.model_dump() for pattern in patterns]}


@app.get("/api/v1/experience/recommendations")
def list_experience_recommendations():
    statistics = get_statistics_engine().list_recommendation_statistics()
    return {"recommendations": [item.model_dump() for item in statistics]}


@app.get("/api/v1/experience/history")
def get_experience_history(limit: int = 100):
    store = get_experience_store()
    experiences = store.get_experiences(limit=limit)
    return {"experiences": [record.model_dump() for record in experiences], "count": len(experiences)}


@app.get("/api/v1/experience/recommendation/{recommendation_id}")
def get_recommendation_detail(recommendation_id: str):
    store = get_experience_store()
    statistics = get_statistics_engine().get_recommendation_statistics(recommendation_id)
    experiences = store.get_by_recommendation(recommendation_id, limit=50)
    patterns = [
        pattern.model_dump()
        for pattern in get_pattern_aggregator().build_patterns()
        if pattern.best_recommendation_id == statistics.recommendation_id
    ]
    return {
        "statistics": statistics.model_dump(),
        "patterns": patterns,
        "experiences": [record.model_dump() for record in experiences],
    }


@app.post("/api/v1/graph/sync")
def sync_graph():
    result = get_graph_builder().sync_all()
    return {"message": "Graph sync completed", **result}


@app.get("/api/v1/graph/neighbors/{service}")
def get_graph_neighbors(service: str):
    try:
        return get_graph_queries().get_neighbors(service).model_dump()
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/api/v1/graph/pattern/{failure}")
def get_graph_pattern(failure: str):
    return get_graph_queries().get_pattern(failure).model_dump()


@app.get("/api/v1/graph/recommendation/{recommendation_id}")
def get_graph_recommendation(recommendation_id: str):
    try:
        return get_graph_queries().get_recommendation(recommendation_id).model_dump()
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/api/v1/graph/query")
def graph_query(payload: dict):
    question = payload.get("question", "")
    if not question:
        raise HTTPException(status_code=400, detail="Missing 'question'")
    return get_graph_queries().run_natural_language_query(question)


@app.get("/api/v1/dashboard/summary")
def get_dashboard_summary():
    store = get_store()
    experience_store = get_experience_store()
    statistics_engine = get_statistics_engine()
    patterns = get_pattern_aggregator().build_patterns()
    graph_client = get_graph_builder().client
    recommendation_stats = statistics_engine.list_recommendation_statistics()

    total_times_used = sum(item.times_used for item in recommendation_stats)
    total_worked = sum(item.worked_count for item in recommendation_stats)
    recommendation_accuracy = round((total_worked / total_times_used) * 100, 2) if total_times_used else 0.0

    return {
        "knowledge_objects": store.count(),
        "operational_patterns": len(patterns),
        "experience_records": experience_store.count(),
        "recommendation_accuracy": recommendation_accuracy,
        "average_confidence": experience_store.average_confidence(),
        "graph_nodes": graph_client.count_nodes(),
        "graph_edges": graph_client.count_edges(),
        "recommendations_tracked": len(recommendation_stats),
    }


@app.get("/api/v1/benchmark/scorecard")
def get_benchmark_scorecard():
    report_path = DATA_DIR / "evaluation_report.json"
    if report_path.exists():
        try:
            with report_path.open(encoding="utf-8") as f:
                report = json.load(f)
            return {
                "available": True,
                "evaluation_date": report.get("evaluation_date", ""),
                "dataset_size": report.get("dataset_size", 0),
                "metrics": report.get("metrics", {}),
                "confusion_summary": report.get("confusion_summary", {}),
                "holdout_results": report.get("holdout_results"),
            }
        except Exception:
            pass
    return {
        "available": False,
        "evaluation_date": None,
        "dataset_size": 0,
        "metrics": {},
        "confusion_summary": {},
        "holdout_results": None,
    }


@app.get("/api/v1/telemetry/health")
async def telemetry_health():
    try:
        telemetry = get_telemetry_provider()
        healthy = await telemetry.health_check()
        return {"connected": healthy, "mcp_url": SIGNOZ_MCP_URL}
    except Exception as e:
        return {"connected": False, "error": str(e)}


def seed_incidents(store):
    for filename in ["fake_incidents.json", "eval_incidents.json", "demo_incidents.json"]:
        filepath = DATA_DIR / filename
        if not filepath.exists():
            continue
        with open(filepath) as f:
            incidents = json.load(f)

        for inc in incidents:
            ko = KnowledgeObject(
                incident_id=inc["id"],
                title=inc["title"],
                summary=inc["summary"],
                service=inc["affected_services"][0] if inc.get("affected_services") else "unknown",
                component=_guess_component(inc),
                failure_type="",
                symptoms=[],
                severity=inc.get("severity", "high"),
                environment="production",
                root_cause=inc["root_cause"],
                fix=inc["fix"],
                fix_type="",
                confidence=1.0,
            )
            store_knowledge_object(ko, inc["title"])
        print(f"Seeded {len(incidents)} knowledge objects from {filename}")


def _guess_component(inc: dict) -> str:
    text = f"{inc.get('title', '')} {inc.get('summary', '')} {inc.get('root_cause', '')}".lower()
    components = ["redis", "kafka", "postgresql", "mysql", "mongodb", "elasticsearch",
                  "cpu", "memory", "disk", "network", "dns", "nginx", "rabbitmq"]
    for c in components:
        if c in text:
            return c
    return "unknown"
