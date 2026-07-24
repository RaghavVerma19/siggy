import os
import json
from groq import Groq
from dotenv import load_dotenv
from utils.fallbacks import summarize_telemetry_fallback

load_dotenv()

_client = None


def _get_client():
    global _client
    if _client is None:
        _client = Groq(api_key=os.getenv("GROQ_API_KEY", ""))
    return _client

SUMMARIZE_PROMPT = """You are an SRE summarizer. Convert raw observability data into a concise incident summary.

Rules:
- service: the affected service name (lowercase)
- latency: the current p99 latency (e.g., "4.8s", "150ms")
- error_rate: the current error rate (e.g., "18%", "0.5%")
- top_errors: list of the 3 most common error messages or patterns
- affected_dependencies: list of infrastructure dependencies (Redis, Kafka, PostgreSQL, etc.)
- severity: "critical" if error_rate > 10% or latency > 5s, "high" if error_rate > 1% or latency > 2s, "medium" otherwise
- summary: one-line human-readable summary of what's happening

Return ONLY valid JSON.

--- RAW DATA ---
Service: {service}
Query: {query}
Logs ({log_count} entries, showing last 10):
{logs_text}

Traces ({trace_count} traces, showing last 5):
{traces_text}

Latency metric: {latency_text}
Error metric: {error_text}
--- END ---"""


def summarize_telemetry(raw_data: dict) -> dict:
    """Convert raw SigNoz telemetry into a structured TelemetrySummary."""
    service = raw_data.get("service", "unknown")
    query = raw_data.get("query", "")

    logs = raw_data.get("logs", [])
    if not isinstance(logs, list):
        if isinstance(logs, dict):
            inner = logs.get("logs", logs.get("data", []))
            logs = inner if isinstance(inner, list) else []
        else:
            logs = []
    logs_text = ""
    for log in (logs[-10:] if len(logs) > 10 else logs):
        if not isinstance(log, dict):
            continue
        body = log.get("body", log.get("message", str(log)))
        logs_text += f"  - [{log.get('timestamp', '')}] {str(body)[:200]}\n"
    if not logs_text:
        logs_text = "  (no error logs found)\n"

    traces = raw_data.get("traces", [])
    if not isinstance(traces, list):
        if isinstance(traces, dict):
            inner = traces.get("traces", traces.get("data", []))
            traces = inner if isinstance(inner, list) else []
        else:
            traces = []
    traces_text = ""
    for t in (traces[-5:] if len(traces) > 5 else traces):
        if not isinstance(t, dict):
            continue
        traces_text += (
            f"  - duration={t.get('duration', 'unknown')} "
            f"status={t.get('status', 'unknown')} "
            f"name={t.get('name', t.get('operationName', ''))}\n"
        )
    if not traces_text:
        traces_text = "  (no slow traces found)\n"

    latency = raw_data.get("latency_metric", {})
    latency_text = json.dumps(latency) if latency else "unavailable"
    error = raw_data.get("error_metric", {})
    error_text = json.dumps(error) if error else "unavailable"

    prompt = SUMMARIZE_PROMPT.format(
        service=service,
        query=query,
        log_count=len(logs),
        logs_text=logs_text,
        trace_count=len(traces),
        traces_text=traces_text,
        latency_text=latency_text,
        error_text=error_text,
    )

    try:
        response = _get_client().chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": "You are an SRE summarizer. Return only valid JSON."},
                {"role": "user", "content": prompt},
            ],
            temperature=0,
        )

        raw = response.choices[0].message.content.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()

        summary = json.loads(raw)
        summary["service"] = service
        return summary
    except Exception:
        return summarize_telemetry_fallback(raw_data)
