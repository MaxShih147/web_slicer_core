# web_slicer_core

Local SLA slicing agent based on PrusaSlicer CLI (headless).

## Prerequisites

- macOS (tested on macOS 15.x)
- Python 3.9+
- PrusaSlicer CLI built (see below)

## Quick Start

### 1. Build PrusaSlicer CLI (if not already built)

```bash
# Build dependencies (first time only)
cd upstream_repo/deps
mkdir -p build && cd build
/path/to/cmake-3.27.9.app/Contents/bin/cmake .. \
  -DCMAKE_BUILD_TYPE=Release \
  -DPrusaSlicer_deps_PACKAGE_EXCLUDES="wxWidgets"
make -j8

# Build main project (headless/CLI only)
cd /path/to/web_slicer_core
mkdir -p build && cd build
/path/to/cmake-3.27.9.app/Contents/bin/cmake ../upstream_repo \
  -DCMAKE_BUILD_TYPE=Release \
  -DSLIC3R_GUI=OFF \
  -DSLIC3R_BUILD_TESTS=OFF \
  -DCMAKE_PREFIX_PATH="$PWD/../upstream_repo/deps/build/destdir/usr/local" \
  -DCMAKE_EXE_LINKER_FLAGS="-framework Foundation"
make -j8
```

### 2. Run the Agent

```bash
./scripts/run_agent.sh
```

The agent will start on `http://127.0.0.1:5179`.

## API Reference

### Health Check

```bash
curl http://127.0.0.1:5179/
```

Response:
```json
{"service": "web_slicer_core", "status": "running", "cli_available": true}
```

### Create Slicing Job

```bash
curl -X POST http://127.0.0.1:5179/api/jobs \
  -F "file=@/path/to/model.stl"
```

Response:
```json
{"job_id": "a1b2c3d4", "status": "pending"}
```

### Get Job Status

```bash
curl http://127.0.0.1:5179/api/jobs/{job_id}
```

Response (processing):
```json
{"job_id": "a1b2c3d4", "status": "processing", "layer_count": null, "error": null}
```

Response (completed):
```json
{"job_id": "a1b2c3d4", "status": "completed", "layer_count": 123, "error": null}
```

Response (failed):
```json
{"job_id": "a1b2c3d4", "status": "failed", "layer_count": null, "error": "Exit code 1: ..."}
```

### Get Layer Image

```bash
curl http://127.0.0.1:5179/api/jobs/{job_id}/layers/50.png --output layer50.png
```

Returns `image/png` or 404 if layer doesn't exist.

## Example Workflow

```bash
# 1. Start the agent (in terminal 1)
./scripts/run_agent.sh

# 2. Submit a job (in terminal 2)
JOB=$(curl -s -X POST http://127.0.0.1:5179/api/jobs \
  -F "file=@workspace/input/01.stl" | jq -r '.job_id')
echo "Job ID: $JOB"

# 3. Poll for completion
while true; do
  STATUS=$(curl -s http://127.0.0.1:5179/api/jobs/$JOB | jq -r '.status')
  echo "Status: $STATUS"
  if [ "$STATUS" = "completed" ] || [ "$STATUS" = "failed" ]; then
    break
  fi
  sleep 1
done

# 4. Get layer count
curl -s http://127.0.0.1:5179/api/jobs/$JOB | jq

# 5. Download a layer
curl http://127.0.0.1:5179/api/jobs/$JOB/layers/50.png --output layer50.png
open layer50.png
```

## Directory Structure

```
web_slicer_core/
├── agent/
│   ├── __init__.py
│   ├── main.py         # FastAPI application
│   ├── config.py       # Configuration
│   ├── models.py       # Pydantic models
│   ├── jobs.py         # Job management
│   └── jobs/           # Job data (gitignored)
│       └── {job_id}/
│           ├── input/model.stl
│           ├── output/model.sl1
│           ├── layers/{0..N}.png
│           ├── status.json
│           └── stderr.log
├── build/              # PrusaSlicer build (gitignored)
├── upstream_repo/      # PrusaSlicer submodule
├── scripts/
│   └── run_agent.sh
├── requirements.txt
└── README.md
```

## License

PrusaSlicer is licensed under AGPLv3. See `upstream_repo/LICENSE` for details.
