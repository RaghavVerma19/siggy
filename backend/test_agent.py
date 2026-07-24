import httpx, json, os

BASE = os.getenv("BASE_URL", "http://localhost:8010")

r = httpx.post(f'{BASE}/api/v1/agent/analyze', json={
    "title": "Payment API timing out",
    "summary": "Payment service returning 504 errors. Redis connections are being rejected. Error rate 25%."
}, timeout=60.0)
print("Status:", r.status_code)
data = r.json()

print("\n=== NORMALIZED ===")
print(json.dumps(data["normalized"], indent=2))

print("\n=== TOP 5 SIMILAR ===")
for i, m in enumerate(data["similar_incidents"], 1):
    print(str(i) + ". " + m["title"] + " (sim=" + str(m["similarity"]) + ")")

print("\n=== ANALYSIS ===")
a = data["analysis"]
print("Common Pattern:", a["common_pattern"])
print("Confidence:", a["confidence"])
print("Recommended Fix:", a["recommended_fix"])
print("\nEvidence:")
for e in a["reasoning_chain"]["evidence"]:
    print("  " + e)
print("\nInvestigation Steps:")
for s in a["investigation_steps"]:
    print("  " + s)
