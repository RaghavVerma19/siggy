"""
End-to-end demo: Telemetry -> Knowledge -> Experience -> Graph
Usage: python test_investigate.py
"""
import httpx
import json
import os

BASE = os.getenv("BASE_URL", "http://localhost:8010")


def step(num, title):
    print(f"\n{'='*60}")
    print(f"STEP {num}: {title}")
    print(f"{'='*60}")


def main():
    step(1, "Health Check")
    r = httpx.get(f"{BASE}/api/v1/health")
    print(json.dumps(r.json(), indent=2))

    step(2, "SigNoz MCP Health")
    r = httpx.get(f"{BASE}/api/v1/telemetry/health")
    print(json.dumps(r.json(), indent=2))
    if not r.json().get("connected"):
        print("WARNING: SigNoz MCP not connected. Telemetry endpoints will fail.")
        print("Make sure SigNoz + MCP server are running via: docker compose up -d")

    step(3, "Investigate (raw telemetry)")
    try:
        r = httpx.post(
            f"{BASE}/api/v1/telemetry/investigate",
            json={"query": "Checkout API is slow, users complaining about timeouts"},
            timeout=60.0,
        )
        print(json.dumps(r.json(), indent=2))
    except Exception as e:
        print(f"Error: {e}")

    step(4, "Full Analysis (telemetry -> rules -> knowledge -> experience -> graph)")
    try:
        r = httpx.post(
            f"{BASE}/api/v1/telemetry/full-analysis",
            json={"query": "Checkout API is slow"},
            timeout=120.0,
        )
        data = r.json()
        print(f"Source: {data.get('source', 'unknown')}")
        print(f"Telemetry Summary: {json.dumps(data.get('telemetry_summary', {}), indent=2)}")
        if data.get("similar_incidents"):
            print(f"Similar Incidents Found: {len(data['similar_incidents'])}")
            for i, inc in enumerate(data["similar_incidents"], 1):
                print(f"  {i}. {inc['title']} (sim={inc.get('similarity', 'N/A')})")
        print(f"Recommendation: {data.get('recommendation', 'N/A')}")
        print(f"Confidence: {data.get('confidence', 'N/A')}")
        print(f"Evidence: {json.dumps(data.get('evidence', []), indent=2)}")
        print(f"Graph Context: {json.dumps(data.get('graph_context', {}), indent=2)}")
    except Exception as e:
        print(f"Error: {e}")

    step(5, "Knowledge Analysis")
    try:
        r = httpx.post(
            f"{BASE}/api/v1/knowledge/analyze",
            json={
                "title": "Checkout API latency spike",
                "summary": "Redis connection pool exhausted during peak traffic causing timeouts",
            },
            timeout=120.0,
        )
        print(json.dumps(r.json(), indent=2))
    except Exception as e:
        print(f"Error: {e}")

    step(6, "Record Experience")
    try:
        r = httpx.post(
            f"{BASE}/api/v1/experience/record",
            json={
                "recommendation_id": "INCREASE_POOL_SIZE",
                "recommendation": "Increase Redis connection pool size from 64 to 128",
                "accepted": True,
                "worked": True,
                "confidence": 0.94,
                "resolution_time_seconds": 660,
                "incident_id": "telemetry-001",
                "engineer_feedback": "Fixed the checkout latency issue",
                "service": "checkout",
                "component": "redis",
                "failure_type": "connection_pool_exhaustion",
                "symptoms": ["high_latency", "request_timeout"],
            },
            timeout=10.0,
        )
        print(json.dumps(r.json(), indent=2))
    except Exception as e:
        print(f"Error: {e}")

    step(7, "Get Experience Statistics")
    try:
        r = httpx.get(
            f"{BASE}/api/v1/experience/statistics",
            params={"recommendation_id": "INCREASE_POOL_SIZE"},
            timeout=10.0,
        )
        print(json.dumps(r.json(), indent=2))
    except Exception as e:
        print(f"Error: {e}")

    step(8, "Graph Sync")
    try:
        r = httpx.post(f"{BASE}/api/v1/graph/sync", timeout=20.0)
        print(json.dumps(r.json(), indent=2))
    except Exception as e:
        print(f"Error: {e}")

    step(9, "Graph Neighbors")
    try:
        r = httpx.get(f"{BASE}/api/v1/graph/neighbors/checkout", timeout=10.0)
        print(json.dumps(r.json(), indent=2))
    except Exception as e:
        print(f"Error: {e}")

    step(10, "Graph Recommendation")
    try:
        r = httpx.get(f"{BASE}/api/v1/graph/recommendation/INCREASE_POOL_SIZE", timeout=10.0)
        print(json.dumps(r.json(), indent=2))
    except Exception as e:
        print(f"Error: {e}")

    step(11, "Natural Language Graph Query")
    try:
        r = httpx.post(
            f"{BASE}/api/v1/graph/query",
            json={"question": "Which recommendation has highest success?"},
            timeout=10.0,
        )
        print(json.dumps(r.json(), indent=2))
    except Exception as e:
        print(f"Error: {e}")

    step(12, "Traditional Agent Analysis (Day 1/2 path still works)")
    try:
        r = httpx.post(
            f"{BASE}/api/v1/agent/analyze",
            json={
                "title": "Payment API timing out",
                "summary": "Payment service returning 504 errors. Redis connections are being rejected.",
            },
            timeout=60.0,
        )
        data = r.json()
        print(f"Normalized: {json.dumps(data.get('normalized', {}), indent=2)}")
        print(f"Similar: {len(data.get('similar_incidents', []))} incidents found")
        a = data.get("analysis", {})
        print(f"Confidence: {a.get('confidence', 'N/A')}")
        print(f"Fix: {a.get('recommended_fix', 'N/A')}")
    except Exception as e:
        print(f"Error: {e}")

    print(f"\n{'='*60}")
    print("DEMO COMPLETE")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
