"""Siggy Sidecar — watches SigNoz alerts and enriches them with memory.

The sidecar polls SigNoz for alerts, runs each through the knowledge pipeline,
and writes enriched recommendations back to SigNoz via OTel span attributes.

Architecture:
    SigNoz (alerts) → SiggySidecar (poll) → Knowledge Pipeline → OTel spans + SQLite

The sidecar is the primary runtime mode for Siggy. It runs as a background
process alongside SigNoz and enriches alerts in-place.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path

from cli.config import SiggyConfig

from utils.paths import siggy_incidents_db

logger = logging.getLogger(__name__)

DB_PATH = siggy_incidents_db()


class SiggySidecar:
    """Watches SigNoz alerts and enriches them with memory-enriched recommendations."""

    def __init__(self, config: SiggyConfig):
        self.config = config
        self._processed_fingerprints: set[str] = set()
        self._db = self._init_db()
        self._running = False
        self._tracer = None
        self._setup_otel_tracer()

        from telemetry.mcp_http import MCPHttpClient
        self._mcp_client = MCPHttpClient(
            mcp_url=os.getenv("SIGNOZ_MCP_URL", "http://localhost:8000/mcp"),
            api_key=os.getenv("SIGNOZ_API_KEY", ""),
            client_name="siggy-sidecar",
        )
        self._consecutive_failures = 0

    def _setup_otel_tracer(self):
        """Set up OTel tracer for writing recommendation spans to SigNoz."""
        try:
            from opentelemetry import trace
            self._tracer = trace.get_tracer("siggy.sidecar")
        except Exception:
            self._tracer = None

    @property
    def is_running(self) -> bool:
        return self._running

    def _init_db(self) -> sqlite3.Connection:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        conn.execute("""
            CREATE TABLE IF NOT EXISTS incidents (
                incident_id TEXT PRIMARY KEY,
                alert_fingerprint TEXT UNIQUE,
                service TEXT,
                severity TEXT,
                status TEXT DEFAULT 'active',
                alert_summary TEXT,
                root_cause TEXT,
                recommendation TEXT,
                recommendation_id TEXT,
                confidence REAL,
                evidence TEXT DEFAULT '[]',
                similar_incidents TEXT DEFAULT '[]',
                graph_context TEXT DEFAULT '{}',
                detected_at TIMESTAMP,
                resolved_at TIMESTAMP,
                source TEXT DEFAULT 'signoz_alert',
                web_url TEXT DEFAULT ''
            )
        """)
        conn.commit()
        return conn

    async def start_polling(self, interval: int = 30):
        """Start the alert polling loop."""
        self._running = True
        print(f"Siggy sidecar polling every {interval}s...")

        while True:
            try:
                await self._poll_cycle()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Poll cycle error: %s", e)

            await asyncio.sleep(interval)

        self._running = False
        print("Siggy sidecar stopped")

    async def _poll_cycle(self):
        """Single poll cycle — fetch alerts from SigNoz via MCP."""
        try:
            result = await self._mcp_client.call_tool("signoz_list_alerts", {
                "silenced": False,
                "inhibited": False,
            })
            alerts = result.get("alerts", result.get("data", []))
            if not isinstance(alerts, list):
                return
            self._consecutive_failures = 0
        except Exception as e:
            self._consecutive_failures += 1
            if self._consecutive_failures <= 2:
                logger.debug("MCP alert fetch failed (attempt %d): %s", self._consecutive_failures, e)
            else:
                logger.warning("MCP alert fetch failed %d times: %s", self._consecutive_failures, e)
                self._mcp_client.reset()
            return

        for alert in alerts:
            if not isinstance(alert, dict):
                continue

            fingerprint = alert.get("fingerprint", "")
            if not fingerprint or fingerprint in self._processed_fingerprints:
                continue

            self._processed_fingerprints.add(fingerprint)
            enriched = await self._enrich_alert(alert)
            if enriched:
                self._store_incident(enriched)
                self._emit_recommendation_span(alert, enriched)
                self._enrich_alert_in_signoz(alert, enriched)
                self._print_incident(enriched)

    async def _enrich_alert(self, alert: dict) -> dict | None:
        """Enrich a SigNoz alert with memory-enriched recommendation."""
        labels = alert.get("labels", {})
        annotations = alert.get("annotations", {})
        status = alert.get("status", {})

        service = labels.get("service_name", labels.get("service", "unknown"))
        severity = labels.get("severity", "medium")
        summary = (
            annotations.get("summary", "")
            or annotations.get("description", "")
            or f"Alert: {labels.get('alertname', 'unknown')} on {service}"
        )

        # Run knowledge pipeline (synchronous, run in thread to avoid blocking)
        rec = None
        similar_incidents = []
        graph_context = {}
        try:
            from knowledge.pipeline import knowledge_pipeline
            result = await asyncio.to_thread(
                knowledge_pipeline,
                title=f"{service}: {summary}",
                summary=summary,
                store_new=False,
            )
            rec = result.get("recommendation", {})
            similar_incidents = result.get("similar_incidents", [])[:3]
            graph_context = rec.get("graph_context", {})
        except Exception as e:
            logger.debug("Knowledge pipeline unavailable: %s", e)

        if rec and rec.get("recommendation"):
            recommendation = rec["recommendation"]
            confidence = rec.get("confidence", 0.5)
            evidence = rec.get("evidence", [])
            reasoning = self._format_reasoning(rec)
            rec_id = rec.get("recommendation_id", "")
        else:
            recommendation, confidence, evidence, reasoning, rec_id = self._rule_based_fallback(service, summary)

        return {
            "incident_id": f"inc_{uuid.uuid4().hex[:8]}",
            "alert_fingerprint": alert.get("fingerprint", str(uuid.uuid4())),
            "service": service,
            "severity": severity,
            "status": "active",
            "alert_summary": summary,
            "root_cause": reasoning,
            "recommendation": recommendation,
            "recommendation_id": rec_id,
            "confidence": confidence,
            "evidence": evidence,
            "similar_incidents": similar_incidents,
            "graph_context": graph_context,
            "detected_at": datetime.utcnow().isoformat(),
            "resolved_at": None,
            "source": "signoz_alert",
            "web_url": alert.get("webUrl", ""),
        }

    def _emit_recommendation_span(self, alert: dict, enriched: dict):
        """Write enriched recommendation back to SigNoz as an OTel span.

        This makes the recommendation visible in SigNoz's Traces Explorer,
        filterable by siggy.recommendation_id, siggy.service, etc.
        """
        if not self._tracer:
            return

        try:
            labels = alert.get("labels", {})
            service = labels.get("service_name", labels.get("service", "unknown"))

            with self._tracer.start_as_current_span("siggy.recommendation") as span:
                span.set_attribute("siggy.recommendation", enriched["recommendation"])
                span.set_attribute("siggy.confidence", enriched["confidence"])
                span.set_attribute("siggy.recommendation_id", enriched["recommendation_id"])
                span.set_attribute("siggy.failure_type", enriched.get("root_cause", "")[:100])
                span.set_attribute("siggy.service", service)
                span.set_attribute("siggy.severity", enriched["severity"])
                span.add_event("memory_enriched_recommendation", {
                    "recommendation": enriched["recommendation"][:500],
                    "confidence": enriched["confidence"],
                    "evidence_count": len(enriched.get("evidence", [])),
                    "similar_incidents": len(enriched.get("similar_incidents", [])),
                })
        except Exception as e:
            logger.debug("Failed to emit OTel span: %s", e)

    def _enrich_alert_in_signoz(self, alert: dict, enriched: dict):
        """Update the alert rule in SigNoz to include Siggy's recommendation.

        This appends the recommendation to the alert rule's description,
        so engineers see it when they click the alert in SigNoz's UI.
        """
        alert_id = alert.get("alertId") or alert.get("id")
        if not alert_id:
            return

        labels = alert.get("labels", {})
        alertname = labels.get("alertname", "unknown")
        service = labels.get("service_name", labels.get("service", "unknown"))

        recommendation = enriched.get("recommendation", "")
        confidence = enriched.get("confidence", 0)
        rec_id = enriched.get("recommendation_id", "")
        evidence = enriched.get("evidence", [])
        evidence_text = "; ".join(evidence[:3]) if evidence else "No evidence available"

        siggy_annotation = (
            f"\n\n--- Siggy Memory Layer ---\n"
            f"Recommendation: {recommendation}\n"
            f"Confidence: {confidence:.0%}\n"
            f"Recommendation ID: {rec_id}\n"
            f"Evidence: {evidence_text}\n"
            f"Powered by Siggy (siggy.ai)"
        )

        try:
            import httpx
            from cli.config import SiggyConfig

            config = SiggyConfig.load()
            # Fetch current rule to preserve existing description
            r = httpx.get(
                f"{config.signoz.url}/api/v2/rules",
                headers={"SIGNOZ-API-KEY": config.signoz.api_key},
                timeout=5,
            )
            if r.status_code >= 400:
                return

            rules = r.json() if isinstance(r.json(), list) else r.json().get("data", [])
            target_rule = None
            for rule in rules:
                if isinstance(rule, dict) and rule.get("id") == alert_id:
                    target_rule = rule
                    break

            if not target_rule:
                return

            # Append Siggy recommendation to description
            current_desc = target_rule.get("description", "")
            if "Siggy Memory Layer" in current_desc:
                # Already enriched — update in place
                import re
                current_desc = re.sub(
                    r"\n\n--- Siggy Memory Layer ---.*$",
                    siggy_annotation,
                    current_desc,
                    flags=re.DOTALL,
                )
            else:
                current_desc += siggy_annotation

            # Update the rule via MCP
            target_rule["description"] = current_desc

            async def _do_update():
                from telemetry.signoz_mcp import get_telemetry_provider
                provider = get_telemetry_provider()
                if provider._client._initialized:
                    await provider.update_alert_rule(alert_id, {"rule": target_rule})

            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.ensure_future(_do_update())
            else:
                loop.run_until_complete(_do_update())

        except Exception as e:
            logger.debug("Failed to enrich alert in SigNoz: %s", e)
        """Format reasoning into a human-readable string."""
        reasoning = rec.get("reasoning", {})
        if not isinstance(reasoning, dict):
            return str(reasoning) if reasoning else ""

        parts = []
        matched = []
        if reasoning.get("matched_service"):
            matched.append("service")
        if reasoning.get("matched_component"):
            matched.append("component")
        if reasoning.get("matched_failure_type"):
            matched.append("failure type")
        if reasoning.get("matched_severity"):
            matched.append("severity")

        match_score = reasoning.get("match_score", "0/4")
        similarity = reasoning.get("similarity", 0)

        if matched:
            parts.append(f"Matched on {', '.join(matched)} ({match_score})")
        if similarity > 0:
            parts.append(f"Similarity: {similarity:.2f}")
        if not parts:
            parts.append("Based on incident pattern analysis")

        return ". ".join(parts) + "."

    def _rule_based_fallback(self, service: str, summary: str) -> tuple:
        """Rule-based fallback when knowledge pipeline is unavailable."""
        summary_lower = summary.lower()
        if "500" in summary_lower:
            rec = "Check application logs for stack traces. Verify downstream dependencies."
            reasoning = "HTTP 500 indicates server-side error."
        elif "timeout" in summary_lower:
            rec = "Check connection pool settings and downstream service health."
            reasoning = "Timeout indicates slow response from downstream."
        elif "429" in summary_lower:
            rec = "Implement rate limiting client-side. Check if traffic spike is legitimate."
            reasoning = "HTTP 429 indicates rate limiting."
        else:
            rec = f"Investigate {service} error logs and check recent changes."
            reasoning = "General error pattern detected."
        return rec, 0.6, [summary], reasoning, ""

    def _store_incident(self, incident: dict):
        """Store enriched incident in SQLite."""
        try:
            self._db.execute(
                """INSERT OR REPLACE INTO incidents
                   (incident_id, alert_fingerprint, service, severity, status,
                    alert_summary, root_cause, recommendation, recommendation_id,
                    confidence, evidence, similar_incidents, graph_context,
                    detected_at, resolved_at, source, web_url)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    incident["incident_id"],
                    incident["alert_fingerprint"],
                    incident["service"],
                    incident["severity"],
                    incident["status"],
                    incident["alert_summary"],
                    incident["root_cause"],
                    incident["recommendation"],
                    incident["recommendation_id"],
                    incident["confidence"],
                    json.dumps(incident.get("evidence", []), default=str),
                    json.dumps(incident.get("similar_incidents", []), default=str),
                    json.dumps(incident.get("graph_context", {}), default=str),
                    incident["detected_at"],
                    incident["resolved_at"],
                    incident["source"],
                    incident.get("web_url", ""),
                ),
            )
            self._db.commit()
        except Exception as e:
            logger.error("Failed to store incident: %s", e)

    def _print_incident(self, incident: dict):
        """Print enriched incident to terminal."""
        severity_colors = {
            "critical": "\033[91m",
            "high": "\033[93m",
            "medium": "\033[96m",
            "low": "\033[92m",
        }
        reset = "\033[0m"
        color = severity_colors.get(incident["severity"], "")

        print(f"\n{'=' * 60}")
        print(f"{color}[{incident['severity'].upper()}]{reset} {incident['service']}")
        print(f"  {incident['alert_summary']}")
        print(f"  Recommendation: {incident['recommendation']}")
        print(f"  Confidence: {incident['confidence']:.0%}")
        if incident.get("root_cause"):
            print(f"  Root Cause: {incident['root_cause']}")
        if incident.get("evidence"):
            for ev in (incident["evidence"] if isinstance(incident["evidence"], list) else [])[:3]:
                print(f"  Evidence: {ev}")
        if incident.get("similar_incidents"):
            count = len(incident["similar_incidents"]) if isinstance(incident["similar_incidents"], list) else 0
            print(f"  Similar Past Incidents: {count}")
        print(f"  Detected: {incident['detected_at']}")
        print(f"{'=' * 60}\n")

    def get_active_incidents(self) -> list[dict]:
        """Get all active incidents from the store."""
        rows = self._db.execute(
            "SELECT * FROM incidents WHERE status = 'active' ORDER BY detected_at DESC"
        ).fetchall()
        return [self._deserialize_incident(row) for row in rows]

    def resolve_incident(self, incident_id: str) -> bool:
        """Mark an incident as resolved."""
        cursor = self._db.execute(
            "UPDATE incidents SET status = 'resolved', resolved_at = ? WHERE incident_id = ?",
            (datetime.utcnow().isoformat(), incident_id),
        )
        self._db.commit()
        return cursor.rowcount > 0

    def get_all_incidents(self, limit: int = 50) -> list[dict]:
        """Get all incidents, most recent first."""
        rows = self._db.execute(
            "SELECT * FROM incidents ORDER BY detected_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [self._deserialize_incident(row) for row in rows]

    def _deserialize_incident(self, row) -> dict:
        """Convert a SQLite row to a dict with parsed JSON fields."""
        d = dict(row)
        for field in ("evidence", "similar_incidents", "graph_context"):
            if field in d and isinstance(d[field], str):
                try:
                    d[field] = json.loads(d[field])
                except (ValueError, TypeError):
                    pass
        return d


# Backwards compatibility alias
IncidentProcessor = SiggySidecar
