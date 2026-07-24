from typing import List, Optional

from memory.vector_store import get_store, COLLECTION_NAME, VectorStore
from memory.provider import MemoryProvider


class IncidentSearch(MemoryProvider):
    """Search with metadata filtering on top of vector similarity."""

    def __init__(self, store: VectorStore | None = None):
        self.store = store or get_store()

    def retrieve(
        self,
        query_embedding: list[float],
        top_k: int = 5,
        filters: Optional[dict] = None,
    ) -> List[dict]:
        cleaned_filters = {}
        if filters:
            for k, v in filters.items():
                if v and v != "unknown" and v != "None":
                    cleaned_filters[k] = v

        return self.store.search_with_filters(
            query_embedding=query_embedding,
            top_k=top_k,
            filters=cleaned_filters if cleaned_filters else None,
        )

    def store(self, incident: dict, embedding: list[float]) -> str:
        return self.store.store_incident(incident, embedding)

    def store_knowledge(self, knowledge_payload: dict, embedding: list[float], point_id: int) -> str:
        return self.store.store_knowledge(knowledge_payload, embedding, point_id)

    def count(self) -> int:
        return self.store.count()


_search = None


def get_search() -> IncidentSearch:
    global _search
    if _search is None:
        _search = IncidentSearch()
    return _search


def reset_search() -> None:
    global _search
    _search = None
