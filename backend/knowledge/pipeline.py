import json
import hashlib
import logging
from typing import Optional

from knowledge.schema import KnowledgeObject, SearchFilters, ExplainableRecommendation
from knowledge.normalizer import (
    normalize_to_knowledge,
    normalize_from_telemetry,
    build_search_filters_from_knowledge,
)
from memory.embeddings import get_embedding
from memory.search import get_search
from experience.ranking import get_ranker
from graph.builder import get_graph_builder
from graph.context_builder import get_graph_context_builder

logger = logging.getLogger(__name__)


def _generate_point_id(ko: KnowledgeObject, title: str = "") -> int:
    raw = f"{ko.service}:{ko.component}:{ko.failure_type}:{title}"
    return int(hashlib.md5(raw.encode()).hexdigest()[:15], 16)


def knowledge_to_embedding_text(ko: KnowledgeObject) -> str:
    return ko.to_embedding_text()


def store_knowledge_object(ko: KnowledgeObject, title: str = "") -> str:
    try:
        search = get_search()
        embedding_text = knowledge_to_embedding_text(ko)
        embedding = get_embedding(embedding_text)
        point_id = _generate_point_id(ko, title)
        payload = ko.to_search_payload()
        stored = search.store_knowledge(payload, embedding, point_id)
    except Exception as e:
        logger.warning("Could not store to vector DB: %s", e)
        stored = ""
    try:
        get_graph_builder().sync_knowledge_object(ko)
        get_graph_builder().sync_operational_patterns()
    except Exception as e:
        logger.warning("Could not sync to graph: %s", e)
    return stored


def search_by_knowledge(
    ko: KnowledgeObject,
    top_k: int = 5,
) -> list[dict]:
    try:
        search = get_search()
        embedding_text = knowledge_to_embedding_text(ko)
        query_embedding = get_embedding(embedding_text)
        filters = build_search_filters_from_knowledge(ko)
        filter_dict = {k: v for k, v in filters.model_dump().items() if v is not None}
        results = search.retrieve(
            query_embedding=query_embedding,
            top_k=top_k,
            filters=filter_dict if filter_dict else None,
        )
        if len(results) < 2:
            results = search.retrieve(
                query_embedding=query_embedding,
                top_k=top_k,
                filters=None,
            )
        return results
    except Exception as e:
        logger.warning("Vector search unavailable, using degraded mode: %s", e)
        return []


def build_explainable_recommendation(
    ko: KnowledgeObject,
    similar_incidents: list[dict],
    llm_fix: str = "",
    llm_confidence: float = 0.0,
) -> ExplainableRecommendation:
    ranker = get_ranker()
    ranked_recommendations = ranker.rank(
        knowledge_object=ko,
        similar_incidents=similar_incidents,
        fallback_recommendation=llm_fix,
        fallback_fix_type=ko.fix_type,
        fallback_confidence=llm_confidence,
    )
    top_ranked = ranked_recommendations[0] if ranked_recommendations else None
    top_match = similar_incidents[0] if similar_incidents else {}

    matched_service = False
    matched_component = False
    matched_failure = False
    matched_severity = False

    evidence = list(top_ranked.evidence) if top_ranked else []

    for inc in similar_incidents:
        if inc.get("service", "").lower() == ko.service.lower():
            matched_service = True
            evidence.append(f"Same service: {ko.service}")
            break

    for inc in similar_incidents:
        if inc.get("component", "").lower() == ko.component.lower():
            matched_component = True
            evidence.append(f"Same component: {ko.component}")
            break

    for inc in similar_incidents:
        if inc.get("failure_type", "").lower() == ko.failure_type.lower():
            matched_failure = True
            evidence.append(f"Same failure type: {ko.failure_type}")
            break

    for inc in similar_incidents:
        if inc.get("severity", "").lower() == ko.severity.lower():
            matched_severity = True
            evidence.append(f"Same severity level: {ko.severity}")
            break

    if top_match:
        sim = top_match.get("similarity", 0)
        evidence.append(f"Top match similarity: {sim:.2f}")
        evidence.append(f"Matched Incident #{top_match.get('incident_id', top_match.get('id', '?'))}")

    match_score = sum([matched_service, matched_component, matched_failure, matched_severity])
    base_confidence = match_score / 4.0
    similarity_boost = top_match.get("similarity", 0) * 0.3 if top_match else 0
    ranking_confidence = top_ranked.final_score if top_ranked else 0.0
    confidence = min(
        max(base_confidence * 0.7 + similarity_boost + (llm_confidence * 0.3), ranking_confidence),
        1.0,
    )

    recommendation = (
        top_ranked.recommendation
        if top_ranked
        else llm_fix or (top_match.get("fix", "") if top_match else "Investigate further")
    )
    recommendation_id = top_ranked.recommendation_id if top_ranked else ""
    recommendation_stats = top_ranked.statistics.model_dump() if top_ranked else None
    operational_pattern = top_ranked.pattern.model_dump() if top_ranked and top_ranked.pattern else None
    graph_context = get_graph_context_builder().build(
        ko,
        ranked_recommendations=[item.model_dump() for item in ranked_recommendations],
    ).model_dump()
    evidence.extend(graph_context.get("evidence", []))

    return ExplainableRecommendation(
        recommendation_id=recommendation_id,
        recommendation=recommendation,
        confidence=round(confidence, 3),
        evidence=evidence,
        reasoning={
            "matched_service": matched_service,
            "matched_component": matched_component,
            "matched_failure_type": matched_failure,
            "matched_severity": matched_severity,
            "similarity": top_match.get("similarity", 0) if top_match else 0,
            "match_score": f"{match_score}/4",
            "evidence_count": len(evidence),
            "ranking_strategy": {
                "base_score": {
                    "similarity_weight": 0.70,
                    "metadata_weight": 0.30,
                },
                "experience_multiplier": {
                    "success_influence": 0.25,
                    "resolution_influence": 0.10,
                    "confidence_influence": 0.05,
                    "bayesian_prior": {"alpha": 2.0, "beta": 2.0},
                    "range": [0.8, 1.2],
                },
            },
        },
        recommendation_stats=recommendation_stats,
        operational_pattern=operational_pattern,
        graph_context=graph_context,
        ranked_recommendations=[item.model_dump() for item in ranked_recommendations],
        knowledge_object=ko,
        similar_incidents=similar_incidents,
    )


def knowledge_pipeline(
    title: str,
    summary: str,
    incident_id: str = "",
    store_new: bool = False,
) -> dict:
    ko = normalize_to_knowledge(title, summary, incident_id)
    if not ko.title:
        ko.title = title

    similar = search_by_knowledge(ko, top_k=5)

    explanation = build_explainable_recommendation(
        ko=ko,
        similar_incidents=similar,
        llm_fix=ko.fix,
        llm_confidence=ko.confidence,
    )

    if store_new and incident_id:
        store_knowledge_object(ko, title)

    return {
        "knowledge_object": ko.model_dump(),
        "similar_incidents": similar,
        "recommendation": explanation.model_dump(),
    }


def knowledge_pipeline_from_telemetry(
    telemetry_summary: dict,
    incident_id: str = "",
    store_new: bool = False,
) -> dict:
    ko = normalize_from_telemetry(telemetry_summary, incident_id)

    similar = search_by_knowledge(ko, top_k=5)

    explanation = build_explainable_recommendation(
        ko=ko,
        similar_incidents=similar,
        llm_fix=ko.fix,
        llm_confidence=ko.confidence,
    )

    if store_new and incident_id:
        store_knowledge_object(ko, telemetry_summary.get("summary", ""))

    return {
        "knowledge_object": ko.model_dump(),
        "similar_incidents": similar,
        "recommendation": explanation.model_dump(),
    }
