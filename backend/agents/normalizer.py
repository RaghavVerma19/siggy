import os
import json
from groq import Groq
from dotenv import load_dotenv

from models.incident import NormalizedIncident
from utils.fallbacks import normalize_incident_fallback

load_dotenv()

client = Groq(api_key=os.getenv("GROQ_API_KEY"))

NORMALIZER_PROMPT = """You are an incident classifier. Convert the raw incident description into a structured JSON object.

Rules:
- service: the affected service name (lowercase, use "unknown" if unclear)
- component: the infrastructure component that failed (e.g., redis, kafka, postgresql, cpu, memory, disk, network)
- failure: the failure type in snake_case (e.g., connection_pool_exhaustion, broker_unavailable, infinite_loop, timeout, memory_leak)
- symptom: the observable symptom in snake_case (e.g., high_latency, request_timeout, cpu_spike, oom_killed, message_backup)
- root_cause: one-line technical root cause
- fix: one-line recommended fix

Return ONLY valid JSON. No markdown, no explanation.

Incident title: {title}
Incident summary: {summary}"""


def normalize_incident(title: str, summary: str) -> NormalizedIncident:
    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {
                    "role": "system",
                    "content": "You are an incident classifier. Return only valid JSON.",
                },
                {
                    "role": "user",
                    "content": NORMALIZER_PROMPT.format(title=title, summary=summary),
                },
            ],
            temperature=0,
        )

        raw = response.choices[0].message.content.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()

        data = json.loads(raw)
        return NormalizedIncident(**data)
    except Exception:
        return normalize_incident_fallback(title, summary)


def build_embedding_text(normalized: NormalizedIncident) -> str:
    return f"{normalized.service} {normalized.component} {normalized.failure} {normalized.symptom} {normalized.root_cause}"
