"""Job management for the web_slicer_core agent."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import subprocess
import uuid
import zipfile
from pathlib import Path
from typing import Optional

from .config import JOBS_DIR, SLICER_ENGINE_CLI, EXPORT_PROJECT_3MF
from .models import JobStatus, SLAConfig, _extract_prz_timing_config
from .prz_encoder import _compute_print_time, sl1_layer_names
from .sla_operations import generate_config_ini, notify_launcher_if_prusa_crashed, _english_locale_env
from .slicing_classifier import classify_slice_result

logger = logging.getLogger(__name__)


def create_job_id() -> str:
    """Generate a unique job ID."""
    return str(uuid.uuid4())[:8]



def get_job_dir(job_id: str) -> Path:
    """Get the directory for a job."""
    return JOBS_DIR / job_id


def get_job_status_file(job_id: str) -> Path:
    """Get the status file path for a job."""
    return get_job_dir(job_id) / "status.json"


def job_exists(job_id: str) -> bool:
    """Check if a job exists."""
    return get_job_dir(job_id).exists()


def read_job_status(job_id: str) -> dict:
    """Read the job status from disk.

    Older status.json files predate the ``error_code`` / ``support_outcome``
    fields. They are normalized to ``None`` on read so every consumer sees a
    consistent shape: a FAILED job without ``error_code`` falls back to the
    generic JOB_FAILED, and a COMPLETED job without ``support_outcome`` simply
    carries no neutral hint.
    """
    status_file = get_job_status_file(job_id)
    if status_file.exists():
        with open(status_file, "r") as f:
            data = json.load(f)
    else:
        data = {
            "status": JobStatus.PENDING,
            "error": None,
            "layer_count": None,
            "estimated_print_time": None,
            "resin_volume_ml": None,
        }
    data.setdefault("error_code", None)
    data.setdefault("support_outcome", None)
    return data


def write_job_status(
    job_id: str,
    status: JobStatus,
    error: Optional[str] = None,
    error_code: Optional[str] = None,
    support_outcome: Optional[str] = None,
    layer_count: Optional[int] = None,
    estimated_print_time: Optional[float] = None,
    resin_volume_ml: Optional[float] = None,
    has_support_mesh: bool = False,
    has_hollow_mesh: bool = False,
    has_cut_mesh: bool = False,
):
    """Write the job status to disk.

    ``error_code`` carries the specific failure code for FAILED jobs;
    ``support_outcome`` carries a neutral marker (e.g. ``SUPPORT_NOT_NEEDED``)
    on a COMPLETED job. Both are optional and absent from older status.json
    files, which readers treat as "no specific code" / "no neutral outcome".
    """
    status_file = get_job_status_file(job_id)
    data = {
        "status": status.value,
        "error": error,
        "error_code": error_code,
        "support_outcome": support_outcome,
        "layer_count": layer_count,
        "estimated_print_time": estimated_print_time,
        "resin_volume_ml": resin_volume_ml,
        "has_support_mesh": has_support_mesh,
        "has_hollow_mesh": has_hollow_mesh,
        "has_cut_mesh": has_cut_mesh,
    }
    with open(status_file, "w") as f:
        json.dump(data, f)


def create_job(job_id: str) -> Path:
    """Create a new job directory structure."""
    job_dir = get_job_dir(job_id)
    (job_dir / "input").mkdir(parents=True, exist_ok=True)
    (job_dir / "output").mkdir(exist_ok=True)
    write_job_status(job_id, JobStatus.PENDING)
    return job_dir


def _load_prz_config(job_dir: Path) -> Optional[dict]:
    """Load the persisted frontend config from jobs/{id}/prz_config.json.

    IO boundary (design D3, boundary 1): swallows file-missing / malformed-JSON
    errors and returns None so the caller can fall back to the fork estimate.
    """
    path = job_dir / "prz_config.json"
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (OSError, ValueError):  # file absent / JSON corrupt
        return None


def resolve_estimated_print_time(
    prz_config: Optional[dict],
    total_layers: Optional[int],
    fallback: Optional[float],
) -> Optional[float]:
    """Resolve the PRZ physical print time, degrading to ``fallback`` on any failure.

    Pure function (design D3, boundary 2): no IO, no side effects. Null-guards
    sit outside the try (no exception-driven control flow); extraction and
    computation share a single try whose any failure returns ``fallback``.
    """
    if not prz_config or not total_layers:
        return fallback  # no config / no layers → use fork estimate
    try:
        timing = _extract_prz_timing_config(prz_config)
        return _compute_print_time(prz_config, total_layers, timing)
    except Exception:
        return fallback  # extraction / computation failure → use fork estimate


async def run_slicing(job_id: str, config: Optional[SLAConfig] = None):
    """Run PrusaSlicer in the background."""
    job_dir = get_job_dir(job_id)
    input_file = job_dir / "input" / "model.stl"
    output_file = job_dir / "output" / "model.sl1"
    support_stl_file = job_dir / "output" / "model_support.stl"
    stderr_file = job_dir / "stderr.log"
    config_file = job_dir / "config.ini"

    # Imported support mesh (dual-track binary rasterization): when the frontend
    # uploaded a separate support STL, the slicer must NOT self-generate supports
    # or a pad (the raft is part of the imported mesh). Force both off so the INI
    # is written with supports_enable=0 / pad_enable=0.
    import_support_file = job_dir / "input" / "support.stl"
    import_support = import_support_file.exists()
    if import_support and config is not None:
        config.supports_enable = False
        config.pad_enable = False

    # Check if supports are enabled
    supports_enabled = config.supports_enable if config else False

    # Update status to processing
    write_job_status(job_id, JobStatus.PROCESSING)

    # Generate config INI if config provided
    if config:
        generate_config_ini(config, config_file)
        # Also save config as JSON for reference
        with open(job_dir / "config.json", "w") as f:
            json.dump(config.model_dump(), f, indent=2)

    try:
        # Run PrusaSlicer CLI
        cmd = [
            str(SLICER_ENGINE_CLI),
            "--export-sla",
            "--export-preview-pngs", "0.25",
            "--output", str(output_file),
        ]

        # Add support STL export if supports are enabled.
        # Mutually exclusive with --import-support-stl below: when a support STL
        # is imported, supports_enable was forced False above, so supports_enabled
        # is False here and this self-generated-support export branch is skipped.
        if supports_enabled:
            cmd.append("--export-support-stl")

        # Add center position
        if config:
            cmd.extend(["--center", f"{config.center_x},{config.center_y}"])

        # Add config file if generated
        if config and config_file.exists():
            cmd.extend(["--load", str(config_file)])

        # Import the separate support mesh as the support track (dual-track).
        if import_support:
            cmd.extend(["--import-support-stl", str(import_support_file)])

        cmd.append(str(input_file))

        # [layer-rle] Emit layers as PRZ-compatible RLE (not PNG) so the PRZ
        # download reads them verbatim — no PNG encode (slice) / decode
        # (download) round-trip. PRZ output is byte-identical (verified). The
        # layers.zip endpoint converts back to PNG on demand for the rare
        # PNG-expecting fallback.
        slice_env = {**_english_locale_env(), "SLA_LAYER_RLE": "1"}

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=slice_env,
        )

        stdout, stderr = await process.communicate()

        # Save stderr for debugging
        with open(stderr_file, "wb") as f:
            f.write(stderr)

        notify_launcher_if_prusa_crashed(process.returncode)

        failure = classify_slice_result(
            exit_code=process.returncode,
            stdout=stdout,
            stderr=stderr,
            input_filename=input_file.name,
            output_file_exists=output_file.exists(),
        )
        if failure is not None:
            write_job_status(
                job_id,
                JobStatus.FAILED,
                error=failure.error,
                error_code=failure.error_code,
            )
            return

        # Successful slice: output file is guaranteed to exist here.
        layer_count, fork_print_time, resin_volume_ml = parse_sl1_metadata(output_file)

        # Sync estimated_print_time to the PRZ physical formula (single source
        # of truth, identical to the PRZ download path). Any failure degrades
        # to the fork SL1 estimate without affecting the COMPLETED status.
        prz_config = _load_prz_config(job_dir)
        if prz_config is None:
            logger.info(
                "prz_config missing, falling back to fork time (job=%s)", job_id
            )
        estimated_print_time = resolve_estimated_print_time(
            prz_config, layer_count, fork_print_time
        )

        # Check if support mesh was generated
        has_support_mesh = support_stl_file.exists()

        # Experimental: Export 3MF project file for support inspection
        if EXPORT_PROJECT_3MF:
            await export_project_3mf(job_id, input_file, job_dir / "output")

        write_job_status(
            job_id,
            JobStatus.COMPLETED,
            layer_count=layer_count,
            estimated_print_time=estimated_print_time,
            resin_volume_ml=resin_volume_ml,
            has_support_mesh=has_support_mesh,
        )

    except Exception as e:
        write_job_status(job_id, JobStatus.FAILED, error=str(e))


async def export_project_3mf(job_id: str, input_file: Path, output_dir: Path):
    """
    Experimental: Export 3MF project file to inspect support preservation.

    This runs a separate PrusaSlicer CLI invocation with --export-3mf.
    The 3MF file can be opened in PrusaSlicer GUI to check if supports
    are preserved or need to be reconstructed.
    """
    output_3mf = output_dir / "project_with_support.3mf"
    stderr_file = output_dir / "3mf_export_stderr.log"

    try:
        cmd = [
            str(SLICER_ENGINE_CLI),
            "--export-3mf",
            "--output", str(output_3mf),
            str(input_file),
        ]

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await process.communicate()

        # Save stderr for debugging
        with open(stderr_file, "wb") as f:
            f.write(stderr)

        if process.returncode != 0:
            # Log but don't fail the job - this is experimental
            error_msg = stderr.decode("utf-8", errors="replace")
            print(f"[experimental] 3MF export failed for job {job_id}: {error_msg}")
        else:
            print(f"[experimental] 3MF exported: {output_3mf}")

    except Exception as e:
        # Log but don't fail the job
        print(f"[experimental] 3MF export error for job {job_id}: {e}")


def parse_sl1_metadata(sl1_file: Path) -> tuple[int, Optional[float], Optional[float]]:
    """Parse layer count and metadata from .sl1 file without extracting PNGs."""
    layer_count = 0
    estimated_print_time = None
    resin_volume_ml = None

    with zipfile.ZipFile(sl1_file, "r") as zf:
        if "config.ini" in zf.namelist():
            try:
                with zf.open("config.ini") as config_file:
                    for raw_line in config_file:
                        line = raw_line.decode("utf-8", errors="ignore").strip()
                        if not line or line.startswith("#") or "=" not in line:
                            continue
                        key, value = (part.strip() for part in line.split("=", 1))
                        if key == "printTime":
                            estimated_print_time = float(value)
                        elif key == "usedMaterial":
                            resin_volume_ml = float(value)
            except Exception:
                estimated_print_time = None
                resin_volume_ml = None

        # 層數以 sl1_layer_names() 統計（單一真值來源）：涵蓋 .rle（PRZ 快路徑）與
        # .png 兩種輸出，並排除縮圖污染。切片器改以 SLA_LAYER_RLE 輸出 .rle 後，
        # 舊的 endswith(".png") 會恆為 0，使 print-time 同步靜默失效。
        layer_count = len(sl1_layer_names(zf.namelist()))

    return layer_count, estimated_print_time, resin_volume_ml


def get_layer_png_from_sl1(job_id: str, layer_idx: int) -> Optional[bytes]:
    """Read a single layer as PNG bytes directly from the .sl1 archive.

    層檔以 sl1_layer_names() 定位（.rle 優先，否則 .png），涵蓋 RLE 與 PNG 兩種輸出。
    選中檔為 .rle 時以 rle_layer_to_png() 即時解碼。索引越界或解碼失敗（如缺解析度）
    皆回 None，由上層端點轉為 HTTP 404（維持既有契約，design D3）。
    """
    from .prz_decoder import rle_layer_to_png

    sl1_path = get_job_dir(job_id) / "output" / "model.sl1"
    if not sl1_path.exists():
        return None

    with zipfile.ZipFile(sl1_path, "r") as zf:
        layer_names = sl1_layer_names(zf.namelist())
        if not (0 <= layer_idx < len(layer_names)):
            return None
        name = layer_names[layer_idx]
        if name.endswith(".rle"):
            return rle_layer_to_png(zf, name)  # None on missing resolution → 404
        return zf.read(name)


def get_support_mesh_path(job_id: str) -> Optional[Path]:
    """Get the path to the support mesh STL file."""
    support_path = get_job_dir(job_id) / "output" / "model_support.stl"
    if support_path.exists():
        return support_path
    return None


def get_input_model_path(job_id: str) -> Optional[Path]:
    """Get the path to the original input model STL file."""
    model_path = get_job_dir(job_id) / "input" / "model.stl"
    if model_path.exists():
        return model_path
    return None


async def run_support_generation(job_id: str, config: Optional[SLAConfig] = None):
    """
    Generate support mesh only (without layer extraction).

    Uses the sla_operations API for clean implementation.
    """
    from .sla_operations import generate_supports

    job_dir = get_job_dir(job_id)
    write_job_status(job_id, JobStatus.PROCESSING)

    try:
        # Use default config if not provided
        if config is None:
            config = SLAConfig(supports_enable=True)

        result = await generate_supports(job_dir, config)
        classification = result.classification

        if classification is not None:
            # Drive status entirely from the classifier's structured verdict
            # (design D1/D4): failures carry the specific error_code; neutral
            # results ride on COMPLETED with a support_outcome; real success
            # sets has_support_mesh.
            if classification.status == JobStatus.FAILED:
                write_job_status(
                    job_id,
                    JobStatus.FAILED,
                    error=result.error,
                    error_code=classification.error_code,
                )
            else:
                write_job_status(
                    job_id,
                    JobStatus.COMPLETED,
                    layer_count=0,  # No layers extracted for support-only
                    support_outcome=classification.support_outcome,
                    has_support_mesh=classification.has_support_mesh,
                )
        elif result.success:
            # Defensive fallback: generate_supports always classifies, but keep
            # a safe path so a missing classification never silently drops status.
            write_job_status(
                job_id,
                JobStatus.COMPLETED,
                layer_count=0,
                has_support_mesh=True,
            )
        else:
            write_job_status(job_id, JobStatus.FAILED, error=result.error)

    except Exception as e:
        write_job_status(job_id, JobStatus.FAILED, error=str(e))


def get_hollow_mesh_path(job_id: str) -> Optional[Path]:
    """Get the path to the hollow interior mesh STL file."""
    hollow_path = get_job_dir(job_id) / "output" / "model_hollow.stl"
    if hollow_path.exists():
        return hollow_path
    return None


async def run_hollow_generation(job_id: str, config: Optional[SLAConfig] = None):
    """
    Generate hollow interior mesh only.

    Uses the sla_operations API for clean implementation.
    """
    from .sla_operations import generate_hollow

    job_dir = get_job_dir(job_id)
    write_job_status(job_id, JobStatus.PROCESSING)

    try:
        # Use default config if not provided
        if config is None:
            config = SLAConfig(hollowing_enable=True)

        result = await generate_hollow(job_dir, config)

        if result.success:
            write_job_status(
                job_id,
                JobStatus.COMPLETED,
                layer_count=0,  # No layers extracted for hollow-only
                has_hollow_mesh=True,
            )
        else:
            write_job_status(job_id, JobStatus.FAILED, error=result.error)

    except Exception as e:
        write_job_status(job_id, JobStatus.FAILED, error=str(e))


def get_cut_mesh_path(job_id: str) -> Optional[Path]:
    """Get the path to the combined cut mesh STL file (contains both upper and lower parts)."""
    output_dir = get_job_dir(job_id) / "output"

    # Check standard naming for combined file
    cut_path = output_dir / "model_cut.stl"
    if cut_path.exists():
        return cut_path

    # If no combined file, return upper part as default
    upper_path = output_dir / "model_upper.stl"
    if upper_path.exists():
        return upper_path

    return None


def get_cut_upper_mesh_path(job_id: str) -> Optional[Path]:
    """Get the path to the upper cut mesh STL file."""
    output_dir = get_job_dir(job_id) / "output"

    # Check for separated upper file
    upper_path = output_dir / "model_upper.stl"
    if upper_path.exists():
        return upper_path

    # Fallback to combined file
    cut_path = output_dir / "model_cut.stl"
    if cut_path.exists():
        return cut_path

    return None


def get_cut_lower_mesh_path(job_id: str) -> Optional[Path]:
    """Get the path to the lower cut mesh STL file."""
    output_dir = get_job_dir(job_id) / "output"

    # Check for separated lower file
    lower_path = output_dir / "model_lower.stl"
    if lower_path.exists():
        return lower_path

    return None


def get_drain_holes_path(job_id: str) -> Optional[Path]:
    """Get the path to the drain holes STL file."""
    drain_path = get_job_dir(job_id) / "output" / "model_drain_holes.stl"
    if drain_path.exists():
        return drain_path
    return None


def get_hex_grid_path(job_id: str) -> Optional[Path]:
    """Get the path to the hex grid STL file."""
    hex_path = get_job_dir(job_id) / "output" / "model_hex_grid.stl"
    if hex_path.exists():
        return hex_path
    return None


def get_boolean_mesh_path(job_id: str) -> Optional[Path]:
    """Get the path to the boolean result STL file."""
    output_dir = get_job_dir(job_id) / "output"

    # Check for any boolean result file
    for op in ["union", "difference", "intersection"]:
        bool_path = output_dir / f"model_boolean_{op}.stl"
        if bool_path.exists():
            return bool_path

    return None


async def run_cut_operation(job_id: str, cut_height: float, keep_mode: str = "both"):
    """
    Cut mesh at specified Z height.

    Uses the sla_operations API for clean implementation.

    Args:
        job_id: Job ID
        cut_height: Z height to cut at
        keep_mode: "both", "upper", or "lower"
    """
    from .models import CutConfig, CutMode
    from .sla_operations import cut_with_plane

    job_dir = get_job_dir(job_id)
    write_job_status(job_id, JobStatus.PROCESSING)

    try:
        # Convert string to CutMode enum
        mode = CutMode(keep_mode) if keep_mode in [m.value for m in CutMode] else CutMode.BOTH
        cut_config = CutConfig(cut_height=cut_height, keep_mode=mode)
        result = await cut_with_plane(job_dir, cut_config)

        if result.success:
            write_job_status(
                job_id,
                JobStatus.COMPLETED,
                layer_count=0,  # No layers for cut operation
                has_cut_mesh=True,
            )
        else:
            write_job_status(job_id, JobStatus.FAILED, error=result.error)

    except Exception as e:
        write_job_status(job_id, JobStatus.FAILED, error=str(e))
