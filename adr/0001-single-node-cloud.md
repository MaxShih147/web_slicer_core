# ADR 0001: Single-Node Cloud Architecture

## Status

Accepted

## Context

We need to deploy a web-based slicing service for partner preview. The deployment target is a single Mac Studio. However, we anticipate migrating to cloud infrastructure in the future.

Building a monolithic application would be faster to deploy initially but would require significant refactoring for cloud migration. Building a fully distributed system is premature for a single machine.

## Decision

Adopt a "single-node cloud" architecture: design the system as if it were running on cloud infrastructure (separate ingress, API, queue, workers, storage), but deploy all components on a single physical machine.

Components communicate through network interfaces (localhost) and filesystem, not through in-process function calls.

## Consequences

**Positive:**

- Cloud migration requires only deployment config changes, not code changes
- Components can be developed, tested, and restarted independently
- Worker count can be adjusted without touching API code
- Clear separation of concerns from day one

**Negative:**

- More complex than a simple monolith for single-machine deployment
- Multiple processes to manage and monitor
- IPC overhead (negligible on localhost, but exists)
- Requires process supervision (launchd / supervisor / Docker)
