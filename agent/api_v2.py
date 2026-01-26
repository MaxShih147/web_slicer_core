"""
API v2 endpoints - DS-Online compatible API.

This module provides API endpoints that match the DS-Online frontend's expected format.
Both v1 (/api/jobs) and v2 (/api/v2/slices) share the same underlying job manager.
"""

import json
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, UploadFile
from pydantic import BaseModel

from .jobs import (
    create_job,
    create_job_id,
    get_layer_path,
    job_exists,
    read_job_status,
    run_slicing,
    run_support_generation,
    run_hollow_generation,
    run_cut_operation,
)
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
    background_tasks.add_task(run_cut_operation, job_id, request.cut_height)

    return V2Response(
        success=True,
        message="Cut operation started",
        data={"cutHeight": request.cut_height}
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
            return V2Response(
                success=True,
                data={
                    "jobId": job_id,
                    "status": status_data["status"],
                    "layerCount": status_data.get("layer_count"),
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
        # Add more mappings as needed
    }

    sla_dict = {}

    # Handle Print section if present
    print_config = config.get("Print", config)

    for ds_key, sla_key in mapping.items():
        if ds_key in print_config:
            sla_dict[sla_key] = print_config[ds_key]

    # Also handle direct snake_case keys (for v1 compatibility)
    for key in ["layer_height", "exposure_time", "initial_exposure_time",
                "supports_enable", "pad_enable",
                "hollowing_enable", "hollowing_min_thickness",
                "hollowing_quality", "hollowing_closing_distance"]:
        if key in config:
            sla_dict[key] = config[key]

    if sla_dict:
        return SLAConfig(**sla_dict)
    return None
