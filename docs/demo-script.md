# Demo Script

This is the recommended live demo flow for a 4-minute judging slot.

## Goal

Show that the system can move from telemetry to an explainable recommendation with memory, graph context, and feedback.

## Story

Use a Redis latency incident in checkout.

Suggested user-facing prompt:

> "Checkout is slow and users are seeing timeouts."

## Live Sequence

1. Open the homepage dashboard.
2. Click `Run Product Demo`.
3. Narrate the flow:
   - telemetry or incident arrives
   - system converts it into structured operational knowledge
   - vector memory retrieves similar incidents
   - graph expands related services and dependencies
   - experience history ranks likely fixes
4. Point to the result card:
   - root cause
   - recommended action
   - confidence
   - historical evidence
5. Point to the relationship map:
   - service
   - component
   - failure
   - recommendation
6. Record a successful outcome in the experience panel.
7. Refresh the dashboard summary and show that learned outcomes are tracked.

## What To Say

- "This is not just a chatbot over logs. It stores incidents as operational memory."
- "We combine similarity search with a graph so the system can explain relationships, not just retrieve text."
- "Recommendations are ranked using what worked before, and engineers can feed outcomes back into the system."

## Fallback Plan

If live telemetry is unstable:

1. Stay on the product demo path.
2. Use the seeded checkout incident.
3. Show the relationship graph and evidence panel.
4. Emphasize that the fallback mode is intentional and keeps the system usable without hosted-model availability.

## Final Line

"The goal is not another AI answer box. The goal is operational memory that becomes more useful every time the team resolves an incident."
