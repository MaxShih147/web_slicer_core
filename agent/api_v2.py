"""
API v2 endpoints - DS-Online compatible API.

This module provides API endpoints that match the DS-Online frontend's expected format.
Both v1 (/api/jobs) and v2 (/api/v2/slices) share the same underlying job manager.
"""

import json
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from .jobs import (
    create_job,
    create_job_id,
    get_layer_path,
    get_job_dir,
    job_exists,
    read_job_status,
    run_slicing,
    run_support_generation,
    run_hollow_generation,
    run_cut_operation,
)
from .sla_operations import perform_boolean
from .models import BooleanOperation
from .models import JobStatus, SLAConfig


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


class V2BooleanRequest(BaseModel):
    """Request for boolean operation on two meshes."""
    operation: str = "difference"  # "union", "difference", or "intersection"


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


@router.post("/boolean")
async def boolean_operation_endpoint(
    mesh_a: UploadFile = File(..., description="First mesh (STL)"),
    mesh_b: UploadFile = File(..., description="Second mesh (STL)"),
    operation: str = Form(default="difference", description="Boolean operation: union, difference, or intersection"),
):
    """
    Perform boolean operation on two meshes (experimental).
    """
    import traceback as tb
    try:
        return await _boolean_operation_impl(mesh_a, mesh_b, operation)
    except HTTPException:
        raise
    except Exception as e:
        err = tb.format_exc()
        with open("/tmp/boolean_error.log", "a") as f:
            f.write(f"\n=== top-level exception ===\n{err}\n")
        raise HTTPException(status_code=500, detail=str(e))


async def _boolean_operation_impl(mesh_a, mesh_b, operation):
    # Validate operation
    try:
        bool_op = BooleanOperation(operation)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid operation: {operation}. Must be 'union', 'difference', or 'intersection'"
        )

    # Validate file extensions
    for f, name in [(mesh_a, "mesh_a"), (mesh_b, "mesh_b")]:
        if not f.filename or not f.filename.lower().endswith(".stl"):
            raise HTTPException(status_code=400, detail=f"{name} must be an STL file")

    # Create job
    job_id = create_job_id()
    job_dir = create_job(job_id)

    # Save uploaded files
    input_dir = job_dir / "input"
    mesh_a_path = input_dir / "mesh_a.stl"
    mesh_b_path = input_dir / "mesh_b.stl"

    try:
        mesh_a_content = await mesh_a.read()
        mesh_b_content = await mesh_b.read()

        with open(mesh_a_path, "wb") as f:
            f.write(mesh_a_content)
        with open(mesh_b_path, "wb") as f:
            f.write(mesh_b_content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save files: {e}")

    # Perform boolean operation
    import traceback as tb
    try:
        result = await perform_boolean(job_dir, mesh_a_path, mesh_b_path, bool_op)
    except Exception as e:
        err = tb.format_exc()
        with open("/tmp/boolean_error.log", "a") as f:
            f.write(f"\n=== {job_id} exception ===\n{err}\n")
        raise HTTPException(status_code=500, detail=str(e))

    if not result.success:
        with open("/tmp/boolean_error.log", "a") as f:
            f.write(f"\n=== {job_id} failed ===\n{result.error}\n")
        raise HTTPException(status_code=500, detail=result.error)

    return V2Response(
        success=True,
        message=f"Boolean {operation} completed",
        data={
            "jobId": job_id,
            "operation": operation,
            "resultPath": f"/api/jobs/{job_id}/boolean.stl",
        }
    )


@router.post("/debug/save-stl")
async def debug_save_stl(
    file: UploadFile = File(...),
    name: str = Form(..., description="Filename to save as (e.g. debug_01_inner.stl)"),
):
    """Save a debug STL file to /tmp/debug_stl/ for inspection."""
    from pathlib import Path
    debug_dir = Path("/tmp/debug_stl")
    debug_dir.mkdir(exist_ok=True)
    out_path = debug_dir / name
    content = await file.read()
    with open(out_path, "wb") as f:
        f.write(content)
    return {"saved": str(out_path), "size": len(content)}


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
            return V2Response(
                success=True,
                data={
                    "jobId": job_id,
                    "status": status_data["status"],
                    "layerCount": status_data.get("layer_count"),
                    "estimatedPrintTime": status_data.get("estimated_print_time"),
                    "resinVolumeMl": status_data.get("resin_volume_ml"),
                    "error": status_data.get("error"),
                    "hasSupportMesh": status_data.get("has_support_mesh", False),
                    "hasHollowMesh": status_data.get("has_hollow_mesh", False),
                    "hasCutMesh": status_data.get("has_cut_mesh", False),
                }
            )

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
    }

    sla_dict = {}

    # Handle Print section if present
    print_config = config.get("Print", config)

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

    # Also handle direct snake_case keys (for v1 compatibility)
    for key in SLAConfig.model_fields:
        if key in config:
            sla_dict[key] = config[key]

    if sla_dict:
        return SLAConfig(**sla_dict)
    return None
