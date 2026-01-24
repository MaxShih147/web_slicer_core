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
    return {"status": JobStatus.PENDING, "error": None, "layer_count": None}


def write_job_status(
    job_id: str,
    status: JobStatus,
    error: Optional[str] = None,
    layer_count: Optional[int] = None,
    has_support_mesh: bool = False,
):
    """Write the job status to disk."""
    status_file = get_job_status_file(job_id)
    data = {
        "status": status.value,
        "error": error,
        "layer_count": layer_count,
        "has_support_mesh": has_support_mesh,
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
            layer_count = extract_layers(output_file, layers_dir)

            # Check if support mesh was generated
            has_support_mesh = support_stl_file.exists()

            # Experimental: Export 3MF project file for support inspection
            if EXPORT_PROJECT_3MF:
                await export_project_3mf(job_id, input_file, job_dir / "output")

            write_job_status(job_id, JobStatus.COMPLETED, layer_count=layer_count, has_support_mesh=has_support_mesh)
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


def extract_layers(sl1_file: Path, layers_dir: Path) -> int:
    """Extract PNG layers from .sl1 file to layers directory."""
    layer_count = 0

    with zipfile.ZipFile(sl1_file, "r") as zf:
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

    return layer_count


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
