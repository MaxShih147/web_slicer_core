"""
API v2 endpoints - DS-Online compatible API.

This module provides API endpoints that match the DS-Online frontend's expected format.
Both v1 (/api/jobs) and v2 (/api/v2/slices) share the same underlying job manager.
"""

import json
import logging
import math
import shutil
import traceback as tb
from typing import Any, Dict, List, Optional

import trimesh
from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile, Request
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from .jobs import (
    create_job,
    create_job_id,
    get_drain_holes_path,
    get_hollow_mesh_path,
    get_input_model_path,
    get_job_dir,
    job_exists,
    read_job_status,
    run_slicing,
    run_support_generation,
    run_hollow_generation,
    run_cut_operation,
)
from .models import BooleanOperation, JobStatus, SLAConfig
from .sla_operations import generate_drain_holes, generate_hex_grid, load_trimesh, parse_binary_stl, perform_boolean, write_binary_stl

logger = logging.getLogger(__name__)


# ============================================================================
# V2 API Models (DS-Online compatible)
# ============================================================================

class V2Response(BaseModel):
    """Standard v2 response wrapper."""
    success: bool
    message: Optional[str] = None
    data: Optional[Dict[str, Any]] = None


class V2SliceCreateRequest(BaseModel):
    """Request to create a new slice job."""
    config: Optional[Dict[str, Any]] = None


class V2ConfigUpdateRequest(BaseModel):
    """Request to update slice job config."""
    config: Dict[str, Any]
    isAppend: bool = True


class V2ModelsAddRequest(BaseModel):
    """Request to add models to a slice job."""
    models: List[Dict[str, Any]]


class V2CutRequest(BaseModel):
    """Request to cut model at a specified Z height."""
    cut_height: float
    keep_mode: str = "both"  # "both", "upper", or "lower"


class V2ExtendBottomRequest(BaseModel):
    """Request to extend bottom vertices of hollow mesh."""
    bottom_z_threshold: float = 0.5  # mm above mesh min Z to select vertices
    extension_distance: float = 10.0  # mm to extend downward


class V2BooleanRequest(BaseModel):
    """Request for boolean operation on two meshes."""
    operation: str = "difference"  # "union", "difference", or "intersection"


class V2GenerateDrainHolesRequest(BaseModel):
    """Request to generate drain hole cylinders at hex grid wall edges."""
    hex_cell_radius: float = 5.0
    wall_thickness: float = 1.0
    grid_count: int = 10
    drain_radius: float = 1.5
    bottom_z: float = 0.0


class V2GenerateHexGridRequest(BaseModel):
    """Request to generate honeycomb hex grid infill mesh."""
    hex_cell_radius: float = 5.0
    wall_thickness: float = 1.0
    grid_count: int = 10
    pyramid_height: float = 3.0
    fallback_height: float = 20.0
    bottom_z: float = 0.0


class V2OrthoProcessRequest(BaseModel):
    """Request for consolidated ortho processing pipeline."""
    hollowing_min_thickness: float = 3.0
    hollowing_quality: float = 0.5
    hollowing_closing_distance: float = 2.0
    bottom_z_threshold: float = 0.5
    extension_distance: float = 10.0
    hex_cell_radius: float = 5.0
    hex_wall_thickness: float = 1.0
    hex_grid_count: int = 10
    hex_pyramid_height: float = 3.0
    drain_hole_radius: float = 1.5


# ============================================================================
# V2 Job State (in-memory for pending jobs before execute)
# ============================================================================

# Store for jobs that are created but not yet executed
# Key: job_id, Value: {config: dict, models: list, status: str}
_pending_jobs: Dict[str, Dict[str, Any]] = {}


# ============================================================================
# V2 Router
# ============================================================================

router = APIRouter(prefix="/api/v2", tags=["v2-slices"])


@router.post("/slices", response_model=V2Response)
async def create_slice_job(request: V2SliceCreateRequest):
    """
    Create a new slice job (DS-Online compatible).

    Unlike v1, this just creates a job ID and stores initial config.
    Models are added separately, and slicing starts on execute.
    """
    job_id = create_job_id()

    # Store in pending jobs (not yet on disk)
    _pending_jobs[job_id] = {
        "config": request.config or {},
        "models": [],
        "status": "created",
    }

    return V2Response(
        success=True,
        message="Slice job created",
        data={"jobId": job_id}
    )


@router.put("/slices/{job_id}/config", response_model=V2Response)
async def update_slice_job_config(job_id: str, request: V2ConfigUpdateRequest):
    """
    Update the config for a slice job.
    """
    if job_id not in _pending_jobs:
        raise HTTPException(status_code=404, detail="Job not found or already executed")

    if request.isAppend:
        # Merge config
        _pending_jobs[job_id]["config"].update(request.config)
    else:
        # Replace config
        _pending_jobs[job_id]["config"] = request.config

    return V2Response(
        success=True,
        message="Config updated"
    )


@router.post("/slices/{job_id}/models", response_model=V2Response)
async def add_models_to_slice_job(job_id: str, request: V2ModelsAddRequest):
    """
    Add models to a slice job.

    Each model should contain vertex data or a reference to an uploaded file.
    """
    if job_id not in _pending_jobs:
        raise HTTPException(status_code=404, detail="Job not found or already executed")

    model_ids = []
    for i, model in enumerate(request.models):
        model_id = f"model_{i}_{len(_pending_jobs[job_id]['models'])}"
        _pending_jobs[job_id]["models"].append({
            "id": model_id,
            **model
        })
        model_ids.append(model_id)

    return V2Response(
        success=True,
        message=f"Added {len(model_ids)} model(s)",
        data={"modelIds": model_ids}
    )


@router.post("/slices/{job_id}/upload", response_model=V2Response)
async def upload_model_file(job_id: str, file: UploadFile = File(...)):
    """
    Upload an STL file to a slice job.

    This is the recommended way to add models - upload the file directly.
    The file will be stored and used when execute is called.
    """
    if job_id not in _pending_jobs:
        raise HTTPException(status_code=404, detail="Job not found or already executed")

    # Validate file extension
    if not file.filename or not file.filename.lower().endswith(".stl"):
        raise HTTPException(status_code=400, detail="Only .stl files are supported")

    # Read file content
    try:
        content = await file.read()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read file: {e}")

    # Store file content in pending job
    model_id = f"file_{len(_pending_jobs[job_id]['models'])}"
    _pending_jobs[job_id]["models"].append({
        "id": model_id,
        "filename": file.filename,
        "stl_data": content,
        "type": "file_upload",
    })

    return V2Response(
        success=True,
        message=f"File '{file.filename}' uploaded",
        data={"modelId": model_id, "filename": file.filename}
    )


@router.post("/slices/{job_id}/use-model-from/{source_job_id}", response_model=V2Response)
async def use_model_from_job(job_id: str, source_job_id: str, source_file: str = "boolean.stl"):
    """
    Reference an existing job's output file as the model for this slice job.
    Avoids re-uploading large files that are already on the server.
    """
    if job_id not in _pending_jobs:
        raise HTTPException(status_code=404, detail="Job not found or already executed")

    # Find the source file on disk
    source_dir = get_job_dir(source_job_id)
    source_path = source_dir / "output" / source_file
    if not source_path.exists():
        # Also check input dir
        source_path = source_dir / "input" / source_file
    if not source_path.exists():
        raise HTTPException(status_code=404, detail=f"Source file '{source_file}' not found in job {source_job_id}")

    # Read the file content and add to pending job
    content = source_path.read_bytes()
    model_id = f"ref_{source_job_id}_{len(_pending_jobs[job_id]['models'])}"
    _pending_jobs[job_id]["models"].append({
        "id": model_id,
        "filename": "model.stl",
        "stl_data": content,
        "type": "server_reference",
    })

    return V2Response(
        success=True,
        message=f"Model referenced from job {source_job_id}/{source_file}",
        data={"modelId": model_id, "sourceJobId": source_job_id}
    )


@router.post("/slices/{job_id}/execute", response_model=V2Response)
async def execute_slice_job(job_id: str, background_tasks: BackgroundTasks):
    """
    Execute the slice job (start slicing).

    This triggers the actual PrusaSlicer process.
    """
    if job_id not in _pending_jobs:
        # Check if it's already on disk (v1 style job)
        if job_exists(job_id):
            status = read_job_status(job_id)
            return V2Response(
                success=True,
                message="Job already exists",
                data={"currentConfig": status}
            )
        raise HTTPException(status_code=404, detail="Job not found")

    pending = _pending_jobs[job_id]

    # Check if models were added
    if not pending["models"]:
        raise HTTPException(status_code=400, detail="No models added to job")

    # Create job directory structure
    job_dir = create_job(job_id)

    # Save model data (first model for now)
    # In a full implementation, this would handle multiple models
    model_data = pending["models"][0]
    input_path = job_dir / "input" / "model.stl"

    if "vertices" in model_data:
        # Model data provided as vertices - would need to convert to STL
        # For now, raise an error as this needs more implementation
        raise HTTPException(
            status_code=501,
            detail="Direct vertex data not yet supported. Please use file upload."
        )
    elif "stl_data" in model_data:
        # Binary STL data provided
        with open(input_path, "wb") as f:
            f.write(model_data["stl_data"])
    else:
        raise HTTPException(status_code=400, detail="Model must contain vertices or stl_data")

    # Convert v2 config to SLAConfig
    config = pending["config"]
    sla_config = _convert_v2_config_to_sla(config)

    # Remove from pending
    del _pending_jobs[job_id]

    # Start slicing in background
    background_tasks.add_task(run_slicing, job_id, sla_config)

    return V2Response(
        success=True,
        message="Slicing started",
        data={"currentConfig": config}
    )


@router.post("/slices/{job_id}/generate-supports", response_model=V2Response)
async def generate_supports_only(job_id: str, background_tasks: BackgroundTasks):
    """
    Generate support mesh only (without slicing).

    This allows users to preview supports before committing to a full slice.
    The support mesh can be fetched via GET /api/jobs/{job_id}/support.stl
    """
    if job_id not in _pending_jobs:
        # Check if it's already on disk
        if job_exists(job_id):
            status = read_job_status(job_id)
            if status.get("has_support_mesh"):
                return V2Response(
                    success=True,
                    message="Supports already generated",
                    data={"hasSupportMesh": True}
                )
        raise HTTPException(status_code=404, detail="Job not found")

    pending = _pending_jobs[job_id]

    # Check if models were added
    if not pending["models"]:
        raise HTTPException(status_code=400, detail="No models added to job")

    # Create job directory structure
    job_dir = create_job(job_id)

    # Save model data
    model_data = pending["models"][0]
    input_path = job_dir / "input" / "model.stl"

    if "vertices" in model_data:
        raise HTTPException(
            status_code=501,
            detail="Direct vertex data not yet supported. Please use file upload."
        )
    elif "stl_data" in model_data:
        with open(input_path, "wb") as f:
            f.write(model_data["stl_data"])
    else:
        raise HTTPException(status_code=400, detail="Model must contain vertices or stl_data")

    # Convert v2 config to SLAConfig (ensure supports_enable is True)
    config = pending["config"]
    config["supports_enable"] = True
    sla_config = _convert_v2_config_to_sla(config)

    # Keep job in pending so it can still be sliced later
    # But mark that we've saved the model
    pending["model_saved"] = True
    pending["job_dir"] = str(job_dir)

    # Start support generation in background
    background_tasks.add_task(run_support_generation, job_id, sla_config)

    return V2Response(
        success=True,
        message="Support generation started",
        data={"currentConfig": config}
    )


@router.post("/slices/{job_id}/generate-hollow", response_model=V2Response)
async def generate_hollow_only(job_id: str, background_tasks: BackgroundTasks):
    """
    Generate hollow interior mesh only (without slicing).

    This allows users to preview the hollow interior before committing to a full slice.
    The hollow mesh can be fetched via GET /api/jobs/{job_id}/hollow.stl
    """
    if job_id not in _pending_jobs:
        # Check if it's already on disk
        if job_exists(job_id):
            status = read_job_status(job_id)
            if status.get("has_hollow_mesh"):
                return V2Response(
                    success=True,
                    message="Hollow already generated",
                    data={"hasHollowMesh": True}
                )
        raise HTTPException(status_code=404, detail="Job not found")

    pending = _pending_jobs[job_id]

    # Check if models were added
    if not pending["models"]:
        raise HTTPException(status_code=400, detail="No models added to job")

    # Create job directory structure
    job_dir = create_job(job_id)

    # Save model data
    model_data = pending["models"][0]
    input_path = job_dir / "input" / "model.stl"

    if "vertices" in model_data:
        raise HTTPException(
            status_code=501,
            detail="Direct vertex data not yet supported. Please use file upload."
        )
    elif "stl_data" in model_data:
        with open(input_path, "wb") as f:
            f.write(model_data["stl_data"])
    else:
        raise HTTPException(status_code=400, detail="Model must contain vertices or stl_data")

    # Convert v2 config to SLAConfig (ensure hollowing_enable is True)
    config = pending["config"]
    config["hollowing_enable"] = True
    sla_config = _convert_v2_config_to_sla(config)

    # Keep job in pending so it can still be sliced later
    # But mark that we've saved the model
    pending["model_saved"] = True
    pending["job_dir"] = str(job_dir)

    # Start hollow generation in background
    background_tasks.add_task(run_hollow_generation, job_id, sla_config)

    return V2Response(
        success=True,
        message="Hollow generation started",
        data={"currentConfig": config}
    )


@router.post("/slices/{job_id}/cut", response_model=V2Response)
async def cut_model(job_id: str, request: V2CutRequest, background_tasks: BackgroundTasks):
    """
    Cut model at specified Z height.

    This uses PrusaSlicer's --cut option to split the model into upper and lower parts.
    The upper part can be fetched via GET /api/jobs/{job_id}/cut.stl
    """
    if job_id not in _pending_jobs:
        # Check if it's already on disk
        if job_exists(job_id):
            status = read_job_status(job_id)
            if status.get("has_cut_mesh"):
                return V2Response(
                    success=True,
                    message="Cut already performed",
                    data={"hasCutMesh": True}
                )
        raise HTTPException(status_code=404, detail="Job not found")

    pending = _pending_jobs[job_id]

    # Check if models were added
    if not pending["models"]:
        raise HTTPException(status_code=400, detail="No models added to job")

    # Create job directory structure
    job_dir = create_job(job_id)

    # Save model data
    model_data = pending["models"][0]
    input_path = job_dir / "input" / "model.stl"

    if "vertices" in model_data:
        raise HTTPException(
            status_code=501,
            detail="Direct vertex data not yet supported. Please use file upload."
        )
    elif "stl_data" in model_data:
        with open(input_path, "wb") as f:
            f.write(model_data["stl_data"])
    else:
        raise HTTPException(status_code=400, detail="Model must contain vertices or stl_data")

    # Keep job in pending so it can be used for other operations
    pending["model_saved"] = True
    pending["job_dir"] = str(job_dir)

    # Start cut operation in background
    background_tasks.add_task(run_cut_operation, job_id, request.cut_height, request.keep_mode)

    return V2Response(
        success=True,
        message="Cut operation started",
        data={"cutHeight": request.cut_height, "keepMode": request.keep_mode}
    )


@router.post("/slices/{job_id}/extend-bottom", response_model=V2Response)
async def extend_bottom(job_id: str, request: V2ExtendBottomRequest):
    """
    Extend bottom vertices of the hollow mesh downward.

    Synchronous operation — reads hollow.stl, moves bottom vertices down,
    recomputes normals, and overwrites the file.
    """
    hollow_path = get_hollow_mesh_path(job_id)
    if hollow_path is None:
        raise HTTPException(status_code=404, detail="Hollow mesh not found for this job")

    # Read the hollow mesh
    triangles = parse_binary_stl(hollow_path)
    if not triangles:
        raise HTTPException(status_code=400, detail="Hollow mesh is empty")

    # Find mesh min Z
    min_z = float("inf")
    for _, v1, v2, v3 in triangles:
        for v in [v1, v2, v3]:
            min_z = min(min_z, v[2])

    z1 = min_z + request.bottom_z_threshold

    # Extend vertices below threshold and recompute normals
    moved_vertices = set()
    new_triangles = []
    for _, v1, v2, v3 in triangles:
        # Move vertices that are at or below z1
        verts = []
        for v in [v1, v2, v3]:
            if v[2] <= z1:
                moved_vertices.add(v)
                verts.append((v[0], v[1], v[2] - request.extension_distance))
            else:
                verts.append(v)

        # Recompute face normal
        e1 = (verts[1][0] - verts[0][0], verts[1][1] - verts[0][1], verts[1][2] - verts[0][2])
        e2 = (verts[2][0] - verts[0][0], verts[2][1] - verts[0][1], verts[2][2] - verts[0][2])
        nx = e1[1] * e2[2] - e1[2] * e2[1]
        ny = e1[2] * e2[0] - e1[0] * e2[2]
        nz = e1[0] * e2[1] - e1[1] * e2[0]
        length = math.sqrt(nx * nx + ny * ny + nz * nz)
        if length > 0:
            nx /= length
            ny /= length
            nz /= length
        normal = (nx, ny, nz)

        new_triangles.append((normal, verts[0], verts[1], verts[2]))

    # Overwrite hollow.stl
    write_binary_stl(hollow_path, new_triangles, "hollow extended")

    return V2Response(
        success=True,
        message=f"Extended {len(moved_vertices)} vertices by {request.extension_distance}mm",
        data={"vertices_moved": len(moved_vertices)},
    )


@router.post("/slices/{job_id}/generate-drain-holes", response_model=V2Response)
async def generate_drain_holes_endpoint(job_id: str, request: V2GenerateDrainHolesRequest):
    """
    Generate drain hole cylinders at hex grid wall edge midpoints.

    Synchronous operation — generates drain cylinders using trimesh and saves
    the result to job_dir/output/model_drain_holes.stl.
    The STL can be fetched via GET /api/jobs/{job_id}/drain_holes.stl
    """
    if not job_exists(job_id):
        raise HTTPException(status_code=404, detail="Job not found")

    job_dir = get_job_dir(job_id)
    output_dir = job_dir / "output"
    output_dir.mkdir(exist_ok=True)

    mesh = generate_drain_holes(
        hex_cell_radius=request.hex_cell_radius,
        wall_thickness=request.wall_thickness,
        grid_count=request.grid_count,
        drain_radius=request.drain_radius,
        bottom_z=request.bottom_z,
    )

    if mesh is None:
        return V2Response(
            success=True,
            message="No drain holes generated (no wall edges found)",
            data={"cylinderCount": 0},
        )

    output_path = output_dir / "model_drain_holes.stl"
    mesh.export(str(output_path))

    return V2Response(
        success=True,
        message=f"Drain holes generated ({len(mesh.faces)} faces)",
        data={
            "resultPath": f"/api/jobs/{job_id}/drain_holes.stl",
            "faces": len(mesh.faces),
        },
    )


@router.post("/slices/{job_id}/generate-hex-grid", response_model=V2Response)
async def generate_hex_grid_endpoint(job_id: str, request: V2GenerateHexGridRequest):
    """
    Generate honeycomb hex grid infill mesh using raycasting against hollow mesh.

    Synchronous operation — loads hollow.stl, raycasts to determine cell heights,
    builds hex grid geometry, and saves result to model_hex_grid.stl.
    The STL can be fetched via GET /api/jobs/{job_id}/hex_grid.stl
    """
    if not job_exists(job_id):
        raise HTTPException(status_code=404, detail="Job not found")

    # Reset boolean debug counter and prepare debug folder
    global _boolean_step_counter
    _boolean_step_counter = 0
    job_dir = get_job_dir(job_id)
    debug_dir = job_dir / "debug"
    if debug_dir.exists():
        shutil.rmtree(debug_dir)
    debug_dir.mkdir(exist_ok=True)

    # Load hollow mesh
    hollow_path = get_hollow_mesh_path(job_id)
    if hollow_path is None:
        raise HTTPException(status_code=404, detail="Hollow mesh not found for this job")

    hollow_mesh = load_trimesh(hollow_path)

    # PrusaSlicer centers the model's bounding box at origin before hollowing.
    # Undo this by translating the hollow mesh by the input model's bbox center.
    input_model_path = get_input_model_path(job_id)
    if input_model_path is not None:
        input_mesh = load_trimesh(input_model_path)
        input_center = (input_mesh.bounds[0] + input_mesh.bounds[1]) / 2
        hollow_mesh.apply_translation(input_center)
        shutil.copy2(input_model_path, debug_dir / "input_model_outer.stl")

    logger.info(f"generate-hex-grid: hollow bounds={hollow_mesh.bounds.tolist()}, "
                f"bottom_z={request.bottom_z}")

    # Save aligned hollow for frontend use and debug
    output_dir = job_dir / "output"
    hollow_mesh.export(str(output_dir / "model_hollow_aligned.stl"))
    hollow_mesh.export(str(debug_dir / "hollow_for_raycasting.stl"))

    mesh = generate_hex_grid(
        radius=request.hex_cell_radius,
        fallback_height=request.fallback_height,
        pyramid_height=request.pyramid_height,
        wall_thickness=request.wall_thickness,
        grid_count=request.grid_count,
        bottom_z=request.bottom_z,
        hollow_mesh=hollow_mesh,
    )

    if mesh is None:
        return V2Response(
            success=True,
            message="No hex grid cells built",
            data={"cellsBuilt": 0},
        )

    output_dir = job_dir / "output"
    output_dir.mkdir(exist_ok=True)
    mesh.export(str(output_dir / "model_hex_grid.stl"))

    return V2Response(
        success=True,
        message=f"Hex grid generated ({len(mesh.faces)} faces)",
        data={
            "resultPath": f"/api/jobs/{job_id}/hex_grid.stl",
            "faces": len(mesh.faces),
        },
    )


@router.post("/boolean")
async def boolean_operation_endpoint(
    mesh_a: UploadFile = File(..., description="First mesh (STL)"),
    mesh_b: UploadFile = File(..., description="Second mesh (STL)"),
    operation: str = Form(default="difference", description="Boolean operation: union, difference, or intersection"),
    parent_job_id: str = Form(default="", description="Parent job ID for debug export"),
):
    """
    Perform boolean operation on two meshes (experimental).
    """
    try:
        return await _boolean_operation_impl(mesh_a, mesh_b, operation, parent_job_id or None)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Boolean {operation} failed")
        raise HTTPException(status_code=500, detail=str(e))


_boolean_step_counter = 0


async def _boolean_operation_impl(mesh_a, mesh_b, operation, parent_job_id=None):
    global _boolean_step_counter
    _boolean_step_counter += 1
    step = _boolean_step_counter

    try:
        bool_op = BooleanOperation(operation)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid operation: {operation}. Must be 'union', 'difference', or 'intersection'"
        )

    for f, name in [(mesh_a, "mesh_a"), (mesh_b, "mesh_b")]:
        if not f.filename or not f.filename.lower().endswith(".stl"):
            raise HTTPException(status_code=400, detail=f"{name} must be an STL file")

    job_id = create_job_id()
    job_dir = create_job(job_id)
    input_dir = job_dir / "input"
    mesh_a_path = input_dir / "mesh_a.stl"
    mesh_b_path = input_dir / "mesh_b.stl"

    mesh_a_content = await mesh_a.read()
    mesh_b_content = await mesh_b.read()
    with open(mesh_a_path, "wb") as f:
        f.write(mesh_a_content)
    with open(mesh_b_path, "wb") as f:
        f.write(mesh_b_content)

    # Debug: save inputs/output to parent job's debug/ folder
    debug_dir = None
    if parent_job_id and job_exists(parent_job_id):
        debug_dir = get_job_dir(parent_job_id) / "debug"
        debug_dir.mkdir(exist_ok=True)
        shutil.copy2(mesh_a_path, debug_dir / f"step{step}_{operation}_inputA.stl")
        shutil.copy2(mesh_b_path, debug_dir / f"step{step}_{operation}_inputB.stl")

    result = await perform_boolean(job_dir, mesh_a_path, mesh_b_path, bool_op)
    if not result.success:
        raise HTTPException(status_code=500, detail=result.error)

    if debug_dir and result.boolean_mesh_path and result.boolean_mesh_path.exists():
        shutil.copy2(result.boolean_mesh_path, debug_dir / f"step{step}_{operation}_output.stl")

    return V2Response(
        success=True,
        message=f"Boolean {operation} completed",
        data={
            "jobId": job_id,
            "operation": operation,
            "resultPath": f"/api/jobs/{job_id}/boolean.stl",
        }
    )


@router.get("/slices/{job_id}/preview.zip")
async def get_preview_zip_v2(job_id: str):
    """
    Get a ZIP of downscaled WebP preview images for layer display.
    Pre-generated in background after slicing; generated on-demand if not ready.
    """
    if not job_exists(job_id):
        raise HTTPException(status_code=404, detail="Job not found")

    status_data = read_job_status(job_id)
    if status_data["status"] != "completed":
        raise HTTPException(
            status_code=400,
            detail=f"Job is not completed (status: {status_data['status']})"
        )

    job_dir = get_job_dir(job_id)
    sl1_path = job_dir / "output" / "model.sl1"
    preview_path = job_dir / "output" / "preview.zip"

    if not sl1_path.exists():
        raise HTTPException(status_code=404, detail=".sl1 archive not found")

    # Run in thread pool to avoid blocking the event loop
    import asyncio
    from .preview_service import generate_preview_zip
    await asyncio.get_event_loop().run_in_executor(
        None, generate_preview_zip, sl1_path, preview_path
    )

    return FileResponse(
        preview_path,
        media_type="application/zip",
        filename="preview.zip",
    )


@router.get("/slices/{job_id}/layers.zip")
async def get_layers_zip_v2(job_id: str):
    """
    Get layer PNGs as a ZIP. Serves the .sl1 directly (it IS a ZIP of PNGs).
    Zero processing time — no resize/re-encode needed.
    """
    if not job_exists(job_id):
        raise HTTPException(status_code=404, detail="Job not found")

    status_data = read_job_status(job_id)
    if status_data["status"] != "completed":
        raise HTTPException(
            status_code=400,
            detail=f"Job is not completed (status: {status_data['status']})"
        )

    job_dir = get_job_dir(job_id)
    sl1_path = job_dir / "output" / "model.sl1"

    if not sl1_path.exists():
        raise HTTPException(status_code=404, detail=".sl1 archive not found")

    return FileResponse(
        sl1_path,
        media_type="application/zip",
        filename="layers.zip",
    )


@router.post("/slices/{job_id}/download.prz")
async def download_prz_v2(job_id: str, request: Request):
    """
    Generate and stream a PRZ file from the .sl1 layers + posted config.
    The POST body is the Mechado config JSON (same structure as default profile).
    """
    if not job_exists(job_id):
        raise HTTPException(status_code=404, detail="Job not found")

    status_data = read_job_status(job_id)
    if status_data["status"] != "completed":
        raise HTTPException(
            status_code=400,
            detail=f"Job is not completed (status: {status_data['status']})"
        )

    job_dir = get_job_dir(job_id)
    sl1_path = job_dir / "output" / "model.sl1"

    if not sl1_path.exists():
        raise HTTPException(status_code=404, detail=".sl1 archive not found")

    config = await request.json()

    from .prz_encoder import encode_prz_streaming

    return StreamingResponse(
        encode_prz_streaming(
            config=config,
            sl1_path=sl1_path,
            estimated_print_time=status_data.get("estimated_print_time") or 0,
            resin_volume_ml=status_data.get("resin_volume_ml") or 0,
        ),
        media_type="application/octet-stream",
        headers={"Content-Disposition": "attachment; filename=model.prz"},
    )


@router.get("/slices/{job_id}", response_model=V2Response)
async def get_slice_job_status(job_id: str):
    """
    Get the status of a slice job.
    """
    # Check disk status first (for jobs that have been executed/generated)
    if job_exists(job_id):
        status_data = read_job_status(job_id)
        # If job is on disk and not pending, return disk status
        if status_data["status"] != "pending":
            response_data = {
                    "jobId": job_id,
                    "status": status_data["status"],
                    "layerCount": status_data.get("layer_count"),
                    "estimatedPrintTime": status_data.get("estimated_print_time"),
                    "resinVolumeMl": status_data.get("resin_volume_ml"),
                    "error": status_data.get("error"),
                    "hasSupportMesh": status_data.get("has_support_mesh", False),
                    "hasHollowMesh": status_data.get("has_hollow_mesh", False),
                    "hasCutMesh": status_data.get("has_cut_mesh", False),
                    "hasOrthoResult": status_data.get("has_ortho_result", False),
            }
            if "ortho_progress" in status_data:
                response_data["orthoProgress"] = status_data["ortho_progress"]
            return V2Response(success=True, data=response_data)

    # Check pending jobs (not yet executed)
    if job_id in _pending_jobs:
        return V2Response(
            success=True,
            data={
                "jobId": job_id,
                "status": _pending_jobs[job_id]["status"],
                "config": _pending_jobs[job_id]["config"],
                "modelCount": len(_pending_jobs[job_id]["models"]),
            }
        )

    # Job not found anywhere
    raise HTTPException(status_code=404, detail="Job not found")


@router.get("/slices/{job_id}/uchars", response_model=V2Response)
async def get_slice_uchars(job_id: str):
    """
    Get layer data as unsigned char arrays (for DS-Online compatibility).

    Note: This returns layer count and paths. Actual pixel data would need
    to be fetched separately due to size.
    """
    if not job_exists(job_id):
        raise HTTPException(status_code=404, detail="Job not found")

    status_data = read_job_status(job_id)
    if status_data["status"] != JobStatus.COMPLETED.value:
        raise HTTPException(
            status_code=400,
            detail=f"Job not completed (status: {status_data['status']})"
        )

    layer_count = status_data.get("layer_count", 0)

    # Return layer metadata (actual data fetched via /layers/{idx}.png)
    return V2Response(
        success=True,
        data={
            "uchars": {
                "layerCount": layer_count,
                "layerEndpoint": f"/api/v2/slices/{job_id}/layers/{{idx}}.png"
            }
        }
    )


@router.get("/slices/{job_id}/gcode", response_model=V2Response)
async def get_slice_gcode(job_id: str):
    """
    Get G-code for the slice job.

    Note: PrusaSlicer SLA output is .sl1 (images), not G-code.
    This endpoint returns metadata about the slicing result.
    """
    if not job_exists(job_id):
        raise HTTPException(status_code=404, detail="Job not found")

    status_data = read_job_status(job_id)
    if status_data["status"] != JobStatus.COMPLETED.value:
        raise HTTPException(
            status_code=400,
            detail=f"Job not completed (status: {status_data['status']})"
        )

    # SLA doesn't produce G-code in the traditional sense
    # Return slicing metadata instead
    return V2Response(
        success=True,
        message="SLA slicing produces layer images, not G-code",
        data={
            "gcode": None,
            "layerCount": status_data.get("layer_count", 0),
            "estimatedPrintTime": status_data.get("estimated_print_time"),
            "resinVolumeMl": status_data.get("resin_volume_ml"),
            "format": "sl1",
        }
    )


@router.post("/slices/{job_id}/ortho-process", response_model=V2Response)
async def ortho_process(job_id: str, request: V2OrthoProcessRequest, background_tasks: BackgroundTasks):
    """
    Run the consolidated ortho processing pipeline server-side.

    Performs all 10 steps (hollow, extend, align, hex grid, drain holes,
    side wall drains, 4x boolean ops) as a single background task.

    The final result can be downloaded via GET /api/jobs/{job_id}/ortho_result.stl
    Poll GET /api/v2/slices/{job_id} for progress updates in orthoProgress field.
    """
    if job_id not in _pending_jobs:
        raise HTTPException(status_code=404, detail="Job not found or already executed")

    pending = _pending_jobs[job_id]

    if not pending["models"]:
        raise HTTPException(status_code=400, detail="No models added to job")

    # Create job directory structure
    job_dir = create_job(job_id)

    # Save model data
    model_data = pending["models"][0]
    input_path = job_dir / "input" / "model.stl"

    if "stl_data" in model_data:
        with open(input_path, "wb") as f:
            f.write(model_data["stl_data"])
    else:
        raise HTTPException(status_code=400, detail="Model must contain stl_data (use file upload)")

    # Remove from pending
    del _pending_jobs[job_id]

    # Start ortho pipeline in background
    from .ortho_pipeline import run_ortho_pipeline

    background_tasks.add_task(
        run_ortho_pipeline,
        job_id,
        hollowing_min_thickness=request.hollowing_min_thickness,
        hollowing_quality=request.hollowing_quality,
        hollowing_closing_distance=request.hollowing_closing_distance,
        bottom_z_threshold=request.bottom_z_threshold,
        extension_distance=request.extension_distance,
        hex_cell_radius=request.hex_cell_radius,
        hex_wall_thickness=request.hex_wall_thickness,
        hex_grid_count=request.hex_grid_count,
        hex_pyramid_height=request.hex_pyramid_height,
        drain_hole_radius=request.drain_hole_radius,
    )

    return V2Response(
        success=True,
        message="Ortho processing pipeline started",
        data={"jobId": job_id}
    )


# ============================================================================
# Helper Functions
# ============================================================================

def _convert_v2_config_to_sla(config: Dict[str, Any]) -> Optional[SLAConfig]:
    """
    Convert DS-Online config format to SLAConfig.

    DS-Online uses keys like "Layer Height", we use "layer_height".
    """
    if not config:
        return None

    # Map DS-Online config keys to SLAConfig fields
    mapping = {
        "Layer Height": "layer_height",
        "Exposure Time": "exposure_time",
        "Bottom Exposure Time": "initial_exposure_time",
        "Machine Type": "printer_model",
        "Resin": "sla_material_settings_id",
        "Center": "center",
        "Anti-aliasing": "anti_aliasing",
        "Anti-aliasing Level": "anti_aliasing_level",
        "Grey Level": "gray_level",
        "Image Blur Pixel": "blur",
    }

    sla_dict = {}

    # Handle Print section if present
    print_config = config.get("Print", config)

    # First, load direct snake_case keys (v1 compatibility) as base values
    for key in SLAConfig.model_fields:
        if key in config:
            sla_dict[key] = config[key]

    # Then apply DS-Online key mapping (overrides snake_case if both exist)
    for ds_key, sla_key in mapping.items():
        if ds_key in print_config:
            sla_dict[sla_key] = print_config[ds_key]

    # Handle "Image Size" array -> display_pixels_x, display_pixels_y
    image_size = print_config.get("Image Size")
    if isinstance(image_size, list) and len(image_size) >= 2:
        sla_dict["display_pixels_x"] = image_size[0]
        sla_dict["display_pixels_y"] = image_size[1]

    # Handle "Bed Size" array -> display_width, display_height
    bed_size = print_config.get("Bed Size")
    if isinstance(bed_size, list) and len(bed_size) >= 2:
        sla_dict["display_width"] = bed_size[0]
        sla_dict["display_height"] = bed_size[1]

    # Handle "Center" array -> center_x, center_y
    # External center values are offsets from display center,
    # so add display_width/2 and display_height/2 to get absolute position.
    center = print_config.get("center")
    if isinstance(center, list) and len(center) >= 2:
        dw = sla_dict.get("display_width", SLAConfig.model_fields["display_width"].default)
        dh = sla_dict.get("display_height", SLAConfig.model_fields["display_height"].default)
        sla_dict["center_x"] = center[0] + dw / 2
        sla_dict["center_y"] = center[1] + dh / 2

    if sla_dict:
        return SLAConfig(**sla_dict)
    return None
