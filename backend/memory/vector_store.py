import os
import json
import logging
from pathlib import Path
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    VectorParams,
    PointStruct,
    Filter,
    FieldCondition,
    MatchValue,
    MatchAny,
)
from dotenv import load_dotenv

from memory.embeddings import get_embedding, get_embeddings_batch, EMBEDDING_DIMS

load_dotenv()

logger = logging.getLogger(__name__)

QDRANT_HOST = os.getenv("QDRANT_HOST", "localhost")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", "6333"))
QDRANT_PATH = os.getenv("QDRANT_PATH")

COLLECTION_NAME = "incidents"

# Default embedded path when no remote Qdrant is available
EMBEDDED_DEFAULT_PATH = os.path.join(str(Path.home()), ".siggy", "qdrant")


class VectorStore:
    def __init__(
        self,
        *,
        host: str | None = None,
        port: int | None = None,
        path: str | None = None,
        collection_name: str = COLLECTION_NAME,
    ):
        self.collection_name = collection_name
        self.path = path or QDRANT_PATH
        self.client = self._create_client(host, port)
        self._ensure_collection()

    def _create_client(self, host: str | None, port: int | None) -> QdrantClient:
        """Create Qdrant client with automatic fallback to embedded mode."""
        # 1. Try local embedded mode if path is set
        if self.path:
            Path(self.path).mkdir(parents=True, exist_ok=True)
            try:
                client = QdrantClient(path=self.path)
                logger.info("Qdrant embedded mode at %s", self.path)
                return client
            except Exception as e:
                logger.warning("Embedded Qdrant failed at %s: %s", self.path, e)

        # 2. Try remote server
        remote_host = host or QDRANT_HOST
        remote_port = port or QDRANT_PORT
        try:
            client = QdrantClient(host=remote_host, port=remote_port)
            # Verify connection
            client.get_collections()
            logger.info("Qdrant remote at %s:%s", remote_host, remote_port)
            return client
        except Exception as e:
            logger.warning("Remote Qdrant unreachable at %s:%s: %s", remote_host, remote_port, e)

        # 3. Fall back to embedded mode automatically
        logger.info("Falling back to embedded Qdrant at %s", EMBEDDED_DEFAULT_PATH)
        Path(EMBEDDED_DEFAULT_PATH).mkdir(parents=True, exist_ok=True)
        return QdrantClient(path=EMBEDDED_DEFAULT_PATH)

    def _ensure_collection(self):
        collections = [c.name for c in self.client.get_collections().collections]
        if self.collection_name not in collections:
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=VectorParams(
                    size=EMBEDDING_DIMS,
                    distance=Distance.COSINE,
                ),
            )

    def store_incident(self, incident: dict, embedding: list[float]) -> str:
        point_id = int(incident["id"])
        payload = {
            "id": incident["id"],
            "title": incident["title"],
            "summary": incident["summary"],
            "root_cause": incident["root_cause"],
            "fix": incident["fix"],
            "affected_services": json.dumps(incident["affected_services"]),
            "severity": incident.get("severity", "high"),
            "storage_format": "legacy",
        }
        self.client.upsert(
            collection_name=self.collection_name,
            points=[
                PointStruct(id=point_id, vector=embedding, payload=payload)
            ],
        )
        return incident["id"]

    def store_knowledge(self, knowledge_payload: dict, embedding: list[float], point_id: int) -> str:
        payload = {**knowledge_payload, "storage_format": "knowledge"}
        self.client.upsert(
            collection_name=self.collection_name,
            points=[
                PointStruct(id=point_id, vector=embedding, payload=payload)
            ],
        )
        return str(point_id)

    def search(self, query_embedding: list[float], top_k: int = 3) -> list[dict]:
        results = self.client.query_points(
            collection_name=self.collection_name,
            query=query_embedding,
            limit=top_k,
        )
        matches = []
        for result in results.points:
            payload = result.payload
            if "affected_services" in payload:
                payload["affected_services"] = json.loads(payload["affected_services"])
            payload["similarity"] = round(result.score, 4)
            matches.append(payload)
        return matches

    def search_with_filters(
        self,
        query_embedding: list[float],
        top_k: int = 5,
        filters: dict | None = None,
    ) -> list[dict]:
        qdrant_filter = self._build_filter(filters) if filters else None
        results = self.client.query_points(
            collection_name=self.collection_name,
            query=query_embedding,
            limit=top_k,
            query_filter=qdrant_filter,
        )
        matches = []
        for result in results.points:
            payload = result.payload
            if "affected_services" in payload:
                payload["affected_services"] = json.loads(payload["affected_services"])
            payload["similarity"] = round(result.score, 4)
            matches.append(payload)
        return matches

    def _build_filter(self, filters: dict) -> Filter:
        conditions = []
        if "severity" in filters and filters["severity"]:
            conditions.append(
                FieldCondition(key="severity", match=MatchValue(value=filters["severity"]))
            )
        if "service" in filters and filters["service"]:
            conditions.append(
                FieldCondition(key="service", match=MatchValue(value=filters["service"]))
            )
        if "component" in filters and filters["component"]:
            conditions.append(
                FieldCondition(key="component", match=MatchValue(value=filters["component"]))
            )
        if "failure_type" in filters and filters["failure_type"]:
            conditions.append(
                FieldCondition(key="failure_type", match=MatchValue(value=filters["failure_type"]))
            )
        if "environment" in filters and filters["environment"]:
            conditions.append(
                FieldCondition(key="environment", match=MatchValue(value=filters["environment"]))
            )
        if "fix_type" in filters and filters["fix_type"]:
            conditions.append(
                FieldCondition(key="fix_type", match=MatchValue(value=filters["fix_type"]))
            )
        return Filter(must=conditions) if conditions else None

    def get_all(self) -> list[dict]:
        results = self.client.scroll(
            collection_name=self.collection_name,
            limit=100,
        )[0]
        incidents = []
        for point in results:
            payload = point.payload
            if "affected_services" in payload:
                payload["affected_services"] = json.loads(payload["affected_services"])
            incidents.append(payload)
        return incidents

    def count(self) -> int:
        return self.client.get_collection(self.collection_name).points_count

    def clear(self) -> None:
        self.client.delete_collection(self.collection_name)
        self._ensure_collection()

    def close(self) -> None:
        self.client.close()


_store = None
_store_available = True


def get_store() -> VectorStore:
    global _store, _store_available
    if _store is None and _store_available:
        try:
            _store = VectorStore()
        except Exception as e:
            logger.error("Failed to initialize Qdrant: %s", e)
            _store_available = False
            return _FallbackVectorStore()
    if _store is None:
        return _FallbackVectorStore()
    return _store


class _FallbackVectorStore:
    """In-memory fallback when Qdrant is completely unavailable."""

    def store_incident(self, incident, embedding): return ""
    def store_knowledge(self, knowledge_payload, embedding, point_id): return ""
    def search(self, query_embedding, top_k=3): return []
    def search_with_filters(self, query_embedding, top_k=5, filters=None): return []
    def get_all(self): return []
    def count(self): return 0
    def clear(self): pass
    def close(self): pass


def reset_store() -> None:
    global _store
    if _store is not None:
        _store.close()
    _store = None
