"""
Pure-arithmetic pre-checks that mirror the engine's SLAPrint::validate() /
PadConfig::validate() decisions — add-support-param-validation.

Of the engine's 9 validate() rules, 7 depend only on numbers already sitting
in SLAConfig (plus, for two of them, information the frontend has but the
backend doesn't normally see — see `manual_point_count` / `printer_bounds`
below). This module predicts those 7 without invoking the engine, so a bad
value can be rejected the moment it is typed instead of after a multi-second
CLI round trip. The other 2 validate() rules need model geometry (model out
of bounds, a pad mesh that fails to build) and cannot be predicted here.

Every formula and constant is taken directly from the fork source — see
test_param_rules_contract.py, which pins each one against
third_party/prusaslicer_fork. Do not "improve" or approximate a formula here
without re-deriving it from the C++.

Two more checks have no engine validate() counterpart at all, because the
engine silently mishandles them rather than rejecting them (see
openspec/changes/add-support-param-validation/design.md and the research
that produced this module):

  - support_points_density_relative == 0 with no manually-supplied points:
    SupportPointGenerator.cpp divides the required point spacing by this
    value, so 0 makes the spacing infinite and silently yields zero points —
    never an engine error, just a support-less print. Reported as
    SUPPORT_POINTS_REQUIRED, naming the density field.
  - shrinkage_compensation enabled with any axis at exactly 0%: the object's
    transform matrix gets a zero diagonal entry and becomes singular — the
    same failure merge-engine-result-classifiers wired up as
    SHRINKAGE_COMPENSATION_INVALID (needle "the object transform is").

`evaluate()` takes already-clamped, already-validated parameter values (the
same shape `SLAConfig().model_dump()` produces) — it does not re-implement
SLAConfig's own validators (e.g. enforce_min_elevation's floor of 5.0). The
one exception is `support_base_safety_distance`'s near-zero clamp to 0.5mm,
which happens inside the ENGINE, not in SLAConfig (models.py deliberately
leaves this field as a passthrough) — see R4 below.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable, Dict, Optional, Tuple

# Engine constant: SLA/Pad.cpp PadConfig::validate()'s MIN_BRIM_SIZE_MM.
_MIN_BRIM_SIZE_MM = 0.1

# Engine constant: SLA/SupportTree.hpp's safety_distance_mm, used by
# make_support_cfg() (SLAPrint.cpp) whenever support_base_safety_distance is
# below EPSILON (libslic3r.h, 1e-4).
_ENGINE_SAFETY_DISTANCE_EPSILON = 1e-4
_ENGINE_DEFAULT_SAFETY_DISTANCE_MM = 0.5


@dataclass(frozen=True)
class Problem:
    code: str
    fields: Tuple[str, ...]
    suggestion: str
    values: Dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class ClampedField:
    field: str
    original: float
    effective: float


@dataclass(frozen=True)
class ParamRule:
    code: str
    scope: str  # "support_params" | "slice_only"
    check: Callable[..., Optional[Problem]]


def _head_fullwidth(p: dict) -> float:
    """SLA/SupportTree.hpp Rule::head_fullwidth(): 2*front_r + width - penetration
    + 2*back_r, where back_r is support_pillar_diameter/2 (see SLAPrint.cpp's
    make_support_cfg — head_back_radius_mm is the PILLAR radius, not a
    separate field). Diameters cancel the /2 * 2, leaving a plain sum."""
    return (
        p["support_head_front_diameter"]
        + p["support_pillar_diameter"]
        + p["support_head_width"]
        - p["support_head_penetration"]
    )


def _is_zero_elevation(p: dict) -> bool:
    """SLAPrint.cpp is_zero_elevation(): pad_enable AND pad_around_object (both)."""
    return bool(p.get("pad_enable")) and bool(p.get("pad_around_object"))


def _check_head_too_wide(p: dict, ctx: dict) -> Optional[Problem]:
    front, pillar = p["support_head_front_diameter"], p["support_pillar_diameter"]
    if front > pillar:
        return Problem(
            code="SUPPORT_HEAD_TOO_WIDE",
            fields=("support_head_front_diameter", "support_pillar_diameter"),
            suggestion="support_head_front_diameter must not exceed support_pillar_diameter",
        )
    return None


def _check_head_penetration_invalid(p: dict, ctx: dict) -> Optional[Problem]:
    penetration, width = p["support_head_penetration"], p["support_head_width"]
    if penetration > width:
        return Problem(
            code="SUPPORT_HEAD_PENETRATION_INVALID",
            fields=("support_head_penetration", "support_head_width"),
            suggestion="support_head_penetration must not exceed support_head_width",
        )
    return None


def _check_elevation_too_low(p: dict, ctx: dict) -> Optional[Problem]:
    if not p.get("supports_enable") or _is_zero_elevation(p):
        return None
    fullwidth = _head_fullwidth(p)
    if p["support_object_elevation"] < fullwidth:
        return Problem(
            code="SUPPORT_ELEVATION_TOO_LOW",
            fields=(
                "support_object_elevation",
                "support_head_front_diameter",
                "support_pillar_diameter",
                "support_head_width",
                "support_head_penetration",
            ),
            suggestion=f"support_object_elevation must be at least {fullwidth:.2f}mm "
                       f"given the current head/pillar dimensions",
            values={"min_support_object_elevation": fullwidth},
        )
    return None


def _check_pad_gap_conflict(p: dict, ctx: dict) -> Optional[Problem]:
    if not p.get("supports_enable") or not _is_zero_elevation(p):
        return None
    raw_safety = p["support_base_safety_distance"]
    effective_safety = (
        _ENGINE_DEFAULT_SAFETY_DISTANCE_MM
        if raw_safety < _ENGINE_SAFETY_DISTANCE_EPSILON
        else raw_safety
    )
    if effective_safety < p["pad_object_gap"]:
        return Problem(
            code="SUPPORT_PAD_GAP_CONFLICT",
            fields=("support_base_safety_distance", "pad_object_gap"),
            suggestion="pad_object_gap must not exceed the effective support_base_safety_distance",
            values={"effective_support_base_safety_distance": effective_safety},
        )
    return None


def _check_pad_config_invalid(p: dict, ctx: dict) -> Optional[Problem]:
    brim = p["pad_brim_size"]
    if brim < _MIN_BRIM_SIZE_MM:
        return Problem(
            code="PAD_CONFIG_INVALID",
            fields=("pad_brim_size",),
            suggestion=f"pad_brim_size must be at least {_MIN_BRIM_SIZE_MM}mm",
            values={"min_pad_brim_size": _MIN_BRIM_SIZE_MM},
        )
    thickness = p["pad_wall_thickness"]
    slope_rad = math.radians(p["pad_wall_slope"])
    if thickness / math.tan(slope_rad) > brim:
        # Reported threshold rounds UP to 1 decimal: a value rounded DOWN
        # would still be rejected by the engine, misleading the user into
        # thinking that exact number is legal.
        exact_min_slope = math.degrees(math.atan(thickness / brim))
        min_slope = math.ceil(exact_min_slope * 10) / 10
        return Problem(
            code="PAD_CONFIG_INVALID",
            fields=("pad_wall_slope", "pad_wall_thickness", "pad_brim_size"),
            suggestion=f"pad_wall_slope must be at least {min_slope}° "
                       f"given the current pad_wall_thickness and pad_brim_size",
            values={"min_pad_wall_slope": min_slope},
        )
    return None


def _check_support_points_required(p: dict, ctx: dict) -> Optional[Problem]:
    if not p.get("supports_enable"):
        return None
    manual_point_count = ctx.get("manual_point_count")
    if manual_point_count is not None and manual_point_count == 0:
        return Problem(
            code="SUPPORT_POINTS_REQUIRED",
            fields=("supports_enable",),
            suggestion="Add at least one manual support point, or let the engine auto-generate them",
        )
    # R5 (no engine validate() counterpart): density_relative == 0 with no
    # manual points relied on silently yields zero auto-generated points.
    if manual_point_count is None and p.get("support_points_density_relative") == 0:
        return Problem(
            code="SUPPORT_POINTS_REQUIRED",
            fields=("support_points_density_relative",),
            suggestion="support_points_density_relative of 0 produces no support points; "
                       "raise it above 0 or supply manual support points",
        )
    return None


def _check_exposure_time_out_of_range(p: dict, ctx: dict) -> Optional[Problem]:
    bounds = ctx.get("printer_bounds")
    if not bounds:
        return None
    exposure = p["exposure_time"]
    if exposure < bounds["min_exposure_time"] or exposure > bounds["max_exposure_time"]:
        return Problem(
            code="EXPOSURE_TIME_OUT_OF_RANGE",
            fields=("exposure_time",),
            suggestion=f"exposure_time must be between {bounds['min_exposure_time']} "
                       f"and {bounds['max_exposure_time']} for this printer profile",
            values={
                "min_exposure_time": bounds["min_exposure_time"],
                "max_exposure_time": bounds["max_exposure_time"],
            },
        )
    initial = p["initial_exposure_time"]
    if initial < bounds["min_initial_exposure_time"] or initial > bounds["max_initial_exposure_time"]:
        return Problem(
            code="EXPOSURE_TIME_OUT_OF_RANGE",
            fields=("initial_exposure_time",),
            suggestion=f"initial_exposure_time must be between {bounds['min_initial_exposure_time']} "
                       f"and {bounds['max_initial_exposure_time']} for this printer profile",
            values={
                "min_initial_exposure_time": bounds["min_initial_exposure_time"],
                "max_initial_exposure_time": bounds["max_initial_exposure_time"],
            },
        )
    return None


def _check_shrinkage_compensation_invalid(p: dict, ctx: dict) -> Optional[Problem]:
    if not p.get("shrinkage_compensation"):
        return None
    zero_axes = [
        axis
        for axis in ("shrinkage_compensation_x", "shrinkage_compensation_y", "shrinkage_compensation_z")
        if p.get(axis) == 0
    ]
    if zero_axes:
        return Problem(
            code="SHRINKAGE_COMPENSATION_INVALID",
            fields=tuple(zero_axes),
            suggestion="shrinkage compensation of exactly 0% makes the object transform singular; "
                       "use a nonzero value or disable shrinkage_compensation",
        )
    return None


# The 7 rules mirroring an engine validate() message directly.
_ENGINE_MIRRORED_RULES: Tuple[ParamRule, ...] = (
    ParamRule(code="SUPPORT_HEAD_TOO_WIDE", scope="support_params", check=_check_head_too_wide),
    ParamRule(
        code="SUPPORT_HEAD_PENETRATION_INVALID",
        scope="support_params",
        check=_check_head_penetration_invalid,
    ),
    ParamRule(code="SUPPORT_ELEVATION_TOO_LOW", scope="support_params", check=_check_elevation_too_low),
    ParamRule(code="SUPPORT_PAD_GAP_CONFLICT", scope="support_params", check=_check_pad_gap_conflict),
    ParamRule(code="PAD_CONFIG_INVALID", scope="support_params", check=_check_pad_config_invalid),
    ParamRule(
        code="SUPPORT_POINTS_REQUIRED", scope="support_params", check=_check_support_points_required
    ),
    ParamRule(
        code="EXPOSURE_TIME_OUT_OF_RANGE", scope="slice_only", check=_check_exposure_time_out_of_range
    ),
)

# D9: no engine validate() counterpart (see module docstring) — added
# alongside the 7 above, not folded into one of them, since it targets its
# own code and its own fields shape. (R5's density check IS folded into
# _check_support_points_required above, since it shares SUPPORT_POINTS_REQUIRED's
# code and "no support points will exist" meaning.)
_D9_RULE = ParamRule(
    code="SHRINKAGE_COMPENSATION_INVALID",
    scope="support_params",
    check=_check_shrinkage_compensation_invalid,
)

RULES: Tuple[ParamRule, ...] = _ENGINE_MIRRORED_RULES + (_D9_RULE,)

_PROFILE_SCOPES = {
    "support": ("support_params",),
    "slice": ("support_params", "slice_only"),
    "slice_imported": ("slice_only",),
}


def rules_for(profile: str) -> Tuple[ParamRule, ...]:
    """Rules for `profile`, derived as the UNION of the scopes it uses — never
    a hand-maintained per-profile list (design.md D1)."""
    scopes = _PROFILE_SCOPES[profile]
    return tuple(r for r in RULES if r.scope in scopes)


def evaluate(
    profile: str,
    params: dict,
    *,
    manual_point_count: Optional[int] = None,
    printer_bounds: Optional[dict] = None,
    per_point=None,
) -> list:
    """Run every rule visible to `profile` against `params`. Returns a list of
    Problem (empty if none). Pure function: no disk, no engine, no job state."""
    ctx = {
        "manual_point_count": manual_point_count,
        "printer_bounds": printer_bounds,
        "per_point": per_point,
    }
    problems = []
    for rule in rules_for(profile):
        problem = rule.check(params, ctx)
        if problem is not None:
            problems.append(problem)
    return problems


def compute_clamps(raw_params: dict) -> list:
    """Fields the backend or engine will silently rewrite, with their original
    and effective values (design.md D5) — computed from RAW (pre-validation)
    input, independent of `evaluate()`."""
    clamps = []
    elevation = raw_params.get("support_object_elevation")
    if elevation is not None and elevation < 5.0:
        clamps.append(ClampedField("support_object_elevation", elevation, 5.0))
    safety = raw_params.get("support_base_safety_distance")
    if safety is not None and safety < _ENGINE_SAFETY_DISTANCE_EPSILON:
        clamps.append(
            ClampedField(
                "support_base_safety_distance", safety, _ENGINE_DEFAULT_SAFETY_DISTANCE_MM
            )
        )
    return clamps
