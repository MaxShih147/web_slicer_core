"""
SLA Operations API - Clean abstraction layer for PrusaSlicer operations.

This module provides a simple, extensible API for various SLA operations:
- Support generation
- Pad generation
- Slicing (full layer export)
- Future: Hollow, drill holes, etc.

Design principles:
1. Each operation is a separate function with clear inputs/outputs
2. Operations can be chained (e.g., generate supports → slice)
3. Consistent error handling and status reporting
4. Easy to extend with new operations
"""

import asyncio
import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional, Dict, Any, List

from .config import PRUSA_SLICER_CLI
from .models import SLAConfig


class OperationType(str, Enum):
    """Available SLA operations."""
    GENERATE_SUPPORTS = "generate_supports"
    SLICE = "slice"
    # Future operations
    # HOLLOW = "hollow"
    # DRILL = "drill"


@dataclass
class OperationResult:
    """Result of an SLA operation."""
    success: bool
    operation: OperationType
    job_id: str
    error: Optional[str] = None
    # Output paths
    support_mesh_path: Optional[Path] = None
    sl1_path: Optional[Path] = None
    layer_count: int = 0
    # Metadata
    metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "operation": self.operation.value,
            "job_id": self.job_id,
            "error": self.error,
            "support_mesh_path": str(self.support_mesh_path) if self.support_mesh_path else None,
            "sl1_path": str(self.sl1_path) if self.sl1_path else None,
            "layer_count": self.layer_count,
            "metadata": self.metadata,
        }


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


async def run_prusa_cli(
    cmd: List[str],
    stderr_file: Optional[Path] = None
) -> tuple[int, bytes, bytes]:
    """
    Run PrusaSlicer CLI command.

    Returns:
        Tuple of (return_code, stdout, stderr)
    """
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()

    if stderr_file:
        with open(stderr_file, "wb") as f:
            f.write(stderr)

    return process.returncode, stdout, stderr


async def generate_supports(
    job_dir: Path,
    config: SLAConfig,
    input_file: Optional[Path] = None,
) -> OperationResult:
    """
    Generate support mesh only (minimal slicing for support preview).

    This runs PrusaSlicer to generate supports but skips layer extraction.
    Optimized for quick preview - uses the configured layer height but
    doesn't extract PNG layers.

    Args:
        job_dir: Job directory containing input/output folders
        config: SLA configuration (supports_enable will be forced True)
        input_file: Optional input STL path. Defaults to job_dir/input/model.stl

    Returns:
        OperationResult with support_mesh_path if successful
    """
    job_id = job_dir.name
    input_file = input_file or (job_dir / "input" / "model.stl")
    output_file = job_dir / "output" / "model.sl1"
    support_stl = job_dir / "output" / "model_support.stl"
    config_file = job_dir / "config.ini"
    stderr_file = job_dir / "stderr_support.log"

    # Ensure supports are enabled
    config.supports_enable = True
    generate_config_ini(config, config_file)

    # Save config as JSON for reference
    with open(job_dir / "config.json", "w") as f:
        json.dump(config.model_dump(), f, indent=2)

    # Build command - we need --export-sla to trigger support generation
    # but we won't extract layers from the result
    cmd = [
        str(PRUSA_SLICER_CLI),
        "--export-sla",
        "--export-support-stl",
        "--output", str(output_file),
        "--load", str(config_file),
        str(input_file),
    ]

    returncode, stdout, stderr = await run_prusa_cli(cmd, stderr_file)

    if returncode != 0:
        error_msg = stderr.decode("utf-8", errors="replace")
        return OperationResult(
            success=False,
            operation=OperationType.GENERATE_SUPPORTS,
            job_id=job_id,
            error=f"PrusaSlicer failed (exit {returncode}): {error_msg}",
        )

    if not support_stl.exists():
        return OperationResult(
            success=False,
            operation=OperationType.GENERATE_SUPPORTS,
            job_id=job_id,
            error="Support mesh was not generated. Model may not need supports.",
        )

    return OperationResult(
        success=True,
        operation=OperationType.GENERATE_SUPPORTS,
        job_id=job_id,
        support_mesh_path=support_stl,
        sl1_path=output_file if output_file.exists() else None,
        metadata={"config": config.model_dump()},
    )


async def slice_model(
    job_dir: Path,
    config: SLAConfig,
    input_file: Optional[Path] = None,
    extract_layers: bool = True,
) -> OperationResult:
    """
    Full slicing with layer extraction.

    Args:
        job_dir: Job directory
        config: SLA configuration
        input_file: Optional input STL path
        extract_layers: Whether to extract PNG layers from SL1

    Returns:
        OperationResult with layer_count and paths
    """
    job_id = job_dir.name
    input_file = input_file or (job_dir / "input" / "model.stl")
    output_file = job_dir / "output" / "model.sl1"
    support_stl = job_dir / "output" / "model_support.stl"
    layers_dir = job_dir / "layers"
    config_file = job_dir / "config.ini"
    stderr_file = job_dir / "stderr_slice.log"

    generate_config_ini(config, config_file)

    with open(job_dir / "config.json", "w") as f:
        json.dump(config.model_dump(), f, indent=2)

    # Build command
    cmd = [
        str(PRUSA_SLICER_CLI),
        "--export-sla",
        "--output", str(output_file),
        "--load", str(config_file),
    ]

    # Add support export if enabled
    if config.supports_enable:
        cmd.append("--export-support-stl")

    cmd.append(str(input_file))

    returncode, stdout, stderr = await run_prusa_cli(cmd, stderr_file)

    if returncode != 0:
        error_msg = stderr.decode("utf-8", errors="replace")
        return OperationResult(
            success=False,
            operation=OperationType.SLICE,
            job_id=job_id,
            error=f"Slicing failed (exit {returncode}): {error_msg}",
        )

    if not output_file.exists():
        return OperationResult(
            success=False,
            operation=OperationType.SLICE,
            job_id=job_id,
            error="Output SL1 file was not created",
        )

    layer_count = 0
    if extract_layers:
        layer_count = _extract_layers_from_sl1(output_file, layers_dir)

    return OperationResult(
        success=True,
        operation=OperationType.SLICE,
        job_id=job_id,
        support_mesh_path=support_stl if support_stl.exists() else None,
        sl1_path=output_file,
        layer_count=layer_count,
        metadata={"config": config.model_dump()},
    )


def _extract_layers_from_sl1(sl1_file: Path, layers_dir: Path) -> int:
    """Extract PNG layers from .sl1 file to layers directory."""
    import zipfile

    layer_count = 0
    layers_dir.mkdir(exist_ok=True)

    with zipfile.ZipFile(sl1_file, "r") as zf:
        for name in sorted(zf.namelist()):
            if name.endswith(".png"):
                try:
                    base = Path(name).stem
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


# =============================================================================
# Future Operations (stubs for extension)
# =============================================================================

async def hollow_model(
    job_dir: Path,
    wall_thickness: float = 2.0,
    input_file: Optional[Path] = None,
) -> OperationResult:
    """
    Hollow the model (future implementation).

    PrusaSlicer supports hollowing via:
    - GUI: Right-click → Hollow
    - CLI: May need custom implementation or external tool
    """
    raise NotImplementedError("Hollow operation not yet implemented")


async def drill_hole(
    job_dir: Path,
    position: tuple[float, float, float],
    diameter: float,
    depth: float,
    input_file: Optional[Path] = None,
) -> OperationResult:
    """
    Drill a hole in the model (future implementation).

    May need to use CSG operations or external tools.
    """
    raise NotImplementedError("Drill operation not yet implemented")
