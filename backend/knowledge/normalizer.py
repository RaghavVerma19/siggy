import os
import json
from groq import Groq
from dotenv import load_dotenv

from knowledge.schema import KnowledgeObject, SearchFilters
from knowledge.taxonomy import (
    FAILURE_TYPES,
    FIX_TYPES,
    SYMPTOM_TYPES,
    SEVERITY_LEVELS,
    ENVIRONMENTS,
)
from utils.fallbacks import closest_match, normalize_knowledge_fallback

load_dotenv()

client = Groq(api_key=os.getenv("GROQ_API_KEY"))

NORMALIZE_PROMPT = """You are an incident classifier. Convert the incident into a structured Knowledge Object.

You MUST use ONLY these canonical values:

FAILURE_TYPES: {failure_types}
FIX_TYPES: {fix_types}
SYMPTOM_TYPES: {symptom_types}
SEVERITY_LEVELS: {severity_levels}
ENVIRONMENTS: {environments}

Rules:
- failure_type: MUST be one of FAILURE_TYPES. Pick the closest match.
- fix_type: MUST be one of FIX_TYPES. Pick the closest match.
- symptoms: MUST use values from SYMPTOM_TYPES. Can be a list of 1-3 symptoms.
- severity: MUST be one of SEVERITY_LEVELS.
- environment: MUST be one of ENVIRONMENTS. Default to "production" if unclear.
- service: lowercase service name, "unknown" if unclear.
- component: the infrastructure component (redis, kafka, postgresql, cpu, memory, disk, network, etc.)
- root_cause: one-line technical root cause.
- fix: one-line recommended fix.
- confidence: 0.0-1.0 based on how confident you are in the classification.

--- INCIDENT ---
Title: {title}
Summary: {summary}

Return ONLY valid JSON matching this schema:
{{
  "title": "concise incident title",
  "service": "string",
  "component": "string",
  "failure_type": "one of FAILURE_TYPES",
  "fix_type": "one of FIX_TYPES",
  "symptoms": ["one of SYMPTOM_TYPES"],
  "severity": "one of SEVERITY_LEVELS",
  "environment": "one of ENVIRONMENTS",
  "root_cause": "string",
  "fix": "string",
  "confidence": 0.0-1.0
}}

Return ONLY valid JSON. No markdown fences. No explanation."""


def normalize_to_knowledge(title: str, summary: str, incident_id: str = "") -> KnowledgeObject:
    from knowledge.normalization_v2 import normalize_deterministic

    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {
                    "role": "system",
                    "content": "You are an incident classifier. Return only valid JSON that matches the required schema exactly. Use ONLY the canonical values provided.",
                },
                {
                    "role": "user",
                    "content": NORMALIZE_PROMPT.format(
                        title=title,
                        summary=summary,
                        failure_types=FAILURE_TYPES,
                        fix_types=FIX_TYPES,
                        symptom_types=SYMPTOM_TYPES,
                        severity_levels=SEVERITY_LEVELS,
                        environments=ENVIRONMENTS,
                    ),
                },
            ],
            temperature=0,
        )

        raw = response.choices[0].message.content.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()

        data = json.loads(raw)
    except Exception:
        data, _report = normalize_deterministic(title, summary, incident_id)

    if data.get("failure_type") not in FAILURE_TYPES:
        data["failure_type"] = closest_match(data.get("failure_type", ""), FAILURE_TYPES, "timeout")
    if data.get("fix_type") not in FIX_TYPES:
        data["fix_type"] = closest_match(data.get("fix_type", ""), FIX_TYPES, "restart_service")
    if data.get("severity") not in SEVERITY_LEVELS:
        data["severity"] = "medium"
    if data.get("environment") not in ENVIRONMENTS:
        data["environment"] = "production"

    cleaned_symptoms = []
    for s in data.get("symptoms", []):
        if s in SYMPTOM_TYPES:
            cleaned_symptoms.append(s)
        else:
            cleaned_symptoms.append(closest_match(s, SYMPTOM_TYPES, "high_latency"))
    data["symptoms"] = cleaned_symptoms[:3]

    return KnowledgeObject(
        incident_id=incident_id,
        title=data.get("title", title),
        summary=summary,
        service=data.get("service", "unknown"),
        component=data.get("component", "unknown"),
        failure_type=data.get("failure_type", ""),
        symptoms=data.get("symptoms", []),
        severity=data.get("severity", "medium"),
        environment=data.get("environment", "production"),
        root_cause=data.get("root_cause", ""),
        fix=data.get("fix", ""),
        fix_type=data.get("fix_type", ""),
        confidence=data.get("confidence", 0.5),
    )


def normalize_from_telemetry(telemetry_summary: dict, incident_id: str = "") -> KnowledgeObject:
    title = telemetry_summary.get("summary", "Unknown incident")
    summary = json.dumps(telemetry_summary)
    return normalize_to_knowledge(title, summary, incident_id)


def build_search_filters_from_knowledge(ko: KnowledgeObject) -> SearchFilters:
    return SearchFilters(
        service=ko.service if ko.service != "unknown" else None,
        environment=ko.environment,
    )


def _closest_match(value: str, valid_values: list[str]) -> str:
    return closest_match(value, valid_values, valid_values[0] if valid_values else "")
