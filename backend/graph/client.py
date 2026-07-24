from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

from graph.schema import GraphEdge, GraphNode

DEFAULT_GRAPH_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "graph.db"


class GraphClient:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or os.getenv("GRAPH_DB_PATH", str(DEFAULT_GRAPH_DB_PATH))
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        with self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS graph_nodes (
                    node_id TEXT PRIMARY KEY,
                    node_type TEXT NOT NULL,
                    label TEXT NOT NULL,
                    properties_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS graph_edges (
                    edge_id TEXT PRIMARY KEY,
                    from_node TEXT NOT NULL,
                    to_node TEXT NOT NULL,
                    relationship_type TEXT NOT NULL,
                    properties_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_graph_node_type ON graph_nodes(node_type)"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_graph_edge_from ON graph_edges(from_node)"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_graph_edge_to ON graph_edges(to_node)"
            )

    def upsert_node(self, node: GraphNode) -> GraphNode:
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO graph_nodes(node_id, node_type, label, properties_json, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(node_id) DO UPDATE SET
                    node_type = excluded.node_type,
                    label = excluded.label,
                    properties_json = excluded.properties_json,
                    updated_at = excluded.updated_at
                """,
                (
                    node.node_id,
                    node.node_type,
                    node.label,
                    json.dumps(node.properties, default=self._json_default),
                    node.updated_at.isoformat(),
                ),
            )
        return node

    def upsert_edge(self, edge: GraphEdge) -> GraphEdge:
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO graph_edges(edge_id, from_node, to_node, relationship_type, properties_json, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(edge_id) DO UPDATE SET
                    from_node = excluded.from_node,
                    to_node = excluded.to_node,
                    relationship_type = excluded.relationship_type,
                    properties_json = excluded.properties_json,
                    updated_at = excluded.updated_at
                """,
                (
                    edge.edge_id,
                    edge.from_node,
                    edge.to_node,
                    edge.relationship_type,
                    json.dumps(edge.properties, default=self._json_default),
                    edge.updated_at.isoformat(),
                ),
            )
        return edge

    def get_node(self, node_id: str) -> GraphNode | None:
        row = self._conn.execute(
            "SELECT * FROM graph_nodes WHERE node_id = ?",
            (node_id,),
        ).fetchone()
        return self._node_from_row(row) if row else None

    def find_nodes(
        self,
        *,
        node_type: str | None = None,
        label: str | None = None,
        limit: int = 100,
    ) -> list[GraphNode]:
        query = "SELECT * FROM graph_nodes"
        clauses = []
        params: list[object] = []
        if node_type:
            clauses.append("node_type = ?")
            params.append(node_type)
        if label:
            clauses.append("LOWER(label) = ?")
            params.append(label.lower())
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY label ASC LIMIT ?"
        params.append(limit)
        rows = self._conn.execute(query, params).fetchall()
        return [self._node_from_row(row) for row in rows]

    def get_neighbors(self, node_id: str, depth: int = 2) -> list[dict]:
        if depth < 1:
            return []

        visited = {node_id}
        frontier = {node_id}
        collected: list[dict] = []

        for _ in range(depth):
            if not frontier:
                break
            placeholders = ",".join("?" for _ in frontier)
            rows = self._conn.execute(
                f"""
                SELECT * FROM graph_edges
                WHERE from_node IN ({placeholders}) OR to_node IN ({placeholders})
                """,
                [*frontier, *frontier],
            ).fetchall()
            next_frontier = set()
            for row in rows:
                edge = self._edge_from_row(row)
                other_id = edge.to_node if edge.from_node in frontier else edge.from_node
                if other_id not in visited:
                    next_frontier.add(other_id)
                    visited.add(other_id)
                other_node = self.get_node(other_id)
                collected.append(
                    {
                        "edge": edge.model_dump(),
                        "node": other_node.model_dump() if other_node else None,
                    }
                )
            frontier = next_frontier

        deduped = []
        seen = set()
        for item in collected:
            edge_id = item["edge"]["edge_id"]
            if edge_id not in seen:
                deduped.append(item)
                seen.add(edge_id)
        return deduped

    def get_edges_for_node(self, node_id: str, relationship_type: str | None = None) -> list[GraphEdge]:
        query = "SELECT * FROM graph_edges WHERE (from_node = ? OR to_node = ?)"
        params: list[object] = [node_id, node_id]
        if relationship_type:
            query += " AND relationship_type = ?"
            params.append(relationship_type)
        rows = self._conn.execute(query, params).fetchall()
        return [self._edge_from_row(row) for row in rows]

    def count_nodes(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) AS count FROM graph_nodes").fetchone()
        return int(row["count"]) if row else 0

    def count_edges(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) AS count FROM graph_edges").fetchone()
        return int(row["count"]) if row else 0

    def clear(self) -> None:
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM graph_edges")
            self._conn.execute("DELETE FROM graph_nodes")

    def close(self) -> None:
        self._conn.close()

    def _json_default(self, value):
        if isinstance(value, datetime):
            return value.isoformat()
        raise TypeError(f"Object of type {value.__class__.__name__} is not JSON serializable")

    def _node_from_row(self, row: sqlite3.Row) -> GraphNode:
        return GraphNode(
            node_id=row["node_id"],
            node_type=row["node_type"],
            label=row["label"],
            properties=json.loads(row["properties_json"]),
            updated_at=row["updated_at"],
        )

    def _edge_from_row(self, row: sqlite3.Row) -> GraphEdge:
        return GraphEdge(
            edge_id=row["edge_id"],
            from_node=row["from_node"],
            to_node=row["to_node"],
            relationship_type=row["relationship_type"],
            properties=json.loads(row["properties_json"]),
            updated_at=row["updated_at"],
        )


_client: GraphClient | None = None


def get_graph_client() -> GraphClient:
    global _client
    if _client is None:
        _client = GraphClient()
    return _client
