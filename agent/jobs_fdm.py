"""Job management for FDM slicing.

Mirrors agent/jobs.py but stays in its own dir tree (`JOBS_DIR/fdm/<id>`)
so SLA and FDM jobs never overlap.
"""
from __future__ import annotations

import json
import uuid
from enum import Enum
from pathlib import Path
from typing import Optional

from .config import JOBS_DIR


FDM_JOBS_ROOT = JOBS_DIR / "fdm"


class FDMJobStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


def create_fdm_job_id() -> str:
    return str(uuid.uuid4())[:8]


def get_fdm_job_dir(job_id: str) -> Path:
    return FDM_JOBS_ROOT / job_id


def get_fdm_status_file(job_id: str) -> Path:
    return get_fdm_job_dir(job_id) / "status.json"


def fdm_job_exists(job_id: str) -> bool:
    return get_fdm_job_dir(job_id).exists()


def read_fdm_status(job_id: str) -> dict:
    status_file = get_fdm_status_file(job_id)
    if status_file.exists():
        with open(status_file, "r") as f:
            return json.load(f)
    return {"status": FDMJobStatus.PENDING.value, "error": None}


def write_fdm_status(
    job_id: str,
    status: FDMJobStatus,
    error: Optional[str] = None,
    has_gcode: bool = False,
    estimated_print_time_s: Optional[float] = None,
    filament_used_mm: Optional[float] = None,
):
    data = {
        "status": status.value,
        "error": error,
        "has_gcode": has_gcode,
        "estimated_print_time_s": estimated_print_time_s,
        "filament_used_mm": filament_used_mm,
    }
    with open(get_fdm_status_file(job_id), "w") as f:
        json.dump(data, f)


def create_fdm_job(job_id: str) -> Path:
    job_dir = get_fdm_job_dir(job_id)
    (job_dir / "input").mkdir(parents=True, exist_ok=True)
    (job_dir / "output").mkdir(exist_ok=True)
    write_fdm_status(job_id, FDMJobStatus.PENDING)
    return job_dir


def get_fdm_input_path(job_id: str) -> Optional[Path]:
    p = get_fdm_job_dir(job_id) / "input" / "model.stl"
    return p if p.exists() else None


def get_fdm_gcode_path(job_id: str) -> Optional[Path]:
    p = get_fdm_job_dir(job_id) / "output" / "model.gcode"
    return p if p.exists() else None
