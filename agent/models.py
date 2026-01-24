"""Pydantic models for the web_slicer_core agent API."""

from enum import Enum
from typing import Optional
from pydantic import BaseModel


class JobStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class JobCreateResponse(BaseModel):
    job_id: str
    status: JobStatus


class JobStatusResponse(BaseModel):
    job_id: str
    status: JobStatus
    layer_count: Optional[int] = None
    error: Optional[str] = None


class SLAConfig(BaseModel):
    """Configuration for SLA slicing parameters."""

    # Layer settings
    layer_height: float = 0.05

    # Exposure settings
    exposure_time: float = 10.0
    initial_exposure_time: float = 15.0

    # Support settings
    supports_enable: bool = False
    support_head_front_diameter: float = 0.4
    support_head_penetration: float = 0.2
    support_pillar_diameter: float = 1.0
    support_points_density_relative: int = 100

    # Pad settings
    pad_enable: bool = False
