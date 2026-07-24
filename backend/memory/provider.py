from abc import ABC, abstractmethod
from typing import List, Optional


class MemoryProvider(ABC):
    """Abstract memory provider. Swappable backends: Qdrant, GraphRAG, SQL, MCP."""

    @abstractmethod
    def retrieve(
        self,
        query_embedding: list[float],
        top_k: int = 5,
        filters: Optional[dict] = None,
    ) -> List[dict]:
        pass

    @abstractmethod
    def store(self, incident: dict, embedding: list[float]) -> str:
        pass

    @abstractmethod
    def count(self) -> int:
        pass
