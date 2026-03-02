# Security Notes

## Single-Origin and CORS

By serving frontend, API, and SSE from a single domain via reverse proxy, we eliminate CORS entirely:

- Browser sees all requests as same-origin
- No `Access-Control-Allow-Origin` headers needed
- No preflight OPTIONS requests
- No risk of misconfigured CORS allowing unintended origins

This is the simplest and most secure approach for a single-deployment system.

## Partner Preview Security Assumptions

This system is designed for a **partner preview** scenario:

- Small number of known users (internal team + select partners)
- Not exposed to the general internet
- Trust level is moderate — users are not adversarial, but input is untrusted

### What this means in practice

- We validate input but don't assume sophisticated attacks
- We protect against accidental abuse, not targeted exploitation
- We prioritize availability and simplicity over defense-in-depth

## Authentication

### Current state: None

No authentication is implemented. The system is accessed via direct URL.

### Planned (when needed)

| Mechanism | Use case |
|-----------|---------|
| Shared secret / API key | Simple partner access control |
| Basic Auth (Nginx) | Quick password gate for the whole site |
| OAuth / OIDC | If integrated with company SSO |

Authentication should be added at the **ingress layer** (Nginx), not in the API. This keeps the API stateless and auth-agnostic.

## Rate Limiting

### Current state: None

### Recommended (single-node)

| Limit | Value | Enforced by |
|-------|-------|------------|
| Requests per minute per IP | 60 | Nginx `limit_req` |
| Concurrent uploads per IP | 2 | Nginx `limit_conn` |
| Queue depth (global) | 50 | API rejects with 503 |

Rate limiting at Nginx is preferred because it operates before the request reaches the API process.

## Upload Limits

| Parameter | Value | Reason |
|-----------|-------|--------|
| Max file size | 100 MB | Largest reasonable STL for SLA printing |
| Allowed file types | `.stl`, `.3mf` | Only formats PrusaSlicer accepts |
| Filename sanitization | Strip path components, limit length | Prevent path traversal |

Enforced at two layers:
1. **Nginx**: `client_max_body_size 100m` — rejects before buffering
2. **API**: validate content-type and file extension

## Sandboxing

### Slicer Runtime Isolation

PrusaSlicer CLI is the highest-risk component (processes untrusted binary input):

| Measure | Status |
|---------|--------|
| Runs as separate process | Yes |
| Runs as unprivileged user | Recommended |
| Filesystem access limited to job directory | Recommended |
| Network access disabled | Recommended |
| Execution timeout | Yes (enforced by worker) |
| Memory limit | Recommended (via ulimit / cgroups) |

On macOS, sandboxing options are limited compared to Linux:
- `ulimit` for resource limits
- Separate user account for worker processes
- Full sandboxing requires Docker (Linux containers via VM)

### Worker Isolation

- Each job runs in its own temporary directory
- Workers should not share state
- A crashed worker must not corrupt other jobs

## What is Intentionally NOT Implemented

| Feature | Why not |
|---------|---------|
| End-to-end encryption | Single-node, localhost communication |
| JWT / session management | No multi-user auth yet |
| RBAC (role-based access) | Single role: "user who can slice" |
| Audit logging | Not required for partner preview |
| Input virus scanning | STL files are geometry, not executable |
| DDoS protection | Not internet-facing in preview phase |
| Secrets management (Vault) | No secrets beyond optional API key |
| Network segmentation | Single machine, all on loopback |

These should be revisited when:
- The system is exposed to the internet
- Multiple tenants / organizations use it
- Compliance requirements arise
