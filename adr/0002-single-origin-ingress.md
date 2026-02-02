# ADR 0002: Single-Origin Ingress

## Status

Accepted

## Context

The system has three types of traffic:

1. Frontend static assets (HTML/JS/CSS)
2. API requests (REST, file uploads)
3. Real-time events (SSE for job progress)

These could be served from separate origins (e.g., `app.example.com`, `api.example.com`, `events.example.com`) or from a single origin with path-based routing.

Separate origins require CORS configuration, which is error-prone and creates browser preflight overhead. Multiple origins also complicate TLS certificate management and cookie scope.

## Decision

Use a single origin with a reverse proxy (Nginx or Traefik) that routes by path:

- `/` → frontend static files
- `/api/*` → FastAPI application
- `/events/*` → SSE endpoint (same FastAPI process)

All traffic enters through one domain and one port (443).

## Consequences

**Positive:**

- No CORS configuration needed — all requests are same-origin
- Single TLS certificate
- Simpler client-side code (no cross-origin fetch headers)
- SSE and API share authentication context naturally
- One DNS record to manage

**Negative:**

- Reverse proxy is a single point of failure (acceptable on single node)
- Path-based routing requires coordination between frontend and backend teams
- Cannot independently scale frontend CDN vs API (not needed on single node)
