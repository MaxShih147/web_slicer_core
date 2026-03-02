# Deployment: Mac Studio (Single Node)

## Overview

All components run on a single Mac Studio (Apple Silicon). The machine acts as ingress, API server, queue broker, worker pool, and storage — simultaneously.

Despite being one machine, each component runs as a **separate process** with defined interfaces, identical to how they would run as separate containers in the cloud.

## Process Layout

```
Mac Studio
├── Nginx (or Traefik)          port 443 / 80
│   ├── /           → frontend static files
│   ├── /api/*      → FastAPI (port 8000)
│   └── /events/*   → FastAPI SSE (port 8000)
├── FastAPI API                  port 8000
├── Redis (or SQLite queue)      port 6379
├── Worker 1                     background process
├── Worker 2                     background process
└── Storage: ./jobs/             local filesystem
```

## Reverse Proxy Role

The reverse proxy is the **only process listening on external ports**. It provides:

- **Single-origin routing**: frontend, API, and SSE all served from one domain
- **TLS termination**: HTTPS at the edge, plain HTTP internally
- **Path-based routing**: clean URL structure without port numbers
- **Static file serving**: frontend SPA served directly by Nginx
- **Future**: rate limiting, request buffering, WebSocket upgrade

### Minimal Nginx config (conceptual)

```nginx
server {
    listen 443 ssl;
    server_name slicer.example.com;

    # Frontend SPA
    location / {
        root /var/www/frontend;
        try_files $uri $uri/ /index.html;
    }

    # API
    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        client_max_body_size 100M;  # STL upload limit
    }

    # SSE events
    location /events/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Connection '';
        proxy_http_version 1.1;
        chunked_transfer_encoding off;
        proxy_buffering off;
        proxy_cache off;
    }
}
```

## Process Separation

Even on a single machine, processes are isolated:

| Process | Managed by | Restart policy |
|---------|-----------|---------------|
| Nginx | launchd / systemd | always restart |
| FastAPI API | uvicorn (supervisor) | always restart |
| Redis | launchd / brew services | always restart |
| Worker(s) | supervisor / systemd | always restart |

Each process:
- Has its own PID and memory space
- Can be restarted independently
- Logs to its own file or stdout
- Can be replaced by a container without code changes

## Docker / Compose (Conceptual)

The single-node deployment can optionally use Docker Compose for process management:

```yaml
# Conceptual — not production-ready
services:
  ingress:
    image: nginx:alpine
    ports: ["443:443", "80:80"]
    volumes:
      - ./nginx.conf:/etc/nginx/conf.d/default.conf
      - ./frontend/dist:/var/www/frontend

  api:
    build: .
    command: uvicorn agent.main:app --host 0.0.0.0 --port 8000
    expose: ["8000"]
    volumes:
      - ./jobs:/app/jobs

  worker:
    build: .
    command: python -m agent.worker
    deploy:
      replicas: 2
    volumes:
      - ./jobs:/app/jobs
      - /path/to/prusa-slicer:/opt/prusa-slicer

  redis:
    image: redis:alpine
    expose: ["6379"]
```

### Why Docker is optional, not required

- Mac Studio has native Python, Nginx, Redis available via Homebrew
- Docker on macOS has virtualization overhead (Linux VM)
- For a single partner preview, bare-metal processes are simpler
- Docker Compose is useful as a **migration rehearsal** — same topology, containerized

## Storage Layout

```
./jobs/
├── {job_id}/
│   ├── input/
│   │   └── model.stl
│   ├── output/
│   │   ├── model.sl1
│   │   ├── model_hollow.stl
│   │   └── model_supported.stl
│   └── meta.json          # job metadata, status, timestamps
```

This layout maps directly to an S3 bucket structure:

```
s3://slicer-jobs/{job_id}/input/model.stl
s3://slicer-jobs/{job_id}/output/model.sl1
```

## Network Considerations

- All inter-process communication is over `127.0.0.1` (loopback)
- No external network dependency except for the client connection
- Redis (if used) listens only on localhost
- API listens only on localhost; Nginx handles external traffic
