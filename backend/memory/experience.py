"""Experience Memory: tracks whether recommendations actually worked."""

import os
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct

from memory.embeddings import get_embedding, EMBEDDING_DIMS
from memory.vector_store import QDRANT_HOST, QDRANT_PORT

EXPERIENCE_COLLECTION = "experience"


class ExperienceMemory:
    def __init__(self):
        self.client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
        self._ensure_collection()

    def _ensure_collection(self):
        collections = [c.name for c in self.client.get_collections().collections]
        if EXPERIENCE_COLLECTION not in collections:
            self.client.create_collection(
                collection_name=EXPERIENCE_COLLECTION,
                vectors_config=VectorParams(
                    size=EMBEDDING_DIMS,
                    distance=Distance.COSINE,
                ),
            )

    def record_outcome(
        self,
        recommendation: str,
        worked: bool,
        confidence: float = 0.0,
        resolution_time: str = "",
        incident_id: str = "",
        notes: str = "",
    ) -> str:
        record = {
            "recommendation": recommendation,
            "worked": worked,
            "confidence": confidence,
            "resolution_time": resolution_time,
            "incident_id": incident_id,
            "notes": notes,
        }

        embedding = get_embedding(recommendation)
        point_id = abs(hash(recommendation + str(worked))) % (2**63)

        self.client.upsert(
            collection_name=EXPERIENCE_COLLECTION,
            points=[PointStruct(id=point_id, vector=embedding, payload=record)],
        )
        return str(point_id)

    def search_similar_outcomes(self, recommendation: str, top_k: int = 5) -> list[dict]:
        embedding = get_embedding(recommendation)
        results = self.client.search(
            collection_name=EXPERIENCE_COLLECTION,
            query_vector=embedding,
            limit=top_k,
        )
        return [r.payload for r in results]

    def get_success_rate(self, recommendation: str) -> dict:
        outcomes = self.search_similar_outcomes(recommendation, top_k=20)
        if not outcomes:
            return {"total": 0, "successes": 0, "rate": None}

        total = len(outcomes)
        successes = sum(1 for o in outcomes if o.get("worked", False))
        return {
            "total": total,
            "successes": successes,
            "rate": round(successes / total, 2) if total > 0 else None,
        }

    def get_experience_context(self, recommendation: str) -> str:
        stats = self.get_success_rate(recommendation)
        if stats["total"] == 0:
            return "No past experience with this recommendation."

        rate = stats["rate"] * 100
        return (
            f"Historical data: This type of recommendation was tried {stats['total']} times, "
            f"succeeded {stats['successes']} times ({rate:.0f}% success rate)."
        )


_experience = None


def get_experience_memory() -> ExperienceMemory:
    global _experience
    if _experience is None:
        _experience = ExperienceMemory()
    return _experience
