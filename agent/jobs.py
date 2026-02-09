"""Job management for the web_slicer_core agent."""

import asyncio
import json
import shutil
import subprocess
import uuid
import zipfile
from pathlib import Path
from typing import Optional

from .config import JOBS_DIR, PRUSA_SLICER_CLI, EXPORT_PROJECT_3MF
from .models import JobStatus, SLAConfig


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
    """Read the job status from disk."""
    status_file = get_job_status_file(job_id)
    if status_file.exists():
        with open(status_file, "r") as f:
            return json.load(f)
    return {
        "status": JobStatus.PENDING,
        "error": None,
        "layer_count": None,
        "estimated_print_time": None,
        "resin_volume_ml": None,
    }


def write_job_status(
    job_id: str,
    status: JobStatus,
    error: Optional[str] = None,
    layer_count: Optional[int] = None,
    estimated_print_time: Optional[float] = None,
    resin_volume_ml: Optional[float] = None,
    has_support_mesh: bool = False,
    has_hollow_mesh: bool = False,
    has_cut_mesh: bool = False,
):
    """Write the job status to disk."""
    status_file = get_job_status_file(job_id)
    data = {
        "status": status.value,
        "error": error,
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
    (job_dir / "layers").mkdir(exist_ok=True)
    write_job_status(job_id, JobStatus.PENDING)
    return job_dir


def generate_config_ini(config: SLAConfig, output_path: Path) -> None:
    """Generate a PrusaSlicer INI config file from SLAConfig."""
    lines = [
        "# Generated SLA config",
        f"layer_height = {config.layer_height}",
        f"exposure_time = {config.exposure_time}",
        f"initial_exposure_time = {config.initial_exposure_time}",
        f"supports_enable = {1 if config.supports_enable else 0}",
        f"support_head_front_diameter = {config.support_head_front_diameter}",
        f"support_head_penetration = {config.support_head_penetration}",
        f"support_pillar_diameter = {config.support_pillar_diameter}",
        f"support_points_density_relative = {config.support_points_density_relative}",
        f"support_object_elevation = {max(5.0, config.support_object_elevation)}",
        f"support_critical_angle = {config.support_critical_angle}",
        f"pad_enable = {1 if config.pad_enable else 0}",
    ]
    with open(output_path, "w") as f:
        f.write("\n".join(lines) + "\n")


async def run_slicing(job_id: str, config: Optional[SLAConfig] = None):
    """Run PrusaSlicer in the background."""
    job_dir = get_job_dir(job_id)
    input_file = job_dir / "input" / "model.stl"
    output_file = job_dir / "output" / "model.sl1"
    support_stl_file = job_dir / "output" / "model_support.stl"
    layers_dir = job_dir / "layers"
    stderr_file = job_dir / "stderr.log"
    config_file = job_dir / "config.ini"

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
            str(PRUSA_SLICER_CLI),
            "--export-sla",
            "--output", str(output_file),
        ]

        # Add support STL export if supports are enabled
        if supports_enabled:
            cmd.append("--export-support-stl")

        # Add config file if generated
        if config and config_file.exists():
            cmd.extend(["--load", str(config_file)])

        cmd.append(str(input_file))

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
            error_msg = stderr.decode("utf-8", errors="replace")
            write_job_status(job_id, JobStatus.FAILED, error=f"Exit code {process.returncode}: {error_msg}")
            return

        # Extract PNG layers from .sl1 (zip file)
        if output_file.exists():
            layer_count, estimated_print_time, resin_volume_ml = extract_layers(output_file, layers_dir)

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
        else:
            write_job_status(job_id, JobStatus.FAILED, error="Output file not created")

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
            str(PRUSA_SLICER_CLI),
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


def extract_layers(sl1_file: Path, layers_dir: Path) -> tuple[int, Optional[float], Optional[float]]:
    """Extract PNG layers and metadata from .sl1 file."""
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
                # Keep slicing success even if metadata parsing fails.
                estimated_print_time = None
                resin_volume_ml = None

        for name in sorted(zf.namelist()):
            if name.endswith(".png"):
                # Extract to layers directory with simplified naming
                # Original: model00000.png -> 0.png
                try:
                    # Parse the layer index from filename like "model00042.png"
                    base = Path(name).stem
                    # Find the numeric part at the end
                    idx_str = ""
                    for c in reversed(base):
                        if c.isdigit():
                            idx_str = c + idx_str
                        else:
                            break
                    if idx_str:
                        idx = int(idx_str)
                        target_path = layers_dir / f"{idx}.png"
                        with zf.open(name) as src, open(target_path, "wb") as dst:
                            dst.write(src.read())
                        layer_count += 1
                except (ValueError, IndexError):
                    continue

    return layer_count, estimated_print_time, resin_volume_ml


def get_layer_path(job_id: str, layer_idx: int) -> Optional[Path]:
    """Get the path to a specific layer PNG."""
    layer_path = get_job_dir(job_id) / "layers" / f"{layer_idx}.png"
    if layer_path.exists():
        return layer_path
    return None


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

        if result.success:
            write_job_status(
                job_id,
                JobStatus.COMPLETED,
                layer_count=0,  # No layers extracted for support-only
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
