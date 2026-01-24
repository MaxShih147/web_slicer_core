# web_slicer_core

Web-based SLA slicing application powered by PrusaSlicer CLI (headless). Features a React frontend with 3D preview, configurable slicing parameters, and support mesh visualization.

## Features

- **SLA Slicing**: Slice STL models into layer images using PrusaSlicer engine
- **3D Preview**: Interactive Three.js viewer with orbit controls (Z-up coordinate system)
- **Support Generation**: Auto-generate supports with configurable parameters
- **Support Mesh Export**: Download generated supports as STL for external use
- **Configurable Parameters**: Layer height, exposure times, support settings, pad options
- **Layer Navigation**: Browse through sliced layers with slider control

## Prerequisites

- macOS (tested on macOS 15.x)
- Python 3.9+
- Node.js 18+
- PrusaSlicer Fork (with `--export-support-stl` feature)

## Quick Start

### 1. Build PrusaSlicer Fork

The project uses a custom PrusaSlicer fork with support mesh STL export capability.

```bash
# Build the fork (includes --export-support-stl feature)
./scripts/build_prusaslicer_fork_macos.sh
```

This builds the binary at `third_party/prusaslicer_build/src/prusa-slicer`.

### 2. Start the Backend

```bash
# Set the path to the forked binary
export PRUSA_SLICER_BIN=$(pwd)/third_party/prusaslicer_build/src/prusa-slicer

# Start the agent
./scripts/run_agent.sh
```

Backend runs at `http://127.0.0.1:5179`

### 3. Start the Frontend

```bash
cd web
npm install
npm run dev
```

Frontend runs at `http://localhost:5173`

### 4. Open Browser

Navigate to `http://localhost:5173`

## Usage

1. **Select STL File**: Click file input to select a model - 3D preview appears immediately
2. **Configure Settings** (optional): Expand "Slicing Config" to adjust parameters
   - Layer height: 0.025mm, 0.05mm, or 0.1mm
   - Exposure time: 1-30 seconds
   - Initial exposure: 5-60 seconds
   - Enable/disable supports with detailed settings
   - Enable/disable pad
3. **Slice**: Click "Slice" button to start processing
4. **View Results**:
   - **3D Preview**: Model (blue) with support mesh overlay (red) if supports enabled
   - **Layer View**: Navigate through individual slice images
5. **Download Support STL**: When supports are generated, download button appears

## SLA Configuration Parameters

| Parameter | Description | Range | Default |
|-----------|-------------|-------|---------|
| `layer_height` | Height of each slice layer | 0.025, 0.05, 0.1 mm | 0.05 mm |
| `exposure_time` | UV exposure per layer | 1-30 s | 10 s |
| `initial_exposure_time` | First layers exposure | 5-60 s | 15 s |
| `supports_enable` | Generate support structures | on/off | off |
| `support_head_front_diameter` | Support tip diameter | 0.2-1.0 mm | 0.4 mm |
| `support_head_penetration` | Tip penetration depth | 0.1-0.5 mm | 0.2 mm |
| `support_pillar_diameter` | Support pillar width | 0.5-2.0 mm | 1.0 mm |
| `support_points_density_relative` | Support density | 50-200% | 100% |
| `pad_enable` | Generate base pad | on/off | off |

## API Reference

### Health Check

```bash
curl http://127.0.0.1:5179/
```

### Create Slicing Job

```bash
# Basic (default config)
curl -X POST http://127.0.0.1:5179/api/jobs \
  -F "file=@model.stl"

# With custom config
curl -X POST http://127.0.0.1:5179/api/jobs \
  -F "file=@model.stl" \
  -F 'config={"layer_height":0.05,"supports_enable":true,"exposure_time":12}'
```

Response:
```json
{"job_id": "a1b2c3d4", "status": "pending"}
```

### Get Job Status

```bash
curl http://127.0.0.1:5179/api/jobs/{job_id}
```

Response:
```json
{
  "job_id": "a1b2c3d4",
  "status": "completed",
  "layer_count": 750,
  "error": null,
  "has_support_mesh": true
}
```

### Get Layer Image

```bash
curl http://127.0.0.1:5179/api/jobs/{job_id}/layers/50.png --output layer50.png
```

### Get Original Model STL

```bash
curl http://127.0.0.1:5179/api/jobs/{job_id}/model.stl --output model.stl
```

### Get Support Mesh STL

```bash
curl http://127.0.0.1:5179/api/jobs/{job_id}/support.stl --output support.stl
```

Only available when `has_support_mesh: true` in job status.

## Architecture

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   React + Vite  │────▶│  FastAPI Agent  │────▶│  PrusaSlicer    │
│   (Frontend)    │     │  (Backend)      │     │  CLI (Fork)     │
│   :5173         │     │  :5179          │     │                 │
└─────────────────┘     └─────────────────┘     └─────────────────┘
        │                       │
        │                       ▼
        │               ┌─────────────────┐
        │               │  Job Storage    │
        │               │  agent/jobs/    │
        │               └─────────────────┘
        │
        ▼
┌─────────────────┐
│  Three.js       │
│  3D Viewer      │
└─────────────────┘
```

## Directory Structure

```
web_slicer_core/
├── agent/
│   ├── main.py              # FastAPI application & endpoints
│   ├── config.py            # Configuration constants
│   ├── models.py            # Pydantic models (SLAConfig, JobStatus)
│   ├── jobs.py              # Job management & slicing logic
│   └── jobs/                # Job data storage (gitignored)
│       └── {job_id}/
│           ├── input/model.stl
│           ├── output/
│           │   ├── model.sl1
│           │   └── model_support.stl  # If supports enabled
│           ├── layers/{0..N}.png
│           ├── config.ini
│           └── status.json
├── web/
│   ├── src/
│   │   ├── App.tsx          # Main application component
│   │   ├── App.css          # Styles
│   │   ├── STLViewer.tsx    # Three.js 3D viewer component
│   │   └── main.tsx         # Entry point
│   ├── package.json
│   └── vite.config.ts
├── third_party/
│   ├── prusaslicer_fork/    # PrusaSlicer fork (submodule)
│   └── prusaslicer_build/   # Build output (gitignored)
├── scripts/
│   ├── run_agent.sh
│   └── build_prusaslicer_fork_macos.sh
├── requirements.txt
└── README.md
```

## PrusaSlicer Fork

This project uses a custom fork of PrusaSlicer (`github.com:MaxShih147/PrusaSlicer.git`) with an additional CLI option:

### `--export-support-stl`

Exports the generated support mesh as a separate STL file after SLA slicing.

```bash
prusa-slicer --export-sla --export-support-stl -o output.sl1 model.stl
# Creates: output.sl1 and model_support.stl
```

**Implementation details:**
- Added in `src/libslic3r/PrintConfig.cpp` (CLI option definition)
- Export logic in `src/CLI/ProcessActions.cpp`
- Uses `SLAPrintObject::support_mesh()` to get the mesh data

## Development

### Backend Development

```bash
# Install dependencies
pip install -r requirements.txt

# Run with auto-reload
cd agent && uvicorn main:app --reload --port 5179
```

### Frontend Development

```bash
cd web
npm install
npm run dev  # Vite dev server with HMR
```

### Building PrusaSlicer Fork

If you need to modify the PrusaSlicer fork:

1. Edit source in `third_party/prusaslicer_fork/`
2. Rebuild:
   ```bash
   cd third_party/prusaslicer_build
   make -j8
   ```
3. Test the binary:
   ```bash
   ./src/prusa-slicer --help | grep export-support
   ```

## Troubleshooting

### "CLI not available"

Ensure `PRUSA_SLICER_BIN` is set correctly:
```bash
export PRUSA_SLICER_BIN=$(pwd)/third_party/prusaslicer_build/src/prusa-slicer
$PRUSA_SLICER_BIN --version
```

### CORS errors in browser

The backend includes CORS middleware for `localhost:5173`. If using a different port, update `agent/main.py`.

### Support mesh not appearing

1. Ensure "Enable Supports" is checked in config panel
2. Check backend logs for "Support mesh exported" message
3. Verify `has_support_mesh: true` in job status response

## License

PrusaSlicer is licensed under AGPLv3. See the fork repository for details.
