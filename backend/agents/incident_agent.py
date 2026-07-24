import os
import json
from groq import Groq
from dotenv import load_dotenv

from memory.embeddings import get_embedding
from memory.search import get_search
from agents.normalizer import normalize_incident, build_embedding_text
from llm.prompt import build_analyze_prompt, build_search_hint_prompt
from utils.fallbacks import analyze_incident_fallback

load_dotenv()

client = Groq(api_key=os.getenv("GROQ_API_KEY"))


class IncidentAgent:
    def __init__(self):
        self.search = get_search()

    def analyze(self, title: str, summary: str) -> dict:
        # Step 1: Normalize
        normalized = normalize_incident(title, summary)

        # Step 2: Embed
        embedding_text = build_embedding_text(normalized)
        query_embedding = get_embedding(embedding_text)

        # Step 3: Search with metadata hints
        hints = build_search_hint_prompt(normalized.model_dump())
        similar_incidents = self.search.retrieve(
            query_embedding=query_embedding,
            top_k=5,
            filters=hints if hints else None,
        )

        # Step 4: If metadata filter too strict, fallback to pure vector search
        if len(similar_incidents) < 2:
            similar_incidents = self.search.retrieve(
                query_embedding=query_embedding,
                top_k=5,
                filters=None,
            )

        # Step 5: Build prompt and call LLM
        prompt = build_analyze_prompt(
            current_incident={"title": title, "summary": summary},
            similar_incidents=similar_incidents,
            normalized=normalized.model_dump(),
        )

        try:
            response = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a senior SRE engineer. "
                            "Always return valid JSON. "
                            "Show your reasoning chain step by step."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0,
            )

            raw = response.choices[0].message.content.strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()

            analysis = json.loads(raw)
        except Exception:
            analysis = analyze_incident_fallback(title, summary, normalized, similar_incidents)

        # Step 6: Build final response
        return {
            "current_incident": {"title": title, "summary": summary},
            "normalized": normalized.model_dump(),
            "similar_incidents": similar_incidents,
            "analysis": analysis,
        }
