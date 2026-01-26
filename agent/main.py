"""FastAPI application for the web_slicer_core agent."""

import asyncio
import json
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

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
    get_cut_mesh_path,
    get_cut_upper_mesh_path,
    get_cut_lower_mesh_path,
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

# CORS configuration for local development
# Supports both web_slicer_core React UI and DS-Online Vue UI
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",   # DS-Online (default Vite port)
        "http://127.0.0.1:5173",
        "http://localhost:5174",   # web_slicer_core React UI (alternate port)
        "http://127.0.0.1:5174",
        "http://localhost:3000",   # Common dev port
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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


def main():
    """Run the server."""
    import uvicorn
    uvicorn.run(app, host=HOST, port=PORT)


if __name__ == "__main__":
    main()
