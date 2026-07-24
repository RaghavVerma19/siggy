import json


def build_analyze_prompt(
    current_incident: dict,
    similar_incidents: list[dict],
    normalized: dict,
) -> str:
    similar_block = ""
    for i, inc in enumerate(similar_incidents, 1):
        similar_block += f"""
--- Past Incident {i} (similarity: {inc['similarity']}) ---
Title: {inc['title']}
Summary: {inc['summary']}
Root Cause: {inc['root_cause']}
Fix: {inc['fix']}
Severity: {inc.get('severity', 'unknown')}
Services: {inc.get('affected_services', [])}
"""

    return f"""You are a senior SRE engineer analyzing a production incident.

Think step by step. Follow this exact reasoning chain:

1. COMPARE: Compare the current incident with each past incident.
2. IDENTIFY: Identify common patterns (same service, same component, same error type, same symptom).
3. EVIDENCE: List specific evidence matches (e.g., "Same service: checkout", "Same component: redis", "Same failure: connection_pool_exhaustion").
4. REASON: Explain why these patterns matter and what they indicate.
5. CONFIDENCE: Rate your confidence (0.0-1.0) based on how many evidence points match.
6. FIX: Recommend a specific fix with investigation steps.

--- CURRENT INCIDENT ---
Title: {current_incident['title']}
Summary: {current_incident['summary']}
Normalized: {json.dumps(normalized)}

--- SIMILAR PAST INCIDENTS ---
{similar_block}

--- END ---

Now analyze. Return ONLY valid JSON with this exact structure:
{{
  "reasoning_chain": {{
    "compare": "comparison of current vs past incidents",
    "identify": "common patterns found",
    "evidence": ["evidence point 1", "evidence point 2", ...],
    "reason": "why these patterns matter"
  }},
  "confidence": 0.0 to 1.0,
  "recommended_fix": "specific actionable fix",
  "investigation_steps": ["step 1", "step 2", ...],
  "common_pattern": "one-line summary of the recurring pattern"
}}

Return ONLY valid JSON. No markdown fences."""


def build_investigation_prompt(
    telemetry_summary: dict,
    similar_incidents: list[dict],
    experience_context: str = "",
) -> str:
    similar_block = ""
    for i, inc in enumerate(similar_incidents, 1):
        similar_block += f"""
--- Past Incident {i} (similarity: {inc.get('similarity', 'N/A')}) ---
Title: {inc.get('title', '')}
Root Cause: {inc.get('root_cause', '')}
Fix: {inc.get('fix', '')}
Severity: {inc.get('severity', 'unknown')}
"""

    experience_block = ""
    if experience_context:
        experience_block = f"\n--- HISTORICAL EXPERIENCE ---\n{experience_context}\n"

    return f"""You are a senior SRE engineer analyzing live telemetry data from a production incident.

A user reported an issue and we gathered telemetry from SigNoz.
Here is the structured summary of the telemetry data:

--- TELEMETRY SUMMARY ---
Service: {telemetry_summary.get('service', 'unknown')}
Latency: {telemetry_summary.get('latency', 'unknown')}
Error Rate: {telemetry_summary.get('error_rate', 'unknown')}
Top Errors: {telemetry_summary.get('top_errors', [])}
Affected Dependencies: {telemetry_summary.get('affected_dependencies', [])}
Summary: {telemetry_summary.get('summary', '')}
--- END TELEMETRY ---

{experience_block}

--- SIMILAR PAST INCIDENTS ---
{similar_block if similar_block else '(No similar past incidents found)'}

--- END ---

Based on the telemetry data and past incidents:
1. What is the root cause?
2. What specific fix should we apply?
3. What steps should we investigate?
4. How confident are you (0.0-1.0)?

Return ONLY valid JSON:
{{
  "root_cause": "technical root cause",
  "recommended_fix": "specific actionable fix",
  "confidence": 0.0 to 1.0,
  "investigation_steps": ["step 1", "step 2", ...],
  "evidence": ["evidence from telemetry", "evidence from past incidents", ...]
}}"""


def build_search_hint_prompt(normalized: dict) -> dict:
    hints = {}
    if normalized.get("component"):
        hints["component"] = normalized["component"]
    if normalized.get("service"):
        hints["service"] = normalized["service"]
    if normalized.get("failure"):
        hints["failure_type"] = normalized["failure"]
    return hints
