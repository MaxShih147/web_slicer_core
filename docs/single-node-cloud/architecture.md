# Single-Node Cloud Architecture

## What is "Single-Node Cloud"?

A single-node cloud is an architecture where one physical machine (Mac Studio) runs all components of a cloud-native system. The key constraint is: **the architecture must be identical to what would run on real cloud infrastructure**, with only the deployment target differing.

This means:

- Components communicate through well-defined interfaces, not shared memory
- Storage is accessed through an abstraction layer, not direct filesystem calls
- Workers are separate processes, not function calls within the API
- Ingress is handled by a reverse proxy, not by the application itself

The goal is zero architectural refactoring when migrating to cloud. Only deployment configuration changes.

## Component Breakdown

| Component | Role | Single-Node Implementation | Cloud Equivalent |
|-----------|------|---------------------------|-----------------|
| **Ingress** | Route traffic, TLS termination | Nginx or Traefik on localhost | AWS ALB / Cloudflare |
| **API** | Job CRUD, validation, metadata | FastAPI process | ECS / Cloud Run |
| **Queue** | Job dispatch, ordering | Redis / SQLite queue | SQS / Cloud Tasks |
| **Worker** | Execute slicing jobs | Separate process(es) | ECS tasks / Lambda |
| **Slicer Runtime** | PrusaSlicer CLI binary | Local binary at known path | Container with binary |
| **Storage** | Job artifacts (STL, gcode) | Local filesystem (`./jobs/`) | S3 / GCS |

## Data Flow

### Slicing Job Lifecycle

```mermaid
sequenceDiagram
    participant C as Client (Browser)
    participant I as Ingress (Nginx)
    participant A as API (FastAPI)
    participant Q as Queue
    participant W as Worker
    participant S as Storage
    participant SR as Slicer Runtime

    C->>I: POST /api/v2/jobs (upload STL)
    I->>A: forward request
    A->>S: store input STL
    A->>Q: enqueue job
    A-->>C: 202 Accepted { job_id }

    C->>I: GET /events/jobs/{id}
    I->>A: forward SSE connection

    W->>Q: poll / dequeue job
    W->>S: fetch input STL
    W->>SR: invoke PrusaSlicer CLI
    SR-->>W: output artifacts
    W->>S: store output artifacts
    W->>A: update job status

    A-->>C: SSE: { status: "processing", progress: 40 }
    A-->>C: SSE: { status: "completed" }

    C->>I: GET /api/v2/jobs/{id}/result
    I->>A: forward request
    A->>S: fetch output
    A-->>C: binary artifact
```

### Component Topology (Single Node)

```mermaid
graph LR
    subgraph "Mac Studio (single node)"
        subgraph "Ingress"
            NG[Nginx / Traefik]
        end

        subgraph "Application"
            API[FastAPI API]
            SSE[SSE endpoint]
        end

        subgraph "Queue"
            Q[Redis / SQLite]
        end

        subgraph "Workers"
            W1[Worker 1]
            W2[Worker 2]
        end

        subgraph "Runtime"
            PS[PrusaSlicer CLI]
        end

        subgraph "Storage"
            FS[Local Filesystem]
        end
    end

    Client -->|HTTPS| NG
    NG -->|/api/*| API
    NG -->|/events/*| SSE
    NG -->|/| StaticFiles[Frontend SPA]

    API --> Q
    W1 --> Q
    W2 --> Q
    W1 --> PS
    W2 --> PS
    W1 --> FS
    W2 --> FS
    API --> FS
```

## Why This Architecture

### Problem

The current system has the API process directly executing slicing operations. This creates:

- **Blocking**: long-running slicing blocks API requests
- **Coupling**: API code is intertwined with slicer invocation
- **No horizontal scaling**: cannot add more slicing capacity without duplicating everything
- **Hard migration**: moving to cloud would require rewriting the application

### Solution

Separate concerns into discrete components with clear boundaries:

1. **API is stateless and fast** - accepts jobs, returns metadata, streams events
2. **Workers are disposable** - crash one, start another, no state lost
3. **Queue decouples** - API and workers don't know about each other
4. **Storage is abstract** - swap LocalFS for S3 with one config change

### Trade-offs

| Benefit | Cost |
|---------|------|
| Cloud-ready architecture | More processes to manage on one machine |
| Worker isolation | Inter-process communication overhead |
| Independent scaling | Queue infrastructure dependency |
| Clean AGPL boundary | Slightly more complex deployment |

## Cloud Migration Path

When moving from single node to cloud:

| Change | What to do |
|--------|-----------|
| Ingress | Replace Nginx with cloud load balancer |
| API | Deploy as container (ECS / Cloud Run) |
| Queue | Replace local queue with SQS / Cloud Tasks |
| Workers | Deploy as container tasks, auto-scale |
| Storage | Switch storage backend from LocalFS to S3 |
| Slicer | Bundle in worker container image |

No application code changes required. Only configuration and deployment descriptors.
