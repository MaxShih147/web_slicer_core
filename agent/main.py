"""FastAPI application for the web_slicer_core agent."""

import asyncio
import json
import os
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse

from .config import HOST, PORT, PRUSA_SLICER_CLI
from .models import JobCreateResponse, JobStatus, JobStatusResponse, SLAConfig
from .jobs import (
    create_job,
    create_job_id,
    get_job_dir,
    get_input_model_path,
    get_layer_path,
    get_support_mesh_path,
    get_hollow_mesh_path,
    get_drain_holes_path,
    get_cut_mesh_path,
    get_cut_upper_mesh_path,
    get_cut_lower_mesh_path,
    get_boolean_mesh_path,
    job_exists,
    read_job_status,
    run_slicing,
)
from .api_v2 import router as v2_router

app = FastAPI(
    title="web_slicer_core Agent",
    description="Local agent for SLA slicing using PrusaSlicer CLI. Supports multiple frontends via versioned APIs.",
    version="0.2.0",
)

# CORS configuration:
# - local development ports
# - hosted UI origin for local-agent bridge
# - optional comma-separated overrides via CORS_ALLOWED_ORIGINS env var
_cors_origins = {
    "https://dentalslice.onrender.com",
    "http://localhost:5173",   # DS-Online (default Vite port)
    "http://127.0.0.1:5173",
    "http://localhost:5174",   # web_slicer_core React UI (alternate port)
    "http://127.0.0.1:5174",
    "http://localhost:5175",
    "http://127.0.0.1:5175",
    "http://localhost:5176",
    "http://127.0.0.1:5176",
    "http://localhost:5177",
    "http://127.0.0.1:5177",
    "http://localhost:5178",   # DS-Online (when other ports in use)
    "http://127.0.0.1:5178",
    "http://localhost:3000",   # Common dev port
    "http://127.0.0.1:3000",
}
_extra_cors_origins = os.getenv("CORS_ALLOWED_ORIGINS", "")
if _extra_cors_origins.strip():
    _cors_origins.update(
        origin.strip()
        for origin in _extra_cors_origins.split(",")
        if origin.strip()
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=sorted(_cors_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global exception handler to catch unhandled errors
from fastapi.responses import JSONResponse
from starlette.requests import Request
import traceback as _tb

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    err = _tb.format_exc()
    with open("/tmp/boolean_error.log", "a") as f:
        f.write(f"\n=== GLOBAL {request.url.path} ===\n{err}\n")
    return JSONResponse(status_code=500, content={"detail": str(exc)})

# Include v2 API router (DS-Online compatible)
app.include_router(v2_router)


@app.get("/")
async def root():
    """Health check endpoint."""
    return {
        "service": "web_slicer_core",
        "status": "running",
        "cli_available": PRUSA_SLICER_CLI.exists(),
    }


@app.get("/test/boolean", response_class=HTMLResponse)
async def boolean_test_page():
    """Test page for boolean operations."""
    return """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Boolean Operations Test</title>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/loaders/STLLoader.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/exporters/STLExporter.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/controls/OrbitControls.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/controls/TransformControls.js"></script>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #1a1a2e; color: #eee; }
        .container { display: flex; height: 100vh; }
        .panel { width: 350px; padding: 20px; background: #16213e; overflow-y: auto; }
        .viewer { flex: 1; position: relative; }
        h1 { font-size: 1.4em; margin-bottom: 10px; color: #4ecca3; }
        h2 { font-size: 1.1em; margin: 15px 0 10px; color: #4ecca3; }
        .hint { font-size: 0.85em; color: #888; margin-bottom: 15px; }
        .file-input { margin: 10px 0; }
        .file-input label { display: block; margin-bottom: 5px; font-size: 0.9em; color: #aaa; }
        .file-input input { width: 100%; padding: 8px; border: 1px solid #333; border-radius: 4px; background: #0f0f23; color: #eee; }
        .operation-select { margin: 15px 0; }
        .operation-select label { display: block; margin-bottom: 5px; font-size: 0.9em; color: #aaa; }
        .operation-select select { width: 100%; padding: 10px; border: 1px solid #333; border-radius: 4px; background: #0f0f23; color: #eee; font-size: 1em; }
        button { width: 100%; padding: 12px; margin: 5px 0; border: none; border-radius: 4px; font-size: 1em; cursor: pointer; transition: all 0.2s; }
        .btn-primary { background: #4ecca3; color: #1a1a2e; }
        .btn-primary:hover { background: #3db892; }
        .btn-primary:disabled { background: #333; color: #666; cursor: not-allowed; }
        .btn-secondary { background: #333; color: #eee; }
        .btn-secondary:hover { background: #444; }
        .btn-small { width: 48%; display: inline-block; padding: 8px; font-size: 0.9em; }
        .btn-active { background: #4ecca3; color: #1a1a2e; }
        .status { margin: 15px 0; padding: 12px; border-radius: 4px; font-size: 0.9em; }
        .status.info { background: #1e3a5f; border: 1px solid #2d5a87; }
        .status.success { background: #1e5f3a; border: 1px solid #2d8757; }
        .status.error { background: #5f1e1e; border: 1px solid #872d2d; }
        .transform-controls { margin: 10px 0; }
        .position-inputs { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 5px; margin: 10px 0; }
        .position-inputs label { font-size: 0.8em; color: #888; }
        .position-inputs input { width: 100%; padding: 6px; border: 1px solid #333; border-radius: 4px; background: #0f0f23; color: #eee; font-size: 0.9em; }
        .preview-info { margin-top: 15px; padding: 15px; background: #0f0f23; border-radius: 4px; font-size: 0.85em; }
        .preview-info h3 { color: #4ecca3; margin-bottom: 10px; font-size: 1em; }
        .preview-info p { margin: 5px 0; color: #aaa; }
        .preview-info span { color: #eee; }
        #canvas-container { width: 100%; height: 100%; }
        .keyboard-hint { position: absolute; bottom: 10px; left: 10px; background: rgba(0,0,0,0.7); padding: 10px 15px; border-radius: 4px; font-size: 0.8em; color: #aaa; }
        .keyboard-hint kbd { background: #333; padding: 2px 6px; border-radius: 3px; margin: 0 2px; }
    </style>
</head>
<body>
    <div class="container">
        <div class="panel">
            <h1>Boolean Operations Test</h1>
            <p class="hint">Click mesh to select, then drag to move. Use buttons to switch transform mode.</p>

            <div class="file-input">
                <label>Mesh A (Base) - Green</label>
                <input type="file" id="meshA" accept=".stl">
            </div>

            <div class="file-input">
                <label>Mesh B (Tool) - Red</label>
                <input type="file" id="meshB" accept=".stl">
            </div>

            <h2>Transform Selected Mesh</h2>
            <div class="transform-controls">
                <button class="btn-secondary btn-small btn-active" id="modeTranslate" onclick="setTransformMode('translate')">Move</button>
                <button class="btn-secondary btn-small" id="modeRotate" onclick="setTransformMode('rotate')">Rotate</button>
            </div>

            <div id="positionControls" style="display:none;">
                <label style="font-size:0.85em; color:#aaa;">Position (selected mesh)</label>
                <div class="position-inputs">
                    <div><label>X</label><input type="number" id="posX" step="1" onchange="updatePosition()"></div>
                    <div><label>Y</label><input type="number" id="posY" step="1" onchange="updatePosition()"></div>
                    <div><label>Z</label><input type="number" id="posZ" step="1" onchange="updatePosition()"></div>
                </div>
            </div>

            <h2>Boolean Operation</h2>
            <div class="operation-select">
                <select id="operation">
                    <option value="difference">Difference (A - B)</option>
                    <option value="union">Union (A + B)</option>
                    <option value="intersection">Intersection (A ∩ B)</option>
                </select>
            </div>

            <button id="executeBtn" class="btn-primary" disabled>Execute Boolean</button>

            <div id="status" class="status info">Upload two STL files to begin</div>

            <button id="downloadBtn" class="btn-secondary" style="display:none;">Download Result</button>

            <div id="previewInfo" class="preview-info" style="display:none;">
                <h3>Result Info</h3>
                <p>Faces: <span id="faceCount">-</span></p>
            </div>

            <h2>View</h2>
            <button class="btn-secondary btn-small" onclick="showMesh('a')">Mesh A</button>
            <button class="btn-secondary btn-small" onclick="showMesh('b')">Mesh B</button>
            <button class="btn-secondary btn-small" onclick="showMesh('result')">Result</button>
            <button class="btn-secondary btn-small" onclick="showMesh('all')">All</button>
        </div>

        <div class="viewer">
            <div id="canvas-container"></div>
            <div class="keyboard-hint">
                <kbd>W</kbd> Move | <kbd>E</kbd> Rotate | <kbd>Click</kbd> Select mesh
            </div>
        </div>
    </div>

    <script>
        let scene, camera, renderer, orbitControls, transformControls;
        let meshA, meshB, meshResult;
        let selectedMesh = null;
        let resultJobId = null;

        function init() {
            const container = document.getElementById('canvas-container');

            scene = new THREE.Scene();
            scene.background = new THREE.Color(0x1a1a2e);

            camera = new THREE.PerspectiveCamera(45, container.clientWidth / container.clientHeight, 0.1, 1000);
            camera.position.set(50, 50, 50);

            renderer = new THREE.WebGLRenderer({ antialias: true });
            renderer.setSize(container.clientWidth, container.clientHeight);
            container.appendChild(renderer.domElement);

            // Orbit controls
            orbitControls = new THREE.OrbitControls(camera, renderer.domElement);
            orbitControls.enableDamping = true;

            // Transform controls
            transformControls = new THREE.TransformControls(camera, renderer.domElement);
            transformControls.addEventListener('dragging-changed', function(event) {
                orbitControls.enabled = !event.value;
            });
            transformControls.addEventListener('change', updatePositionInputs);
            scene.add(transformControls);

            // Lights
            scene.add(new THREE.AmbientLight(0x404040, 0.5));
            const light1 = new THREE.DirectionalLight(0xffffff, 0.8);
            light1.position.set(50, 50, 50);
            scene.add(light1);
            const light2 = new THREE.DirectionalLight(0xffffff, 0.4);
            light2.position.set(-50, -50, -50);
            scene.add(light2);

            // Grid
            scene.add(new THREE.GridHelper(100, 20, 0x333333, 0x222222));

            // Raycaster for selection
            const raycaster = new THREE.Raycaster();
            const mouse = new THREE.Vector2();

            renderer.domElement.addEventListener('click', function(event) {
                const rect = renderer.domElement.getBoundingClientRect();
                mouse.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
                mouse.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;

                raycaster.setFromCamera(mouse, camera);
                const meshes = [meshA, meshB, meshResult].filter(m => m && m.visible);
                const intersects = raycaster.intersectObjects(meshes);

                if (intersects.length > 0) {
                    selectMesh(intersects[0].object);
                }
            });

            // Keyboard shortcuts
            window.addEventListener('keydown', function(event) {
                if (event.key === 'w') setTransformMode('translate');
                if (event.key === 'e') setTransformMode('rotate');
            });

            window.addEventListener('resize', onWindowResize);
            animate();
        }

        function selectMesh(mesh) {
            selectedMesh = mesh;
            transformControls.attach(mesh);
            document.getElementById('positionControls').style.display = 'block';
            updatePositionInputs();
        }

        function setTransformMode(mode) {
            transformControls.setMode(mode);
            document.getElementById('modeTranslate').classList.toggle('btn-active', mode === 'translate');
            document.getElementById('modeRotate').classList.toggle('btn-active', mode === 'rotate');
        }

        function updatePositionInputs() {
            if (selectedMesh) {
                document.getElementById('posX').value = selectedMesh.position.x.toFixed(1);
                document.getElementById('posY').value = selectedMesh.position.y.toFixed(1);
                document.getElementById('posZ').value = selectedMesh.position.z.toFixed(1);
            }
        }

        function updatePosition() {
            if (selectedMesh) {
                selectedMesh.position.set(
                    parseFloat(document.getElementById('posX').value) || 0,
                    parseFloat(document.getElementById('posY').value) || 0,
                    parseFloat(document.getElementById('posZ').value) || 0
                );
            }
        }

        function onWindowResize() {
            const container = document.getElementById('canvas-container');
            camera.aspect = container.clientWidth / container.clientHeight;
            camera.updateProjectionMatrix();
            renderer.setSize(container.clientWidth, container.clientHeight);
        }

        function animate() {
            requestAnimationFrame(animate);
            orbitControls.update();
            renderer.render(scene, camera);
        }

        function loadSTL(file, color) {
            return new Promise((resolve, reject) => {
                const reader = new FileReader();
                reader.onload = function(e) {
                    const loader = new THREE.STLLoader();
                    const geometry = loader.parse(e.target.result);
                    geometry.computeBoundingBox();

                    const material = new THREE.MeshPhongMaterial({
                        color: color,
                        specular: 0x111111,
                        shininess: 30,
                        transparent: true,
                        opacity: 0.85
                    });
                    const mesh = new THREE.Mesh(geometry, material);
                    resolve(mesh);
                };
                reader.onerror = reject;
                reader.readAsArrayBuffer(file);
            });
        }

        function loadSTLFromURL(url, color) {
            return new Promise((resolve, reject) => {
                const loader = new THREE.STLLoader();
                loader.load(url, function(geometry) {
                    const material = new THREE.MeshPhongMaterial({ color: color, specular: 0x111111, shininess: 30 });
                    resolve(new THREE.Mesh(geometry, material));
                }, undefined, reject);
            });
        }

        // Export mesh with transforms applied to geometry
        function exportMeshAsSTL(mesh) {
            // Clone geometry and apply world matrix
            const clonedGeometry = mesh.geometry.clone();
            mesh.updateMatrixWorld();
            clonedGeometry.applyMatrix4(mesh.matrixWorld);

            const exporter = new THREE.STLExporter();
            const tempMesh = new THREE.Mesh(clonedGeometry);
            const stlString = exporter.parse(tempMesh, { binary: true });
            return new Blob([stlString], { type: 'application/octet-stream' });
        }

        function showMesh(which) {
            if (meshA) meshA.visible = (which === 'a' || which === 'all');
            if (meshB) meshB.visible = (which === 'b' || which === 'all');
            if (meshResult) meshResult.visible = (which === 'result' || which === 'all');
            transformControls.detach();
            selectedMesh = null;
            document.getElementById('positionControls').style.display = 'none';
        }

        function setStatus(message, type = 'info') {
            const status = document.getElementById('status');
            status.textContent = message;
            status.className = 'status ' + type;
        }

        function updateExecuteButton() {
            document.getElementById('executeBtn').disabled = !(meshA && meshB);
        }

        // File input handlers
        document.getElementById('meshA').addEventListener('change', async function(e) {
            const file = e.target.files[0];
            if (file) {
                if (meshA) scene.remove(meshA);
                meshA = await loadSTL(file, 0x4ecca3);
                scene.add(meshA);
                selectMesh(meshA);
                setStatus('Mesh A loaded. Click to select, drag to move.', 'success');
            }
            updateExecuteButton();
        });

        document.getElementById('meshB').addEventListener('change', async function(e) {
            const file = e.target.files[0];
            if (file) {
                if (meshB) scene.remove(meshB);
                meshB = await loadSTL(file, 0xe94560);
                meshB.position.set(10, 0, 0); // Offset so they don't overlap initially
                scene.add(meshB);
                selectMesh(meshB);
                setStatus('Mesh B loaded. Position it over Mesh A for boolean.', 'success');
            }
            updateExecuteButton();
        });

        // Execute boolean with transformed positions
        document.getElementById('executeBtn').addEventListener('click', async function() {
            const operation = document.getElementById('operation').value;
            const btn = this;

            btn.disabled = true;
            btn.textContent = 'Processing...';
            setStatus('Applying transforms and executing ' + operation + '...', 'info');

            // Export meshes with their current transforms
            const blobA = exportMeshAsSTL(meshA);
            const blobB = exportMeshAsSTL(meshB);

            const formData = new FormData();
            formData.append('mesh_a', blobA, 'mesh_a.stl');
            formData.append('mesh_b', blobB, 'mesh_b.stl');
            formData.append('operation', operation);

            try {
                const response = await fetch('/api/v2/boolean', {
                    method: 'POST',
                    body: formData
                });

                const result = await response.json();

                if (result.success) {
                    resultJobId = result.data.jobId;
                    setStatus('Boolean ' + operation + ' completed!', 'success');

                    if (meshResult) scene.remove(meshResult);
                    meshResult = await loadSTLFromURL(result.data.resultPath, 0xf9ed69);
                    scene.add(meshResult);

                    showMesh('result');

                    document.getElementById('downloadBtn').style.display = 'block';
                    document.getElementById('previewInfo').style.display = 'block';
                    document.getElementById('faceCount').textContent = meshResult.geometry.attributes.position.count / 3;

                } else {
                    setStatus('Error: ' + (result.detail || result.message || 'Unknown error'), 'error');
                }
            } catch (err) {
                setStatus('Error: ' + err.message, 'error');
            }

            btn.disabled = false;
            btn.textContent = 'Execute Boolean';
        });

        document.getElementById('downloadBtn').addEventListener('click', function() {
            if (resultJobId) {
                window.location.href = '/api/jobs/' + resultJobId + '/boolean.stl';
            }
        });

        init();
    </script>
</body>
</html>
"""


@app.post("/api/jobs", response_model=JobCreateResponse)
async def create_slicing_job(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    config: Optional[str] = Form(None),
):
    """
    Create a new slicing job.

    Upload a .stl file to start SLA slicing.
    Optionally provide a JSON config string with slicing parameters.
    """
    # Validate file extension
    if not file.filename or not file.filename.lower().endswith(".stl"):
        raise HTTPException(status_code=400, detail="Only .stl files are supported")

    # Parse config if provided
    sla_config: Optional[SLAConfig] = None
    if config:
        try:
            config_data = json.loads(config)
            sla_config = SLAConfig(**config_data)
        except json.JSONDecodeError as e:
            raise HTTPException(status_code=400, detail=f"Invalid config JSON: {e}")
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid config: {e}")

    # Create job
    job_id = create_job_id()
    job_dir = create_job(job_id)

    # Save uploaded file
    input_path = job_dir / "input" / "model.stl"
    try:
        content = await file.read()
        with open(input_path, "wb") as f:
            f.write(content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save file: {e}")

    # Schedule slicing in background
    background_tasks.add_task(run_slicing, job_id, sla_config)

    return JobCreateResponse(job_id=job_id, status=JobStatus.PENDING)


@app.get("/api/jobs/{job_id}", response_model=JobStatusResponse)
async def get_job_status(job_id: str):
    """
    Get the status of a slicing job.
    """
    if not job_exists(job_id):
        raise HTTPException(status_code=404, detail="Job not found")

    status_data = read_job_status(job_id)

    return JobStatusResponse(
        job_id=job_id,
        status=JobStatus(status_data["status"]),
        layer_count=status_data.get("layer_count"),
        estimated_print_time=status_data.get("estimated_print_time"),
        resin_volume_ml=status_data.get("resin_volume_ml"),
        error=status_data.get("error"),
        has_support_mesh=status_data.get("has_support_mesh", False),
        has_hollow_mesh=status_data.get("has_hollow_mesh", False),
        has_cut_mesh=status_data.get("has_cut_mesh", False),
    )


@app.get("/api/jobs/{job_id}/layers/{idx}.png")
async def get_layer_image(job_id: str, idx: int):
    """
    Get a specific layer image as PNG.
    """
    if not job_exists(job_id):
        raise HTTPException(status_code=404, detail="Job not found")

    # Check job is completed
    status_data = read_job_status(job_id)
    if status_data["status"] != JobStatus.COMPLETED.value:
        raise HTTPException(
            status_code=400,
            detail=f"Job is not completed (status: {status_data['status']})"
        )

    # Get layer path
    layer_path = get_layer_path(job_id, idx)
    if layer_path is None:
        raise HTTPException(status_code=404, detail=f"Layer {idx} not found")

    return FileResponse(
        layer_path,
        media_type="image/png",
        filename=f"{idx}.png",
    )


@app.get("/api/jobs/{job_id}/support.stl")
async def get_support_mesh(job_id: str):
    """
    Get the support mesh as STL file.
    """
    if not job_exists(job_id):
        raise HTTPException(status_code=404, detail="Job not found")

    # Check job is completed
    status_data = read_job_status(job_id)
    if status_data["status"] != JobStatus.COMPLETED.value:
        raise HTTPException(
            status_code=400,
            detail=f"Job is not completed (status: {status_data['status']})"
        )

    # Get support mesh path
    support_path = get_support_mesh_path(job_id)
    if support_path is None:
        raise HTTPException(status_code=404, detail="Support mesh not available")

    return FileResponse(
        support_path,
        media_type="application/octet-stream",
        filename="support.stl",
    )


@app.get("/api/jobs/{job_id}/model.stl")
async def get_input_model(job_id: str):
    """
    Get the original input model as STL file.
    """
    if not job_exists(job_id):
        raise HTTPException(status_code=404, detail="Job not found")

    # Get input model path
    model_path = get_input_model_path(job_id)
    if model_path is None:
        raise HTTPException(status_code=404, detail="Model not found")

    return FileResponse(
        model_path,
        media_type="application/octet-stream",
        filename="model.stl",
    )


@app.get("/api/jobs/{job_id}/hollow.stl")
async def get_hollow_mesh(job_id: str):
    """
    Get the hollow interior mesh as STL file.
    """
    if not job_exists(job_id):
        raise HTTPException(status_code=404, detail="Job not found")

    # Check job is completed
    status_data = read_job_status(job_id)
    if status_data["status"] != JobStatus.COMPLETED.value:
        raise HTTPException(
            status_code=400,
            detail=f"Job is not completed (status: {status_data['status']})"
        )

    # Get hollow mesh path
    hollow_path = get_hollow_mesh_path(job_id)
    if hollow_path is None:
        raise HTTPException(status_code=404, detail="Hollow mesh not available")

    return FileResponse(
        hollow_path,
        media_type="application/octet-stream",
        filename="hollow.stl",
    )


@app.get("/api/jobs/{job_id}/drain_holes.stl")
async def get_drain_holes_mesh(job_id: str):
    """
    Get the drain holes mesh as STL file.
    """
    if not job_exists(job_id):
        raise HTTPException(status_code=404, detail="Job not found")

    drain_path = get_drain_holes_path(job_id)
    if drain_path is None:
        raise HTTPException(status_code=404, detail="Drain holes mesh not available")

    return FileResponse(
        drain_path,
        media_type="application/octet-stream",
        filename="drain_holes.stl",
    )


@app.get("/api/jobs/{job_id}/cut.stl")
async def get_cut_mesh(job_id: str):
    """
    Get the cut mesh as STL file.

    Note: PrusaSlicer's --cut outputs both upper and lower parts combined
    into a single STL file. Both parts are repositioned to z=0.
    """
    if not job_exists(job_id):
        raise HTTPException(status_code=404, detail="Job not found")

    # Check job is completed
    status_data = read_job_status(job_id)
    if status_data["status"] != JobStatus.COMPLETED.value:
        raise HTTPException(
            status_code=400,
            detail=f"Job is not completed (status: {status_data['status']})"
        )

    # Get cut mesh path
    cut_path = get_cut_mesh_path(job_id)
    if cut_path is None:
        raise HTTPException(status_code=404, detail="Cut mesh not available")

    return FileResponse(
        cut_path,
        media_type="application/octet-stream",
        filename="cut.stl",
    )


@app.get("/api/jobs/{job_id}/cut_upper.stl")
async def get_cut_upper_mesh(job_id: str):
    """
    Get the upper cut mesh as STL file.
    """
    if not job_exists(job_id):
        raise HTTPException(status_code=404, detail="Job not found")

    status_data = read_job_status(job_id)
    if status_data["status"] != JobStatus.COMPLETED.value:
        raise HTTPException(
            status_code=400,
            detail=f"Job is not completed (status: {status_data['status']})"
        )

    cut_path = get_cut_upper_mesh_path(job_id)
    if cut_path is None:
        raise HTTPException(status_code=404, detail="Upper cut mesh not available")

    return FileResponse(
        cut_path,
        media_type="application/octet-stream",
        filename="cut_upper.stl",
    )


@app.get("/api/jobs/{job_id}/cut_lower.stl")
async def get_cut_lower_mesh(job_id: str):
    """
    Get the lower cut mesh as STL file.
    """
    if not job_exists(job_id):
        raise HTTPException(status_code=404, detail="Job not found")

    status_data = read_job_status(job_id)
    if status_data["status"] != JobStatus.COMPLETED.value:
        raise HTTPException(
            status_code=400,
            detail=f"Job is not completed (status: {status_data['status']})"
        )

    cut_path = get_cut_lower_mesh_path(job_id)
    if cut_path is None:
        raise HTTPException(status_code=404, detail="Lower cut mesh not available")

    return FileResponse(
        cut_path,
        media_type="application/octet-stream",
        filename="cut_lower.stl",
    )


@app.get("/api/jobs/{job_id}/boolean.stl")
async def get_boolean_mesh(job_id: str):
    """
    Get the boolean operation result as STL file.
    """
    if not job_exists(job_id):
        raise HTTPException(status_code=404, detail="Job not found")

    bool_path = get_boolean_mesh_path(job_id)
    if bool_path is None:
        raise HTTPException(status_code=404, detail="Boolean result not available")

    return FileResponse(
        bool_path,
        media_type="application/octet-stream",
        filename="boolean.stl",
    )


def main():
    """Run the server."""
    import uvicorn
    uvicorn.run(app, host=HOST, port=PORT)


if __name__ == "__main__":
    main()
