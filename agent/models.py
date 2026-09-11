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
    # Neutral support-generation outcome (e.g. "SUPPORT_NOT_NEEDED") on a
    # COMPLETED job. Optional/absent for jobs that predate the field or that
    # produced a real support mesh.
    support_outcome: Optional[str] = None
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
    # Whether the engine may prop up a lonely tall pillar with pillars of its
    # own. Manual placement turns it off: one placement should produce one
    # support, not three.
    support_auxiliary_pillars: bool = True

    @field_validator('support_object_elevation')
    @classmethod
    def enforce_min_elevation(cls, v: float) -> float:
        return max(5.0, v)

    # Support tree global parameters (F1/B2).
    #
    # Decision record lives in the *DS-Online* repo, not this one:
    #   DS-Online/openspec/changes/archive/2026-09-10-add-support-tree-global-params
    # It covers why "organic" is rejected at the API layer, why
    # support_max_pillar_link_distance must NOT get a min-value guard, and why
    # support_base_safety_distance is passed through unmodified. The code landed
    # here (commit 826786b) without those docs, so name the repo explicitly —
    # searching this repo's history for the change name finds nothing.
    #
    # Engine (PrintConfig.cpp) already registers and reads these options; this
    # only opens the API entry point. Field names match the engine option key
    # 1:1 so generate_config_ini's generic field-name-driven write works as-is.
    support_head_width: float = 1.0
    support_base_diameter: float = 4.0
    support_base_height: float = 1.0
    support_bracing_angle: float = 45.0
    support_max_bridge_length: float = 15.0
    # 0 is a legal value (means "no pillar linking") — MUST NOT get a min-value
    # validator like support_object_elevation's enforce_min_elevation.
    support_max_pillar_link_distance: float = 10.0
    support_max_bridges_on_pillar: int = 3
    support_small_pillar_diameter_percent: float = 50.0
    support_buildplate_only: bool = False

    # Engine silently clamps values below EPSILON to a constant 0.5mm
    # (SLAPrint.cpp:81-83). This is pre-existing engine behavior; SHALL NOT be
    # modified or intercepted here — pass the value through as-is and let API
    # consumers document the 0→0.5mm behavior themselves.
    support_base_safety_distance: float = 1.0

    # Engine enum key is a plain string (s_keys_map_SLAPillarConnectionMode:
    # "zigzag"/"cross"/"dynamic"). Follows the existing plain-str convention
    # used by display_orientation rather than a real Python Enum.
    support_pillar_connection_mode: str = "dynamic"

    @field_validator('support_pillar_connection_mode')
    @classmethod
    def validate_pillar_connection_mode(cls, v: str) -> str:
        allowed = {"zigzag", "cross", "dynamic"}
        if v not in allowed:
            raise ValueError(f"support_pillar_connection_mode must be one of {sorted(allowed)}")
        return v

    # Engine enum key (s_keys_map_SLASupportTreeType) only registers
    # "default"/"branching" — "organic" is a commented-out TODO in
    # PrintConfig.cpp:227-230 and would fail at the engine's enum
    # deserialization stage if it reached generate_config_ini. Reject it here.
    # TODO: "branching" opens the entry point, but its 19 branchingsupport_*
    # fields are not migrated in this change — the engine falls back to its
    # own defaults for them (PrusaSlicer only overrides keys actually sent).
    # Migrate them in bulk the same way as the 9 standard fields above, when
    # tunable "branching" mode is needed.
    support_tree_type: str = "default"

    @field_validator('support_tree_type')
    @classmethod
    def validate_tree_type(cls, v: str) -> str:
        allowed = {"default", "branching"}
        if v not in allowed:
            raise ValueError(f"support_tree_type must be one of {sorted(allowed)}")
        return v

    # Declared but not yet functional (parking item): only takes effect when
    # paired with enforcer/blocker marker volumes on the model
    # (SLAPrintSteps.cpp:1073, vol->is_support_enforcer()/is_support_blocker()).
    # sla_operations.py currently has no marker-volume data flow (only
    # --import-support-points / --prior-supports), so setting this has no
    # observable effect yet. Needs that data flow as a follow-up feature.
    support_enforcers_only: bool = False

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


def gate_blur(blur_enabled: Any, blur_pixel: Any) -> Any:
    """依 `Image Blur` 開關閘控 blur 強度，回傳最終的 `blur` 值。

    `Image Blur` 是**啟用與否**的開關，`Image Blur Pixel` 是**強度刻度**。閘控只決定
    「要不要套用」，MUST NOT 被解讀為對刻度做任何轉換——開關為 true 或缺失時，強度值
    原封不動直接複製，「不得二次刻度轉換」的既有約定完全不變。

    三態語意：

        開關 falsy（False / 0）  -> 0            使用者已關閉，不得執行
        開關 truthy             -> blur_pixel   直接複製
        開關不存在（None）        -> blur_pixel   向後相容：舊 config 不含此鍵，行為不變

    `None` 同時代表「鍵不存在」與「值為 JSON null」，兩者都退回直接複製。

    **這是全系統唯一的 blur 閘控真值來源**，目前有三個消費端：

      * `api_v2._extract_sla_from_mechado()` —— mechado config → SLAConfig
      * `api_v2._convert_v2_config_to_sla()` —— 舊版扁平 config → SLAConfig
      * `prz_encoder._write_header()`        —— PRZ header 的 `blur_level` 欄位

    前兩者若不一致，`execute_slice_job` 的「base(mechado) ← override(snake)」合併會依
    請求順序產生不可預期的 `blur`；第三者若不一致，PRZ 會宣稱一個與層圖不符的模糊強度。
    住在 `models.py` 而非 `api_v2.py` 是因為 `prz_encoder` 是 `api_v2` 的**下游**——把閘控
    留在 api_v2 會迫使低階編碼器反向匯入整個 FastAPI 路由模組。

    背景：前端在使用者未勾選 blur 時仍會送出 `Image Blur Pixel = 1`，而本函式導入前
    後端完全沒有讀取開關，於是切片一律以 blur 啟用執行。以 16K 幅面實測，該狀態下
    光柵化耗時是關閉時的 5.9 倍（262 秒 vs 40 秒）。
    """
    if blur_enabled is None:
        return blur_pixel
    return blur_pixel if blur_enabled else 0


class BooleanOperation(str, Enum):
    """Boolean operation type."""
    UNION = "union"
    DIFFERENCE = "difference"
    INTERSECTION = "intersection"
