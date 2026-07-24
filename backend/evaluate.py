from __future__ import annotations

import json
import os
import shutil
import statistics
import sys
import tempfile
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from experience.aggregator import ExperiencePatternAggregator
from experience.models import ExperienceRecordCreate, canonicalize_recommendation_id
from experience.ranking import ExperienceAwareRanker
from experience.statistics import ExperienceStatisticsEngine
from experience.store import ExperienceStore
from graph.builder import GraphBuilder
from graph.client import GraphClient
from graph.context_builder import GraphContextBuilder
from graph.queries import GraphQueryService
from knowledge.normalizer import build_search_filters_from_knowledge
from knowledge.normalization_v2 import normalize_deterministic, NormalizationReport
from knowledge.schema import KnowledgeObject
from memory.embeddings import get_embedding
from memory.search import IncidentSearch
from memory.vector_store import VectorStore
from utils.fallbacks import normalize_knowledge_fallback


BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
REPORT_DIR = Path(os.getenv("EVALUATION_REPORT_DIR", str(DATA_DIR)))
REPORT_JSON_PATH = REPORT_DIR / "evaluation_report.json"
REPORT_MD_PATH = REPORT_DIR / "evaluation_report.md"

REFERENCE_DATASETS = [
    DATA_DIR / "fake_incidents.json",
    DATA_DIR / "eval_incidents.json",
]
BENCHMARK_DATASET = DATA_DIR / "benchmark_incidents.json"
HOLDOUT_DATASET = DATA_DIR / "holdout_incidents.json"

EVALUATION_FIELDS = ["service", "component", "failure_type", "fix_type", "severity"]


def _load_json(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _guess_knowledge_object(incident: dict) -> KnowledgeObject:
    inferred = normalize_knowledge_fallback(incident["title"], incident["summary"], incident.get("id", ""))
    service = incident.get("affected_services", [None])[0] or inferred["service"]
    return KnowledgeObject(
        incident_id=incident.get("id", ""),
        title=incident["title"],
        summary=incident["summary"],
        service=service,
        component=inferred["component"],
        failure_type=inferred["failure_type"],
        symptoms=inferred["symptoms"],
        severity=incident.get("severity", inferred["severity"]),
        environment="production",
        root_cause=incident["root_cause"],
        fix=incident["fix"],
        fix_type=inferred["fix_type"],
        confidence=1.0,
    )


def _normalize_text(value: str) -> str:
    return " ".join((value or "").lower().replace("_", " ").split())


def _matches_keywords(text: str, keywords: list[str]) -> bool:
    normalized = _normalize_text(text)
    return all(keyword.lower() in normalized for keyword in keywords)


def _baseline_recommendations(similar_incidents: list[dict]) -> list[str]:
    scored: dict[str, float] = {}
    for incident in similar_incidents:
        recommendation = incident.get("fix", "").strip()
        if not recommendation:
            continue
        scored[recommendation] = max(scored.get(recommendation, 0.0), float(incident.get("similarity", 0.0)))
    return [item[0] for item in sorted(scored.items(), key=lambda pair: (-pair[1], pair[0]))]


def _mean(values: list[float]) -> float:
    return round(statistics.fmean(values), 2) if values else 0.0


def _pct(numerator: int, denominator: int) -> float:
    return round((numerator / denominator) * 100, 2) if denominator else 0.0


class EvaluationRuntime:
    def __init__(self) -> None:
        self.temp_root = Path(tempfile.mkdtemp(prefix="signoz-eval-"))
        self.vector_store = VectorStore(
            path=str(self.temp_root / "qdrant"),
            collection_name="evaluation_incidents",
        )
        self.search = IncidentSearch(store=self.vector_store)
        self.experience_store = ExperienceStore(db_path=str(self.temp_root / "experience.db"))
        self.statistics = ExperienceStatisticsEngine(self.experience_store)
        self.aggregator = ExperiencePatternAggregator(self.experience_store, self.statistics)
        self.ranker = ExperienceAwareRanker(self.statistics, self.aggregator)
        self.graph_client = GraphClient(db_path=str(self.temp_root / "graph.db"))
        self.graph_builder = GraphBuilder(self.graph_client, self.statistics, self.aggregator)
        self.graph_context_builder = GraphContextBuilder(self.graph_client, self.statistics, self.aggregator)
        self.graph_queries = GraphQueryService(self.graph_client)

    def close(self) -> None:
        try:
            self.vector_store.close()
        except Exception:
            pass
        try:
            self.graph_client.close()
        except Exception:
            pass
        try:
            self.experience_store.close()
        except Exception:
            pass
        shutil.rmtree(self.temp_root, ignore_errors=True)

    def seed_reference_memory(self, incidents: list[dict]) -> None:
        for incident in incidents:
            knowledge_object = _guess_knowledge_object(incident)
            point_id = int(incident["id"])
            embedding = get_embedding(knowledge_object.to_embedding_text())
            self.vector_store.store_knowledge(knowledge_object.to_search_payload(), embedding, point_id)
            self.graph_builder.sync_knowledge_object(knowledge_object)

    def seed_experience_history(self, incidents: list[dict]) -> None:
        profiles = {
            "increase_pool_size": (0.96, 540),
            "add_exponential_backoff": (0.9, 780),
            "reduce_log_retention": (0.91, 900),
            "reduce_query_load": (0.86, 1260),
            "renew_certificate": (0.98, 300),
            "restart_service": (0.58, 1320),
        }

        for incident in incidents:
            knowledge_object = _guess_knowledge_object(incident)
            success_rate, resolution = profiles.get(knowledge_object.fix_type, (0.72, 1200))
            canonical_id = canonicalize_recommendation_id(
                recommendation=knowledge_object.fix,
                fix_type=knowledge_object.fix_type,
            )
            canonical_label = canonical_id.replace("_", " ").title()

            for offset in range(4):
                self.experience_store.record_experience(
                    ExperienceRecordCreate(
                        incident_id=f"{incident['id']}-success-{offset}",
                        recommendation_id=canonical_id,
                        recommendation=canonical_label,
                        accepted=True,
                        worked=offset < round(success_rate * 4),
                        resolution_time_seconds=resolution + (offset * 45),
                        engineer_feedback="Benchmark success history",
                        confidence=0.82 + (offset * 0.03),
                        service=knowledge_object.service,
                        component=knowledge_object.component,
                        failure_type=knowledge_object.failure_type,
                        symptoms=knowledge_object.symptoms,
                    )
                )

            self.experience_store.record_experience(
                ExperienceRecordCreate(
                    incident_id=f"{incident['id']}-fallback",
                    recommendation_id="RESTART_SERVICE",
                    recommendation="Restart Service",
                    accepted=True,
                    worked=False,
                    resolution_time_seconds=1500,
                    engineer_feedback="Generic restart did not fully resolve the issue",
                    confidence=0.51,
                    service=knowledge_object.service,
                    component=knowledge_object.component,
                    failure_type=knowledge_object.failure_type,
                    symptoms=knowledge_object.symptoms,
                )
            )

        self.graph_builder.sync_operational_patterns()

    def search_by_knowledge(self, knowledge_object: KnowledgeObject, top_k: int = 5) -> list[dict]:
        embedding = get_embedding(knowledge_object.to_embedding_text())
        filters = build_search_filters_from_knowledge(knowledge_object)
        filter_dict = {k: v for k, v in filters.model_dump().items() if v is not None}
        results = self.search.retrieve(
            query_embedding=embedding,
            top_k=top_k,
            filters=filter_dict or None,
        )
        if len(results) < 2:
            results = self.search.retrieve(query_embedding=embedding, top_k=top_k, filters=None)
        return results

    def evaluate_case(self, case: dict) -> dict:
        start_total = time.perf_counter()

        normalization_start = time.perf_counter()
        normalized, norm_report = normalize_deterministic(case["title"], case["summary"], case["id"])
        knowledge_object = KnowledgeObject(
            incident_id=case["id"],
            title=normalized["title"],
            summary=case["summary"],
            service=normalized["service"],
            component=normalized["component"],
            failure_type=normalized["failure_type"],
            symptoms=normalized["symptoms"],
            severity=normalized["severity"],
            environment=normalized["environment"],
            root_cause=normalized["root_cause"],
            fix=normalized["fix"],
            fix_type=normalized["fix_type"],
            confidence=normalized["confidence"],
        )
        normalization_ms = (time.perf_counter() - normalization_start) * 1000

        retrieval_start = time.perf_counter()
        similar_incidents = self.search_by_knowledge(knowledge_object, top_k=5)
        retrieval_ms = (time.perf_counter() - retrieval_start) * 1000

        baseline_recommendations = _baseline_recommendations(similar_incidents)

        ranking_start = time.perf_counter()
        ranked = self.ranker.rank(
            knowledge_object=knowledge_object,
            similar_incidents=similar_incidents,
            fallback_recommendation=knowledge_object.fix,
            fallback_fix_type=knowledge_object.fix_type,
            fallback_confidence=knowledge_object.confidence,
        )
        graph_context = self.graph_context_builder.build(
            knowledge_object,
            ranked_recommendations=[item.model_dump() for item in ranked],
        )
        ranking_ms = (time.perf_counter() - ranking_start) * 1000

        graph_start = time.perf_counter()
        graph_checks = []
        try:
            graph_checks.append(self.graph_queries.get_neighbors(knowledge_object.service).model_dump())
        except Exception:
            graph_checks.append(None)
        try:
            graph_checks.append(self.graph_queries.get_pattern(knowledge_object.failure_type).model_dump())
        except Exception:
            graph_checks.append(None)
        graph_checks.append(
            self.graph_queries.run_natural_language_query(
                f"Which services depend on {knowledge_object.component}?"
            )
        )
        graph_query_ms = (time.perf_counter() - graph_start) * 1000

        top_ranked = ranked[0] if ranked else None
        recommendation_text = top_ranked.recommendation if top_ranked else knowledge_object.fix
        recommendation_confidence = round(top_ranked.final_score if top_ranked else knowledge_object.confidence, 3)
        ranked_texts = [item.recommendation for item in ranked[:3]]
        baseline_top3 = baseline_recommendations[:3]
        expected_recommendation_keywords = case["expected_recommendation_keywords"]

        normalization_fields = {}
        normalization_confusions = {}
        for field in EVALUATION_FIELDS:
            expected_key = f"expected_{field}"
            expected_value = case.get(expected_key, "")
            predicted_value = knowledge_object.model_dump().get(field, "")
            match = predicted_value == expected_value
            normalization_fields[field] = match
            if not match:
                normalization_confusions[field] = {
                    "expected": expected_value,
                    "predicted": predicted_value,
                }
        normalization_accuracy = sum(normalization_fields.values()) / len(normalization_fields)

        top_match = similar_incidents[0] if similar_incidents else {}
        top3_retrieval_hit = any(
            _matches_keywords(item.get("root_cause", ""), case["expected_root_cause_keywords"])
            for item in similar_incidents[:3]
        )
        top1_retrieval_hit = _matches_keywords(top_match.get("root_cause", ""), case["expected_root_cause_keywords"])

        top1_baseline_hit = _matches_keywords(baseline_recommendations[0], expected_recommendation_keywords) if baseline_recommendations else False
        top3_baseline_hit = any(_matches_keywords(item, expected_recommendation_keywords) for item in baseline_top3)
        top1_ranked_hit = _matches_keywords(recommendation_text, expected_recommendation_keywords)
        top3_ranked_hit = any(_matches_keywords(item, expected_recommendation_keywords) for item in ranked_texts)

        total_ms = (time.perf_counter() - start_total) * 1000

        return {
            "id": case["id"],
            "title": case["title"],
            "knowledge_object": knowledge_object.model_dump(mode="json"),
            "similar_titles": [item.get("title", "") for item in similar_incidents[:3]],
            "recommendation": recommendation_text,
            "recommendation_confidence": recommendation_confidence,
            "ranked_recommendations": ranked_texts,
            "baseline_recommendations": baseline_top3,
            "graph_evidence": graph_context.evidence,
            "metrics": {
                "normalization_accuracy": round(normalization_accuracy, 3),
                "normalization_fields": normalization_fields,
                "normalization_confusions": normalization_confusions,
                "normalization_method": norm_report.method,
                "retrieval_top1_hit": top1_retrieval_hit,
                "retrieval_top3_hit": top3_retrieval_hit,
                "baseline_top1_hit": top1_baseline_hit,
                "baseline_top3_hit": top3_baseline_hit,
                "ranked_top1_hit": top1_ranked_hit,
                "ranked_top3_hit": top3_ranked_hit,
                "confidence": recommendation_confidence,
                "normalization_latency_ms": round(normalization_ms, 2),
                "retrieval_latency_ms": round(retrieval_ms, 2),
                "ranking_latency_ms": round(ranking_ms, 2),
                "graph_query_latency_ms": round(graph_query_ms, 2),
                "response_latency_ms": round(total_ms, 2),
            },
        }


def _build_confusion_summary(results: list[dict]) -> dict:
    confusion_by_field: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    method_counts: dict[str, int] = defaultdict(int)
    field_correct = {field: 0 for field in EVALUATION_FIELDS}
    total = len(results)

    for item in results:
        method = item["metrics"].get("normalization_method", "unknown")
        method_counts[method] += 1
        for field in EVALUATION_FIELDS:
            if item["metrics"]["normalization_fields"][field]:
                field_correct[field] += 1
            else:
                confusions = item["metrics"].get("normalization_confusions", {})
                if field in confusions:
                    pair = confusions[field]
                    confusion_key = f"{pair['expected']} -> {pair['predicted']}"
                    confusion_by_field[field][confusion_key] += 1

    field_confusion_tables: dict[str, list[dict]] = {}
    for field in EVALUATION_FIELDS:
        top_confusions = sorted(
            confusion_by_field[field].items(),
            key=lambda x: -x[1],
        )[:5]
        field_confusion_tables[field] = [
            {"pair": pair, "count": count, "pct": _pct(count, total)}
            for pair, count in top_confusions
        ]

    return {
        "field_accuracy": {
            field: {
                "correct": field_correct[field],
                "incorrect": total - field_correct[field],
                "accuracy_pct": _pct(field_correct[field], total),
            }
            for field in EVALUATION_FIELDS
        },
        "field_confusion_top5": field_confusion_tables,
        "normalization_method_distribution": dict(method_counts),
    }


def _build_summary(cases: list[dict], runtime: EvaluationRuntime) -> dict:
    results = [runtime.evaluate_case(case) for case in cases]
    total = len(results)

    retrieval_top1 = sum(1 for item in results if item["metrics"]["retrieval_top1_hit"])
    retrieval_top3 = sum(1 for item in results if item["metrics"]["retrieval_top3_hit"])
    baseline_top1 = sum(1 for item in results if item["metrics"]["baseline_top1_hit"])
    baseline_top3 = sum(1 for item in results if item["metrics"]["baseline_top3_hit"])
    ranked_top1 = sum(1 for item in results if item["metrics"]["ranked_top1_hit"])
    ranked_top3 = sum(1 for item in results if item["metrics"]["ranked_top3_hit"])

    normalization_scores = [item["metrics"]["normalization_accuracy"] for item in results]
    response_latencies = [item["metrics"]["response_latency_ms"] for item in results]
    retrieval_latencies = [item["metrics"]["retrieval_latency_ms"] for item in results]
    graph_latencies = [item["metrics"]["graph_query_latency_ms"] for item in results]
    confidences = [item["metrics"]["confidence"] for item in results]

    field_names = EVALUATION_FIELDS
    field_accuracy = {
        field: _pct(
            sum(1 for item in results if item["metrics"]["normalization_fields"][field]),
            total,
        )
        for field in field_names
    }

    confusion_summary = _build_confusion_summary(results)

    summary = {
        "evaluation_date": "July 23, 2026",
        "dataset_size": total,
        "reference_memory_size": runtime.vector_store.count(),
        "experience_records_seeded": runtime.experience_store.count(),
        "graph_nodes": runtime.graph_client.count_nodes(),
        "graph_edges": runtime.graph_client.count_edges(),
        "metrics": {
            "incident_retrieval_top1_accuracy": _pct(retrieval_top1, total),
            "incident_retrieval_top3_accuracy": _pct(retrieval_top3, total),
            "recommendation_top1_accuracy": _pct(ranked_top1, total),
            "recommendation_top3_accuracy": _pct(ranked_top3, total),
            "baseline_recommendation_top1_accuracy": _pct(baseline_top1, total),
            "baseline_recommendation_top3_accuracy": _pct(baseline_top3, total),
            "experience_ranking_improvement_top1": round(_pct(ranked_top1, total) - _pct(baseline_top1, total), 2),
            "experience_ranking_improvement_top3": round(_pct(ranked_top3, total) - _pct(baseline_top3, total), 2),
            "knowledge_normalization_accuracy": round(_mean(normalization_scores) * 100, 2),
            "average_confidence": round(_mean(confidences), 3),
            "average_response_time_ms": _mean(response_latencies),
            "average_retrieval_latency_ms": _mean(retrieval_latencies),
            "average_graph_query_latency_ms": _mean(graph_latencies),
            "normalization_field_accuracy": field_accuracy,
        },
        "confusion_summary": confusion_summary,
        "case_results": results,
    }
    return summary


def _format_markdown(summary: dict) -> str:
    metrics = summary["metrics"]
    rows = [
        ("Incident Retrieval Accuracy (Top-1)", f"{metrics['incident_retrieval_top1_accuracy']}%"),
        ("Incident Retrieval Accuracy (Top-3)", f"{metrics['incident_retrieval_top3_accuracy']}%"),
        ("Recommendation Accuracy (Top-1)", f"{metrics['recommendation_top1_accuracy']}%"),
        ("Recommendation Accuracy (Top-3)", f"{metrics['recommendation_top3_accuracy']}%"),
        ("Average Confidence", str(metrics["average_confidence"])),
        ("Average Response Time", f"{metrics['average_response_time_ms']} ms"),
        ("Average Retrieval Time", f"{metrics['average_retrieval_latency_ms']} ms"),
        ("Graph Query Time", f"{metrics['average_graph_query_latency_ms']} ms"),
        ("Knowledge Normalization Accuracy", f"{metrics['knowledge_normalization_accuracy']}%"),
        ("Experience Ranking Improvement (Top-1)", f"{metrics['experience_ranking_improvement_top1']} pts"),
    ]

    hardest_cases = sorted(
        summary["case_results"],
        key=lambda item: (
            item["metrics"]["ranked_top1_hit"],
            item["metrics"]["normalization_accuracy"],
            item["metrics"]["confidence"],
        ),
    )[:5]

    lines = [
        "# Evaluation Report",
        "",
        f"Generated on {summary['evaluation_date']}.",
        "",
        "## Scorecard",
        "",
        "| Metric | Result |",
        "| --- | --- |",
    ]
    for label, value in rows:
        lines.append(f"| {label} | {value} |")

    lines.extend(
        [
            "",
            "## Dataset",
            "",
            f"- Benchmark cases: {summary['dataset_size']}",
            f"- Seeded memory incidents: {summary['reference_memory_size']}",
            f"- Seeded experience records: {summary['experience_records_seeded']}",
            f"- Graph nodes / edges: {summary['graph_nodes']} / {summary['graph_edges']}",
            "",
            "## Normalization Breakdown",
            "",
            "| Field | Accuracy |",
            "| --- | --- |",
        ]
    )

    for field, accuracy in summary["metrics"]["normalization_field_accuracy"].items():
        lines.append(f"| {field} | {accuracy}% |")

    confusion = summary.get("confusion_summary", {})
    method_dist = confusion.get("normalization_method_distribution", {})
    if method_dist:
        lines.extend(
            [
                "",
                "## Normalization Method Distribution",
                "",
                "| Method | Count |",
                "| --- | --- |",
            ]
        )
        for method, count in sorted(method_dist.items(), key=lambda x: -x[1]):
            lines.append(f"| {method} | {count} |")

    confusion_tables = confusion.get("field_confusion_top5", {})
    any_confusions = any(v for v in confusion_tables.values())
    if any_confusions:
        lines.extend(["", "## Field Confusion Matrix (Top Mispairs)", ""])
        for field in EVALUATION_FIELDS:
            pairs = confusion_tables.get(field, [])
            if not pairs:
                continue
            lines.extend(
                [
                    f"### {field.title()}",
                    "",
                    "| Misclassification | Count | Rate |",
                    "| --- | --- | --- |",
                ]
            )
            for entry in pairs:
                lines.append(f"| {entry['pair']} | {entry['count']} | {entry['pct']}% |")
            lines.append("")

    lines.extend(
        [
            "## Lowest-Confidence Cases",
            "",
            "| Case | Recommendation | Confidence |",
            "| --- | --- | --- |",
        ]
    )
    for case in hardest_cases:
        lines.append(
            f"| {case['title']} | {case['recommendation']} | {case['metrics']['confidence']} |"
        )

    return "\n".join(lines) + "\n"


def evaluate(include_holdout: bool = False) -> dict:
    reference_incidents: list[dict] = []
    for path in REFERENCE_DATASETS:
        reference_incidents.extend(_load_json(path))
    benchmark_cases = _load_json(BENCHMARK_DATASET)

    runtime = EvaluationRuntime()
    try:
        runtime.seed_reference_memory(reference_incidents)
        runtime.seed_experience_history(reference_incidents)
        summary = _build_summary(benchmark_cases, runtime)

        if include_holdout and HOLDOUT_DATASET.exists():
            holdout_cases = _load_json(HOLDOUT_DATASET)
            holdout_summary = _build_summary(holdout_cases, runtime)
            summary["holdout_results"] = {
                "evaluation_date": holdout_summary["evaluation_date"],
                "dataset_size": holdout_summary["dataset_size"],
                "metrics": holdout_summary["metrics"],
                "confusion_summary": holdout_summary.get("confusion_summary", {}),
            }
    finally:
        runtime.close()

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_JSON_PATH.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    REPORT_MD_PATH.write_text(_format_markdown(summary), encoding="utf-8")
    return summary


def evaluate_holdout_only() -> dict:
    if not HOLDOUT_DATASET.exists():
        return {"error": "Holdout dataset not found", "metrics": {}}

    reference_incidents: list[dict] = []
    for path in REFERENCE_DATASETS:
        reference_incidents.extend(_load_json(path))
    holdout_cases = _load_json(HOLDOUT_DATASET)

    runtime = EvaluationRuntime()
    try:
        runtime.seed_reference_memory(reference_incidents)
        runtime.seed_experience_history(reference_incidents)
        summary = _build_summary(holdout_cases, runtime)
    finally:
        runtime.close()

    return summary


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="SigNoz Memory System Evaluation")
    parser.add_argument("--holdout", action="store_true", help="Include holdout benchmark")
    parser.add_argument("--holdout-only", action="store_true", help="Evaluate holdout set only")
    args = parser.parse_args()

    if args.holdout_only:
        summary = evaluate_holdout_only()
        label = "HOLDOUT"
    else:
        summary = evaluate(include_holdout=args.holdout)
        label = "MAIN"

    metrics = summary["metrics"]
    print("=" * 72)
    print(f"SIGNOZ MEMORY SYSTEM EVALUATION ({label})")
    print("=" * 72)
    print(f"Evaluation date: {summary['evaluation_date']}")
    print(f"Benchmark cases: {summary['dataset_size']}")
    print(f"Reference incidents: {summary['reference_memory_size']}")
    print(f"Experience records seeded: {summary['experience_records_seeded']}")
    print("-" * 72)
    print(f"Incident retrieval top-1 accuracy : {metrics['incident_retrieval_top1_accuracy']}%")
    print(f"Incident retrieval top-3 accuracy : {metrics['incident_retrieval_top3_accuracy']}%")
    print(f"Recommendation top-1 accuracy    : {metrics['recommendation_top1_accuracy']}%")
    print(f"Recommendation top-3 accuracy    : {metrics['recommendation_top3_accuracy']}%")
    print(f"Average confidence               : {metrics['average_confidence']}")
    print(f"Average response time            : {metrics['average_response_time_ms']} ms")
    print(f"Average retrieval latency        : {metrics['average_retrieval_latency_ms']} ms")
    print(f"Average graph query latency      : {metrics['average_graph_query_latency_ms']} ms")
    print(f"Normalization accuracy          : {metrics['knowledge_normalization_accuracy']}%")
    print(
        f"Experience ranking improvement   : {metrics['experience_ranking_improvement_top1']} pts (Top-1)"
    )
    print("-" * 72)
    confusion = summary.get("confusion_summary", {})
    if confusion.get("normalization_method_distribution"):
        print("Normalization methods:", confusion["normalization_method_distribution"])
    if confusion.get("field_confusion_top5"):
        print("Top field confusions:")
        for field, pairs in confusion["field_confusion_top5"].items():
            if pairs:
                top = pairs[0]
                print(f"  {field}: {top['pair']} ({top['count']}x)")
    print("-" * 72)
    print(f"Report written to: {REPORT_JSON_PATH}")
    print(f"Markdown summary: {REPORT_MD_PATH}")
