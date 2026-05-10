"""Orca-format profile reader for the FDM pipeline.

Reads the JSON tree shipped under ``agent/profiles/`` (a snapshot copied from
PhrozenOrca). Each profile is one of three types — ``machine``, ``filament``,
``process`` — and may declare an ``inherits`` parent. We walk the chain and
merge so each leaf profile resolves to a flat dict.

The resolved keys are then remapped from Orca's naming (which mostly comes
from the Bambu Studio fork) onto PrusaSlicer's ini option names so the same
ini that comes out of here can be loaded with ``prusa-slicer --load``.

Anything that doesn't have a Prusa equivalent (Bambu firmware fields like
``supertack_plate_temp``, Klipper-only ``pressure_advance``, Orca's tree
support enum values, …) is silently dropped — better to slice with sane
PrusaSlicer defaults than to feed it nonsense.
"""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional


# Default location: alongside this module. Override with PROFILES_DIR for
# dev (point at PhrozenOrca/resources/profiles to test live edits).
DEFAULT_PROFILES_DIR = Path(__file__).parent / "profiles"


def get_profiles_dir() -> Path:
    return Path(os.environ.get("PROFILES_DIR", str(DEFAULT_PROFILES_DIR)))


# ───────────────────────────── key remap ──────────────────────────────
#
# Orca-key → PrusaSlicer-ini-key. Keys not in this map are dropped from
# the final ini (Prusa wouldn't recognize them anyway). Same-named keys
# are listed explicitly for clarity, even though the rename is a no-op.

_ORCA_TO_PRUSA: dict[str, str] = {
    # ── Quality / layer ─────────────────────────────────────────────
    "layer_height": "layer_height",
    "initial_layer_print_height": "first_layer_height",
    "line_width": "extrusion_width",
    "initial_layer_line_width": "first_layer_extrusion_width",
    "outer_wall_line_width": "external_perimeter_extrusion_width",
    "inner_wall_line_width": "perimeter_extrusion_width",
    "sparse_infill_line_width": "infill_extrusion_width",
    "internal_solid_infill_line_width": "solid_infill_extrusion_width",
    "top_surface_line_width": "top_infill_extrusion_width",
    "support_line_width": "support_material_extrusion_width",

    # ── Strength / shells / infill ──────────────────────────────────
    "wall_loops": "perimeters",
    "top_shell_layers": "top_solid_layers",
    "bottom_shell_layers": "bottom_solid_layers",
    "sparse_infill_density": "fill_density",
    "sparse_infill_pattern": "fill_pattern",
    "infill_wall_overlap": "infill_overlap",
    "infill_direction": "fill_angle",
    "thin_walls": "thin_walls",
    "ensure_vertical_shell_thickness": "ensure_vertical_shell_thickness",

    # ── Speed ───────────────────────────────────────────────────────
    "outer_wall_speed": "external_perimeter_speed",
    "inner_wall_speed": "perimeter_speed",
    "sparse_infill_speed": "infill_speed",
    "internal_solid_infill_speed": "solid_infill_speed",
    "top_surface_speed": "top_solid_infill_speed",
    "small_perimeter_speed": "small_perimeter_speed",
    "bridge_speed": "bridge_speed",
    "gap_infill_speed": "gap_fill_speed",
    "travel_speed": "travel_speed",
    "initial_layer_speed": "first_layer_speed",
    "support_speed": "support_material_speed",
    "support_interface_speed": "support_material_interface_speed",
    "max_volumetric_speed": "max_volumetric_speed",

    # ── Acceleration ────────────────────────────────────────────────
    "default_acceleration": "default_acceleration",
    "outer_wall_acceleration": "external_perimeter_acceleration",
    "inner_wall_acceleration": "perimeter_acceleration",
    "initial_layer_acceleration": "first_layer_acceleration",
    "top_surface_acceleration": "top_solid_infill_acceleration",
    "travel_acceleration": "travel_acceleration",
    "bridge_acceleration": "bridge_acceleration",

    # ── Support ─────────────────────────────────────────────────────
    "enable_support": "support_material",
    "support_threshold_angle": "support_material_threshold",
    "support_pattern": "support_material_pattern",
    "support_on_build_plate_only": "support_material_buildplate_only",
    "support_interface_top_layers": "support_material_interface_layers",
    "support_filament": "support_material_extruder",
    "raft_layers": "raft_layers",

    # ── Skirt / brim ────────────────────────────────────────────────
    "skirt_loops": "skirts",
    "skirt_distance": "skirt_distance",
    "skirt_height": "skirt_height",
    "brim_width": "brim_width",

    # ── Cooling ─────────────────────────────────────────────────────
    "close_fan_the_first_x_layers": "disable_fan_first_layers",
    "fan_max_speed": "max_fan_speed",
    "fan_min_speed": "min_fan_speed",
    "fan_cooling_layer_time": "slowdown_below_layer_time",
    "overhang_fan_speed": "bridge_fan_speed",
    "reduce_fan_stop_start_freq": "fan_always_on",

    # ── Retraction ──────────────────────────────────────────────────
    "retraction_length": "retract_length",
    "retraction_speed": "retract_speed",
    "deretraction_speed": "deretract_speed",
    "z_hop": "retract_lift",
    "retraction_minimum_travel": "retract_before_travel",
    "wipe": "wipe",
    "wipe_distance": "wipe_distance",

    # ── Filament ────────────────────────────────────────────────────
    "filament_type": "filament_type",
    "filament_diameter": "filament_diameter",
    "filament_density": "filament_density",
    "filament_cost": "filament_cost",
    "filament_flow_ratio": "extrusion_multiplier",
    "nozzle_temperature": "temperature",
    "nozzle_temperature_initial_layer": "first_layer_temperature",
    "hot_plate_temp": "bed_temperature",
    "hot_plate_temp_initial_layer": "first_layer_bed_temperature",

    # ── Misc / process ──────────────────────────────────────────────
    "spiral_mode": "spiral_vase",
    "fuzzy_skin": "fuzzy_skin",
    "seam_position": "seam_position",
    "reduce_crossing_wall": "avoid_crossing_perimeters",

    # ── Machine ─────────────────────────────────────────────────────
    "nozzle_diameter": "nozzle_diameter",
    "printable_area": "bed_shape",
    "printable_height": "max_print_height",
    "gcode_flavor": "gcode_flavor",
}

# Some Orca enum values don't match Prusa's. The map below transforms the
# value AFTER the key has been remapped (i.e. keyed by the Prusa key).
_VALUE_TRANSFORMS: dict[str, dict[str, str]] = {
    "fill_pattern": {
        # Orca-only patterns we coerce to the closest Prusa equivalent.
        "crosshatch": "rectilinear",
        "monotonic": "rectilinear",
        "monotonicline": "rectilinear",
        "alignedrectilinear": "alignedrectilinear",
        "lightning": "rectilinear",
        "tpms_d": "gyroid",
    },
    "support_material_style": {
        # Orca uses 'normal(auto)' / 'tree(auto)' etc; Prusa wants grid/snug/organic.
        "normal(auto)": "grid",
        "normal(manual)": "grid",
        "tree(auto)": "organic",
        "tree(manual)": "organic",
    },
    # Orca: 'disabled' | 'ensure_critical_only' | 'ensure_all'
    # Prusa: 0 | 1
    "ensure_vertical_shell_thickness": {
        "disabled": "0",
        "ensure_critical_only": "1",
        "ensure_all": "1",
    },
    # Orca: 'none' | 'external' | 'all'  → Prusa accepts same enum, no-op map.
    "fuzzy_skin": {
        "none": "none",
        "external": "external",
        "all": "all",
    },
}


# Keys whose ini value MUST carry a "%" suffix (PrusaSlicer's coPercent type).
_PERCENT_KEYS = {"fill_density", "infill_overlap"}


# ──────────────────────── loader ────────────────────────

def _read_json(path: Path) -> Optional[dict]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


@lru_cache(maxsize=1)
def _build_index() -> dict[str, dict]:
    """Walk the profiles dir and index every JSON by ``name``.

    Names are global within the bundle (Orca relies on this for inheritance).
    Returns a dict of name → raw profile dict (still in Orca shape).
    """
    root = get_profiles_dir()
    index: dict[str, dict] = {}
    if not root.exists():
        return index
    for path in root.rglob("*.json"):
        # Skip vendor manifests like "Phrozen.json" — they have no `inherits`
        # and we don't want them mistaken for actual profiles.
        if path.parent == root:
            continue
        data = _read_json(path)
        if not isinstance(data, dict) or "name" not in data:
            continue
        name = data["name"]
        index[name] = data
        # Track which vendor the file lives under so we can group later.
        # The library is laid out two ways:
        #   <Vendor>/<type>/<file>            → vendor = <Vendor>
        #   OrcaFilamentLibrary/<type>/<sub-vendor>/<file> → vendor = <sub-vendor>
        #   OrcaFilamentLibrary/<type>/<file> → vendor = "Generic" (e.g. "Generic PLA @System")
        parts = path.relative_to(root).parts
        if parts and parts[0] == "OrcaFilamentLibrary":
            vendor = parts[2] if len(parts) >= 4 else "Generic"
        else:
            vendor = parts[0] if len(parts) > 1 else ""
        data.setdefault("_vendor", vendor)
        data.setdefault("_path", str(path))
    return index


def reset_cache() -> None:
    """Bust the module-level cache. Call after profiles dir changes on disk."""
    _build_index.cache_clear()
    resolve.cache_clear()


# ──────────────────────── resolution ────────────────────────

@lru_cache(maxsize=512)
def resolve(name: str) -> dict[str, Any]:
    """Fully resolve a profile by walking its inheritance chain.

    Returned dict still uses Orca-style keys; call :func:`to_prusa_ini` to
    rename and clean for PrusaSlicer.
    """
    index = _build_index()
    profile = index.get(name)
    if profile is None:
        return {}
    parent_name = profile.get("inherits")
    base: dict[str, Any] = {}
    if parent_name and parent_name != name:
        base = dict(resolve(parent_name))
    out = base
    for k, v in profile.items():
        if k.startswith("_") or k in {"inherits", "from", "instantiation",
                                       "is_custom_defined", "type",
                                       "compatible_printers_condition",
                                       "compatible_process_condition",
                                       "filename_format", "version",
                                       "setting_id", "filament_id",
                                       "filament_settings_id", "filament_vendor",
                                       "print_settings_id"}:
            continue
        out[k] = v
    return out


# ──────────────────────── conversion ────────────────────────

def _flatten(value: Any) -> Any:
    """Orca uses arrays for some fields to support multi-extruder. Take
    the first element for our single-extruder pipeline and leave scalars
    alone.
    """
    if isinstance(value, list):
        return value[0] if value else ""
    return value


def _format_for_ini(key: str, value: Any) -> Optional[str]:
    """Coerce a remapped value into the string PrusaSlicer's ini parser
    accepts. Returns ``None`` if the value should be skipped.
    """
    # bed_shape is the one Prusa key that wants the full array joined with
    # commas — Orca's printable_area is e.g. ["0x0","300x0","300x300","0x300"].
    if key == "bed_shape" and isinstance(value, list):
        joined = ",".join(str(p) for p in value if p)
        return joined or None

    v = _flatten(value)
    if v is None or v == "":
        return None
    # Booleans serialize as 1/0 (Orca already uses "0"/"1" strings, but
    # native bools may sneak in via overrides).
    if isinstance(v, bool):
        return "1" if v else "0"
    # Some values come in as Orca enum strings — transform if known.
    transforms = _VALUE_TRANSFORMS.get(key)
    if transforms and isinstance(v, str) and v in transforms:
        v = transforms[v]
    s = str(v).strip()
    # Strip any %% Orca might have left and re-add for percent-typed keys.
    if key in _PERCENT_KEYS:
        if not s.endswith("%"):
            s = f"{s}%"
    elif s.endswith("%"):
        # Orca often expresses speeds/accelerations as a percentage of a
        # base value; Prusa wants absolute numbers for most keys. Rather
        # than do the math wrong, drop and let Prusa fall back to default.
        return None
    return s


def to_prusa_ini(orca_resolved: dict[str, Any]) -> dict[str, str]:
    """Rename + clean a resolved Orca profile dict into PrusaSlicer ini
    ready key/value pairs.
    """
    out: dict[str, str] = {}
    for orca_key, raw in orca_resolved.items():
        prusa_key = _ORCA_TO_PRUSA.get(orca_key)
        if prusa_key is None:
            continue  # Unknown / unsupported in PrusaSlicer
        formatted = _format_for_ini(prusa_key, raw)
        if formatted is None:
            continue
        out[prusa_key] = formatted
    return out


# ──────────────────────── catalogue ────────────────────────

def list_machines() -> list[dict[str, Any]]:
    """User-facing machine list (only ``instantiation: true`` profiles)."""
    out = []
    for name, p in _build_index().items():
        # We want the per-nozzle printer profiles (e.g. "Phrozen Arco 0.4 nozzle").
        if p.get("printer_technology") != "FFF":
            continue
        if p.get("instantiation") != "true":
            continue
        resolved = resolve(name)
        vendor = p.get("_vendor", "")
        model = resolved.get("printer_model", "")
        cover_url = None
        if model and vendor:
            # Cover convention: ``<vendor>/<model>_cover.png`` lives next
            # to the vendor manifest. We just expose a URL here; the
            # /api/v2/fdm/profiles/cover endpoint serves the bytes.
            cover_path = get_profiles_dir() / vendor / f"{model}_cover.png"
            if cover_path.exists():
                from urllib.parse import quote
                cover_url = f"/api/v2/fdm/profiles/cover/{quote(vendor)}/{quote(model)}"
        out.append({
            "name": name,
            "vendor": vendor,
            "model": model,
            "nozzle": _flatten(resolved.get("nozzle_diameter", "")),
            "coverUrl": cover_url,
            "params": to_prusa_ini(resolved),
        })
    out.sort(key=lambda x: (x["vendor"], x["name"]))
    return out


def get_cover_path(vendor: str, model: str) -> Optional[Path]:
    """Return the on-disk path to a machine's cover image, or None."""
    if not vendor or not model:
        return None
    p = get_profiles_dir() / vendor / f"{model}_cover.png"
    return p if p.exists() else None


def list_filaments() -> list[dict[str, Any]]:
    out = []
    for name, p in _build_index().items():
        if p.get("type") != "filament":
            continue
        if p.get("instantiation") != "true":
            continue
        resolved = resolve(name)
        out.append({
            "name": name,
            "vendor": p.get("_vendor", ""),
            "type": _flatten(resolved.get("filament_type", "")),
            "compatible_machines": resolved.get("compatible_printers", []),
            "params": to_prusa_ini(resolved),
        })
    out.sort(key=lambda x: (x["vendor"], x["name"]))
    return out


def list_processes() -> list[dict[str, Any]]:
    out = []
    for name, p in _build_index().items():
        if p.get("type") != "process":
            continue
        if p.get("instantiation") != "true":
            continue
        resolved = resolve(name)
        out.append({
            "name": name,
            "vendor": p.get("_vendor", ""),
            "compatible_machines": resolved.get("compatible_printers", []),
            "params": to_prusa_ini(resolved),
        })
    out.sort(key=lambda x: (x["vendor"], x["name"]))
    return out


def get_bundle_version() -> str:
    """Read the Phrozen vendor manifest's version field. Falls back to
    "unknown" if no manifest is found.
    """
    root = get_profiles_dir()
    for vendor_json in root.glob("*.json"):
        data = _read_json(vendor_json)
        if isinstance(data, dict) and "version" in data:
            return data["version"]
    return "unknown"


def merge_profiles(
    machine: Optional[str] = None,
    filament: Optional[str] = None,
    process: Optional[str] = None,
    overrides: Optional[dict[str, Any]] = None,
) -> dict[str, str]:
    """Compose final ini params: machine → filament → process → overrides.

    Each profile is fetched, resolved, remapped to Prusa keys, and merged
    in this order (later wins). Overrides come from the user panel.
    """
    out: dict[str, str] = {}
    for name in (machine, filament, process):
        if not name:
            continue
        out.update(to_prusa_ini(resolve(name)))
    if overrides:
        # Overrides may already be Prusa-style keys (the panel uses snake_case
        # matching Prusa) — apply directly.
        for k, v in overrides.items():
            formatted = _format_for_ini(k, v)
            if formatted is None:
                continue
            out[k] = formatted
    return out
