# ADR 0003: SSE Over Polling for Job Progress

## Status

Accepted

## Context

Slicing jobs take seconds to minutes. The client needs to know when a job transitions through states (queued → processing → completed/failed) and receive progress updates during processing.

Options considered:

1. **Polling**: client sends `GET /api/v2/jobs/{id}` every N seconds
2. **Server-Sent Events (SSE)**: server pushes updates over a long-lived HTTP connection
3. **WebSocket**: full-duplex connection between client and server

## Decision

Use Server-Sent Events (SSE) for job progress notifications.

- Client opens `GET /events/jobs/{id}` — receives a stream of events
- Server pushes `{ status, progress, message }` as job state changes
- Connection auto-reconnects on drop (built into EventSource API)

## Consequences

**Positive:**

- Lower latency than polling — updates arrive immediately
- Lower server load than polling — no repeated requests
- Simpler than WebSocket — HTTP-based, works through proxies, no upgrade negotiation
- Native browser support via `EventSource` API with automatic reconnection
- Unidirectional (server → client) matches our use case exactly

**Negative:**

- Long-lived connections consume server resources (one per active job viewer)
- Nginx/proxy must be configured to disable buffering for SSE endpoints
- Limited to ~6 concurrent connections per domain in HTTP/1.1 (not an issue with HTTP/2)
- If bidirectional communication is needed later (e.g., cancel job), a separate API call or WebSocket upgrade would be required
