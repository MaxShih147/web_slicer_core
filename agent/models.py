"""Pydantic models for the web_slicer_core agent API."""

from enum import Enum
from typing import Any, Dict, Optional
from pydantic import BaseModel, field_validator, model_validator


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
    initial_layer_height: Optional[float] = None  # fallback 至 layer_height（未設定時）

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

    # Image quality settings
    anti_aliasing: bool = True
    anti_aliasing_level: int = 0
    gray_level: int = 0
    blur: int = 0

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
    display_orientation: str = "landscape"

    # Center position (mm), defaults to center of display
    center_x: Optional[float] = None
    center_y: Optional[float] = None

    # Shrinkage compensation
    shrinkage_compensation: bool = False
    shrinkage_compensation_x: float = 100.0
    shrinkage_compensation_y: float = 100.0
    shrinkage_compensation_z: float = 100.0

    # Tolerance compensation
    tolerance_compensation: bool = False
    tolerance_compensation_a: float = 0.0
    tolerance_compensation_b: float = 0.0
    bottom_tolerance_compensation: bool = False
    bottom_tolerance_compensation_a: float = 0.0
    bottom_tolerance_compensation_b: float = 0.0
    bottom_layer_count: int = 6

    # Retract motion (PRZ-specific). Maps to Mechado "Print.*" keys.
    # None means "not set by caller" — encoder's Case 4 fallback applies.
    retract_distance: Optional[float] = None                  # Print.Retract Distance
    bottom_retract_distance: Optional[float] = None           # Print.Bottom Retract Distance
    retract_second_distance: Optional[float] = None           # Print.Retract Second Distance
    bottom_retract_second_distance: Optional[float] = None    # Print.Bottom Retract Second Distance

    @model_validator(mode='after')
    def fallback_initial_layer_height(self) -> 'SLAConfig':
        if self.initial_layer_height is None:
            self.initial_layer_height = self.layer_height
        return self

    @model_validator(mode='after')
    def set_center_defaults(self) -> 'SLAConfig':
        if self.center_x is None or self.center_x < 0:
            self.center_x = self.display_width / 2
        if self.center_y is None or self.center_y < 0:
            self.center_y = self.display_height / 2
        return self


class CutMode(str, Enum):
    """Which parts to keep after cutting."""
    BOTH = "both"
    UPPER = "upper"
    LOWER = "lower"


class CutConfig(BaseModel):
    """Configuration for plane-cut operation."""

    cut_height: float = 0.0  # Z height to cut at (mm)
    keep_mode: CutMode = CutMode.BOTH  # Which parts to keep


class PrzPrintTimingConfig(BaseModel):
    """PRZ print motion timing configuration."""

    # delay_mode: 0=lightOff, 1=waitTime
    exposure_delay_mode: int = 1

    # lightOff mode parameter, 0–120s
    light_off_delay: float = 1.0

    # waitTime mode parameters, 0–60s
    rest_before_lift: float = 0.0
    rest_after_lift: float = 0.0
    rest_after_retract: float = 1.0

    # bottom layer overrides; None falls back to normal layer values via model_validator
    bottom_rest_before_lift: Optional[float] = None
    bottom_rest_after_lift: Optional[float] = None
    bottom_rest_after_retract: Optional[float] = None

    @field_validator('exposure_delay_mode')
    @classmethod
    def validate_delay_mode(cls, v: int) -> int:
        if v not in (0, 1):
            raise ValueError('exposure_delay_mode must be 0 or 1')
        return v

    @field_validator('light_off_delay')
    @classmethod
    def validate_light_off_delay(cls, v: float) -> float:
        if not 0.0 <= v <= 120.0:
            raise ValueError('light_off_delay must be in range 0–120 s')
        return v

    @field_validator('rest_before_lift', 'rest_after_lift', 'rest_after_retract')
    @classmethod
    def validate_rest(cls, v: float) -> float:
        if not 0.0 <= v <= 60.0:
            raise ValueError('rest parameters must be in range 0–60 s')
        return v

    @field_validator(
        'bottom_rest_before_lift', 'bottom_rest_after_lift', 'bottom_rest_after_retract',
        mode='before',
    )
    @classmethod
    def validate_bottom_rest(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and not 0.0 <= v <= 60.0:
            raise ValueError('bottom rest parameters must be in range 0–60 s')
        return v

    @model_validator(mode='after')
    def apply_bottom_fallbacks(self) -> 'PrzPrintTimingConfig':
        if self.bottom_rest_before_lift is None:
            self.bottom_rest_before_lift = self.rest_before_lift
        if self.bottom_rest_after_lift is None:
            self.bottom_rest_after_lift = self.rest_after_lift
        if self.bottom_rest_after_retract is None:
            self.bottom_rest_after_retract = self.rest_after_retract
        return self


# DS-Online Title Case key → PrzPrintTimingConfig field name
# Keys live under the "Print" section of the DS-Online config dict.
_DS_TO_PRZ_TIMING: Dict[str, str] = {
    "Exposure Delay Mode":       "exposure_delay_mode",
    "Light-off Delay":           "light_off_delay",
    "Rest Before Lift":          "rest_before_lift",
    "Rest After Lift":           "rest_after_lift",
    "Rest After Retract":        "rest_after_retract",
    "Bottom Rest Before Lift":   "bottom_rest_before_lift",
    "Bottom Rest After Lift":    "bottom_rest_after_lift",
    "Bottom Rest After Retract": "bottom_rest_after_retract",
}


def _extract_prz_timing_config(config: Dict[str, Any]) -> PrzPrintTimingConfig:
    """
    Extract PRZ print timing parameters from a DS-Online config dict.

    Supports both nested {"Print": {...}} and flat formats (consistent with
    _convert_v2_config_to_sla). Keys absent from the frontend payload use
    PrzPrintTimingConfig defaults.
    """
    print_config = config.get("Print", config)
    timing_dict: Dict[str, Any] = {}
    for ds_key, field_name in _DS_TO_PRZ_TIMING.items():
        if ds_key in print_config:
            timing_dict[field_name] = print_config[ds_key]
    return PrzPrintTimingConfig(**timing_dict)


class BooleanOperation(str, Enum):
    """Boolean operation type."""
    UNION = "union"
    DIFFERENCE = "difference"
    INTERSECTION = "intersection"
