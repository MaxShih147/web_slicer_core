"""
API v2 endpoints - DS-Online compatible API.

This module provides API endpoints that match the DS-Online frontend's expected format.
Both v1 (/api/jobs) and v2 (/api/v2/slices) share the same underlying job manager.
"""

import asyncio
import io
import json
import logging
import math
import shutil
import time
import traceback as tb
import uuid
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

if TYPE_CHECKING:
    from .prz_decoder import PrzFile

import trimesh
from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile, Request
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel, ValidationError

from .errors import (
    APIError,
    boolean_failed,
    boolean_invalid_mesh,
    file_not_found,
    hollow_generation_failed,
    internal_error,
    invalid_model,
    job_already_executed,
    job_failed,
    job_not_found,
    job_still_processing,
    missing_body,
    model_not_found,
    model_out_of_bounds,
    no_drain_holes,
    no_hex_grid_cells,
    support_elevation_too_low,
    support_generation_failed,
    support_head_penetration_invalid,
    support_head_too_wide,
    support_pad_gap_conflict,
    support_points_required,
    validation_error,
)
from .jobs import (
    create_job,
    create_job_id,
    get_drain_holes_path,
    get_hollow_mesh_path,
    get_input_model_path,
    get_job_dir,
    get_job_progress,
    job_exists,
    read_job_status,
    run_slicing,
    run_support_generation,
    run_hollow_generation,
    run_cut_operation,
    write_job_status,
)
from .models import BooleanOperation, JobStatus, SLAConfig, _extract_prz_timing_config, gate_blur
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
    # Full Mechado config (Title Case "Print.*") for PRZ physical print-time sync;
    # kept separate from the snake_case slicing `config`. Optional / backward-compatible.
    prz_config: Optional[Dict[str, Any]] = None
    # Per-job geometry: model bounding-box center offset [x, y] from display center.
    # Frontend-only value (not part of the reusable Mechado printer profile), so it
    # rides as a top-level field rather than being injected into prz_config.
    center: Optional[List[float]] = None


class V2ConfigUpdateRequest(BaseModel):
    """Request to update slice job config."""
    config: Dict[str, Any]
    isAppend: bool = True
    # Full Mechado config (Title Case "Print.*") for PRZ physical print-time sync;
    # kept separate from the snake_case slicing `config`. Optional / backward-compatible.
    prz_config: Optional[Dict[str, Any]] = None


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

# Store for parsed PRZ file sessions
# Key: session_id (UUID v4 str)
# Value: (PrzFile, last_access_timestamp)  — PrzFile holds a memoryview into the raw bytes
_prz_sessions: Dict[str, Tuple["PrzFile", float]] = {}


# ============================================================================
# Helpers
# ============================================================================

def _require_pending(job_id: str) -> dict:
    """Return pending job dict, or raise JOB_NOT_FOUND / JOB_ALREADY_EXECUTED."""
    if job_id in _pending_jobs:
        return _pending_jobs[job_id]
    if job_exists(job_id):
        raise job_already_executed(job_id)
    raise job_not_found(job_id)


def _validate_stl_bytes(content: bytes, field: str = "model") -> None:
    """Raise invalid_model if *content* is not a valid STL."""
    try:
        mesh = trimesh.load(io.BytesIO(content), file_type="stl")
        if isinstance(mesh, trimesh.Scene):
            mesh = mesh.dump(concatenate=True)
        if not isinstance(mesh, trimesh.Trimesh) or len(mesh.faces) == 0:
            raise ValueError("empty mesh")
    except APIError:
        raise
    except Exception as exc:
        raise invalid_model(f"{field} STL content is corrupted or format is invalid: {exc}")


def _save_model_to_job(model_data: dict, input_path) -> None:
    """Write model bytes to *input_path*, raising INVALID_MODEL / VALIDATION_ERROR as needed."""
    if "stl_data" in model_data:
        content = model_data["stl_data"]
        _validate_stl_bytes(content, "model")
        with open(input_path, "wb") as f:
            f.write(content)
    elif "vertices" in model_data:
        raise validation_error("Direct vertex data is not yet supported; please use file upload")
    else:
        raise missing_body("Model must contain stl_data; please use file upload")


_ERROR_CODE_FACTORIES = {
    "HOLLOW_GENERATION_FAILED": hollow_generation_failed,
    "SUPPORT_HEAD_TOO_WIDE": support_head_too_wide,
    "SUPPORT_HEAD_PENETRATION_INVALID": support_head_penetration_invalid,
    "SUPPORT_ELEVATION_TOO_LOW": support_elevation_too_low,
    "SUPPORT_POINTS_REQUIRED": support_points_required,
    "SUPPORT_PAD_GAP_CONFLICT": support_pad_gap_conflict,
    "MODEL_OUT_OF_BOUNDS": model_out_of_bounds,
    "SUPPORT_GENERATION_FAILED": support_generation_failed,
}


def _error_from_status(status_data: dict) -> APIError:
    """Return the most specific APIError for a failed job based on its stored error_code."""
    code = status_data.get("error_code")
    factory = _ERROR_CODE_FACTORIES.get(code) if code else None
    if factory:
        return factory(status_data.get("error"))
    return job_failed(status_data.get("error"))


def _job_status_or_raise(job_id: str) -> dict:
    """Read job status, raising JOB_NOT_FOUND if the job doesn't exist."""
    if not job_exists(job_id):
        raise job_not_found(job_id)
    return read_job_status(job_id)


def _require_completed(status_data: dict, job_id: str) -> None:
    """Raise the appropriate error if the job is not completed."""
    status = status_data["status"]
    if status == JobStatus.FAILED.value:
        raise job_failed(status_data.get("error"))
    if status != JobStatus.COMPLETED.value:
        raise job_still_processing()


# ============================================================================
# V2 Router
# ============================================================================

router = APIRouter(prefix="/api/v2", tags=["v2-slices"])


def _evict_expired_sessions() -> None:
    """Evict PRZ sessions whose last_access timestamp is older than 1800 seconds."""
    now = time.time()
    expired = [sid for sid, (_, ts) in list(_prz_sessions.items()) if now - ts > 1800]
    for sid in expired:
        _prz_sessions.pop(sid, None)
        logger.debug("PRZ session evicted (TTL): %s", sid)


async def prz_session_cleanup_loop() -> None:
    """Background task: evict PRZ sessions idle for > 30 minutes.

    Scans every 5 minutes; removes sessions whose last_access timestamp is
    older than 1800 seconds.  Call via asyncio.create_task() at app startup.
    """
    while True:
        await asyncio.sleep(300)
        _evict_expired_sessions()


@router.post("/slices", response_model=V2Response)
async def create_slice_job(request: V2SliceCreateRequest):
    """
    Create a new slice job (DS-Online compatible).

    Unlike v1, this just creates a job ID and stores initial config.
    Models are added separately, and slicing starts on execute.
    """
    try:
        job_id = create_job_id()
        _pending_jobs[job_id] = {
            "config": request.config or {},
            "models": [],
            "status": "created",
        }
        if request.prz_config is not None:
            _pending_jobs[job_id]["prz_config"] = request.prz_config
        if request.center is not None:
            _pending_jobs[job_id]["center"] = request.center
        return V2Response(success=True, message="Slice job created", data={"jobId": job_id})
    except APIError:
        raise
    except Exception as exc:
        raise internal_error(str(exc))


@router.put("/slices/{job_id}/config", response_model=V2Response)
async def update_slice_job_config(job_id: str, request: V2ConfigUpdateRequest):
    """
    Update the config for a slice job.
    """
    pending = _require_pending(job_id)

    if request.isAppend:
        pending["config"].update(request.config)
    else:
        pending["config"] = request.config

    if request.prz_config is not None:
        pending["prz_config"] = request.prz_config

    return V2Response(success=True, message="Config updated")


@router.post("/slices/{job_id}/models", response_model=V2Response)
async def add_models_to_slice_job(job_id: str, request: V2ModelsAddRequest):
    """
    Add models to a slice job.

    Each model should contain vertex data or a reference to an uploaded file.
    """
    pending = _require_pending(job_id)

    if not request.models:
        raise missing_body("models list is empty")

    model_ids = []
    for i, model in enumerate(request.models):
        model_id = f"model_{i}_{len(pending['models'])}"
        pending["models"].append({"id": model_id, **model})
        model_ids.append(model_id)

    return V2Response(
        success=True,
        message=f"Added {len(model_ids)} model(s)",
        data={"modelIds": model_ids},
    )


@router.post("/slices/{job_id}/upload", response_model=V2Response)
async def upload_model_file(job_id: str, file: UploadFile = File(...)):
    """
    Upload an STL file to a slice job.

    This is the recommended way to add models - upload the file directly.
    The file will be stored and used when execute is called.
    """
    pending = _require_pending(job_id)

    if not file or not file.filename:
        raise missing_body("No file provided")

    if not file.filename.lower().endswith(".stl"):
        raise validation_error("Only .stl files are supported")

    try:
        content = await file.read()
    except APIError:
        raise
    except Exception as exc:
        raise internal_error(f"Failed to read uploaded file: {exc}")

    if not content:
        raise missing_body("Uploaded file is empty")

    _validate_stl_bytes(content, file.filename)

    model_id = f"file_{len(pending['models'])}"
    pending["models"].append({
        "id": model_id,
        "filename": file.filename,
        "stl_data": content,
        "type": "file_upload",
    })

    return V2Response(
        success=True,
        message=f"File '{file.filename}' uploaded",
        data={"modelId": model_id, "filename": file.filename},
    )


@router.post("/slices/{job_id}/upload-support", response_model=V2Response)
async def upload_support_file(job_id: str, file: UploadFile = File(...)):
    """
    Upload a separate support-mesh STL for the slice job.

    The support is kept distinct from the model (it is NOT merged) and is landed
    as input/support.stl on execute. run_slicing then passes it to the slicer via
    --import-support-stl, with self-generated supports/pad disabled. Sharing the
    model's world origin (Contract A) keeps the two aligned without a transform.
    """
    pending = _require_pending(job_id)

    if not file or not file.filename:
        raise missing_body("No support file provided")

    if not file.filename.lower().endswith(".stl"):
        raise validation_error("Only .stl files are supported for supports")

    try:
        content = await file.read()
    except APIError:
        raise
    except Exception as exc:
        raise internal_error(f"Failed to read uploaded support file: {exc}")

    if not content:
        raise missing_body("Uploaded support file is empty")

    _validate_stl_bytes(content, file.filename)

    pending["support_stl"] = content

    return V2Response(
        success=True,
        message=f"Support file '{file.filename}' uploaded",
        data={"filename": file.filename, "bytes": len(content)},
    )


@router.post("/slices/{job_id}/use-model-from/{source_job_id}", response_model=V2Response)
async def use_model_from_job(job_id: str, source_job_id: str, source_file: str = "boolean.stl"):
    """
    Reference an existing job's output file as the model for this slice job.
    Avoids re-uploading large files that are already on the server.
    """
    if job_id not in _pending_jobs:
        raise job_not_found(job_id)

    source_dir = get_job_dir(source_job_id)
    source_path = source_dir / "output" / source_file
    if not source_path.exists():
        source_path = source_dir / "input" / source_file
    if not source_path.exists():
        raise model_not_found(f"Source file '{source_file}' not found in job {source_job_id}")

    try:
        content = source_path.read_bytes()
    except Exception as exc:
        raise internal_error(f"Failed to read source file: {exc}")

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
        data={"modelId": model_id, "sourceJobId": source_job_id},
    )


@router.post("/slices/{job_id}/execute", response_model=V2Response)
async def execute_slice_job(job_id: str, background_tasks: BackgroundTasks):
    """
    Execute the slice job (start slicing).

    This triggers the actual PrusaSlicer process.
    """
    if job_id not in _pending_jobs:
        if job_exists(job_id):
            raise job_already_executed(job_id)
        raise job_not_found(job_id)

    pending = _pending_jobs[job_id]

    if not pending["models"]:
        raise model_not_found("No models have been added to this job")

    try:
        job_dir = create_job(job_id)
        input_path = job_dir / "input" / "model.stl"
        _save_model_to_job(pending["models"][0], input_path)
        # Land the separate support mesh (if uploaded) as input/support.stl.
        # run_slicing detects it and passes --import-support-stl to the slicer.
        support_blob = pending.get("support_stl")
        if support_blob:
            with open(job_dir / "input" / "support.stl", "wb") as f:
                f.write(support_blob)
        config = pending["config"]
        # Persist the Mechado prz_config (NOT the snake_case slicing config) so
        # run_slicing computes the PRZ physical print time from the same source
        # as the PRZ download path. Apply the same _inject_retract_overrides
        # pre-process as the download path for bit-wise consistency (design D5).
        prz_cfg = pending.get("prz_config")
        if prz_cfg is not None:
            _inject_retract_overrides(prz_cfg)
            with open(job_dir / "prz_config.json", "w") as f:
                json.dump(prz_cfg, f)
        sla_config = _build_sla_config(prz_cfg, config, pending.get("center"))
        del _pending_jobs[job_id]
        background_tasks.add_task(run_slicing, job_id, sla_config)
        return V2Response(success=True, message="Slicing started", data={"currentConfig": config})
    except APIError:
        raise
    except Exception as exc:
        raise internal_error(str(exc))


@router.post("/slices/{job_id}/generate-supports", response_model=V2Response)
async def generate_supports_only(job_id: str, background_tasks: BackgroundTasks):
    """
    Generate support mesh only (without slicing).

    This allows users to preview supports before committing to a full slice.
    The support mesh can be fetched via GET /api/jobs/{job_id}/support.stl
    """
    if job_id not in _pending_jobs:
        if job_exists(job_id):
            status = read_job_status(job_id)
            if status.get("has_support_mesh"):
                return V2Response(success=True, message="Supports already generated", data={"hasSupportMesh": True})
        raise job_not_found(job_id)

    pending = _pending_jobs[job_id]

    if not pending["models"]:
        raise model_not_found("No models have been added to this job")

    try:
        job_dir = create_job(job_id)
        input_path = job_dir / "input" / "model.stl"
        _save_model_to_job(pending["models"][0], input_path)
        config = pending["config"]
        config["supports_enable"] = True
        sla_config = _convert_v2_config_to_sla(config)
        pending["model_saved"] = True
        pending["job_dir"] = str(job_dir)
        background_tasks.add_task(run_support_generation, job_id, sla_config)
        return V2Response(success=True, message="Support generation started", data={"currentConfig": config})
    except APIError:
        raise
    except Exception as exc:
        raise internal_error(str(exc))


@router.post("/slices/{job_id}/generate-hollow", response_model=V2Response)
async def generate_hollow_only(job_id: str, background_tasks: BackgroundTasks):
    """
    Generate hollow interior mesh only (without slicing).

    This allows users to preview the hollow interior before committing to a full slice.
    The hollow mesh can be fetched via GET /api/jobs/{job_id}/hollow.stl
    """
    if job_id not in _pending_jobs:
        if job_exists(job_id):
            status = read_job_status(job_id)
            if status.get("has_hollow_mesh"):
                return V2Response(success=True, message="Hollow already generated", data={"hasHollowMesh": True})
        raise job_not_found(job_id)

    pending = _pending_jobs[job_id]

    if not pending["models"]:
        raise model_not_found("No models have been added to this job")

    try:
        job_dir = create_job(job_id)
        input_path = job_dir / "input" / "model.stl"
        _save_model_to_job(pending["models"][0], input_path)
        config = pending["config"]
        config["hollowing_enable"] = True
        sla_config = _convert_v2_config_to_sla(config)
        pending["model_saved"] = True
        pending["job_dir"] = str(job_dir)
        background_tasks.add_task(run_hollow_generation, job_id, sla_config)
        return V2Response(success=True, message="Hollow generation started", data={"currentConfig": config})
    except APIError:
        raise
    except Exception as exc:
        raise internal_error(str(exc))


@router.post("/slices/{job_id}/cut", response_model=V2Response)
async def cut_model(job_id: str, request: V2CutRequest, background_tasks: BackgroundTasks):
    """
    Cut model at specified Z height.

    This uses PrusaSlicer's --cut option to split the model into upper and lower parts.
    The upper part can be fetched via GET /api/jobs/{job_id}/cut.stl
    """
    if request.keep_mode not in ("both", "upper", "lower"):
        raise validation_error(
            f"keep_mode must be 'both', 'upper', or 'lower'; got '{request.keep_mode}'"
        )

    if job_id not in _pending_jobs:
        if job_exists(job_id):
            status = read_job_status(job_id)
            if status.get("has_cut_mesh"):
                return V2Response(success=True, message="Cut already performed", data={"hasCutMesh": True})
        raise job_not_found(job_id)

    pending = _pending_jobs[job_id]

    if not pending["models"]:
        raise model_not_found("No models have been added to this job")

    try:
        job_dir = create_job(job_id)
        input_path = job_dir / "input" / "model.stl"
        _save_model_to_job(pending["models"][0], input_path)
        pending["model_saved"] = True
        pending["job_dir"] = str(job_dir)
        background_tasks.add_task(run_cut_operation, job_id, request.cut_height, request.keep_mode)
        return V2Response(
            success=True,
            message="Cut operation started",
            data={"cutHeight": request.cut_height, "keepMode": request.keep_mode},
        )
    except APIError:
        raise
    except Exception as exc:
        raise internal_error(str(exc))


@router.post("/slices/{job_id}/extend-bottom", response_model=V2Response)
async def extend_bottom(job_id: str, request: V2ExtendBottomRequest):
    """
    Extend bottom vertices of the hollow mesh downward.

    Synchronous operation — reads hollow.stl, moves bottom vertices down,
    recomputes normals, and overwrites the file.
    """
    if not job_exists(job_id):
        raise job_not_found(job_id)

    if request.bottom_z_threshold < 0:
        raise validation_error("bottom_z_threshold must be >= 0")
    if request.extension_distance < 0:
        raise validation_error("extension_distance must be >= 0")

    hollow_path = get_hollow_mesh_path(job_id)
    if hollow_path is None:
        raise model_not_found("Hollow mesh not found for this job")

    try:
        triangles = parse_binary_stl(hollow_path)
    except Exception as exc:
        raise invalid_model(f"Hollow mesh could not be parsed: {exc}")

    if not triangles:
        raise invalid_model("Hollow mesh is empty or invalid")

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

    try:
        # Overwrite hollow.stl
        write_binary_stl(hollow_path, new_triangles, "hollow extended")
    except Exception as exc:
        raise internal_error(f"Failed to write extended hollow mesh: {exc}")

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
        raise job_not_found(job_id)

    if request.drain_radius < 0:
        raise validation_error("drain_radius must be >= 0")
    if request.hex_cell_radius <= 0:
        raise validation_error("hex_cell_radius must be > 0")
    if request.wall_thickness < 0:
        raise validation_error("wall_thickness must be >= 0")

    try:
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
    except APIError:
        raise
    except Exception as exc:
        raise internal_error(str(exc))

    if mesh is None:
        raise no_drain_holes()

    try:
        output_path = output_dir / "model_drain_holes.stl"
        mesh.export(str(output_path))
    except Exception as exc:
        raise internal_error(f"Failed to save drain holes mesh: {exc}")

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
        raise job_not_found(job_id)

    if request.hex_cell_radius <= 0:
        raise validation_error("hex_cell_radius must be > 0")
    if request.wall_thickness < 0:
        raise validation_error("wall_thickness must be >= 0")

    hollow_path = get_hollow_mesh_path(job_id)
    if hollow_path is None:
        raise model_not_found("Hollow mesh not found for this job")

    try:
        # Reset boolean debug counter and prepare debug folder
        global _boolean_step_counter
        _boolean_step_counter = 0
        job_dir = get_job_dir(job_id)
        debug_dir = job_dir / "debug"
        if debug_dir.exists():
            shutil.rmtree(debug_dir)
        debug_dir.mkdir(exist_ok=True)

        hollow_mesh = load_trimesh(hollow_path)
    except APIError:
        raise
    except Exception as exc:
        raise invalid_model(f"Failed to load hollow mesh: {exc}")

    try:
        # PrusaSlicer centers the model's bounding box at origin before hollowing.
        # Undo this by translating the hollow mesh by the input model's bbox center.
        input_model_path = get_input_model_path(job_id)
        if input_model_path is not None:
            input_mesh = load_trimesh(input_model_path)
            input_center = (input_mesh.bounds[0] + input_mesh.bounds[1]) / 2
            hollow_mesh.apply_translation(input_center)
            shutil.copy2(input_model_path, debug_dir / "input_model_outer.stl")

        logger.info(
            f"generate-hex-grid: hollow bounds={hollow_mesh.bounds.tolist()}, "
            f"bottom_z={request.bottom_z}"
        )

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
    except APIError:
        raise
    except Exception as exc:
        raise internal_error(str(exc))

    if mesh is None:
        raise no_hex_grid_cells()

    try:
        output_dir = job_dir / "output"
        output_dir.mkdir(exist_ok=True)
        mesh.export(str(output_dir / "model_hex_grid.stl"))
    except Exception as exc:
        raise internal_error(f"Failed to save hex grid mesh: {exc}")

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
    except APIError:
        raise
    except Exception as exc:
        logger.exception(f"Boolean {operation} failed")
        raise internal_error(str(exc))


_boolean_step_counter = 0


async def _boolean_operation_impl(mesh_a, mesh_b, operation, parent_job_id=None):
    global _boolean_step_counter
    _boolean_step_counter += 1
    step = _boolean_step_counter

    try:
        bool_op = BooleanOperation(operation)
    except ValueError:
        raise validation_error(
            f"Invalid operation '{operation}'; must be 'union', 'difference', or 'intersection'"
        )

    for f, name in [(mesh_a, "mesh_a"), (mesh_b, "mesh_b")]:
        if not f or not f.filename:
            raise missing_body(f"{name} file is required")
        if not f.filename.lower().endswith(".stl"):
            raise validation_error(f"{name} must be an STL file")

    try:
        mesh_a_content = await mesh_a.read()
        mesh_b_content = await mesh_b.read()
    except Exception as exc:
        raise internal_error(f"Failed to read uploaded files: {exc}")

    _validate_stl_bytes(mesh_a_content, "mesh_a")
    _validate_stl_bytes(mesh_b_content, "mesh_b")

    try:
        job_id = create_job_id()
        job_dir = create_job(job_id)
        write_job_status(job_id, JobStatus.PROCESSING)
        input_dir = job_dir / "input"
        mesh_a_path = input_dir / "mesh_a.stl"
        mesh_b_path = input_dir / "mesh_b.stl"

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
    except APIError:
        raise
    except Exception as exc:
        raise internal_error(str(exc))

    if not result.success:
        write_job_status(job_id, JobStatus.FAILED, error=result.error)
        if result.error_code == "BOOLEAN_INVALID_MESH":
            raise boolean_invalid_mesh()
        raise boolean_failed(result.error)

    if debug_dir and result.boolean_mesh_path and result.boolean_mesh_path.exists():
        shutil.copy2(result.boolean_mesh_path, debug_dir / f"step{step}_{operation}_output.stl")

    write_job_status(job_id, JobStatus.COMPLETED)

    return V2Response(
        success=True,
        message=f"Boolean {operation} completed",
        data={
            "jobId": job_id,
            "operation": operation,
            "resultPath": f"/api/jobs/{job_id}/boolean.stl",
        },
    )


@router.get("/slices/{job_id}/preview.zip")
async def get_preview_zip_v2(job_id: str):
    """
    Get a ZIP of downscaled WebP preview images for layer display.
    Pre-generated in background after slicing; generated on-demand if not ready.
    """
    status_data = _job_status_or_raise(job_id)
    _require_completed(status_data, job_id)

    job_dir = get_job_dir(job_id)
    sl1_path = job_dir / "output" / "model.sl1"
    prusa_preview_path = job_dir / "output" / "model_preview.zip"
    preview_path = job_dir / "output" / "preview.zip"

    if not sl1_path.exists():
        raise file_not_found(".sl1 archive not found")

    # Prefer PrusaSlicer-generated preview ZIP (much faster)
    if prusa_preview_path.exists():
        return FileResponse(prusa_preview_path, media_type="application/zip", filename="preview.zip")

    # Fallback: Python-generated preview
    import asyncio
    from .preview_service import generate_preview_zip
    try:
        await asyncio.get_event_loop().run_in_executor(None, generate_preview_zip, sl1_path, preview_path)
    except Exception as exc:
        raise internal_error(f"Failed to generate preview: {exc}")

    return FileResponse(preview_path, media_type="application/zip", filename="preview.zip")


def _rle_sl1_to_png_zip(sl1_path) -> bytes:
    """[layer-rle] Convert an RLE-layer .sl1 to a ZIP of layer PNGs on demand.

    Used by the layers.zip endpoint when PrusaSlicer emitted RLE layers (the
    fast PRZ path) but a PNG-expecting consumer (rare frontend fallback) asks
    for layer PNGs. The decoded bitmaps are identical to the original PNG path.
    """
    import io
    import zipfile

    from .prz_decoder import rle_layer_to_png
    from .prz_encoder import sl1_layer_names

    with zipfile.ZipFile(sl1_path) as zf:
        names = zf.namelist()
        # 層檔列舉統一走 sl1_layer_names（單一真值來源）。此路徑僅在 RLE 模式被呼叫，
        # 故選出的即 .rle 層檔（.rle 優先）。
        rle_names = [n for n in sl1_layer_names(names) if n.endswith(".rle")]
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w", zipfile.ZIP_STORED) as oz:
            for name in rle_names:
                # 共用單層解碼 helper；整包語意：解析度缺失（helper 回 None）即整包無效 → raise。
                png = rle_layer_to_png(zf, name)
                if png is None:
                    raise validation_error("cannot determine layer resolution for RLE->PNG")
                oz.writestr(name[:-4] + ".png", png)
        return out.getvalue()


@router.get("/slices/{job_id}/layers.zip")
async def get_layers_zip_v2(job_id: str):
    """
    Get layer PNGs as a ZIP. Standard PNG .sl1 is served directly (zero
    processing). If PrusaSlicer emitted RLE layers (fast PRZ path), they are
    converted back to PNG on demand for this rare PNG-expecting fallback.
    """
    status_data = _job_status_or_raise(job_id)
    _require_completed(status_data, job_id)

    sl1_path = get_job_dir(job_id) / "output" / "model.sl1"
    if not sl1_path.exists():
        raise file_not_found(".sl1 archive not found")

    import zipfile
    with zipfile.ZipFile(sl1_path) as zf:
        has_rle = any(n.endswith(".rle") for n in zf.namelist())

    if not has_rle:
        return FileResponse(sl1_path, media_type="application/zip", filename="layers.zip")

    png_zip = await asyncio.get_event_loop().run_in_executor(
        None, _rle_sl1_to_png_zip, sl1_path
    )
    return Response(
        content=png_zip,
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=layers.zip"},
    )


def _decode_preview_rgb(field: Optional[dict]) -> Optional["np.ndarray"]:
    """Decode a preview field { width, height, rgb_b64 } into (H, W, 3) uint8.
    Returns None if missing/invalid; encoder will fall back to a black preview."""
    if not isinstance(field, dict):
        return None
    width = field.get("width")
    height = field.get("height")
    b64 = field.get("rgb_b64")
    if not (isinstance(width, int) and isinstance(height, int) and isinstance(b64, str)):
        return None
    if width <= 0 or height <= 0:
        return None
    import base64
    import numpy as np
    try:
        raw = base64.b64decode(b64, validate=False)
    except Exception:
        return None
    if len(raw) != width * height * 3:
        return None
    return np.frombuffer(raw, dtype=np.uint8).reshape(height, width, 3)


@router.post("/slices/{job_id}/download.prz")
async def download_prz_v2(job_id: str, request: Request):
    """
    Generate and stream a PRZ file from the .sl1 layers + posted config.

    POST body is JSON:
      - Mechado config fields (same structure as default profile), AND
      - optional `preview_small`: { width, height, rgb_b64 } (raw RGB Uint8Array, base64)
      - optional `preview_large`: { width, height, rgb_b64 }
    The encoder will Lanczos-resize previews to PRZ's 116×116 / 290×290 slots.
    """
    status_data = _job_status_or_raise(job_id)
    _require_completed(status_data, job_id)

    sl1_path = get_job_dir(job_id) / "output" / "model.sl1"
    if not sl1_path.exists():
        raise file_not_found(".sl1 archive not found")

    # config body 與 preview 皆為 optional。容忍空 body（不視為錯誤），
    # 以便支援「config 已存在 job 內」的新流程。
    raw = await request.body()
    if raw:
        try:
            body = json.loads(raw)
        except Exception:
            raise validation_error("Request body must be valid JSON")
        if not isinstance(body, dict):
            raise validation_error("Request body must be a JSON object")
    else:
        body = {}

    preview_small_rgb = _decode_preview_rgb(body.pop("preview_small", None))
    preview_large_rgb = _decode_preview_rgb(body.pop("preview_large", None))
    config = _resolve_prz_download_config(job_id, body)
    _inject_retract_overrides(config)

    try:
        timing = _extract_prz_timing_config(config)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors())

    from .prz_encoder import encode_prz_streaming

    return StreamingResponse(
        encode_prz_streaming(
            config=config,
            sl1_path=sl1_path,
            timing=timing,
            resin_volume_mm3=(status_data.get("resin_volume_ml") or 0) * 1000,
            preview_small_rgb=preview_small_rgb,
            preview_large_rgb=preview_large_rgb,
        ),
        media_type="application/octet-stream",
        headers={"Content-Disposition": "attachment; filename=model.prz"},
    )


@router.post("/detect-boundary", response_model=V2Response)
async def detect_boundary_endpoint(file: UploadFile = File(...)):
    """Detect boundary edges on an uploaded STL mesh and return boundary loop points."""
    import asyncio
    import tempfile
    from .boundary_detection import detect_boundary

    with tempfile.NamedTemporaryFile(suffix=".stl", delete=False) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

    try:
        result = await asyncio.to_thread(detect_boundary, tmp_path)
    finally:
        import os
        os.unlink(tmp_path)

    if not result.loops:
        return V2Response(success=True, message="No boundary loops found", data={"loops": []})

    loops_data = []
    for i, loop in enumerate(result.loops):
        loops_data.append({
            "index": i,
            "vertex_count": len(loop.vertex_indices),
            "perimeter": round(loop.perimeter, 2),
            "centroid": loop.centroid.tolist(),
            "points": loop.points.tolist(),
            "is_main": i == result.main_loop_index,
        })

    return V2Response(
        success=True,
        data={
            "total_boundary_edges": result.total_boundary_edges,
            "loop_count": len(result.loops),
            "main_loop_index": result.main_loop_index,
            "loops": loops_data,
        },
    )


@router.post("/smooth-boundary", response_model=V2Response)
async def smooth_boundary_endpoint(request: Request):
    """
    Smooth boundary loop points using Taubin smoothing.

    Accepts raw points and smoothing parameters, returns smoothed points.
    No STL upload needed — works purely on point data.
    """
    import numpy as np
    from .boundary_detection import smooth_boundary_loop

    body = await request.json()
    loops = body.get("loops", [])
    iterations = body.get("iterations", 20)
    lam = body.get("lambda", 0.5)
    mu = body.get("mu", -0.53)

    smoothed_loops = []
    for loop in loops:
        points = np.array(loop["points"], dtype=np.float64)
        smoothed = smooth_boundary_loop(points, iterations=iterations, lam=lam, mu=mu)
        smoothed_loops.append({
            "points": smoothed.tolist(),
            "perimeter": round(float(np.sum(np.linalg.norm(
                np.diff(smoothed, axis=0, append=smoothed[:1]), axis=1
            ))), 2),
        })

    return V2Response(success=True, data={"loops": smoothed_loops})


@router.post("/apply-boundary")
async def apply_boundary_endpoint(
    file: UploadFile = File(...),
    data: str = Form(...),
):
    """
    Apply smoothed boundary to mesh vertices with gradual falloff.

    Accepts STL file + JSON data with original/smoothed points.
    Returns modified STL file.
    """
    import asyncio
    import json
    import tempfile
    from .boundary_detection import apply_boundary_to_mesh

    params = json.loads(data)
    original_points = params["original_points"]
    smoothed_points = params["smoothed_points"]
    falloff_rings = params.get("falloff_rings", 3)

    with tempfile.NamedTemporaryFile(suffix=".stl", delete=False) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

    try:
        stl_bytes = await asyncio.to_thread(
            apply_boundary_to_mesh,
            tmp_path,
            original_points,
            smoothed_points,
            falloff_rings,
        )
    finally:
        import os
        os.unlink(tmp_path)

    return Response(
        content=stl_bytes,
        media_type="application/octet-stream",
        headers={"Content-Disposition": "attachment; filename=model.stl"},
    )


@router.post("/generate-base")
async def generate_base_endpoint(
    file: UploadFile = File(...),
    elevation: float = Form(0.1),
    chamfer: bool = Form(False),
    skip_orient: bool = Form(False),
):
    """
    Generate base for dental mesh: auto-orient + wall + bottom.

    Accepts STL file only. Backend auto-detects boundary, orients mesh,
    and generates wall + bottom face.
    Returns combined STL (original + wall + bottom).
    """
    import asyncio
    import tempfile
    from .boundary_detection import generate_base

    with tempfile.NamedTemporaryFile(suffix=".stl", delete=False) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

    try:
        stl_bytes = await asyncio.to_thread(
            generate_base,
            tmp_path,
            elevation=elevation,
            chamfer=chamfer,
            skip_orient=skip_orient,
        )
    finally:
        import os
        os.unlink(tmp_path)

    return Response(
        content=stl_bytes,
        media_type="application/octet-stream",
        headers={"Content-Disposition": "attachment; filename=model_with_base.stl"},
    )


@router.post("/apply-boundary-and-base")
async def apply_boundary_and_base_endpoint(
    file: UploadFile = File(...),
    data: str = Form(...),
):
    """
    Consolidated base generation: apply the smoothed boundary AND generate the
    base in a single call, parsing the STL only once. Avoids the second upload +
    parse + vertex-merge that calling /apply-boundary then /generate-base incurs.

    ``data`` is JSON with: original_points, smoothed_points, falloff_rings,
    elevation, chamfer, skip_orient. Returns the combined STL.
    """
    import asyncio
    import json
    import os
    import tempfile
    from .boundary_detection import apply_boundary_then_base

    params = json.loads(data)
    with tempfile.NamedTemporaryFile(suffix=".stl", delete=False) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

    try:
        stl_bytes = await asyncio.to_thread(
            apply_boundary_then_base,
            tmp_path,
            params["original_points"],
            params["smoothed_points"],
            params.get("elevation", 0.1),
            params.get("chamfer", False),
            params.get("skip_orient", True),
            params.get("falloff_rings", 3),
        )
    finally:
        os.unlink(tmp_path)

    return Response(
        content=stl_bytes,
        media_type="application/octet-stream",
        headers={"Content-Disposition": "attachment; filename=model_with_base.stl"},
    )


@router.post("/auto-orient", response_model=V2Response)
async def auto_orient_endpoint(
    file: UploadFile = File(...),
    mode: int = Form(2),
    debug: bool = Form(False),
):
    """
    Compute dental auto-orientation Euler angles for an uploaded model.

    Accepts a local-space STL. Returns ``data.rotation_rad = [rx, ry, rz]``
    (radians) to be applied with Euler order 'ZYX' on the frontend.

    When ``debug`` is true, also returns the debug mesh info (decision/candidate/
    concave face indices + drill cylinders) for visualization. Default is off —
    those arrays are large, so they are only computed/sent on demand.

    Currently only surgical-guide mode (2) is ported to the backend; other
    modes still run in the frontend WASM module.
    """
    import os
    import tempfile

    import numpy as np

    if mode != 2:
        return V2Response(
            success=False,
            message=f"auto-orient mode {mode} is not supported on the backend yet",
        )

    with tempfile.NamedTemporaryFile(suffix=".stl", delete=False) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

    try:
        mesh = load_trimesh(tmp_path)
        vertices = np.asarray(mesh.vertices, dtype=np.float32)
        faces = np.asarray(mesh.faces, dtype=np.uint32)

        from .auto_orient_surg_guide import compute_auto_orientation_surg_guide_detail

        detail = await asyncio.to_thread(
            compute_auto_orientation_surg_guide_detail, vertices, faces, False, debug
        )
    finally:
        os.unlink(tmp_path)

    data = {"rotation_rad": detail["rotation_rad"]}
    if debug:
        data.update({
            "decision_faces": detail["decision_faces"],
            "step_faces": detail["step_faces"],
            "candidate_faces": detail["candidate_faces"],
            "concave_faces": detail.get("concave_faces", []),
            "cylinders": detail.get("cylinders", []),
        })
    return V2Response(success=True, data=data)


@router.get("/slices/{job_id}", response_model=V2Response)
async def get_slice_job_status(job_id: str):
    """
    Get the status of a slice job.
    """
    # Check disk status first (for jobs that have been executed/generated)
    if job_exists(job_id):
        status_data = read_job_status(job_id)
        if status_data["status"] != "pending":
            if status_data["status"] == JobStatus.FAILED.value:
                # Return 200 with structured failure info so polling clients can
                # distinguish "still running" (success:true) from "failed" (success:false)
                # without interpreting a 409 as a client-side error.
                err = _error_from_status(status_data)
                from fastapi.responses import JSONResponse
                return JSONResponse(
                    status_code=200,
                    content={
                        "success": False,
                        "code": err.code,
                        "message": err.message,
                        "data": {"retryable": err.retryable, "traceId": err.trace_id},
                    },
                )
            response_data = {
                "jobId": job_id,
                "status": status_data["status"],
                "layerCount": status_data.get("layer_count"),
                "estimatedPrintTime": status_data.get("estimated_print_time"),
                "resinVolumeMl": status_data.get("resin_volume_ml"),
                "error": status_data.get("error"),
                # Neutral support outcome (e.g. SUPPORT_NOT_NEEDED) rides on the
                # success:true path — a "no supports needed" result is NOT a
                # failure and must not block downstream slicing.
                "supportOutcome": status_data.get("support_outcome"),
                "hasSupportMesh": status_data.get("has_support_mesh", False),
                "hasHollowMesh": status_data.get("has_hollow_mesh", False),
                "hasCutMesh": status_data.get("has_cut_mesh", False),
                "hasOrthoResult": status_data.get("has_ortho_result", False),
            }
            if "ortho_progress" in status_data:
                response_data["orthoProgress"] = status_data["ortho_progress"]

            # Slice progress (percent + STAGE_* identifier) lives in the agent's
            # in-memory store, not status.json. The field is OMITTED entirely when
            # unavailable — never 0 or null, which a polling client would read as
            # the progress going backwards. Terminal jobs have already had their
            # entry cleared, so a COMPLETED response carries no progress.
            progress = get_job_progress(job_id)
            if progress is not None:
                response_data["progress"] = progress

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
            },
        )

    raise job_not_found(job_id)


@router.get("/slices/{job_id}/uchars", response_model=V2Response)
async def get_slice_uchars(job_id: str):
    """
    Get layer data as unsigned char arrays (for DS-Online compatibility).

    Note: This returns layer count and paths. Actual pixel data would need
    to be fetched separately due to size.
    """
    status_data = _job_status_or_raise(job_id)
    _require_completed(status_data, job_id)

    layer_count = status_data.get("layer_count", 0)

    # Return layer metadata (actual data fetched via /layers/{idx}.png)
    return V2Response(
        success=True,
        data={
            "uchars": {
                "layerCount": layer_count,
                "layerEndpoint": f"/api/v2/slices/{job_id}/layers/{{idx}}.png",
            }
        },
    )


@router.get("/slices/{job_id}/gcode", response_model=V2Response)
async def get_slice_gcode(job_id: str):
    """
    Get G-code for the slice job.

    Note: PrusaSlicer SLA output is .sl1 (images), not G-code.
    This endpoint returns metadata about the slicing result.
    """
    status_data = _job_status_or_raise(job_id)
    _require_completed(status_data, job_id)

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
    pending = _require_pending(job_id)

    if not pending["models"]:
        raise model_not_found("No models have been added to this job")

    try:
        job_dir = create_job(job_id)
        input_path = job_dir / "input" / "model.stl"
        _save_model_to_job(pending["models"][0], input_path)
        del _pending_jobs[job_id]

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
        return V2Response(success=True, message="Ortho processing pipeline started", data={"jobId": job_id})
    except APIError:
        raise
    except Exception as exc:
        raise internal_error(str(exc))


# ============================================================================
# PRZ Parser Endpoint
# ============================================================================

_PRZ_MAX_UPLOAD_BYTES = 500 * 1024 * 1024  # 500 MB


def _ndarray_to_png_bytes(arr) -> bytes:
    """Encode a uint8 numpy ndarray as PNG bytes (grayscale or RGB)."""
    from io import BytesIO
    from PIL import Image
    buf = BytesIO()
    Image.fromarray(arr).save(buf, format="PNG")
    return buf.getvalue()


@router.post("/prz/parse")
async def parse_prz_endpoint(file: UploadFile = File(..., description="PRZ V3.0 binary file")):
    """
    Parse a PRZ V3.0 file and return its header fields plus base64 preview images.

    Accepts multipart/form-data with a 'file' field containing a .prz binary.
    Returns JSON: header fields, preview_small_b64 (PNG base64), preview_large_b64 (PNG base64),
    layer_count, and session_id for subsequent layer image requests.
    """
    import base64
    import dataclasses

    from .prz_decoder import parse_prz

    file_data = await file.read()
    if len(file_data) > _PRZ_MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File too large (max 500 MB)")

    try:
        prz = parse_prz(file_data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    session_id = str(uuid.uuid4())
    _prz_sessions[session_id] = (prz, time.time())

    return {
        "header": dataclasses.asdict(prz.header),
        "preview_small_b64": base64.b64encode(_ndarray_to_png_bytes(prz.preview_small)).decode(),
        "preview_large_b64": base64.b64encode(_ndarray_to_png_bytes(prz.preview_large)).decode(),
        "layer_count": prz.header.total_layers,
        "session_id": session_id,
    }


@router.get("/prz/{session_id}/layer/{index}")
async def get_prz_layer(session_id: str, index: int):
    """
    Return a single decoded PRZ layer as a grayscale PNG.

    Requires a session_id obtained from POST /prz/parse.
    Each successful call resets the session TTL (30 minutes).
    """
    entry = _prz_sessions.get(session_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"PRZ session not found: {session_id}")

    prz, _ = entry
    layer_count = prz.header.total_layers
    if index < 0 or index >= layer_count:
        raise HTTPException(
            status_code=422,
            detail=f"Layer index {index} out of range [0, {layer_count})",
        )

    arr = prz.decode_layer_image(index)
    _prz_sessions[session_id] = (prz, time.time())  # reset TTL

    return Response(content=_ndarray_to_png_bytes(arr), media_type="image/png")


@router.delete("/prz/{session_id}", status_code=204)
async def delete_prz_session(session_id: str):
    """
    Release a PRZ session from server memory.

    Call this when the viewer is closed to free the cached PRZ file immediately
    rather than waiting for the TTL to expire.
    """
    if session_id not in _prz_sessions:
        raise HTTPException(status_code=404, detail=f"PRZ session not found: {session_id}")
    _prz_sessions.pop(session_id)
    return Response(status_code=204)


# ============================================================================
# Helper Functions
# ============================================================================

# SLAConfig snake_case key → Mechado "Print.*" Title Case key
_SLA_RETRACT_TO_MECHADO = {
    "retract_distance":               "Retract Distance",
    "bottom_retract_distance":        "Bottom Retract Distance",
    "retract_second_distance":        "Retract Second Distance",
    "bottom_retract_second_distance": "Bottom Retract Second Distance",
}


def _inject_retract_overrides(config: Dict[str, Any]) -> None:
    """Guarantee retract keys land in the nested Mechado `Print` section.

    The PRZ encoder reads via `_get_float(config, "Print.Retract Distance")`,
    which splits on `.` and requires NESTED dict structure:
        config["Print"]["Retract Distance"]

    Frontend may send any of these source formats; this function normalises
    them all into the nested form expected by the encoder (priority order):

      1. Nested Mechado:     config["Print"]["Retract Distance"]   ← canonical
      2. Top-level Mechado:  config["Retract Distance"]
      3. Dotted-flat:        config["Print.Retract Distance"]
      4. SLAConfig snake:    config["retract_distance"]

    Mutates `config` in-place: ensures `config["Print"]` is a dict and contains
    every available retract key under its Mechado Title Case name.
    """
    print_section = config.get("Print")
    if not isinstance(print_section, dict):
        print_section = {}
        config["Print"] = print_section

    for sla_key, mechado_key in _SLA_RETRACT_TO_MECHADO.items():
        if mechado_key in print_section:
            continue  # canonical nested form already present
        if mechado_key in config:
            print_section[mechado_key] = config[mechado_key]
            continue
        dotted = f"Print.{mechado_key}"
        if dotted in config:
            print_section[mechado_key] = config[dotted]
            continue
        if sla_key in config:
            print_section[mechado_key] = config[sla_key]


# blur 閘控的真值來源已移至 `models.gate_blur`，因為 `prz_encoder` 也要用它，而
# prz_encoder 是本模組的下游——留在這裡會迫使它反向匯入整個路由模組。此別名保留
# 既有呼叫點與測試中的 `_gate_blur` 名稱。
_gate_blur = gate_blur


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
        "Shrinkage Compensation": "shrinkage_compensation",
        "Shrinkage Compensation X": "shrinkage_compensation_x",
        "Shrinkage Compensation Y": "shrinkage_compensation_y",
        "Shrinkage Compensation Z": "shrinkage_compensation_z",
        "Tolerance Compensation": "tolerance_compensation",
        "Tolerance Compensation A": "tolerance_compensation_a",
        "Tolerance Compensation B": "tolerance_compensation_b",
        "Bottom Tolerance Compensation": "bottom_tolerance_compensation",
        "Bottom Tolerance Compensation A": "bottom_tolerance_compensation_a",
        "Bottom Tolerance Compensation B": "bottom_tolerance_compensation_b",
        "Bottom Layer Count": "bottom_layer_count",
        "Retract Distance": "retract_distance",
        "Bottom Retract Distance": "bottom_retract_distance",
        "Retract Second Distance": "retract_second_distance",
        "Bottom Retract Second Distance": "bottom_retract_second_distance",
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

    # `Image Blur` 開關閘控（見 _gate_blur）。必須在 mapping 迴圈之後套用，才能作用在
    # 已解析出的強度值上——不論它來自 snake `blur` 還是 DS-Online 的 `Image Blur Pixel`。
    blur_gated = _gate_blur(print_config.get("Image Blur"), sla_dict.get("blur"))
    if blur_gated is not None:
        sla_dict["blur"] = blur_gated

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


def _extract_sla_from_mechado(
    mechado: Dict[str, Any],
    center: Optional[List[float]] = None,
) -> Dict[str, Any]:
    """從完整三段式 mechado config 萃取 SLAConfig 切片參數（回傳 dict，未建模）。

    方案 B（單一真相）：DS-Online 前端只送一份完整 mechado config（含 Machine /
    Print / Advanced 三段），後端由此萃取出 prusa 切片所需的 snake_case 欄位。

    與 `_convert_v2_config_to_sla` 的差異：本函式理解三段式巢狀結構，並涵蓋
    `Machine` 與 `Advanced` 區段（舊函式僅讀 `Print` 或頂層 snake，會丟失這兩段）。

    重要約定：
      - `display_width`/`display_height` 取自 `Machine.bed_size[2]`/`[3]`
        （bed_size 結構為 [x0, y0, x1, y1]，前兩元素為原點，非幅面尺寸）。
      - `Advanced.Anti-aliasing Level` 與 `Advanced.Image Blur Pixel` 在 mechado
        中已是後端刻度（前端 uiToDefault 已套 UI→backend 轉換），此處直接複製，
        不可再套任何刻度轉換。
      - `blur` 額外受 `Advanced."Image Blur"` 開關閘控（見 `_gate_blur`）。開關與刻度
        正交：閘控只決定要不要套用，不改變強度值本身。
      - `printer_model` 取自 `Machine.machine_type`（前端不另傳）。
      - 任一來源欄位缺失時，留給 SLAConfig 預設值，不拋錯（僅記 log）。

    NOTE: 萃取出的 `anti_aliasing_level` 為切片控制值（Prusa 刻度 0/1/2），僅供
    SLAConfig / prusa_slicer_fork 使用，不代表 PRZ 最終的顯示內容。
    """
    machine = mechado.get("Machine") or {}
    print_c = mechado.get("Print") or {}
    advanced = mechado.get("Advanced") or {}
    out: Dict[str, Any] = {}

    def put(key: str, val: Any) -> None:
        """僅在來源存在（非 None）時寫入；缺值留給 SLAConfig 預設。"""
        if val is not None:
            out[key] = val

    # ── 核心 9 欄位（對應前端 uiToBackendSlicing 權威清單）──────────────
    put("layer_height", print_c.get("Layer Height"))                      # 1

    image_size = machine.get("image_size")
    if isinstance(image_size, list) and len(image_size) >= 2:
        put("display_pixels_x", image_size[0])                            # 2
        put("display_pixels_y", image_size[1])                            # 3

    bed_size = machine.get("bed_size")                                    # [x0, y0, x1, y1]
    if isinstance(bed_size, list) and len(bed_size) >= 4:
        put("display_width", bed_size[2])                                 # 4  (索引標準)
        put("display_height", bed_size[3])                                # 5  (索引標準)

    put("anti_aliasing", advanced.get("Anti-aliasing"))                  # 6
    put("anti_aliasing_level", advanced.get("Anti-aliasing Level"))      # 7  直接複製
    put("gray_level", advanced.get("Grey Level"))                        # 8
    # 9  強度直接複製（不得二次刻度轉換），但受 `Image Blur` 開關閘控——見 _gate_blur
    put("blur", _gate_blur(advanced.get("Image Blur"),
                           advanced.get("Image Blur Pixel")))

    # ── 隨附欄位（非幾何 9 欄，但 SLAConfig 需要）────────────────────────
    put("printer_model", machine.get("machine_type"))
    put("exposure_time", print_c.get("Exposure Time"))
    put("initial_exposure_time", print_c.get("Bottom Exposure Time"))
    put("bottom_layer_count", print_c.get("Bottom Layer Count"))
    for sla_key, mechado_key in _SLA_RETRACT_TO_MECHADO.items():
        put(sla_key, print_c.get(mechado_key))

    # ── center：相對位移 → 絕對座標（依賴正確的 display_width/height）─────
    if isinstance(center, list) and len(center) >= 2:
        dw = out.get("display_width", SLAConfig.model_fields["display_width"].default)
        dh = out.get("display_height", SLAConfig.model_fields["display_height"].default)
        out["center_x"] = center[0] + dw / 2
        out["center_y"] = center[1] + dh / 2

    # 缺關鍵幾何欄位時記 log（不拋錯），便於除錯靜默退預設的情況。
    for critical in ("layer_height", "display_width", "display_height"):
        if critical not in out:
            logger.warning(
                "_extract_sla_from_mechado: missing '%s' in mechado config; "
                "SLAConfig default will be used", critical,
            )

    return out


def _resolve_prz_download_config(job_id: str, config: Dict[str, Any]) -> Dict[str, Any]:
    """解析 download.prz 的 config 來源（design：config body 改 optional）。

    - body 顯式提供（非空）config → 以 body 為優先，直接回傳。
    - body 未提供 config → 降級從 job 持久化的 `prz_config.json` 讀取。
    - 兩者皆無 → 拋出 validation error（無可用 config 生成 PRZ）。
    """
    if config:
        return config
    prz_config_path = get_job_dir(job_id) / "prz_config.json"
    if prz_config_path.exists():
        with open(prz_config_path) as f:
            return json.load(f)
    raise validation_error(
        "No config provided in request body and no persisted "
        "prz_config.json found for this job"
    )


def _build_sla_config(
    prz_config: Optional[Dict[str, Any]],
    snake_config: Optional[Dict[str, Any]],
    center: Optional[List[float]] = None,
) -> Optional[SLAConfig]:
    """組裝最終 SLAConfig：mechado 萃取為 base、snake config 欄位級覆蓋（design D3）。

    優先序（last-write-wins，欄位級）：
        _extract_sla_from_mechado(prz_config, center)   ← base
            └─ snake_config（PUT /config 傳入）的非 None 欄位逐欄覆蓋

    - 新流程：只送 mechado（snake_config 為空）→ 純萃取結果。
    - 舊流程：無 mechado、僅 snake_config → base 為空，行為退回
      `_convert_v2_config_to_sla(snake_config)`，與變更前一致。
    """
    snake = snake_config or {}
    merged: Dict[str, Any] = {}
    if prz_config is not None:
        merged.update(_extract_sla_from_mechado(prz_config, center))
    merged.update({k: v for k, v in snake.items() if v is not None})
    if merged:
        return SLAConfig(**merged)
    return _convert_v2_config_to_sla(snake)
