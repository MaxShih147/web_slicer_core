"""Pydantic models for the web_slicer_core agent API."""

from enum import Enum
from typing import Optional
from pydantic import BaseModel, field_validator


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
    estimated_print_time: Optional[float] = None
    resin_volume_ml: Optional[float] = None
    error: Optional[str] = None
    has_support_mesh: bool = False
    has_hollow_mesh: bool = False
    has_cut_mesh: bool = False


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
    support_object_elevation: float = 5.0
    support_critical_angle: float = 45.0

    @field_validator('support_object_elevation')
    @classmethod
    def enforce_min_elevation(cls, v: float) -> float:
        return max(5.0, v)

    # Pad settings
    pad_enable: bool = False

    # Hollow settings
    hollowing_enable: bool = False
    hollowing_min_thickness: float = 3.0
    hollowing_quality: float = 0.5
    hollowing_closing_distance: float = 2.0

    # Gamma correction
    gamma_correction: float = 1.0

    # Printer / material
    printer_model: str = ""
    sla_material_settings_id: str = ""

    # Display resolution
    display_pixels_x: int = 2560
    display_pixels_y: int = 1440

    # Display physical size (mm)
    display_width: float = 120.0
    display_height: float = 68.0


class CutMode(str, Enum):
    """Which parts to keep after cutting."""
    BOTH = "both"
    UPPER = "upper"
    LOWER = "lower"


class CutConfig(BaseModel):
    """Configuration for plane-cut operation."""

    cut_height: float = 0.0  # Z height to cut at (mm)
    keep_mode: CutMode = CutMode.BOTH  # Which parts to keep


class BooleanOperation(str, Enum):
    """Boolean operation type."""
    UNION = "union"
    DIFFERENCE = "difference"
    INTERSECTION = "intersection"
