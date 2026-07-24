import os
import json
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

client = Groq(api_key=os.getenv("GROQ_API_KEY"))

RECOMMENDER_PROMPT = """You are an SRE incident resolution expert. A new incident has occurred. Below are similar incidents from the past with their root causes and fixes.

Use these past incidents to recommend the best fix for the new incident.

IMPORTANT: Return your response as valid JSON with this exact structure:
{{
  "recommended_fix": "detailed fix recommendation",
  "confidence": 0.0 to 1.0,
  "explanation": "brief explanation of why this fix is recommended"
}}

--- NEW INCIDENT ---
Title: {title}
Summary: {summary}
Normalized: {normalized}

--- SIMILAR PAST INCIDENTS ---
{similar_incidents}

--- END ---

Based on the above similar incidents, recommend the best fix for the new incident. Return ONLY valid JSON."""


def recommend_fix(
    title: str,
    summary: str,
    normalized: dict,
    similar_incidents: list[dict],
) -> dict:
    incidents_text = ""
    for i, inc in enumerate(similar_incidents, 1):
        incidents_text += f"""
Incident {i}:
  Title: {inc['title']}
  Root Cause: {inc['root_cause']}
  Fix: {inc['fix']}
  Similarity: {inc['similarity']}
"""

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {
                "role": "system",
                "content": "You are an SRE expert. Return only valid JSON.",
            },
            {
                "role": "user",
                "content": RECOMMENDER_PROMPT.format(
                    title=title,
                    summary=summary,
                    normalized=str(normalized),
                    similar_incidents=incidents_text.strip(),
                ),
            },
        ],
        temperature=0,
    )

    raw = response.choices[0].message.content.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()

    return json.loads(raw)
