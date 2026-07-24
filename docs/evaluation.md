# Evaluation

## Benchmark Suite

The project includes an evaluation harness at `backend/evaluate.py`.

It seeds:

- reference memory from synthetic incidents
- synthetic experience history
- graph relationships and operational patterns

It then evaluates **30 benchmark incidents** against:

- top-1 and top-3 incident retrieval accuracy
- top-1 and top-3 recommendation accuracy
- average confidence
- average response time
- average retrieval latency
- average graph query latency
- knowledge normalization accuracy
- experience re-ranking impact versus the raw retrieval baseline

## Latest Snapshot

Measured on **July 22, 2026**.

| Metric | Result |
| --- | --- |
| Incident Retrieval Accuracy (Top-1) | 53.33% |
| Incident Retrieval Accuracy (Top-3) | 73.33% |
| Recommendation Accuracy (Top-1) | 26.67% |
| Recommendation Accuracy (Top-3) | 40.0% |
| Average Confidence | 0.63 |
| Average Response Time | 36.28 ms |
| Average Retrieval Time | 8.35 ms |
| Graph Query Time | 9.9 ms |
| Knowledge Normalization Accuracy | 57.0% |
| Experience Ranking Improvement (Top-1) | -50.0 pts |

## Interpretation

What looks good:

- the evaluation suite is now automated and repeatable
- latency is already strong for a demo environment
- graph query time is low enough for interactive use
- the benchmark exposes field-level normalization accuracy

What needs work next:

- recommendation quality is not yet strong enough for a polished claim
- the current experience re-ranking logic is hurting top-1 accuracy versus the raw retrieval baseline on this synthetic suite
- normalization quality is acceptable for fallback mode, but not strong enough to anchor a high-confidence production narrative

## Recommended Next Fixes

1. Improve normalization accuracy first, especially `fix_type` and `severity`.
2. Tune recommendation ranking against this benchmark until it beats the baseline.
3. Add a small set of benchmark cases for telemetry-first flows, not only text incidents.
4. Expose the scorecard in the frontend as a judge-facing evaluation dashboard.

## Running It

```bash
cd backend
python evaluate.py
```

During local development you can override the report output location with:

```bash
EVALUATION_REPORT_DIR=/path/to/output python evaluate.py
```
