import traceback
try:
    from agents.normalizer import normalize_incident
    from memory.embeddings import get_embedding
    from memory.vector_store import get_store
    from agents.recommender import recommend_fix

    print("=== STEP 1: Normalize ===")
    norm = normalize_incident("Payment timeout", "Redis connections maxed out causing payment service failures")
    print("Normalized:", norm)

    print("\n=== STEP 2: Embed ===")
    emb_text = norm.service + " " + norm.component + " " + norm.failure + " " + norm.symptom + " " + norm.root_cause
    embedding = get_embedding(emb_text)
    print("Embedding len:", len(embedding))

    print("\n=== STEP 3: Search ===")
    store = get_store()
    matches = store.search(embedding, top_k=3)
    print("Matches:", len(matches))
    for m in matches:
        print("  -", m["title"], "(similarity:", m["similarity"], ")")

    print("\n=== STEP 4: Recommend ===")
    rec = recommend_fix("Payment timeout", "Redis connections maxed out causing payment service failures", norm.model_dump(), matches)
    print("Recommendation:", rec)

    print("\n=== ALL PASSED ===")
except Exception as e:
    traceback.print_exc()
