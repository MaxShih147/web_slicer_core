"""FDM slicing HTTP API.

Lives at `/api/v2/fdm/...` so it never collides with the SLA pipeline at
`/api/v2/slices/...`. Mirrors the SLA job lifecycle (create → upload →
slice → poll → download) but with FDM-specific output (`.gcode`).
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, BackgroundTasks, Body, File, UploadFile
from fastapi.responses import FileResponse

from .fdm_slicing import run_fdm_slicing
from .jobs_fdm import (
    FDMJobStatus,
    create_fdm_job,
    create_fdm_job_id,
    fdm_job_exists,
    get_fdm_gcode_path,
    get_fdm_input_path,
    get_fdm_job_dir,
    read_fdm_status,
)


router = APIRouter(prefix="/api/v2/fdm", tags=["fdm"])


@router.post("/jobs")
async def create_fdm_job_endpoint():
    """Create an empty FDM job and return its id."""
    job_id = create_fdm_job_id()
    create_fdm_job(job_id)
    return {
        "success": True,
        "message": "FDM job created",
        "data": {"jobId": job_id},
    }


@router.post("/jobs/{job_id}/upload")
async def upload_fdm_model(job_id: str, file: UploadFile = File(...)):
    """Upload the STL to slice."""
    if not fdm_job_exists(job_id):
        return {
            "success": False,
            "code": "JOB_NOT_FOUND",
            "message": f"FDM job '{job_id}' not found",
        }
    if not file.filename or not file.filename.lower().endswith(".stl"):
        return {
            "success": False,
            "code": "BAD_FILE",
            "message": "Only .stl files are supported",
        }
    input_path = get_fdm_job_dir(job_id) / "input" / "model.stl"
    content = await file.read()
    with open(input_path, "wb") as f:
        f.write(content)
    return {
        "success": True,
        "message": "Model uploaded",
        "data": {"jobId": job_id, "size": len(content)},
    }


@router.post("/jobs/{job_id}/slice")
async def start_fdm_slice(
    job_id: str,
    background_tasks: BackgroundTasks,
    body: Optional[dict[str, Any]] = Body(default=None),
):
    """Kick off slicing in the background.

    Optional body shape: ``{"params": {"layer_height": 0.2, ...}}`` —
    snake_case keys map 1:1 to PrusaSlicer ini option names. The values
    are written into ``<job>/config.ini`` and PrusaSlicer is invoked
    with ``--load <ini>``. CLI flags from the body override anything in
    a default profile.
    """
    if not fdm_job_exists(job_id):
        return {
            "success": False,
            "code": "JOB_NOT_FOUND",
            "message": f"FDM job '{job_id}' not found",
        }
    if get_fdm_input_path(job_id) is None:
        return {
            "success": False,
            "code": "NO_INPUT",
            "message": "Upload an STL first",
        }
    params = (body or {}).get("params") if isinstance(body, dict) else None
    background_tasks.add_task(run_fdm_slicing, job_id, params)
    return {
        "success": True,
        "message": "FDM slicing started",
        "data": {"jobId": job_id},
    }


@router.get("/jobs/{job_id}")
async def get_fdm_job(job_id: str):
    """Poll status."""
    if not fdm_job_exists(job_id):
        return {
            "success": False,
            "code": "JOB_NOT_FOUND",
            "message": f"FDM job '{job_id}' not found",
        }
    status = read_fdm_status(job_id)
    return {
        "success": True,
        "data": {
            "jobId": job_id,
            "status": status.get("status"),
            "error": status.get("error"),
            "hasGcode": status.get("has_gcode", False),
            "estimatedPrintTimeS": status.get("estimated_print_time_s"),
            "filamentUsedMm": status.get("filament_used_mm"),
        },
    }


@router.get("/jobs/{job_id}/gcode")
async def download_fdm_gcode(job_id: str):
    """Download the produced .gcode."""
    if not fdm_job_exists(job_id):
        return {
            "success": False,
            "code": "JOB_NOT_FOUND",
            "message": f"FDM job '{job_id}' not found",
        }
    status = read_fdm_status(job_id)
    if status.get("status") != FDMJobStatus.COMPLETED.value:
        return {
            "success": False,
            "code": "JOB_NOT_READY",
            "message": f"FDM job is {status.get('status')}",
        }
    gcode_path = get_fdm_gcode_path(job_id)
    if gcode_path is None:
        return {
            "success": False,
            "code": "GCODE_MISSING",
            "message": "G-code file not found",
        }
    return FileResponse(
        gcode_path,
        media_type="text/plain",
        filename=f"{job_id}.gcode",
    )
