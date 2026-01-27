# web_slicer_core

Web-based SLA slicing application powered by PrusaSlicer CLI (headless). Features a React frontend with 3D preview, configurable slicing parameters, and support mesh visualization.

## Features

- **SLA Slicing**: Slice STL models into layer images using PrusaSlicer engine
- **3D Preview**: Interactive Three.js viewer with orbit controls (Z-up coordinate system)
- **Support Generation**: Auto-generate supports with configurable parameters
- **Support Mesh Export**: Download generated supports as STL for external use
- **Hollow Interior Generation**: Generate hollow interior mesh for visualization (NEW)
- **Configurable Parameters**: Layer height, exposure times, support settings, pad options, hollowing
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

Frontend runs at `http://localhost:5174`

### 4. Web Interfaces

| Interface | URL | Description |
|-----------|-----|-------------|
| **React UI** | http://localhost:5174 | Main frontend - slicing, preview, supports, hollow |
| **Boolean Test** | http://localhost:5179/test/boolean | Experimental boolean operations test page |
| **API Docs** | http://localhost:5179/docs | Swagger UI for API exploration |

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
| `hollowing_enable` | Enable hollowing | on/off | off |
| `hollowing_min_thickness` | Wall thickness | 0.5-10 mm | 3.0 mm |
| `hollowing_quality` | Voxel quality (higher = finer) | 0.1-1.0 | 0.5 |
| `hollowing_closing_distance` | Smoothing distance | 0-10 mm | 2.0 mm |

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

### Get Support Mesh STL (includes pad)

```bash
curl http://127.0.0.1:5179/api/jobs/{job_id}/support.stl --output support.stl
```

Returns combined mesh of supports and pad (if enabled). Only available when `has_support_mesh: true` in job status.

### Generate Hollow Interior (v2 API)

```bash
# 1. Create job with hollow config
curl -X POST http://127.0.0.1:5179/api/v2/slices \
  -H "Content-Type: application/json" \
  -d '{"config": {"hollowing_enable": true, "hollowing_min_thickness": 2.0}}'

# 2. Upload model
curl -X POST http://127.0.0.1:5179/api/v2/slices/{job_id}/upload \
  -F "file=@model.stl"

# 3. Generate hollow interior
curl -X POST http://127.0.0.1:5179/api/v2/slices/{job_id}/generate-hollow

# 4. Poll status until completed
curl http://127.0.0.1:5179/api/v2/slices/{job_id}
# Response: {"data": {"status": "completed", "hasHollowMesh": true}}

# 5. Download hollow mesh
curl http://127.0.0.1:5179/api/jobs/{job_id}/hollow.stl --output hollow.stl
```

### Get Hollow Mesh STL

```bash
curl http://127.0.0.1:5179/api/jobs/{job_id}/hollow.stl --output hollow.stl
```

Returns the hollow interior mesh. Only available when `has_hollow_mesh: true` in job status.

## Architecture

The backend supports multiple frontends through versioned API endpoints:

```
┌─────────────────────┐     ┌─────────────────────┐
│   DS-Online (Vue)   │     │  web_slicer_core    │
│   Dental Slicer UI  │     │  (React) Basic UI   │
│   :5173             │     │  :5174              │
└──────────┬──────────┘     └──────────┬──────────┘
           │                           │
           │  /api/v2/slices           │  /api/jobs
           │                           │
           ▼                           ▼
┌─────────────────────────────────────────────────┐
│            FastAPI Backend (:5179)              │
│  ┌─────────────────┐   ┌─────────────────────┐  │
│  │ /api/v2/slices  │   │ /api/jobs (v1)      │  │
│  │ DS-Online API   │   │ Original API        │  │
│  └────────┬────────┘   └──────────┬──────────┘  │
│           └────────────┬──────────┘             │
│                        ▼                        │
│           ┌─────────────────────┐               │
│           │    Job Manager      │               │
│           │  (shared service)   │               │
│           └──────────┬──────────┘               │
│                      ▼                          │
│           ┌─────────────────────┐               │
│           │   PrusaSlicer CLI   │               │
│           │   (Fork + support   │               │
│           │    mesh export)     │               │
│           └─────────────────────┘               │
└─────────────────────────────────────────────────┘
                       │
                       ▼
              ┌─────────────────┐
              │  Job Storage    │
              │  agent/jobs/    │
              └─────────────────┘
```

### Layer Abstraction

```
┌─────────────────────────────────────────────────────────────┐
│  UI Layer                                                   │
│  - DS-Online (Vue + Three.js + PrimeVue)                   │
│  - web_slicer_core (React + Three.js)                      │
├─────────────────────────────────────────────────────────────┤
│  API Layer (FastAPI)                                        │
│  - /api/jobs/* (v1 - original)                             │
│  - /api/v2/slices/* (v2 - DS-Online compatible)            │
├─────────────────────────────────────────────────────────────┤
│  Service Layer                                              │
│  - Job Manager (create, status, polling)                   │
│  - Config Manager (INI generation, validation)             │
├─────────────────────────────────────────────────────────────┤
│  Engine Layer                                               │
│  - PrusaSlicer CLI Adapter                                 │
│  - Support mesh export (--export-support-stl)              │
│  - Hollow interior export (--export-hollow-stl)            │
└─────────────────────────────────────────────────────────────┘
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

This project uses a custom fork of PrusaSlicer (`github.com:MaxShih147/PrusaSlicer.git`) with additional CLI options:

### `--export-support-stl`

Exports the generated support and pad meshes as a combined STL file after SLA slicing.

```bash
prusa-slicer --export-sla --export-support-stl -o output.sl1 model.stl
# Creates: output.sl1 and model_support.stl
```

The exported STL includes:
- Support structures (if `supports_enable = true`)
- Pad/raft (if `pad_enable = true`)

**Implementation details:**
- Added in `src/libslic3r/PrintConfig.cpp` (CLI option definition)
- Export logic in `src/CLI/ProcessActions.cpp`
- Uses `SLAPrintObject::support_mesh()` and `SLAPrintObject::pad_mesh()`

### `--export-hollow-stl`

Generates and exports the hollow interior mesh as STL. This is a standalone operation that doesn't require full slicing.

```bash
prusa-slicer --export-hollow-stl \
  --hollowing-min-thickness 2 \
  --hollowing-quality 0.5 \
  --hollowing-closing-distance 1 \
  -o interior.stl model.stl
# Creates: interior.stl (hollow interior mesh only)
```

**Parameters:**
- `--hollowing-min-thickness`: Wall thickness in mm (default: 2.0)
- `--hollowing-quality`: Voxel quality 0.1-1.0 (default: 0.5, higher = finer detail)
- `--hollowing-closing-distance`: Morphological closing distance in mm (default: 0.5)

**Important notes:**
- Wall thickness must be appropriate for model size (small models need thinner walls)
- The interior mesh has flipped normals for proper visualization
- Uses OpenVDB for voxelization and interior generation

**Implementation details:**
- CLI option defined in `src/libslic3r/PrintConfig.cpp`
- Handler in `src/CLI/ProcessActions.cpp`
- Uses `sla::generate_interior()` from `libslic3r/SLA/Hollowing.hpp`
- Normals flipped via `sla::swap_normals()` for visualization

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

---

## Feature Status & Roadmap

### ✅ Implemented Features

| Feature | CLI | Backend API | Frontend | Notes |
|---------|-----|-------------|----------|-------|
| SLA Slicing | ✅ `--export-sla` | ✅ `/execute` | ✅ | Full layer export |
| Support Generation | ✅ `--export-support-stl` | ✅ `/generate-supports` | ✅ | Includes pad mesh |
| Hollow Interior | ✅ `--export-hollow-stl` | ✅ `/generate-hollow` | ✅ | Interior mesh only |
| Layer Preview | ✅ | ✅ `/layers/{idx}.png` | ✅ | PNG extraction from SL1 |
| 3D Visualization | - | - | ✅ | Three.js with Z-up |

### 🚧 TODO / Future Work

#### High Priority
- [ ] **Drain Holes**: Add `--export-drill-stl` for drain hole generation
  - PrusaSlicer has `DrainHole` in `Hollowing.hpp`
  - Needs position input (click-to-place in UI)
- [ ] **Combined Hollow + Supports**: Single operation for hollowed model with internal supports
- [ ] **Hollow Preview Before Apply**: Show preview without generating full mesh

#### Medium Priority
- [ ] **Auto-Orient**: Expose PrusaSlicer's auto-orient via CLI
- [ ] **Support Editing**: Manual support point placement/removal
- [ ] **Infill Patterns**: Support for partial hollowing with infill
- [ ] **Multi-Model Support**: Handle multiple models in single job

#### Low Priority / Research
- [ ] **WebAssembly Port**: Run hollowing in browser (OpenVDB is complex)
- [ ] **Streaming Layers**: WebSocket for real-time layer streaming during slice
- [ ] **Diff Slicing**: Only re-slice changed regions

### ⚠️ Known Issues & Limitations

1. **Wall Thickness vs Model Size**
   - Small models need thinner walls (0.5-1mm)
   - Large models can use thicker walls (2-3mm)
   - Error "interior mesh is empty" means wall is too thick for model

2. **Hollow Mesh Positioning**
   - Frontend must apply same transform as original model
   - Currently copies position/rotation/scale from selected model
   - If model is transformed after hollow generation, mesh will be misaligned

3. **Memory Usage**
   - Hollowing uses OpenVDB which can be memory-intensive
   - High quality setting (1.0) on large models may use several GB RAM

4. **No Incremental Updates**
   - Changing hollow parameters requires full regeneration
   - No caching of intermediate voxel grids

5. **Single Model Per Job**
   - v2 API currently only processes first uploaded model
   - Multi-model support requires job structure changes

### 🏗️ Architecture Decisions

#### Why Export Interior Mesh Only?

**Decision**: Export only the hollow interior mesh, not a combined hollowed model.

**Rationale**:
- Frontend already has the original mesh
- Smaller data transfer (interior only vs full hollowed model)
- Can toggle hollow preview on/off without re-fetching
- Allows different materials/transparency for interior visualization
- PrusaSlicer stores interior separately in `sla::Interior`

**Trade-off**: Frontend must combine meshes; can't directly print the exported hollow mesh.

#### Why Flip Normals in CLI?

**Decision**: Flip normals in PrusaSlicer CLI before export (`sla::swap_normals()`).

**Rationale**:
- Interior mesh faces inward by default (for boolean subtraction)
- Visualization requires outward-facing normals
- Better to flip once at export than in every frontend
- Consistent with how support mesh is exported

#### Why Separate `/generate-hollow` Endpoint?

**Decision**: Hollow generation is a separate endpoint, not part of `/execute`.

**Rationale**:
- Hollow preview doesn't need full slicing
- Faster feedback loop for parameter tuning
- Can hollow without committing to slice
- Matches `/generate-supports` pattern
- Future: could cache hollow result for final slice

#### Job State Model

```
                    ┌─────────────┐
                    │   created   │  (in-memory, _pending_jobs)
                    └──────┬──────┘
                           │ upload model
                           ▼
                    ┌─────────────┐
         ┌─────────│   pending   │─────────┐
         │         └─────────────┘         │
         │ generate-supports    generate-hollow
         ▼                                 ▼
   ┌───────────┐                    ┌───────────┐
   │ processing│                    │ processing│
   └─────┬─────┘                    └─────┬─────┘
         │                                │
         ▼                                ▼
   ┌───────────┐                    ┌───────────┐
   │ completed │                    │ completed │
   │ +supports │                    │ +hollow   │
   └───────────┘                    └───────────┘
         │
         │ execute (full slice)
         ▼
   ┌───────────┐
   │ completed │
   │ +layers   │
   └───────────┘
```

---

## Future Directions & Business Paths (Internal Checklist)

> This section is a self-reminder for future product and business evolution.
> Not all items are meant to be pursued at once.

### A. Slicing-as-a-Service (SaaS / API-first)

**Idea**: Expose the slicer as a headless, scalable service rather than a desktop tool.

**Potential value**:
- Remove slicer maintenance burden for customers
- Enable cloud / automation / AI pipelines
- Natural fit for batch processing and scale

**Target users**:
- Manufacturing platforms
- Dental labs
- Cloud manufacturing services
- AI-generated model pipelines

**Indicators to revisit**:
- [ ] Stable job-based API
- [ ] Clear cost metrics (per job / per GB / per minute)
- [ ] Demand for non-interactive slicing

### B. Process Intelligence Layer (High-margin differentiation)

**Idea**: Sell decision-making instead of slicing itself.

**Examples**:
- Support quality evaluation
- Failure risk estimation
- Auto parameter / support suggestions
- Comparative analysis between slicing strategies

**Why this matters**:
- Support = process know-how, not just geometry
- Enables AI-driven optimization
- Hard to copy, high long-term value

**Indicators to revisit**:
- [ ] Support data is structured and comparable
- [ ] Repeated slicing failures observed in users
- [ ] Need for "why did this fail?" answers

### C. OEM / Embedded Slicer Licensing

**Idea**: Provide the slicer as an embedded or white-label component for hardware vendors.

**Potential value**:
- Recurring licensing revenue
- Strong fit with device-centric workflows
- Avoids consumer software competition

**Target customers**:
- 3D printer manufacturers
- Specialized hardware startups
- Non-general-purpose printing systems

**Indicators to revisit**:
- [ ] Requests for custom workflow / UI
- [ ] Need for tight hardware-software integration
- [ ] Vendor reluctance to maintain slicer teams

### D. Data, Traceability & Compliance Layer

**Idea**: Turn slicing outputs and parameters into auditable, traceable production records.

**Examples**:
- Layer-level archives
- Parameter history
- Reproducibility reports
- Compliance-ready logs

**Why it's valuable**:
- Required in medical / dental / industrial contexts
- Seen as a cost of doing business, not a feature
- High willingness to pay

**Indicators to revisit**:
- [ ] Regulated customers (medical, dental, ISO)
- [ ] Need for print reproducibility
- [ ] QA / audit requirements

### Strategic Notes

- This project is not just a slicer; it is a **platform around slicing**
- Engine choice is a means, not the product
- Supports, layers, and parameters are **data assets**, not UI details
- Monetization should prioritize **process value**, not feature count

---

## License

PrusaSlicer is licensed under AGPLv3. See the fork repository for details.
