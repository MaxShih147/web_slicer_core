"""FastAPI application for the web_slicer_core agent."""

import asyncio
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from .config import HOST, PORT, PRUSA_SLICER_CLI
from .models import JobCreateResponse, JobStatus, JobStatusResponse
from .jobs import (
    create_job,
    create_job_id,
    get_job_dir,
    get_layer_path,
    job_exists,
    read_job_status,
    run_slicing,
)

app = FastAPI(
    title="web_slicer_core Agent",
    description="Local agent for SLA slicing using PrusaSlicer CLI",
    version="0.1.0",
)

# CORS configuration for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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
):
    """
    Create a new slicing job.

    Upload a .stl file to start SLA slicing.
    """
    # Validate file extension
    if not file.filename or not file.filename.lower().endswith(".stl"):
        raise HTTPException(status_code=400, detail="Only .stl files are supported")

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
    background_tasks.add_task(run_slicing, job_id)

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


def main():
    """Run the server."""
    import uvicorn
    uvicorn.run(app, host=HOST, port=PORT)


if __name__ == "__main__":
    main()
