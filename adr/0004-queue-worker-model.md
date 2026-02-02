# ADR 0004: Queue-Worker Model for Slicing Jobs

## Status

Accepted

## Context

Slicing operations (PrusaSlicer CLI) are CPU-intensive and take seconds to minutes. Running them inside the API request handler blocks the event loop, limits concurrency, and makes the API unresponsive during heavy loads.

Options considered:

1. **In-process**: run slicer in API thread/process pool (current approach)
2. **Background task**: FastAPI BackgroundTasks / asyncio subprocess
3. **Queue + worker**: separate worker processes pull jobs from a shared queue

## Decision

Adopt a queue-worker model:

- API enqueues jobs into a shared queue (Redis or SQLite-based)
- Independent worker processes dequeue and execute jobs
- Workers invoke PrusaSlicer CLI via subprocess
- Workers write results to shared storage and update job status

## Consequences

**Positive:**

- API stays fast and responsive — never blocks on slicing
- Worker count is configurable — scale by adding processes
- Workers are disposable — crash one, others continue
- Clean process boundary around PrusaSlicer (AGPL isolation)
- Maps directly to cloud patterns (SQS + ECS tasks, Cloud Tasks + Cloud Run)

**Negative:**

- Requires a queue broker (Redis or SQLite) — additional dependency
- Job status must be stored externally (not in API memory)
- Slightly higher latency for small jobs (queue overhead)
- Need a mechanism to detect stale/crashed jobs (heartbeat or reaper)
