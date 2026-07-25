from __future__ import annotations

import json
import os
import sqlite3
import threading
import uuid
from pathlib import Path
from typing import Optional

from experience.models import (
    ExperienceRecord,
    ExperienceRecordCreate,
    canonicalize_recommendation_id,
)

from utils.paths import siggy_experience_db

DEFAULT_DB_PATH = siggy_experience_db()


class ExperienceStore:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or os.getenv("EXPERIENCE_DB_PATH", str(DEFAULT_DB_PATH))
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._ensure_tables()

    def _ensure_tables(self) -> None:
        with self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS experiences (
                    experience_id TEXT PRIMARY KEY,
                    incident_id TEXT NOT NULL,
                    recommendation_id TEXT NOT NULL,
                    recommendation TEXT NOT NULL,
                    accepted INTEGER NOT NULL,
                    worked INTEGER NOT NULL,
                    resolution_time_seconds INTEGER NOT NULL,
                    engineer_feedback TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    service TEXT NOT NULL,
                    component TEXT NOT NULL,
                    failure_type TEXT NOT NULL,
                    symptoms_json TEXT NOT NULL,
                    timestamp TEXT NOT NULL
                )
                """
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_experiences_recommendation ON experiences(recommendation_id)"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_experiences_failure ON experiences(failure_type)"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_experiences_service ON experiences(service)"
            )

    def record_experience(self, payload: ExperienceRecordCreate) -> ExperienceRecord:
        recommendation_id = canonicalize_recommendation_id(
            recommendation_id=payload.recommendation_id,
            recommendation=payload.recommendation,
        )
        record = ExperienceRecord(
            experience_id=str(uuid.uuid4()),
            incident_id=payload.incident_id,
            recommendation_id=recommendation_id,
            recommendation=payload.recommendation,
            accepted=payload.accepted,
            worked=payload.worked,
            resolution_time_seconds=max(payload.resolution_time_seconds, 0),
            engineer_feedback=payload.engineer_feedback,
            confidence=max(0.0, min(payload.confidence, 1.0)),
            service=payload.service or "unknown",
            component=payload.component or "unknown",
            failure_type=payload.failure_type,
            symptoms=payload.symptoms,
            timestamp=payload.timestamp,
        )

        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO experiences (
                    experience_id, incident_id, recommendation_id, recommendation,
                    accepted, worked, resolution_time_seconds, engineer_feedback,
                    confidence, service, component, failure_type, symptoms_json, timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.experience_id,
                    record.incident_id,
                    record.recommendation_id,
                    record.recommendation,
                    int(record.accepted),
                    int(record.worked),
                    record.resolution_time_seconds,
                    record.engineer_feedback,
                    record.confidence,
                    record.service,
                    record.component,
                    record.failure_type,
                    json.dumps(record.symptoms),
                    record.timestamp.isoformat(),
                ),
            )
        return record

    def get_experiences(
        self,
        *,
        recommendation_id: str | None = None,
        failure_type: str | None = None,
        service: str | None = None,
        limit: int = 200,
    ) -> list[ExperienceRecord]:
        query = "SELECT * FROM experiences"
        clauses = []
        params: list[object] = []

        if recommendation_id:
            clauses.append("recommendation_id = ?")
            params.append(canonicalize_recommendation_id(recommendation_id=recommendation_id))
        if failure_type:
            clauses.append("failure_type = ?")
            params.append(failure_type)
        if service:
            clauses.append("service = ?")
            params.append(service)

        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        rows = self._conn.execute(query, params).fetchall()
        return [self._row_to_model(row) for row in rows]

    def get_by_recommendation(self, recommendation_id: str, limit: int = 200) -> list[ExperienceRecord]:
        return self.get_experiences(recommendation_id=recommendation_id, limit=limit)

    def get_by_failure(self, failure_type: str, limit: int = 200) -> list[ExperienceRecord]:
        return self.get_experiences(failure_type=failure_type, limit=limit)

    def get_by_service(self, service: str, limit: int = 200) -> list[ExperienceRecord]:
        return self.get_experiences(service=service, limit=limit)

    def recommendation_catalog(self) -> list[dict]:
        rows = self._conn.execute(
            """
            SELECT recommendation_id, MAX(recommendation) AS recommendation, COUNT(*) AS count
            FROM experiences
            GROUP BY recommendation_id
            ORDER BY count DESC, recommendation_id ASC
            """
        ).fetchall()
        return [dict(row) for row in rows]

    def count(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) AS count FROM experiences").fetchone()
        return int(row["count"]) if row else 0

    def average_confidence(self) -> float:
        row = self._conn.execute("SELECT AVG(confidence) AS avg_confidence FROM experiences").fetchone()
        value = row["avg_confidence"] if row and row["avg_confidence"] is not None else 0.0
        return round(float(value), 3)

    def close(self) -> None:
        self._conn.close()

    def _row_to_model(self, row: sqlite3.Row) -> ExperienceRecord:
        return ExperienceRecord(
            experience_id=row["experience_id"],
            incident_id=row["incident_id"],
            recommendation_id=row["recommendation_id"],
            recommendation=row["recommendation"],
            accepted=bool(row["accepted"]),
            worked=bool(row["worked"]),
            resolution_time_seconds=row["resolution_time_seconds"],
            engineer_feedback=row["engineer_feedback"],
            confidence=row["confidence"],
            service=row["service"],
            component=row["component"],
            failure_type=row["failure_type"],
            symptoms=json.loads(row["symptoms_json"]),
            timestamp=row["timestamp"],
        )


_store: ExperienceStore | None = None


def get_experience_store() -> ExperienceStore:
    global _store
    if _store is None:
        _store = ExperienceStore()
    return _store
