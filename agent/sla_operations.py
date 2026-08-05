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
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional, Dict, Any, List

import struct

from .config import SLICER_ENGINE_CLI
from .models import BooleanOperation, CutConfig, CutMode, JobStatus, SLAConfig
from .support_classifier import SupportClassification, classify_support_result

logger = logging.getLogger(__name__)


def notify_launcher_if_prusa_crashed(returncode: Optional[int]) -> None:
    """Write Launcher sentinel when the slicing engine died by signal and crash test is armed.

    Used by Bundle-Launcher hybrid flow: Prusa native crash → agent sentinel →
    Launcher opens DiagnosticReports then process.crash() for the OS dialog.
    """
    if os.environ.get("BUNDLE_FORCE_PRUSA_STACK_OVERFLOW", "")[:1] != "1":
        return
    if returncode is None or returncode == 0:
        return
    # POSIX: negative == -signal; 128+signal is the shell-style encoding.
    if not (returncode < 0 or returncode >= 128):
        return
    sentinel = os.environ.get("BUNDLE_PRUSA_CRASH_SENTINEL")
    if not sentinel:
        return
    path = Path(sentinel)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "returncode": returncode,
                    "pid": os.getpid(),
                    "timestamp": time.time(),
                }
            ),
            encoding="utf-8",
        )
        logger.warning(
            "Wrote engine crash sentinel returncode=%s path=%s",
            returncode,
            path,
        )
    except OSError as exc:
        logger.error("Failed to write engine crash sentinel: %s", exc)

# Layer height used only for support-point detection (not for the final print).
# Coarser slices cut the dominant "Slicing model" cost with negligible impact on
# detected support points. See generate_supports().
SUPPORT_DETECTION_LAYER_HEIGHT = 0.15

# Locale forced to English (the C locale) whenever the engine CLI runs, so the
# classifier's Step 1 validate() substring comparison stays reliable (design D5).
# PrusaSlicer's validate() messages are wrapped in _u8L()/I18N::translate, which
# falls back to the source English strings when the active locale has no matching
# catalog; pinning C locale removes any chance a translated message slips past
# the English substring match. The stdout markers are raw literals and unaffected,
# but we pin unconditionally for determinism.
ENGINE_LOCALE_ENV = {
    "LC_ALL": "C",
    "LANG": "C",
    "LANGUAGE": "C",
}


def _english_locale_env() -> dict:
    """Return the current environment with the locale pinned to English (design D5)."""
    env = os.environ.copy()
    env.update(ENGINE_LOCALE_ENV)
    return env


def load_trimesh(path) -> "trimesh.Trimesh":
    """Load an STL file as a single trimesh.Trimesh."""
    import trimesh
    mesh = trimesh.load(str(path))
    if isinstance(mesh, trimesh.Scene):
        mesh = trimesh.util.concatenate(mesh.dump())
    return mesh


class OperationType(str, Enum):
    """Available SLA operations."""
    GENERATE_SUPPORTS = "generate_supports"
    GENERATE_HOLLOW = "generate_hollow"
    SLICE = "slice"
    CUT = "cut"
    BOOLEAN = "boolean"
    # Future operations
    # DRILL = "drill"


@dataclass
class OperationResult:
    """Result of an SLA operation."""
    success: bool
    operation: OperationType
    job_id: str
    error: Optional[str] = None
    error_code: Optional[str] = None
    # Output paths
    support_mesh_path: Optional[Path] = None
    hollow_mesh_path: Optional[Path] = None
    cut_upper_mesh_path: Optional[Path] = None
    cut_lower_mesh_path: Optional[Path] = None
    boolean_mesh_path: Optional[Path] = None
    sl1_path: Optional[Path] = None
    layer_count: int = 0
    # Metadata
    metadata: Optional[Dict[str, Any]] = None
    # Structured verdict from the support-generation classifier (design D1).
    # Only populated by generate_supports(); other operations leave it None.
    classification: Optional[SupportClassification] = None

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "operation": self.operation.value,
            "job_id": self.job_id,
            "error": self.error,
            "support_mesh_path": str(self.support_mesh_path) if self.support_mesh_path else None,
            "hollow_mesh_path": str(self.hollow_mesh_path) if self.hollow_mesh_path else None,
            "cut_upper_mesh_path": str(self.cut_upper_mesh_path) if self.cut_upper_mesh_path else None,
            "cut_lower_mesh_path": str(self.cut_lower_mesh_path) if self.cut_lower_mesh_path else None,
            "boolean_mesh_path": str(self.boolean_mesh_path) if self.boolean_mesh_path else None,
            "sl1_path": str(self.sl1_path) if self.sl1_path else None,
            "layer_count": self.layer_count,
            "metadata": self.metadata,
        }


def generate_config_ini(config: SLAConfig, output_path: Path) -> None:
    """Generate a PrusaSlicer INI config file from SLAConfig."""
    lines = ["# Generated SLA config"]
    for field_name, value in config.model_dump().items():
        if isinstance(value, bool):
            lines.append(f"{field_name} = {1 if value else 0}")
        else:
            lines.append(f"{field_name} = {value}")
    lines.append(f"bed_shape = {config.display_width},{config.display_height}")
    # Declare SLA technology explicitly so the CLI runs the SLA pipeline even
    # when --export-sla is omitted (the support-only fast path leaves it out;
    # without this the CLI would default to FFF).
    lines.append("printer_technology = SLA")
    with open(output_path, "w") as f:
        f.write("\n".join(lines) + "\n")


async def run_prusa_cli(
    cmd: List[str],
    stderr_file: Optional[Path] = None,
    stdout_file: Optional[Path] = None,
) -> tuple[int, bytes, bytes]:
    """
    Run PrusaSlicer CLI command.

    Both streams are captured in full and returned. Key result signals are
    split across the two streams (validate errors on stderr; "model out of
    bounds" and the support/pad markers on stdout), so callers that classify
    the result MUST read both. Pass ``stdout_file`` / ``stderr_file`` to also
    persist the raw bytes to disk for debugging.

    Returns:
        Tuple of (return_code, stdout, stderr)
    """
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=_english_locale_env(),  # pin English locale so validate() stays English (D5)
    )
    stdout, stderr = await process.communicate()

    if stdout_file:
        with open(stdout_file, "wb") as f:
            f.write(stdout)

    if stderr_file:
        with open(stderr_file, "wb") as f:
            f.write(stderr)

    notify_launcher_if_prusa_crashed(process.returncode)
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
    stdout_file = job_dir / "stdout_support.log"

    # Ensure supports are enabled
    config.supports_enable = True

    # Support-point detection works off per-layer island analysis, not the final
    # print resolution. This path doesn't produce an sl1, so slice the object at
    # a coarser height to slash the dominant "Slicing model" cost. The real print
    # slicing path still uses the configured layer height.
    detect_config = config.model_copy(update={
        "layer_height": SUPPORT_DETECTION_LAYER_HEIGHT,
        "initial_layer_height": SUPPORT_DETECTION_LAYER_HEIGHT,
    })
    generate_config_ini(detect_config, config_file)

    # Save config as JSON for reference
    with open(job_dir / "config.json", "w") as f:
        json.dump(config.model_dump(), f, indent=2)

    # Build command - export only the support STL. Omitting --export-sla lets
    # the slicer take the support-only fast path: it stops after the pad step,
    # skipping slice-supports + rasterization + sl1 packing (none of which the
    # support mesh depends on).
    cmd = [
        str(SLICER_ENGINE_CLI),
        "--export-support-stl",
        "--output", str(output_file),
        "--load", str(config_file),
        str(input_file),
    ]

    returncode, stdout, stderr = await run_prusa_cli(cmd, stderr_file, stdout_file)

    # Classify purely from the CLI text output — never the exit code. The fork's
    # validate() failures exit 0 (design D1), so returncode is not trusted here;
    # notify_launcher_if_prusa_crashed (inside run_prusa_cli) still watches it for
    # genuine signal-death, decoupled from this classification.
    classification = classify_support_result(
        stdout=stdout,
        stderr=stderr,
        support_stl_exists=support_stl.exists(),
    )

    if classification.status == JobStatus.FAILED:
        return OperationResult(
            success=False,
            operation=OperationType.GENERATE_SUPPORTS,
            job_id=job_id,
            error=classification.detail or "Support generation failed",
            classification=classification,
        )

    # COMPLETED: either a real support mesh (has_support_mesh) or a neutral
    # "no supports needed" result. Only expose the STL as a support mesh when the
    # classifier confirms real pillars — a pad-only STL is not a support mesh.
    return OperationResult(
        success=True,
        operation=OperationType.GENERATE_SUPPORTS,
        job_id=job_id,
        support_mesh_path=support_stl if classification.has_support_mesh else None,
        sl1_path=output_file if output_file.exists() else None,
        metadata={"config": config.model_dump()},
        classification=classification,
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
    config_file = job_dir / "config.ini"
    stderr_file = job_dir / "stderr_slice.log"

    generate_config_ini(config, config_file)

    with open(job_dir / "config.json", "w") as f:
        json.dump(config.model_dump(), f, indent=2)

    # Build command
    cmd = [
        str(SLICER_ENGINE_CLI),
        "--export-sla",
        "--export-preview-pngs", "0.25",
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

    # Count layers from .sl1 (no extraction needed, served directly on demand)
    layer_count = 0
    if extract_layers:
        import zipfile as _zf
        with _zf.ZipFile(output_file, "r") as zf:
            layer_count = sum(1 for n in zf.namelist() if n.endswith(".png"))

    return OperationResult(
        success=True,
        operation=OperationType.SLICE,
        job_id=job_id,
        support_mesh_path=support_stl if support_stl.exists() else None,
        sl1_path=output_file,
        layer_count=layer_count,
        metadata={"config": config.model_dump()},
    )



# =============================================================================
# Hollow Operation
# =============================================================================

async def generate_hollow(
    job_dir: Path,
    config: SLAConfig,
    input_file: Optional[Path] = None,
) -> OperationResult:
    """
    Generate hollow interior mesh only.

    This runs PrusaSlicer with --export-hollow-stl to generate just the
    interior mesh for visualization. The frontend will combine this with
    the original mesh.

    Args:
        job_dir: Job directory containing input/output folders
        config: SLA configuration with hollowing parameters
        input_file: Optional input STL path. Defaults to job_dir/input/model.stl

    Returns:
        OperationResult with hollow_mesh_path if successful
    """
    job_id = job_dir.name
    input_file = input_file or (job_dir / "input" / "model.stl")
    hollow_stl = job_dir / "output" / "model_hollow.stl"
    stderr_file = job_dir / "stderr_hollow.log"

    # Save config as JSON for reference
    with open(job_dir / "config_hollow.json", "w") as f:
        json.dump(config.model_dump(), f, indent=2)

    # Build command for hollow export
    cmd = [
        str(SLICER_ENGINE_CLI),
        "--export-hollow-stl",
        f"--hollowing-min-thickness={config.hollowing_min_thickness}",
        f"--hollowing-quality={config.hollowing_quality}",
        f"--hollowing-closing-distance={config.hollowing_closing_distance}",
        "--output", str(hollow_stl),
        str(input_file),
    ]

    returncode, stdout, stderr = await run_prusa_cli(cmd, stderr_file)

    if returncode != 0:
        error_msg = stderr.decode("utf-8", errors="replace")
        return OperationResult(
            success=False,
            operation=OperationType.GENERATE_HOLLOW,
            job_id=job_id,
            error=f"Slicing engine failed (exit {returncode}): {error_msg}",
        )

    if not hollow_stl.exists():
        return OperationResult(
            success=False,
            operation=OperationType.GENERATE_HOLLOW,
            job_id=job_id,
            error="Hollow interior mesh was not generated.",
        )

    return OperationResult(
        success=True,
        operation=OperationType.GENERATE_HOLLOW,
        job_id=job_id,
        hollow_mesh_path=hollow_stl,
        metadata={"config": config.model_dump()},
    )


# =============================================================================
# STL Mesh Utilities
# =============================================================================

def parse_binary_stl(file_path: Path) -> List[tuple]:
    """
    Parse a binary STL file and return list of triangles.
    Each triangle is (normal, v1, v2, v3) where each is (x, y, z).
    """
    triangles = []
    with open(file_path, "rb") as f:
        # Skip 80-byte header
        f.read(80)
        # Read triangle count
        num_triangles = struct.unpack("<I", f.read(4))[0]

        for _ in range(num_triangles):
            # Normal (3 floats)
            normal = struct.unpack("<3f", f.read(12))
            # Vertex 1, 2, 3 (each 3 floats)
            v1 = struct.unpack("<3f", f.read(12))
            v2 = struct.unpack("<3f", f.read(12))
            v3 = struct.unpack("<3f", f.read(12))
            # Attribute byte count (unused)
            f.read(2)
            triangles.append((normal, v1, v2, v3))

    return triangles


def write_binary_stl(file_path: Path, triangles: List[tuple], header: str = ""):
    """Write triangles to a binary STL file."""
    with open(file_path, "wb") as f:
        # 80-byte header
        header_bytes = header.encode("utf-8")[:80].ljust(80, b"\0")
        f.write(header_bytes)
        # Triangle count
        f.write(struct.pack("<I", len(triangles)))
        # Triangles
        for normal, v1, v2, v3 in triangles:
            f.write(struct.pack("<3f", *normal))
            f.write(struct.pack("<3f", *v1))
            f.write(struct.pack("<3f", *v2))
            f.write(struct.pack("<3f", *v3))
            f.write(struct.pack("<H", 0))  # Attribute byte count


def separate_mesh_components(triangles: List[tuple]) -> List[List[tuple]]:
    """
    Separate triangles into connected components using Union-Find.
    Returns list of triangle lists, one per component.
    """
    if not triangles:
        return []

    # Build vertex-to-triangle mapping
    # Round vertices to handle floating point precision
    def vertex_key(v):
        return (round(v[0], 4), round(v[1], 4), round(v[2], 4))

    vertex_to_triangles: Dict[tuple, List[int]] = {}
    for i, (_, v1, v2, v3) in enumerate(triangles):
        for v in [v1, v2, v3]:
            key = vertex_key(v)
            if key not in vertex_to_triangles:
                vertex_to_triangles[key] = []
            vertex_to_triangles[key].append(i)

    # Union-Find
    parent = list(range(len(triangles)))

    def find(x):
        if parent[x] != x:
            parent[x] = find(parent[x])
        return parent[x]

    def union(x, y):
        px, py = find(x), find(y)
        if px != py:
            parent[px] = py

    # Union triangles that share vertices
    for tri_indices in vertex_to_triangles.values():
        for i in range(1, len(tri_indices)):
            union(tri_indices[0], tri_indices[i])

    # Group triangles by component
    components: Dict[int, List[tuple]] = {}
    for i, tri in enumerate(triangles):
        root = find(i)
        if root not in components:
            components[root] = []
        components[root].append(tri)

    return list(components.values())


def get_component_z_range(component: List[tuple]) -> tuple:
    """Get the min and max Z values of a component."""
    min_z = float("inf")
    max_z = float("-inf")
    for _, v1, v2, v3 in component:
        for v in [v1, v2, v3]:
            min_z = min(min_z, v[2])
            max_z = max(max_z, v[2])
    return min_z, max_z


def separate_stl_parts(
    input_path: Path,
    output_dir: Path,
    base_name: str = "model"
) -> tuple[Optional[Path], Optional[Path]]:
    """
    Separate a multi-part STL into upper and lower components.

    PrusaSlicer's --cut places both parts at z=0, but they remain
    as separate connected components. We identify upper vs lower
    by comparing the original Z extent of each component.

    Returns (upper_path, lower_path) - either may be None if not found.
    """
    triangles = parse_binary_stl(input_path)
    components = separate_mesh_components(triangles)

    if len(components) < 2:
        # Only one component, can't separate
        return None, None

    # Sort components by their max Z (higher = upper part)
    # After PrusaSlicer cut, the "upper" part typically has a larger Z extent
    components_with_z = []
    for comp in components:
        min_z, max_z = get_component_z_range(comp)
        components_with_z.append((max_z - min_z, max_z, comp))

    # Sort by Z extent (largest first) - the upper part is usually taller after placement
    components_with_z.sort(key=lambda x: (-x[0], -x[1]))

    upper_path = None
    lower_path = None

    if len(components_with_z) >= 1:
        upper_path = output_dir / f"{base_name}_upper.stl"
        write_binary_stl(upper_path, components_with_z[0][2], f"{base_name} upper part")

    if len(components_with_z) >= 2:
        lower_path = output_dir / f"{base_name}_lower.stl"
        write_binary_stl(lower_path, components_with_z[1][2], f"{base_name} lower part")

    return upper_path, lower_path


# =============================================================================
# Cut Operation
# =============================================================================

async def cut_with_plane(
    job_dir: Path,
    cut_config: CutConfig,
    input_file: Optional[Path] = None,
) -> OperationResult:
    """
    Cut mesh at specified Z height using PrusaSlicer's --cut option.

    This uses PrusaSlicer CLI to cut the model at the specified Z height,
    then separates the parts based on the keep_mode setting.

    Args:
        job_dir: Job directory containing input/output folders
        cut_config: Configuration with cut_height and keep_mode parameters
        input_file: Optional input STL path. Defaults to job_dir/input/model.stl

    Returns:
        OperationResult with cut_upper_mesh_path and/or cut_lower_mesh_path
    """
    job_id = job_dir.name
    input_file = input_file or (job_dir / "input" / "model.stl")
    stderr_file = job_dir / "stderr_cut.log"

    output_dir = job_dir / "output"
    output_dir.mkdir(exist_ok=True)

    # Temporary output file for PrusaSlicer (combined parts)
    combined_stl = output_dir / "model_cut_combined.stl"

    # Save config as JSON for reference
    with open(job_dir / "config_cut.json", "w") as f:
        import json
        json.dump({
            "cut_height": cut_config.cut_height,
            "keep_mode": cut_config.keep_mode.value,
        }, f, indent=2)

    # Build command for cut operation
    # PrusaSlicer --cut <Z> outputs both upper and lower parts in one STL
    cmd = [
        str(SLICER_ENGINE_CLI),
        f"--cut={cut_config.cut_height}",
        "--export-stl",
        "--output", str(combined_stl),
        str(input_file),
    ]

    returncode, stdout, stderr = await run_prusa_cli(cmd, stderr_file)

    if returncode != 0:
        error_msg = stderr.decode("utf-8", errors="replace")
        return OperationResult(
            success=False,
            operation=OperationType.CUT,
            job_id=job_id,
            error=f"Slicing engine cut failed (exit {returncode}): {error_msg}",
        )

    if not combined_stl.exists():
        return OperationResult(
            success=False,
            operation=OperationType.CUT,
            job_id=job_id,
            error="Cut operation did not produce output file. The cut height may be outside the model bounds.",
        )

    # Separate the combined STL into upper and lower parts
    upper_path, lower_path = separate_stl_parts(combined_stl, output_dir, "model")

    # Determine which files to return based on keep_mode
    result_upper = None
    result_lower = None

    if cut_config.keep_mode == CutMode.BOTH:
        result_upper = upper_path
        result_lower = lower_path
        # Also keep the combined file as model_cut.stl for backwards compatibility
        combined_stl.rename(output_dir / "model_cut.stl")
    elif cut_config.keep_mode == CutMode.UPPER:
        result_upper = upper_path
        # Clean up lower and combined
        if lower_path and lower_path.exists():
            lower_path.unlink()
        if combined_stl.exists():
            combined_stl.unlink()
    elif cut_config.keep_mode == CutMode.LOWER:
        result_lower = lower_path
        # Clean up upper and combined
        if upper_path and upper_path.exists():
            upper_path.unlink()
        if combined_stl.exists():
            combined_stl.unlink()

    # Check if we got any output
    if result_upper is None and result_lower is None:
        # Fallback: if separation failed, use the combined file
        if combined_stl.exists():
            combined_stl.rename(output_dir / "model_cut.stl")
            result_upper = output_dir / "model_cut.stl"

    if result_upper is None and result_lower is None:
        return OperationResult(
            success=False,
            operation=OperationType.CUT,
            job_id=job_id,
            error="Failed to separate cut parts. The model may have only one component.",
        )

    return OperationResult(
        success=True,
        operation=OperationType.CUT,
        job_id=job_id,
        cut_upper_mesh_path=result_upper,
        cut_lower_mesh_path=result_lower,
        metadata={
            "cut_height": cut_config.cut_height,
            "keep_mode": cut_config.keep_mode.value,
        },
    )


# =============================================================================
# Future Operations (stubs for extension)
# =============================================================================

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


# =============================================================================
# Boolean Operations (Experimental)
# =============================================================================

def boolean_meshes(
    mesh_a: "trimesh.Trimesh",
    mesh_b: "trimesh.Trimesh",
    operation: BooleanOperation,
) -> "trimesh.Trimesh":
    """
    Perform boolean operation on two trimesh objects in memory.

    Returns the result trimesh. Raises RuntimeError on failure.
    """
    import manifold3d
    import numpy as np
    import trimesh as _trimesh

    logger = logging.getLogger(__name__)
    logger.info(f"Boolean {operation.value}: A={len(mesh_a.faces)} faces, B={len(mesh_b.faces)} faces")

    def trimesh_to_manifold(mesh):
        verts = np.array(mesh.vertices, dtype=np.float32)
        faces = np.array(mesh.faces, dtype=np.int32)
        mesh_gl = manifold3d.Mesh(vert_properties=verts, tri_verts=faces)
        return manifold3d.Manifold(mesh_gl)

    def manifold_to_trimesh(man):
        mesh_gl = man.to_mesh()
        return _trimesh.Trimesh(
            vertices=mesh_gl.vert_properties[:, :3],
            faces=mesh_gl.tri_verts,
            process=True,
        )

    try:
        man_a = trimesh_to_manifold(mesh_a)
        man_b = trimesh_to_manifold(mesh_b)
    except Exception as e:
        logger.warning(f"  Manifold conversion failed: {e}, falling back to trimesh repair")
        for mesh in [mesh_a, mesh_b]:
            if not mesh.is_volume:
                _trimesh.repair.fill_holes(mesh)
                _trimesh.repair.fix_winding(mesh)
                _trimesh.repair.fix_normals(mesh)
                mesh.merge_vertices()
        man_a = trimesh_to_manifold(mesh_a)
        man_b = trimesh_to_manifold(mesh_b)

    if operation == BooleanOperation.UNION:
        result_man = man_a + man_b
    elif operation == BooleanOperation.DIFFERENCE:
        result_man = man_a - man_b
    elif operation == BooleanOperation.INTERSECTION:
        result_man = man_a ^ man_b
    else:
        raise RuntimeError(f"Unknown operation: {operation}")

    result = manifold_to_trimesh(result_man)
    if result is None or (hasattr(result, 'is_empty') and result.is_empty):
        raise RuntimeError("Boolean operation resulted in empty mesh")

    logger.info(f"  Result: {len(result.faces)} faces, watertight={result.is_watertight}")
    return result


def boolean_operation(
    mesh_a_path: Path,
    mesh_b_path: Path,
    operation: BooleanOperation,
    output_path: Path,
) -> tuple[bool, Optional[str], Optional[str]]:
    """
    Perform boolean operation on two meshes using trimesh + manifold3d.

    Args:
        mesh_a_path: Path to first mesh (STL)
        mesh_b_path: Path to second mesh (STL)
        operation: Boolean operation type (union, difference, intersection)
        output_path: Path to write result STL

    Returns:
        Tuple of (success, error_message, error_code)
    """
    try:
        import trimesh
    except ImportError:
        return False, "trimesh not installed. Run: pip install trimesh manifold3d", None

    _stage = "init"
    try:
        import logging
        _log = logging.getLogger(__name__)

        def _manifold_props(man):
            """Return (status_str, num_tri, is_empty, valid_bool); never raises.
            valid is always bool: False when any property read fails (conservative)."""
            try:
                st = str(man.status())
            except Exception:
                st = "error"
            try:
                nt = man.num_tri()
            except Exception:
                nt = "error"
            try:
                ie = man.is_empty()
            except Exception:
                ie = "error"
            try:
                valid = (st == "Error.NoError" and isinstance(nt, int) and nt > 0 and ie is False)
            except Exception:
                valid = False
            return st, nt, ie, valid

        def _is_valid_manifold(man):
            """Return True only when status==NoError, num_tri>0, not empty; False on any read error."""
            _, _, _, v = _manifold_props(man)
            return v

        def _remove_repeated_index_faces(mesh, label):
            """Remove faces where any two vertex indices are equal (repeated-index faces).

            Only removes faces where face[i] == face[j] for i≠j.
            Does not use area or coordinate thresholds.
            Calls remove_unreferenced_vertices() after deletion so Trimesh cache
            is invalidated via the standard _data hash path.

            Returns a dict: removed_faces, faces_before, faces_after,
                            vertices_before, vertices_after.
            Returns removed_faces=0 (no-op) if none found.
            Returns removed_faces=-1 on unexpected error.
            """
            try:
                _fa = np.asarray(mesh.faces)
                _verts_before = len(mesh.vertices)
                _faces_before = len(_fa)

                _ri_mask = (
                    (_fa[:, 0] == _fa[:, 1]) |
                    (_fa[:, 1] == _fa[:, 2]) |
                    (_fa[:, 0] == _fa[:, 2])
                )
                _removed = int(np.sum(_ri_mask))

                if _removed == 0:
                    return {
                        "removed_faces": 0,
                        "faces_before": _faces_before,
                        "faces_after": _faces_before,
                        "vertices_before": _verts_before,
                        "vertices_after": _verts_before,
                    }

                # Assign via property setter — triggers _data hash change,
                # which auto-invalidates all Trimesh topology caches.
                mesh.faces = _fa[~_ri_mask]
                mesh.remove_unreferenced_vertices()

                _faces_after = len(mesh.faces)
                _verts_after = len(mesh.vertices)

                return {
                    "removed_faces": _removed,
                    "faces_before": _faces_before,
                    "faces_after": _faces_after,
                    "vertices_before": _verts_before,
                    "vertices_after": _verts_after,
                }

            except Exception as _exc:
                return {"removed_faces": -1, "error": str(_exc)}

        def _remove_exact_duplicate_faces(mesh, label):
            """Remove exact-duplicate faces that share the same winding via cyclic rotation.

            Two faces are same-winding duplicates when one is a cyclic rotation of the
            other: (a,b,c), (b,c,a), (c,a,b) are the same face.  One representative per
            group is kept; the rest are removed.

            Faces with identical vertex sets but opposite winding, e.g. (a,b,c) and
            (a,c,b), are counted and logged but are NOT removed.

            Assumes repeated-index faces have already been removed.
            Calls remove_unreferenced_vertices() after deletion to invalidate Trimesh cache.

            Returns a dict: removed_faces, faces_before, faces_after,
                            same_winding_groups, opposite_winding_pairs.
            removed_faces==0 means no-op; removed_faces==-1 means unexpected error.
            """
            try:
                _fa = np.asarray(mesh.faces, dtype=np.int64)
                _faces_before = len(_fa)
                _verts_before = len(mesh.vertices)
                if _faces_before == 0:
                    return {
                        "removed_faces": 0, "faces_before": 0, "faces_after": 0,
                        "vertices_before": _verts_before, "vertices_after": _verts_before,
                        "same_winding_groups": 0, "opposite_winding_pairs": 0,
                    }

                # Canonical (min-cyclic) rotation: rotate so the smallest vertex index
                # comes first.  Assumes all 3 indices in each face are distinct (guaranteed
                # after repeated-index cleanup), so argmin gives a unique position.
                _N = len(_fa)
                _min_pos = np.argmin(_fa, axis=1)          # (N,) position of min vertex
                _idx = np.arange(_N)
                _canon = np.stack([
                    _fa[_idx, _min_pos % 3],
                    _fa[_idx, (_min_pos + 1) % 3],
                    _fa[_idx, (_min_pos + 2) % 3],
                ], axis=1)                                  # (N, 3) canonical rows

                # First occurrences of each unique canonical form → keep those faces.
                _, _u_first = np.unique(_canon, axis=0, return_index=True)
                _keep_mask = np.zeros(_N, dtype=bool)
                _keep_mask[_u_first] = True
                _removed = _N - int(_u_first.size)

                # Count canonical-form groups that had more than one member.
                _, _canon_counts = np.unique(_canon, axis=0, return_counts=True)
                _same_winding_groups = int(np.sum(_canon_counts > 1))

                # Opposite-winding detection: among the kept representatives, two faces
                # with identical sorted vertex sets but different canonical forms are
                # coincident with opposite winding.
                _sorted_kept = np.sort(_fa[_keep_mask], axis=1)
                _, _vs_counts = np.unique(_sorted_kept, axis=0, return_counts=True)
                _opp_winding_pairs = int(np.sum(_vs_counts > 1))

                if _removed > 0:
                    mesh.faces = _fa[_keep_mask]
                    mesh.remove_unreferenced_vertices()
                    _faces_after = len(mesh.faces)
                    _verts_after = len(mesh.vertices)
                else:
                    _faces_after = _faces_before
                    _verts_after = _verts_before

                return {
                    "removed_faces": _removed,
                    "faces_before": _faces_before, "faces_after": _faces_after,
                    "vertices_before": _verts_before, "vertices_after": _verts_after,
                    "same_winding_groups": _same_winding_groups,
                    "opposite_winding_pairs": _opp_winding_pairs,
                }

            except Exception as _exc:
                return {"removed_faces": -1, "error": str(_exc)}

        def _compute_boundary_seam_pairs(mesh, match_factor=0.1, len_rel_tol=0.3,
                                          eps_floor=1e-7):
            """Core seam pairing logic. Returns a data dict; never logs, never raises.

            Extracts directed boundary edges and finds mutual-best anti-parallel pairs
            using a 6-D KD-tree (stores (pos[d],pos[c]) for edge (c,d); queries at
            (pos[a],pos[b]) for edge (a,b) to satisfy a↔d, b↔c).

            Returns dict with keys: ok, error, boundary_edges, be, pa, pb, elen,
            median_L, actual_tol, match_factor, eps_floor, matched_pairs, matched_set,
            has_candidate, n_ambiguous, n_unmatched, coverage.
            """
            try:
                from scipy.spatial import cKDTree as _BSPKDT
                _fa = np.asarray(mesh.faces, dtype=np.int64)
                _va = np.asarray(mesh.vertices, dtype=np.float64)
                if len(_fa) == 0 or len(_va) == 0:
                    return {"ok": False, "error": "empty_mesh", "boundary_edges": 0}

                _ed = np.asarray(mesh.edges, dtype=np.int64)
                _es = np.ascontiguousarray(mesh.edges_sorted)
                _esv = _es.view(np.dtype((np.void, _es.dtype.itemsize * 2))).ravel()
                _, _inv, _cnts = np.unique(_esv, return_inverse=True, return_counts=True)
                _be = _ed[_cnts[_inv] == 1]
                _B = len(_be)

                _empty_ret = {
                    "ok": True, "error": None, "boundary_edges": 0,
                    "be": _be, "pa": None, "pb": None, "elen": None,
                    "median_L": 0.0, "actual_tol": eps_floor,
                    "match_factor": match_factor, "eps_floor": eps_floor,
                    "matched_pairs": [], "matched_set": set(),
                    "has_candidate": set(), "n_ambiguous": 0,
                    "n_unmatched": 0, "coverage": 0.0,
                }
                if _B == 0:
                    return _empty_ret

                _pa = _va[_be[:, 0]]
                _pb = _va[_be[:, 1]]
                _elen = np.linalg.norm(_pb - _pa, axis=1)
                _median_L = float(np.median(_elen))
                _actual_tol = max(match_factor * _median_L, eps_floor)

                _kdt = _BSPKDT(np.concatenate([_pb, _pa], axis=1))
                _kd_r = max(_actual_tol * 3.0 * 1.415, eps_floor)
                _cand_lists = _kdt.query_ball_point(
                    np.concatenate([_pa, _pb], axis=1), r=_kd_r
                )

                _best_for = {}
                _has_candidate = set()
                for _i, _cands in enumerate(_cand_lists):
                    _li = _elen[_i]
                    _best_j = None
                    _best_d = float("inf")
                    for _j in _cands:
                        if _j == _i:
                            continue
                        _lj = _elen[_j]
                        _tol_ij = max(match_factor * max(_li, _lj, _median_L), eps_floor)
                        _d_ad = float(np.linalg.norm(_pa[_i] - _pb[_j]))
                        if _d_ad > _tol_ij:
                            continue
                        _d_bc = float(np.linalg.norm(_pb[_i] - _pa[_j]))
                        if _d_bc > _tol_ij:
                            continue
                        _lmax = max(_li, _lj)
                        if _lmax > 0 and abs(_li - _lj) / _lmax > len_rel_tol:
                            continue
                        _d_sum = _d_ad + _d_bc
                        if _d_sum < _best_d:
                            _best_d = _d_sum
                            _best_j = _j
                    if _best_j is not None:
                        _best_for[_i] = (_best_j, _best_d)
                        _has_candidate.add(_i)

                _matched_pairs = []
                _matched_set = set()
                for _i in sorted(_best_for):
                    if _i in _matched_set:
                        continue
                    _j, _d_sum = _best_for[_i]
                    if _j in _matched_set:
                        continue
                    if _j in _best_for and _best_for[_j][0] == _i:
                        _matched_pairs.append((_i, _j, _d_sum))
                        _matched_set.add(_i)
                        _matched_set.add(_j)

                _n_matched = len(_matched_pairs)
                _n_has_cand = len(_has_candidate)
                return {
                    "ok": True, "error": None, "boundary_edges": _B,
                    "be": _be, "pa": _pa, "pb": _pb, "elen": _elen,
                    "median_L": _median_L, "actual_tol": _actual_tol,
                    "match_factor": match_factor, "eps_floor": eps_floor,
                    "matched_pairs": _matched_pairs, "matched_set": _matched_set,
                    "has_candidate": _has_candidate,
                    "n_ambiguous": max(0, _n_has_cand - 2 * _n_matched),
                    "n_unmatched": _B - 2 * _n_matched,
                    "coverage": (2 * _n_matched) / _B,
                }
            except Exception as _exc:
                return {"ok": False, "error": f"{type(_exc).__name__}: {_exc}",
                        "boundary_edges": 0}

        def _ei_stats(faces):
            """Return (boundary_edges, non_manifold_edges, same_dir_edges) from a face array.
            Returns (-1,-1,-1) on error."""
            try:
                _fa = np.asarray(faces, dtype=np.int64)
                if len(_fa) == 0:
                    return 0, 0, 0
                _ed = np.concatenate(
                    [_fa[:, [0, 1]], _fa[:, [1, 2]], _fa[:, [2, 0]]], axis=0
                )
                _es = np.sort(_ed, axis=1)
                _esv = np.ascontiguousarray(_es).view(
                    np.dtype((np.void, _es.dtype.itemsize * 2))
                ).ravel()
                _, _inv, _cnts = np.unique(_esv, return_inverse=True, return_counts=True)
                _be = int(np.sum(_cnts == 1))
                _nme = int(np.sum(_cnts >= 3))
                _two_keys = np.where(_cnts == 2)[0]
                _sde = 0
                if len(_two_keys) > 0:
                    _occ = np.where(np.isin(_inv, _two_keys))[0]
                    _k2 = _inv[_occ]
                    _sk = np.argsort(_k2, kind="stable")
                    _pairs2 = _ed[_occ][_sk].reshape(-1, 2, 2)
                    _sde = int(np.sum(_pairs2[:, 0, 0] == _pairs2[:, 1, 0]))
                return _be, _nme, _sde
            except Exception:
                return -1, -1, -1

        def _count_multi_fan(faces):
            """Count vertices whose incident faces form >1 fan (topologically non-manifold).
            Returns -1 on error."""
            try:
                _fa = np.asarray(faces, dtype=np.int64)
                _N = len(_fa)
                if _N == 0:
                    return 0
                _sv = np.concatenate([_fa[:, 0], _fa[:, 1], _fa[:, 2]])
                _dv = np.concatenate([_fa[:, 1], _fa[:, 2], _fa[:, 0]])
                _fv = np.tile(np.arange(_N, dtype=np.int64), 3)
                _hed = {}
                _vfi = {}
                for _s, _d, _f in zip(_sv.tolist(), _dv.tolist(), _fv.tolist()):
                    _hed[(_s, _d)] = _f
                    _vfi.setdefault(_s, []).append((_f, _d))
                _multi = 0
                for _v, _fi in _vfi.items():
                    if len(_fi) < 2:
                        continue
                    _inc = {f for f, _ in _fi}
                    _adj = {f: [] for f in _inc}
                    for _fi2, _u in _fi:
                        _nb = _hed.get((_u, _v), -1)
                        if _nb != -1 and _nb in _inc:
                            if _nb not in _adj[_fi2]:
                                _adj[_fi2].append(_nb)
                            if _fi2 not in _adj[_nb]:
                                _adj[_nb].append(_fi2)
                    _vis = set()
                    _nc = 0
                    for _s2 in _inc:
                        if _s2 in _vis:
                            continue
                        _nc += 1
                        _q = [_s2]
                        while _q:
                            _cur = _q.pop()
                            if _cur in _vis:
                                continue
                            _vis.add(_cur)
                            for _n2 in _adj[_cur]:
                                if _n2 not in _vis:
                                    _q.append(_n2)
                    if _nc > 1:
                        _multi += 1
                return _multi
            except Exception:
                return -1

        def _count_components(m):
            """Count connected face components via adjacency. Returns -1 on error."""
            try:
                from scipy.sparse import csr_matrix as _csr
                from scipy.sparse.csgraph import connected_components as _scc
                _nf = len(m.faces)
                if _nf == 0:
                    return 0
                _fad = np.asarray(m.face_adjacency)
                if len(_fad) == 0:
                    return _nf
                _r = np.concatenate([_fad[:, 0], _fad[:, 1]])
                _c = np.concatenate([_fad[:, 1], _fad[:, 0]])
                _adj = _csr(
                    (np.ones(len(_r), dtype=np.int8), (_r, _c)), shape=(_nf, _nf)
                )
                _nc, _ = _scc(_adj, directed=False)
                return int(_nc)
            except Exception:
                return -1

        def _transactional_seam_weld(mesh, label):
            """Transactional boundary seam welding on a working copy of mesh.

            Uses conservative pairing thresholds (2 % endpoint distance, 5 % length ratio,
            zero ambiguous).  Builds vertex equivalence classes via union-find, computes
            class-mean positions, remaps faces, validates pre- and post-weld structure,
            and adopts the result only when all structural conditions pass.

            Returns dict: adopted (bool), mesh (welded copy or original), manifold
            (Manifold if conversion succeeded, else None), reason (str).
            """
            def _bail(reason):
                return {"adopted": False, "mesh": mesh, "manifold": None, "reason": reason}

            try:
                _weld_mf  = 0.02   # 2 % endpoint tolerance for welding
                _weld_lr  = 0.05   # 5 % edge-length ratio tolerance for welding
                _eps_floor = 1e-7

                _pd = _compute_boundary_seam_pairs(mesh, _weld_mf, _weld_lr, _eps_floor)
                if not _pd["ok"]:
                    return _bail(_pd["error"])

                _B = _pd["boundary_edges"]
                if _B == 0:
                    return _bail("no_boundary_edges")

                _pairs = _pd["matched_pairs"]
                _n_pairs = len(_pairs)
                if _n_pairs == 0:
                    return _bail("no_conservative_pairs")

                if _pd["n_ambiguous"] > 0:
                    return _bail(f"ambiguous_pairs={_pd['n_ambiguous']}")

                _be = _pd["be"]

                # Endpoint correspondences: pair (i,j) means edge i=(a,b) and edge j=(c,d)
                # with pos[a]≈pos[d] and pos[b]≈pos[c], so merge a↔d and b↔c.
                _correspondences = []
                for _pi, _pj, _ in _pairs:
                    _correspondences.append((int(_be[_pi, 0]), int(_be[_pj, 1])))
                    _correspondences.append((int(_be[_pi, 1]), int(_be[_pj, 0])))
                _n_corr = len(_correspondences)

                # Union-Find to build vertex equivalence classes.
                _n_v = len(mesh.vertices)
                _uf_p = list(range(_n_v))
                _uf_r = [0] * _n_v

                def _uf_find(x):
                    while _uf_p[x] != x:
                        _uf_p[x] = _uf_p[_uf_p[x]]
                        x = _uf_p[x]
                    return x

                def _uf_union(x, y):
                    rx, ry = _uf_find(x), _uf_find(y)
                    if rx == ry:
                        return
                    if _uf_r[rx] < _uf_r[ry]:
                        rx, ry = ry, rx
                    _uf_p[ry] = rx
                    if _uf_r[rx] == _uf_r[ry]:
                        _uf_r[rx] += 1

                for _va_v, _vb_v in _correspondences:
                    _uf_union(_va_v, _vb_v)

                # Seam vertices and remap array (non-seam vertices map to themselves).
                _seam_verts = set()
                for _a, _b in _correspondences:
                    _seam_verts.add(_a)
                    _seam_verts.add(_b)
                _remap = np.arange(_n_v, dtype=np.int64)
                for _sv in _seam_verts:
                    _remap[_sv] = _uf_find(_sv)

                # Collect equivalence classes (root → frozenset of members).
                _classes = {}
                for _sv in _seam_verts:
                    _root = int(_uf_find(_sv))
                    _classes.setdefault(_root, set()).add(_sv)
                for _root in list(_classes.keys()):
                    _classes[_root].add(_root)
                _n_classes = len(_classes)
                _n_welded_v = sum(len(m) for m in _classes.values())

                # Pre-validation: check tentative remapped faces for NME and SDE.
                # Reject the whole welding attempt if either would be introduced.
                _orig_faces = np.asarray(mesh.faces, dtype=np.int64)
                _tent = _remap[_orig_faces]
                _degen_tent = (
                    (_tent[:, 0] == _tent[:, 1]) |
                    (_tent[:, 1] == _tent[:, 2]) |
                    (_tent[:, 0] == _tent[:, 2])
                )
                _t_be, _t_nme, _t_sde = _ei_stats(_tent[~_degen_tent])
                if _t_nme > 0 or _t_sde > 0:
                    return _bail(f"pre_validation_nme={_t_nme}_sde={_t_sde}")

                # Before-weld structural stats.
                _be_before, _nme_before, _sde_before = _ei_stats(_orig_faces)
                _mf_before = _count_multi_fan(_orig_faces)
                _comps_before = _count_components(mesh)

                # Build working copy: update representative vertex positions to class mean.
                _orig_verts = np.asarray(mesh.vertices, dtype=np.float64)
                _wc_verts = _orig_verts.copy()
                for _root, _members in _classes.items():
                    _wc_verts[_root] = np.mean([_orig_verts[m] for m in _members], axis=0)

                # Remap faces; remove any that became degenerate after merging.
                _wc_faces = _remap[_orig_faces]
                _degen_mask = (
                    (_wc_faces[:, 0] == _wc_faces[:, 1]) |
                    (_wc_faces[:, 1] == _wc_faces[:, 2]) |
                    (_wc_faces[:, 0] == _wc_faces[:, 2])
                )
                _n_degen_rm = int(np.sum(_degen_mask))
                _wc_faces_clean = _wc_faces[~_degen_mask]
                if len(_wc_faces_clean) == 0:
                    return _bail("all_faces_degenerate_after_weld")

                _wc = trimesh.Trimesh(
                    vertices=_wc_verts, faces=_wc_faces_clean, process=False
                )
                _wc.remove_unreferenced_vertices()
                trimesh.repair.fix_winding(_wc)
                trimesh.repair.fix_normals(_wc)

                # Vertex displacement stats (all seam vertices, including representatives).
                _disp_vals = []
                for _root, _members in _classes.items():
                    _np2 = _wc_verts[_root]
                    for _m in _members:
                        _disp_vals.append(float(np.linalg.norm(_orig_verts[_m] - _np2)))
                _disp_arr = np.asarray(_disp_vals) if _disp_vals else np.array([0.0])
                _disp_med = float(np.median(_disp_arr))
                _disp_max = float(np.max(_disp_arr))

                # After-weld structural stats.
                _wc_faces_arr = np.asarray(_wc.faces, dtype=np.int64)
                _be_after, _nme_after, _sde_after = _ei_stats(_wc_faces_arr)
                _mf_after = _count_multi_fan(_wc_faces_arr)
                _comps_after = _count_components(_wc)
                _wc_winding = _wc.is_winding_consistent

                # Attempt Manifold conversion from welded copy.
                try:
                    _wm_cand = trimesh_to_manifold(_wc)
                    _wm_st, _wm_nt, _wm_ie, _wm_valid = _manifold_props(_wm_cand)
                except Exception:
                    _wm_cand = None
                    _wm_st, _wm_nt, _wm_ie, _wm_valid = "error", 0, True, False

                # Adoption conditions (all proportional/structural; no fixed coordinates).
                _adopt = True
                _reject_reason = None
                _nme_b = _nme_before if isinstance(_nme_before, int) else 0
                _sde_b = _sde_before if isinstance(_sde_before, int) else 0
                _cc_b  = _comps_before if isinstance(_comps_before, int) else 0
                _cc_a  = _comps_after  if isinstance(_comps_after, int) else 0

                if not (isinstance(_be_after, int) and isinstance(_be_before, int)):
                    _adopt = False
                    _reject_reason = "be_stats_error"
                elif _be_after >= _be_before:
                    _adopt = False
                    _reject_reason = (
                        f"boundary_not_reduced  be_before={_be_before}  be_after={_be_after}"
                    )
                elif isinstance(_nme_after, int) and _nme_after > _nme_b:
                    _adopt = False
                    _reject_reason = (
                        f"nme_increased  before={_nme_before}  after={_nme_after}"
                    )
                elif isinstance(_sde_after, int) and _sde_after > _sde_b:
                    _adopt = False
                    _reject_reason = (
                        f"sde_increased  before={_sde_before}  after={_sde_after}"
                    )
                elif not _wc_winding:
                    _adopt = False
                    _reject_reason = "winding_inconsistent_after_weld"
                elif _cc_a > _cc_b + 1:
                    _adopt = False
                    _reject_reason = (
                        f"components_increased  before={_comps_before}  after={_comps_after}"
                    )

                if _adopt:
                    return {
                        "adopted": True,
                        "mesh": _wc,
                        "manifold": _wm_cand if _wm_valid else None,
                        "reason": "all_conditions_passed",
                    }
                return _bail(_reject_reason)

            except Exception as _exc:
                return {
                    "adopted": False, "mesh": mesh, "manifold": None,
                    "reason": f"error_{type(_exc).__name__}",
                }

        def _try_repair_planar_boundary(mesh, label):
            """Attempt to close a planar boundary network by cap-triangulation.

            Transactional: all geometric modifications operate on a working copy
            of the input mesh.  The original mesh is never modified.

            Preconditions (evaluated in order; eligibility log is emitted once):
              1. mesh has faces and vertices
              2. no degenerate faces (repeated-index | coord-collapsed | near-collinear)
              3. non_manifold_edges == 0  AND  same_direction_shared_edges == 0
              4. boundary_edges > 0
              5. no degree-1 boundary vertices (no open-chain endpoints)
              6. boundary vertices nearly coplanar (SVD best-fit plane, scale-relative tol)
              7. boundary plane lies near one extreme of the mesh along the plane normal

            Pipeline (only runs when all preconditions pass):
              shapely.polygonize_full  →  mapbox_earcut  →  winding orient
              →  working-copy validation  →  manifold3d validation

            Returns dict:
                applied          : bool
                reason           : str
                mesh             : repaired Trimesh if applied, else original mesh unchanged
                boundary_edges_before, boundary_edges_after
                new_vertices, new_faces, polygon_regions, cap_area, elapsed_ms

            Never raises; unexpected exceptions are caught and logged.
            """
            import time as _pbrt
            _t_start = _pbrt.perf_counter()

            def _ms():
                return round((_pbrt.perf_counter() - _t_start) * 1000, 1)

            def _base_ret(applied, reason, wmesh, **kw):
                return {
                    "applied": applied, "reason": reason, "mesh": wmesh,
                    "boundary_edges_before": kw.get("be_before", "unknown"),
                    "boundary_edges_after": kw.get("be_after", "unknown"),
                    "new_vertices": kw.get("new_vertices", 0),
                    "new_faces": kw.get("new_faces", 0),
                    "polygon_regions": kw.get("polygon_regions", 0),
                    "cap_area": kw.get("cap_area", 0.0),
                    "elapsed_ms": _ms(),
                }

            # ── PRECONDITION 1: mesh has faces and vertices ───────────────
            try:
                _n_faces = len(mesh.faces)
                _n_verts = len(mesh.vertices)
            except Exception as _e0:
                return _base_ret(False, "cannot_read_mesh_geometry", mesh)

            if _n_faces == 0 or _n_verts == 0:
                return _base_ret(False, "empty_mesh", mesh)

            # ── PRECONDITION 2: no degenerate faces ──────────────────────
            # Same classification as _mesh_topology_info: A | B-tol | C
            _degen_total = 0
            try:
                _fa = np.asarray(mesh.faces)
                _mv = np.asarray(mesh.vertices)
                _tol_mg = 1e-8
                _ri_m = (
                    (_fa[:, 0] == _fa[:, 1]) |
                    (_fa[:, 1] == _fa[:, 2]) |
                    (_fa[:, 0] == _fa[:, 2])
                )
                _fv = _mv[_fa]
                _cc_m = (
                    (np.max(np.abs(_fv[:, 0] - _fv[:, 1]), axis=1) <= _tol_mg) |
                    (np.max(np.abs(_fv[:, 1] - _fv[:, 2]), axis=1) <= _tol_mg) |
                    (np.max(np.abs(_fv[:, 0] - _fv[:, 2]), axis=1) <= _tol_mg)
                ) & ~_ri_m
                try:
                    _nd_m = mesh.nondegenerate_faces(height=_tol_mg)
                    _nc_m = ~_nd_m & ~_ri_m & ~_cc_m
                except Exception:
                    _nc_m = (np.asarray(mesh.area_faces) == 0.0) & ~_ri_m & ~_cc_m
                _degen_total = (
                    int(np.sum(_ri_m)) + int(np.sum(_cc_m)) + int(np.sum(_nc_m))
                )
            except Exception as _e1:
                return _base_ret(False, "degenerate_check_error", mesh)

            if _degen_total > 0:
                return _base_ret(False, "precondition_degenerate_faces", mesh)

            # ── PRECONDITION 3+4: NME=0, SDE=0, boundary_edges > 0 ──────
            _n_be = 0
            _bep = None
            _nme_pre = _sde_pre = 0
            try:
                _es_pre = np.ascontiguousarray(mesh.edges_sorted)
                _dirs_pre = np.ascontiguousarray(mesh.edges)
                _esv_pre = _es_pre.view(
                    np.dtype((np.void, _es_pre.dtype.itemsize * 2))
                ).ravel()
                _, _inv_pre, _cnts_pre = np.unique(
                    _esv_pre, return_inverse=True, return_counts=True
                )
                _nme_pre = int(np.sum(_cnts_pre >= 3))
                _be_mask_pre = _cnts_pre[_inv_pre] == 1
                _n_be = int(np.sum(_be_mask_pre))
                _bep = _es_pre[_be_mask_pre]      # (n_be, 2)

                _two_keys_pre = np.where(_cnts_pre == 2)[0]
                if len(_two_keys_pre) > 0:
                    _tf_occ_pre = np.where(np.isin(_inv_pre, _two_keys_pre))[0]
                    _tf_k_pre = _inv_pre[_tf_occ_pre]
                    _sk_pre = np.argsort(_tf_k_pre, kind="stable")
                    _td_pre = _dirs_pre[_tf_occ_pre][_sk_pre].reshape(-1, 2, 2)
                    _sde_pre = int(np.sum(_td_pre[:, 0, 0] == _td_pre[:, 1, 0]))
                else:
                    _sde_pre = 0
            except Exception as _e2:
                return _base_ret(False, "edge_incidence_error", mesh)

            if _nme_pre > 0 or _sde_pre > 0:
                return _base_ret(False, "precondition_nme_or_sde", mesh,
                                 be_before=_n_be)

            if _n_be == 0:
                return _base_ret(False, "no_boundary_edges", mesh)

            # ── PRECONDITION 5: no degree-1 boundary vertices ─────────────
            _d1 = _d3p = 0
            _bvu = _remap_bv = _bepr = _bdeg = None
            _n_bv = 0
            try:
                _bvu = np.unique(_bep.ravel())
                _n_bv = len(_bvu)
                _remap_bv = np.full(len(mesh.vertices), -1, dtype=np.int64)
                _remap_bv[_bvu] = np.arange(_n_bv, dtype=np.int64)
                _bepr = _remap_bv[_bep]
                _bdeg = np.bincount(_bepr.ravel(), minlength=_n_bv)
                _d1 = int(np.sum(_bdeg == 1))
                _d3p = int(np.sum(_bdeg >= 3))
            except Exception as _e3:
                return _base_ret(False, "boundary_degree_error", mesh,
                                 be_before=_n_be)

            if _d1 > 0:
                return _base_ret(False, "boundary_has_open_chain_endpoints", mesh,
                                 be_before=_n_be)

            # ── PRECONDITION 6: boundary vertices nearly coplanar (SVD) ──
            _plane_normal = _u_axis = _v_axis = None
            _bverts_3d = _bv_centroid = _bv_centered = None
            _max_dev = _med_dev = _p95_dev = _bv_diag = _planarity_tol = 0.0
            try:
                _bverts_3d = _mv[_bvu]
                _bv_centroid = _bverts_3d.mean(axis=0)
                _bv_centered = _bverts_3d - _bv_centroid
                _bv_bbox_d = _bverts_3d.max(axis=0) - _bverts_3d.min(axis=0)
                _bv_diag = float(np.linalg.norm(_bv_bbox_d))
                if _bv_diag < 1e-12:
                    return _base_ret(False, "boundary_vertices_degenerate_bbox", mesh,
                                     be_before=_n_be)
                _, _svals, _Vt = np.linalg.svd(_bv_centered, full_matrices=False)
                _plane_normal = _Vt[-1]
                _u_axis = _Vt[0]
                _v_axis = _Vt[1]
                _deviations = np.abs(_bv_centered @ _plane_normal)
                _max_dev = float(np.max(_deviations))
                _med_dev = float(np.median(_deviations))
                _p95_dev = float(np.percentile(_deviations, 95))
                _planarity_tol = max(_bv_diag * 1e-3, 1e-6)
            except Exception as _e4:
                return _base_ret(False, "planarity_svd_error", mesh,
                                 be_before=_n_be)

            # ── PRECONDITION 7: boundary plane at mesh extreme ────────────
            _dist_to_min = _dist_to_max = _extreme_tol = _mesh_diag_3d = 0.0
            try:
                _all_mv_proj = _mv @ _plane_normal
                _bv_proj_mean = float((_bverts_3d @ _plane_normal).mean())
                _dist_to_min = abs(_bv_proj_mean - float(_all_mv_proj.min()))
                _dist_to_max = abs(_bv_proj_mean - float(_all_mv_proj.max()))
                _mesh_bbox_d = _mv.max(axis=0) - _mv.min(axis=0)
                _mesh_diag_3d = float(np.linalg.norm(_mesh_bbox_d))
                _extreme_tol = max(_mesh_diag_3d * 0.05, _planarity_tol)
            except Exception as _e5:
                return _base_ret(False, "extreme_check_error", mesh, be_before=_n_be)

            _not_planar = _max_dev > _planarity_tol
            _not_extreme = min(_dist_to_min, _dist_to_max) > _extreme_tol
            _eligible = not _not_planar and not _not_extreme
            _elig_reason = (
                "boundary_not_planar" if _not_planar else
                "boundary_plane_not_at_mesh_extreme" if _not_extreme else
                "ok"
            )

            if not _eligible:
                return _base_ret(False, _elig_reason, mesh, be_before=_n_be)

            # ── PROJECT boundary vertices to 2D ───────────────────────────
            _bverts_2d = None
            try:
                _basis_2d = np.column_stack([_u_axis, _v_axis])   # (3, 2)
                _bverts_2d = _bv_centered @ _basis_2d             # (n_bv, 2)
            except Exception as _e6:
                return _base_ret(False, "projection_error", mesh, be_before=_n_be)

            # ── BUILD MultiLineString ─────────────────────────────────────
            _mls = None
            try:
                from shapely.geometry import MultiLineString as _MLS
                _lines = []
                for _ei in range(len(_bep)):
                    _ia = int(_remap_bv[_bep[_ei, 0]])
                    _ib = int(_remap_bv[_bep[_ei, 1]])
                    _lines.append((
                        (float(_bverts_2d[_ia, 0]), float(_bverts_2d[_ia, 1])),
                        (float(_bverts_2d[_ib, 0]), float(_bverts_2d[_ib, 1])),
                    ))
                _mls = _MLS(_lines)
            except Exception as _e7:
                return _base_ret(False, "multilinestring_build_error", mesh,
                                 be_before=_n_be)

            # ── POLYGONIZE ────────────────────────────────────────────────
            _poly_list = []
            _n_regions = _n_holes_total = _n_dangles = _n_cuts = _n_invalid = 0
            _total_proj_area = 0.0
            try:
                from shapely.ops import polygonize_full as _pgfull
                _polys, _cuts, _dangs, _inv_rings = _pgfull(_mls)
                _poly_list = list(_polys.geoms) if not _polys.is_empty else []
                _n_regions = len(_poly_list)
                _n_holes_total = sum(len(list(p.interiors)) for p in _poly_list)
                _n_dangles = len(list(_dangs.geoms)) if not _dangs.is_empty else 0
                _n_cuts = len(list(_cuts.geoms)) if not _cuts.is_empty else 0
                _n_invalid = len(list(_inv_rings.geoms)) if not _inv_rings.is_empty else 0
                _total_proj_area = sum(p.area for p in _poly_list)
            except Exception as _e8:
                return _base_ret(False, "polygonize_error", mesh, be_before=_n_be)

            if _n_regions == 0:
                return _base_ret(False, "polygonization_no_bounded_regions", mesh,
                                 be_before=_n_be)
            if _n_dangles > 0:
                return _base_ret(False, "polygonization_has_dangles", mesh,
                                 be_before=_n_be)
            if _n_invalid > 0:
                return _base_ret(False, "polygonization_has_invalid_rings", mesh,
                                 be_before=_n_be)

            # ── BUILD COORD→VERTEX LOOKUP (scipy KDTree on 2D proj) ───────
            _lookup_tol = max(_bv_diag * 1e-6, 1e-10)
            try:
                from scipy.spatial import cKDTree as _KDT
                _kdtree = _KDT(_bverts_2d)
            except Exception as _e9:
                return _base_ret(False, "kdtree_build_error", mesh, be_before=_n_be)

            def _ring_to_bv_indices(ring_coords):
                """Map shapely ring coord list to bvu-space indices.
                Strips the closing duplicate.  Returns None on any lookup miss."""
                _pts = np.array(ring_coords, dtype=np.float64)
                if (len(_pts) >= 2 and
                        np.allclose(_pts[0], _pts[-1], atol=_lookup_tol * 100)):
                    _pts = _pts[:-1]
                if len(_pts) < 3:
                    return None
                _dists, _idxs = _kdtree.query(_pts, k=1)
                if np.any(_dists > _lookup_tol):
                    return None
                return _idxs   # indices into _bverts_2d / _bvu

            # ── TRIANGULATE each polygon region with earcut ───────────────
            _all_cap_faces = []
            _n_new_verts = 0
            _n_new_faces_total = 0
            _n_discarded_degen = 0
            _cap_area = 0.0

            try:
                import mapbox_earcut as _earcut

                for _poly in _poly_list:
                    _ext_bv_idx = _ring_to_bv_indices(list(_poly.exterior.coords))
                    if _ext_bv_idx is None:
                        return _base_ret(False, "coord_mapping_failed_exterior", mesh,
                                         be_before=_n_be)

                    _ring_bv = list(_ext_bv_idx)         # indices into _bverts_2d/_bvu
                    _ring_ends = [len(_ring_bv)]          # ring_end_indices for earcut

                    for _hole in _poly.interiors:
                        _h_bv_idx = _ring_to_bv_indices(list(_hole.coords))
                        if _h_bv_idx is None:
                            return _base_ret(False, "coord_mapping_failed_hole", mesh,
                                             be_before=_n_be)
                        _ring_bv.extend(_h_bv_idx)
                        _ring_ends.append(len(_ring_bv))

                    _ring_bv_arr = np.array(_ring_bv, dtype=np.int64)
                    _earcut_pts = _bverts_2d[_ring_bv_arr].astype(np.float32)
                    _earcut_rings = np.array(_ring_ends, dtype=np.uint32)
                    _tris_flat = _earcut.triangulate_float32(_earcut_pts, _earcut_rings)

                    if len(_tris_flat) == 0:
                        return _base_ret(False, "earcut_no_triangles", mesh,
                                         be_before=_n_be)

                    # earcut indices → bvu-space → original mesh vertex indices
                    _tris_local = _tris_flat.reshape(-1, 3).astype(np.int64)
                    _tris_3d = _bvu[_ring_bv_arr[_tris_local]]   # (T, 3) orig idx

                    # Discard repeated-index triangles (earcut may produce them for
                    # degenerate rings; safe to remove here)
                    _rdeg = (
                        (_tris_3d[:, 0] == _tris_3d[:, 1]) |
                        (_tris_3d[:, 1] == _tris_3d[:, 2]) |
                        (_tris_3d[:, 0] == _tris_3d[:, 2])
                    )
                    _n_discarded_degen += int(np.sum(_rdeg))
                    _tris_3d = _tris_3d[~_rdeg]

                    if len(_tris_3d) == 0:
                        return _base_ret(False, "all_triangles_degenerate_after_map", mesh,
                                         be_before=_n_be)

                    _all_cap_faces.append(_tris_3d)
                    _n_new_faces_total += len(_tris_3d)

            except Exception as _e10:
                return _base_ret(False, "triangulation_error", mesh, be_before=_n_be)

            # ── CAP AREA + WINDING ORIENTATION ────────────────────────────
            _all_cap_arr = np.concatenate(_all_cap_faces, axis=0)   # (N_cap, 3)

            try:
                _v0c = _mv[_all_cap_arr[:, 0]]
                _v1c = _mv[_all_cap_arr[:, 1]]
                _v2c = _mv[_all_cap_arr[:, 2]]
                _cap_area = float(
                    np.sum(np.linalg.norm(np.cross(_v1c - _v0c, _v2c - _v0c), axis=1)) / 2.0
                )
            except Exception:
                pass

            # Orient cap: outward direction = away from mesh interior
            try:
                _all_mv_proj = _mv @ _plane_normal
                _bv_proj_mean = float((_bverts_3d @ _plane_normal).mean())
                _interior_proj = float(np.median(_all_mv_proj))
                # interior on + side → outward = -normal; interior on - side → outward = +normal
                _outward_n = -_plane_normal if _interior_proj > _bv_proj_mean else _plane_normal

                _t0c = _all_cap_arr[0]
                _e1c = _mv[_t0c[1]] - _mv[_t0c[0]]
                _e2c = _mv[_t0c[2]] - _mv[_t0c[0]]
                _sample_n = np.cross(_e1c, _e2c)
                _sn_len = np.linalg.norm(_sample_n)
                if _sn_len > 1e-14:
                    _sample_n /= _sn_len
                    if np.dot(_sample_n, _outward_n) < 0:
                        _all_cap_arr = _all_cap_arr[:, ::-1]
            except Exception:
                pass   # winding errors: fall through, fix_winding handles it

            # ── BUILD WORKING COPY ────────────────────────────────────────
            try:
                import copy as _copy
                _wmesh = _copy.deepcopy(mesh)
                _wfaces_orig = np.asarray(_wmesh.faces, dtype=np.int64)
                _combined = np.concatenate(
                    [_wfaces_orig, _all_cap_arr.astype(np.int64)], axis=0
                )
                _wmesh.faces = _combined.astype(np.int32)
            except Exception as _e11:
                return _base_ret(False, "working_copy_error", mesh, be_before=_n_be)

            try:
                trimesh.repair.fix_winding(_wmesh)
                trimesh.repair.fix_normals(_wmesh)
                _wmesh.merge_vertices()
                _wmesh.remove_unreferenced_vertices()
            except Exception as _e12:
                pass

            # ── VALIDATE WORKING COPY ─────────────────────────────────────
            _w_be = _w_nme = _w_sde = _w_degen = "error"
            _w_wt = _w_vol = "error"

            try:
                _wfa = np.asarray(_wmesh.faces)
                _wvt = np.asarray(_wmesh.vertices)

                # Degenerate check (same classification as precondition 2)
                _w_ri = (
                    (_wfa[:, 0] == _wfa[:, 1]) |
                    (_wfa[:, 1] == _wfa[:, 2]) |
                    (_wfa[:, 0] == _wfa[:, 2])
                )
                _w_fv = _wvt[_wfa]
                _w_cc = (
                    (np.max(np.abs(_w_fv[:, 0] - _w_fv[:, 1]), axis=1) <= 1e-8) |
                    (np.max(np.abs(_w_fv[:, 1] - _w_fv[:, 2]), axis=1) <= 1e-8) |
                    (np.max(np.abs(_w_fv[:, 0] - _w_fv[:, 2]), axis=1) <= 1e-8)
                ) & ~_w_ri
                try:
                    _w_nd = _wmesh.nondegenerate_faces(height=1e-8)
                    _w_nc = ~_w_nd & ~_w_ri & ~_w_cc
                except Exception:
                    _w_nc = (np.asarray(_wmesh.area_faces) == 0.0) & ~_w_ri & ~_w_cc
                _w_degen = (
                    int(np.sum(_w_ri)) + int(np.sum(_w_cc)) + int(np.sum(_w_nc))
                )

                # Edge incidence on working copy
                _w_es = np.ascontiguousarray(_wmesh.edges_sorted)
                _w_esv = _w_es.view(
                    np.dtype((np.void, _w_es.dtype.itemsize * 2))
                ).ravel()
                _, _w_inv, _w_cnts = np.unique(
                    _w_esv, return_inverse=True, return_counts=True
                )
                _w_be = int(np.sum(_w_cnts == 1))
                _w_nme = int(np.sum(_w_cnts >= 3))

                _w_dirs = np.ascontiguousarray(_wmesh.edges)
                _w2keys = np.where(_w_cnts == 2)[0]
                if len(_w2keys) > 0:
                    _wtf_occ = np.where(np.isin(_w_inv, _w2keys))[0]
                    _wtf_k = _w_inv[_wtf_occ]
                    _wsk = np.argsort(_wtf_k, kind="stable")
                    _wtd = _w_dirs[_wtf_occ][_wsk].reshape(-1, 2, 2)
                    _w_sde = int(np.sum(_wtd[:, 0, 0] == _wtd[:, 1, 0]))
                else:
                    _w_sde = 0

                _w_wt = _wmesh.is_watertight
                _w_vol = _wmesh.is_volume

            except Exception as _ve:
                pass

            # Manifold validation
            _w_man_st = _w_man_nt = _w_man_ie = _w_man_valid = "error"
            try:
                _w_man = trimesh_to_manifold(_wmesh)
                _w_man_st, _w_man_nt, _w_man_ie, _w_man_valid = _manifold_props(_w_man)
            except Exception as _me:
                _w_man_valid = False
                _w_man_st = f"exception:{type(_me).__name__}"
                _w_man_nt = 0
                _w_man_ie = True

            _v_ok = (
                isinstance(_w_be, int) and _w_be == 0 and
                isinstance(_w_nme, int) and _w_nme == 0 and
                isinstance(_w_sde, int) and _w_sde == 0 and
                isinstance(_w_degen, int) and _w_degen == 0 and
                _w_wt is True and
                _w_vol is True and
                _w_man_valid is True
            )

            if _v_ok:
                return _base_ret(
                    True, "ok", _wmesh,
                    be_before=_n_be, be_after=_w_be,
                    new_vertices=_n_new_verts,
                    new_faces=_n_new_faces_total,
                    polygon_regions=_n_regions,
                    cap_area=_cap_area,
                )

            _fail_reason = (
                "boundary_not_closed"
                if isinstance(_w_be, int) and _w_be > 0 else
                "nme_remaining"
                if isinstance(_w_nme, int) and _w_nme > 0 else
                "sde_remaining"
                if isinstance(_w_sde, int) and _w_sde > 0 else
                "degenerate_faces_remaining"
                if isinstance(_w_degen, int) and _w_degen > 0 else
                "not_watertight"
                if _w_wt is not True else
                "not_volume"
                if _w_vol is not True else
                "manifold_invalid"
            )
            return _base_ret(
                False, _fail_reason, mesh,
                be_before=_n_be, be_after=_w_be,
                polygon_regions=_n_regions,
            )

        _stage = "loading mesh_a"
        mesh_a = trimesh.load(str(mesh_a_path))

        _stage = "loading mesh_b"
        mesh_b = trimesh.load(str(mesh_b_path))

        # Ensure we have Trimesh objects (not Scene)
        if isinstance(mesh_a, trimesh.Scene):
            mesh_a = trimesh.util.concatenate(mesh_a.dump())
        if isinstance(mesh_b, trimesh.Scene):
            mesh_b = trimesh.util.concatenate(mesh_b.dump())

        _log.info(f"Boolean {operation.value}: A={len(mesh_a.faces)} faces, B={len(mesh_b.faces)} faces")

        # Use manifold3d directly to bypass trimesh's volume check.
        # Manifold can handle non-volume meshes by forcing them through
        # its own internal repair pipeline.
        import manifold3d
        import numpy as np

        def trimesh_to_manifold(mesh):
            """Convert trimesh to Manifold, forcing repair for non-volume meshes."""
            verts = np.array(mesh.vertices, dtype=np.float32)
            faces = np.array(mesh.faces, dtype=np.int32)
            mesh_gl = manifold3d.Mesh(vert_properties=verts, tri_verts=faces)
            return manifold3d.Manifold(mesh_gl)

        def manifold_to_trimesh(man):
            """Convert Manifold back to trimesh."""
            mesh_gl = man.to_mesh()
            result_mesh = trimesh.Trimesh(
                vertices=mesh_gl.vert_properties[:, :3],
                faces=mesh_gl.tri_verts,
                process=True,
            )
            return result_mesh

        # --- Primary conversion ---
        # Track whether fallback is needed and why; initialise valid flags to False
        # so any early exception leaves them conservative.
        _a_valid = False
        _b_valid = False
        _need_fallback = False
        _fallback_reason = None

        try:
            _stage = "converting mesh_a (primary)"
            man_a = trimesh_to_manifold(mesh_a)
            _a_st, _a_nt, _a_ie, _a_valid = _manifold_props(man_a)

            _stage = "converting mesh_b (primary)"
            man_b = trimesh_to_manifold(mesh_b)
            _b_st, _b_nt, _b_ie, _b_valid = _manifold_props(man_b)

        except Exception as e:
            _need_fallback = True
            _fallback_reason = "exception"

        # manifold3d.Manifold() can silently return an invalid object (Error.NotManifold,
        # num_tri=0, is_empty=True) without raising.  Treat that as a conversion failure.
        if not _need_fallback and (not _a_valid or not _b_valid):
            _need_fallback = True
            _fallback_reason = "invalid_manifold"

        # --- Fallback repair + retry ---
        if _need_fallback:
            _stage = "fallback repair"

            # Holds a validated Manifold from Mesh.merge() if that path succeeds,
            # allowing the retry block to skip trimesh_to_manifold(mesh_a).
            _merge_man_a = None

            for _rlabel, _rmesh in [("mesh_a", mesh_a), ("mesh_b", mesh_b)]:
                _actual_mesh = mesh_a if _rlabel == "mesh_a" else mesh_b
                if not _rmesh.is_volume:
                    if _rlabel == "mesh_a":
                        # Remove repeated-index faces before fill_holes so that
                        # fill_holes does not treat garbage-component boundaries as holes.
                        _ri_result = _remove_repeated_index_faces(mesh_a, "mesh_a")
                        if len(mesh_a.faces) == 0:
                            return False, (
                                "mesh_a has no faces remaining after repeated-index cleanup"
                            ), None
                        # Remove exact-duplicate faces (same winding, cyclic-rotation equal).
                        _edf_result = _remove_exact_duplicate_faces(mesh_a, "mesh_a")
                        # Attempt manifold3d Mesh.merge() as an additional structural fix.
                        # If it yields a valid Manifold, adopt it directly and skip the
                        # planar repair / fill_holes path.  Any failure falls through to
                        # the existing repair sequence.
                        try:
                            if hasattr(manifold3d.Mesh, "merge"):
                                _verts_m = np.array(mesh_a.vertices, dtype=np.float32)
                                _faces_m = np.array(mesh_a.faces, dtype=np.int32)
                                _raw_mesh_m = manifold3d.Mesh(
                                    vert_properties=_verts_m, tri_verts=_faces_m
                                )
                                _raw_mesh_m.merge()
                                _merged_man = manifold3d.Manifold(_raw_mesh_m)
                                if _is_valid_manifold(_merged_man):
                                    _merge_man_a = _merged_man
                        except Exception:
                            pass
                        if _merge_man_a is None:
                            # Transactional seam welding: close boundary by merging
                            # geometrically near-coincident anti-parallel edge endpoint
                            # pairs.  Conservative thresholds (2 % tol, 5 % length ratio,
                            # zero ambiguous).  All work on a working copy; adopted only
                            # when structure validates.  Even if Manifold conversion still
                            # fails due to multi-fan vertices, the welded copy is kept so
                            # the next stage can handle post-weld fan splitting.
                            _weld_result = _transactional_seam_weld(mesh_a, "mesh_a")
                            if _weld_result["adopted"]:
                                mesh_a = _weld_result["mesh"]
                                if _weld_result["manifold"] is not None:
                                    _merge_man_a = _weld_result["manifold"]
                        if _merge_man_a is None:
                            # Attempt transactional planar-boundary cap repair.
                            # All modifications run on a working copy; original mesh_a
                            # is only replaced if the repaired copy passes full Manifold
                            # validation.  On any failure the existing fill_holes path runs.
                            _planar_result = _try_repair_planar_boundary(mesh_a, "mesh_a")
                            if _planar_result["applied"]:
                                mesh_a = _planar_result["mesh"]
                            else:
                                trimesh.repair.fill_holes(mesh_a)
                                trimesh.repair.fix_winding(mesh_a)
                                trimesh.repair.fix_normals(mesh_a)
                                mesh_a.merge_vertices()
                    else:
                        # mesh_b also needs repair; apply the same cleanup first.
                        _remove_repeated_index_faces(mesh_b, "mesh_b")
                        if len(mesh_b.faces) == 0:
                            return False, (
                                "mesh_b has no faces remaining after repeated-index cleanup"
                            ), None
                        trimesh.repair.fill_holes(mesh_b)
                        trimesh.repair.fix_winding(mesh_b)
                        trimesh.repair.fix_normals(mesh_b)
                        mesh_b.merge_vertices()

            # Retry mesh_a — exceptions propagate to the outer try/except
            _stage = "retrying mesh_a conversion"
            if _merge_man_a is not None:
                # Mesh.merge() already produced a validated Manifold; use it directly
                # without re-running trimesh_to_manifold so merge info is preserved.
                man_a = _merge_man_a
            else:
                man_a = trimesh_to_manifold(mesh_a)
            if not _is_valid_manifold(man_a):
                return False, "mesh_a repair failed: still invalid after repair", "BOOLEAN_INVALID_MESH"

            # Retry mesh_b — exceptions propagate to the outer try/except
            _stage = "retrying mesh_b conversion"
            man_b = trimesh_to_manifold(mesh_b)
            if not _is_valid_manifold(man_b):
                return False, "mesh_b repair failed: still invalid after repair", "BOOLEAN_INVALID_MESH"

        # --- Defensive union pre-check ---
        # Guards against any future code path that could reach here with an invalid Manifold.
        _stage = f"{operation.value}"
        if not _is_valid_manifold(man_a):
            return False, "union pre-check: mesh_a is invalid", "BOOLEAN_INVALID_MESH"
        if not _is_valid_manifold(man_b):
            return False, "union pre-check: mesh_b is invalid", "BOOLEAN_INVALID_MESH"

        # --- Union ---
        if operation == BooleanOperation.UNION:
            result_man = man_a + man_b
        elif operation == BooleanOperation.DIFFERENCE:
            result_man = man_a - man_b
        elif operation == BooleanOperation.INTERSECTION:
            result_man = man_a ^ man_b
        else:
            return False, f"Unknown operation: {operation}", None

        _stage = "converting result"
        result = manifold_to_trimesh(result_man)

        _stage = "checking result"
        if result is None or (hasattr(result, 'is_empty') and result.is_empty):
            return False, "Boolean operation resulted in empty mesh", None

        _log.info(f"  Result: {len(result.faces)} faces, watertight={result.is_watertight}")

        # Export result
        result.export(str(output_path))
        return True, None, None

    except Exception as e:
        import traceback as _tb_mod
        _tb = _tb_mod.format_exc()
        err = f"Boolean operation failed: {str(e)}\n{_tb}"
        try:
            _log.error(f"Boolean {operation.value} failed at {_stage}: {type(e).__name__}: {e}")
        except Exception:
            pass
        print(err, flush=True)
        return False, err, None


def generate_drain_holes(
    hex_cell_radius: float = 5.0,
    wall_thickness: float = 1.0,
    grid_count: int = 10,
    drain_radius: float = 1.5,
    bottom_z: float = 0.0,
):
    """
    Generate drain hole cylinders at hex grid wall edge midpoints.

    Ports the algorithm from DS-Online drillService.js generateDrainHoles().
    Creates cylinders at each wall midpoint between neighboring hex cells,
    oriented perpendicular to the wall direction, lying in the XY plane.

    Args:
        hex_cell_radius: Hex cell radius (mm)
        wall_thickness: Gap between cells (mm)
        grid_count: Number of cells per row
        drain_radius: Drain hole cylinder radius (mm)
        bottom_z: Z position of the print bed

    Returns:
        trimesh.Trimesh mesh of all drain cylinders, or None if no walls found
    """
    import math
    import numpy as np
    import trimesh
    from trimesh import transformations

    spacing = hex_cell_radius + wall_thickness / 2
    col_step = spacing * math.sqrt(3)
    row_step = spacing * 1.5
    half_cols = (grid_count - 1) / 2
    half_rows = (grid_count - 1) / 2

    def cell_center(row, col):
        x_offset = (row % 2) * (col_step / 2)
        return (
            (col - half_cols) * col_step + x_offset,
            (row - half_rows) * row_step,
        )

    walls = []
    seen = set()

    def edge_key(r1, c1, r2, c2):
        a = r1 * 1000 + c1
        b = r2 * 1000 + c2
        return (min(a, b), max(a, b))

    for row in range(grid_count):
        for col in range(grid_count):
            neighbors = [
                (row, col + 1),
                (row + 1, (col - 1) if (row % 2 == 0) else col),
                (row + 1, col if (row % 2 == 0) else (col + 1)),
            ]

            for nr, nc in neighbors:
                if nr < 0 or nr >= grid_count or nc < 0 or nc >= grid_count:
                    continue
                key = edge_key(row, col, nr, nc)
                if key in seen:
                    continue
                seen.add(key)

                ax, ay = cell_center(row, col)
                bx, by = cell_center(nr, nc)
                mid_x = (ax + bx) / 2
                mid_y = (ay + by) / 2
                angle = math.atan2(by - ay, bx - ax)
                walls.append((mid_x, mid_y, angle))

    if not walls:
        return None

    cyl_length = wall_thickness * 3
    cylinders = []

    for mid_x, mid_y, angle in walls:
        cyl = trimesh.creation.cylinder(
            radius=drain_radius,
            height=cyl_length,
            sections=32,
        )
        # Rotate from Z-aligned to XY plane at the wall direction angle.
        # Ry(PI/2) maps Z→X, then Rz(angle) maps X→wall direction.
        ry = transformations.rotation_matrix(np.pi / 2, [0, 1, 0])
        rz = transformations.rotation_matrix(angle, [0, 0, 1])
        transform = rz @ ry
        transform[:3, 3] = [mid_x, mid_y, bottom_z]
        cyl.apply_transform(transform)
        cylinders.append(cyl)

    merged = trimesh.util.concatenate(cylinders)
    return merged


def generate_hex_grid(
    radius: float = 5.0,
    fallback_height: float = 20.0,
    pyramid_height: float = 5.0,
    wall_thickness: float = 1.0,
    grid_count: int = 5,
    bottom_z: float = 0.0,
    hollow_mesh=None,
):
    """
    Generate a honeycomb hex grid mesh with heights adapted to hollow mesh ceiling.

    Ports the algorithm from DS-Online infillService.js generateHexGrid().

    Args:
        radius: Hex cell radius (mm)
        fallback_height: Fallback prism height if no hollow mesh or ray miss (mm)
        pyramid_height: Height of the hexagonal pyramid dome (mm)
        wall_thickness: Gap between cells (mm)
        grid_count: Number of cells per row
        bottom_z: Z position of the print bed
        hollow_mesh: trimesh.Trimesh hollow mesh for ray-based height adaptation

    Returns:
        trimesh.Trimesh mesh or None if no cells built
    """
    import math
    import numpy as np
    import trimesh

    vertices = []
    faces = []
    base_idx = 0
    vertices_per_cell = 14  # 1 bottom center + 6 bottom ring + 6 top ring + 1 apex

    # Honeycomb spacing (flat-top hex)
    spacing = radius + wall_thickness / 2
    col_step = spacing * math.sqrt(3)
    row_step = spacing * 1.5

    # Setup raycasting for finding hollow mesh ceiling
    has_hollow = hollow_mesh is not None
    inner_max_z = fallback_height
    if has_hollow:
        inner_max_z = hollow_mesh.bounds[1][2] + 5  # max Z + 5

    # Grid placement: anchor the lattice to the model's XY centre and size it to
    # fully cover the model's XY bounding box. Cells that miss the hollow are
    # culled by the raycast below, so over-provisioning is safe. This fixes the
    # off-centre case: the hollow is aligned to the input model's centre, so the
    # hex must be too — anchoring to (0,0) left off-centre models only partially
    # covered. Falls back to an origin-centred grid_count x grid_count grid when
    # no hollow mesh is available.
    if has_hollow:
        bmin = hollow_mesh.bounds[0]
        bmax = hollow_mesh.bounds[1]
        center_x = (bmin[0] + bmax[0]) / 2.0
        center_y = (bmin[1] + bmax[1]) / 2.0
        span_x = bmax[0] - bmin[0]
        span_y = bmax[1] - bmin[1]
        # +3 cells of margin so the grid overruns the model edges before culling
        n_cols = max(grid_count, int(math.ceil(span_x / col_step)) + 3)
        n_rows = max(grid_count, int(math.ceil(span_y / row_step)) + 3)
    else:
        center_x = 0.0
        center_y = 0.0
        n_cols = grid_count
        n_rows = grid_count

    half_cols = (n_cols - 1) / 2
    half_rows = (n_rows - 1) / 2

    # Batch all ray origins/directions for a single intersects_location call
    ray_origins_list = []
    ray_cells = []  # (row, col, cx, cy) for each ray

    for row in range(n_rows):
        for col in range(n_cols):
            x_offset = (row % 2) * (col_step / 2)
            cx = (col - half_cols) * col_step + x_offset + center_x
            cy = (row - half_rows) * row_step + center_y
            ray_origins_list.append([cx, cy, -100.0])
            ray_cells.append((row, col, cx, cy))

    # Perform batched raycasting
    cell_heights = {}  # (row, col) -> prism_height or None (skip)

    if has_hollow and ray_origins_list:
        ray_origins = np.array(ray_origins_list, dtype=np.float64)
        ray_dirs = np.tile([0.0, 0.0, 1.0], (len(ray_origins_list), 1))
        locations, index_ray, _ = hollow_mesh.ray.intersects_location(ray_origins, ray_dirs)

        # Group hit Z values by ray index
        for i, (row, col, cx, cy) in enumerate(ray_cells):
            hits = locations[index_ray == i]
            if len(hits) > 0:
                max_z = float(hits[:, 2].max())
                h_val = max_z - pyramid_height
                if h_val < 1:
                    cell_heights[(row, col)] = None  # skip
                else:
                    cell_heights[(row, col)] = h_val
            else:
                cell_heights[(row, col)] = inner_max_z - pyramid_height

    cells_built = 0
    cells_skipped = 0

    for row, col, cx, cy in ray_cells:
        if has_hollow:
            h = cell_heights.get((row, col))
            if h is None:
                cells_skipped += 1
                continue
            prism_height = h
        else:
            prism_height = fallback_height

        # Build hex cell vertices
        hex_points = []
        for i in range(6):
            angle = (math.pi / 3) * i - math.pi / 6
            hex_points.append((
                cx + radius * math.cos(angle),
                cy + radius * math.sin(angle),
            ))

        # Bottom center (base_idx + 0)
        vertices.append([cx, cy, bottom_z])
        # Bottom ring (base_idx + 1..6)
        for i in range(6):
            vertices.append([hex_points[i][0], hex_points[i][1], bottom_z])
        # Top ring (base_idx + 7..12)
        for i in range(6):
            vertices.append([hex_points[i][0], hex_points[i][1], prism_height])
        # Apex (base_idx + 13)
        vertices.append([cx, cy, prism_height + pyramid_height])

        # Bottom face (6 triangles, fan from center)
        for i in range(6):
            nxt = (i + 1) % 6
            faces.append([base_idx + 0, base_idx + 1 + nxt, base_idx + 1 + i])

        # Prism side faces (6 quads = 12 triangles)
        for i in range(6):
            nxt = (i + 1) % 6
            b0 = base_idx + 1 + i
            b1 = base_idx + 1 + nxt
            t0 = base_idx + 7 + i
            t1 = base_idx + 7 + nxt
            faces.append([b0, b1, t1])
            faces.append([b0, t1, t0])

        # Pyramid faces (6 triangles)
        for i in range(6):
            nxt = (i + 1) % 6
            faces.append([base_idx + 7 + i, base_idx + 7 + nxt, base_idx + 13])

        base_idx += vertices_per_cell
        cells_built += 1

    if cells_built == 0:
        return None

    mesh = trimesh.Trimesh(
        vertices=np.array(vertices, dtype=np.float64),
        faces=np.array(faces, dtype=np.int64),
        process=False,
    )

    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"Hex grid: {cells_built} cells built, {cells_skipped} skipped, "
                f"radius={radius}, wall={wall_thickness}, pyramid={pyramid_height}")

    return mesh


async def perform_boolean(
    job_dir: Path,
    mesh_a_path: Path,
    mesh_b_path: Path,
    operation: BooleanOperation,
) -> OperationResult:
    """
    Perform boolean operation on two meshes.

    Args:
        job_dir: Job directory for output
        mesh_a_path: Path to first mesh (STL)
        mesh_b_path: Path to second mesh (STL)
        operation: Boolean operation type

    Returns:
        OperationResult with boolean_mesh_path if successful
    """
    job_id = job_dir.name
    output_dir = job_dir / "output"
    output_dir.mkdir(exist_ok=True)

    output_path = output_dir / f"model_boolean_{operation.value}.stl"

    # Run boolean operation in thread pool to avoid blocking the event loop
    import asyncio
    loop = asyncio.get_event_loop()
    success, error, error_code = await loop.run_in_executor(
        None, boolean_operation, mesh_a_path, mesh_b_path, operation, output_path
    )

    if not success:
        return OperationResult(
            success=False,
            operation=OperationType.BOOLEAN,
            job_id=job_id,
            error=error,
            error_code=error_code,
        )

    return OperationResult(
        success=True,
        operation=OperationType.BOOLEAN,
        job_id=job_id,
        boolean_mesh_path=output_path,
        metadata={
            "operation": operation.value,
            "mesh_a": str(mesh_a_path),
            "mesh_b": str(mesh_b_path),
        },
    )
