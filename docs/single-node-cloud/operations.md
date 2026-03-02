# Operations

## Job Lifecycle

```
created → queued → processing → completed
                             → failed
                             → timeout
```

| State | Description | Transitions to |
|-------|-------------|---------------|
| `created` | Job accepted, input stored | `queued` |
| `queued` | Job in queue, waiting for worker | `processing` |
| `processing` | Worker executing slicer | `completed`, `failed`, `timeout` |
| `completed` | Output artifacts stored | terminal |
| `failed` | Worker reported error | terminal (retryable) |
| `timeout` | Worker exceeded time limit | terminal (retryable) |

## Failure Handling

### API failures

- API is stateless; restart has no side effects
- In-flight SSE connections are dropped; client reconnects
- No job data is lost (stored in filesystem / queue)

### Worker failures

- Worker crashes mid-job: job remains in `processing` state
- Heartbeat timeout (if implemented) moves job back to `queued`
- Without heartbeat: operator manually requeues, or a reaper process detects stale jobs

### Slicer runtime failures

- PrusaSlicer CLI returns non-zero exit code
- Worker captures stderr and stores it in job metadata
- Job transitions to `failed` with error detail
- No retry: same input is likely to fail again (bad geometry, unsupported features)

### Queue failures

- Redis crash: jobs in memory are lost unless persistence is enabled (AOF/RDB)
- SQLite queue: durable by default, survives process restart
- Recommendation: use SQLite for single-node, Redis only if latency matters

## Retry Strategy

| Failure type | Retry? | Strategy |
|-------------|--------|----------|
| Slicer error (bad mesh) | No | Report to user |
| Slicer timeout | Once | Re-enqueue with same params |
| Worker crash | Yes | Job returns to queue via reaper |
| Storage write failure | No | Fail job, alert operator |
| Queue unavailable | N/A | API returns 503 |

Retry count is stored in job metadata. Max retries: 1 for timeouts, 0 for slicer errors.

## Logs and Artifacts

### Log locations

| Component | Log destination |
|-----------|----------------|
| Nginx | `/var/log/nginx/access.log`, `error.log` |
| API (uvicorn) | stdout (captured by supervisor) |
| Worker | stdout + per-job log in `jobs/{id}/worker.log` |
| Slicer | stderr captured by worker, stored in `jobs/{id}/slicer.log` |

### Artifact retention

- Job directories are retained for a configurable period (default: 7 days)
- A cleanup cron job deletes expired job directories
- Completed jobs: keep output artifacts
- Failed jobs: keep input + error logs for debugging

### Monitoring (minimal)

For single-node deployment, monitoring is lightweight:

- Process health: check if each process PID is alive
- Disk usage: alert if `./jobs/` exceeds threshold
- Queue depth: number of pending jobs
- API latency: Nginx access log analysis

## Machine Restart

When the Mac Studio restarts (power failure, OS update, manual reboot):

1. **Nginx**: auto-starts via launchd / brew services
2. **Redis**: auto-starts via launchd; recovers state from AOF/RDB if enabled
3. **API**: auto-starts via launchd or supervisor
4. **Workers**: auto-start via launchd or supervisor
5. **Jobs in `processing` state**: stale — reaper moves them back to `queued` or marks as `failed`
6. **SSE connections**: all dropped — clients reconnect and re-subscribe
7. **Storage**: intact (filesystem survives reboot)

### Startup order

```
1. Storage (filesystem) — always available
2. Queue (Redis / SQLite) — must be up before API and workers
3. API — can start accepting requests
4. Workers — start pulling from queue
5. Nginx — start routing traffic
```

Nginx should start last (or health-check upstream) to avoid routing to a not-yet-ready API.
