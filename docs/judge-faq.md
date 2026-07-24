# Judge FAQ

## Why GraphRAG instead of only vector search?

Vector search finds similar text. The graph explains operational relationships like service-to-component dependencies, repeated failure patterns, and recommendation history. We use vector search to find relevant incidents and the graph to expand context and justify the answer.

## Why use Qdrant and a graph together?

They solve different problems. Qdrant is good at similarity retrieval across incident history. The graph is good at dependency and neighborhood questions such as "which services depend on Redis?" or "what recommendation has the strongest history for this failure type?"

## How does the Experience Engine learn?

Each recommendation can be recorded with acceptance, outcome, resolution time, and feedback. Those records are aggregated into recommendation statistics and operational patterns that influence future ranking.

## How do you prevent bad feedback from degrading the system?

Feedback is stored as explicit outcomes rather than blindly retraining a model. That makes it auditable and reversible. Ranking is based on transparent counts, success rates, and resolution times.

## How is this different from SigNoz AI?

The focus here is persistent operational memory. We are not only summarizing telemetry. We are storing normalized incidents, retrieving prior cases, tracking recommendation success, and exposing graph-based operational relationships.

## What happens if the LLM is unavailable?

The backend falls back to deterministic local heuristics for telemetry summarization, normalization, embeddings, and recommendation support. Quality drops, but the system remains functional and demoable.

## How does fallback mode work?

Fallback mode uses rule-based extraction and deterministic helpers to infer service, component, failure type, fix type, symptoms, and summaries. It is less accurate than the intended hosted path but keeps the workflow alive end to end.

## Can this scale to millions of incidents?

That is the intended architecture direction. Vector retrieval and graph storage can scale independently. The main scaling work is around better indexing, batching graph sync, multi-tenant separation, and more disciplined benchmark coverage.

## Why is the evaluation suite important?

Because without it, the project is just architecture. The benchmark makes the system falsifiable. It shows what currently works, what is fast, and where recommendation quality still needs tuning.
