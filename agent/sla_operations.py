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

import struct

from .config import PRUSA_SLICER_CLI
from .models import BooleanOperation, CutConfig, CutMode, SLAConfig


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
        str(PRUSA_SLICER_CLI),
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
            error=f"PrusaSlicer failed (exit {returncode}): {error_msg}",
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
        str(PRUSA_SLICER_CLI),
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
            error=f"PrusaSlicer cut failed (exit {returncode}): {error_msg}",
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

def boolean_operation(
    mesh_a_path: Path,
    mesh_b_path: Path,
    operation: BooleanOperation,
    output_path: Path,
) -> tuple[bool, Optional[str]]:
    """
    Perform boolean operation on two meshes using trimesh + manifold3d.

    Args:
        mesh_a_path: Path to first mesh (STL)
        mesh_b_path: Path to second mesh (STL)
        operation: Boolean operation type (union, difference, intersection)
        output_path: Path to write result STL

    Returns:
        Tuple of (success, error_message)
    """
    try:
        import trimesh
    except ImportError:
        return False, "trimesh not installed. Run: pip install trimesh manifold3d"

    try:
        import logging
        logger = logging.getLogger(__name__)

        # Load meshes
        mesh_a = trimesh.load(str(mesh_a_path))
        mesh_b = trimesh.load(str(mesh_b_path))

        # Ensure we have Trimesh objects (not Scene)
        if isinstance(mesh_a, trimesh.Scene):
            mesh_a = trimesh.util.concatenate(mesh_a.dump())
        if isinstance(mesh_b, trimesh.Scene):
            mesh_b = trimesh.util.concatenate(mesh_b.dump())

        logger.warning(f"Boolean {operation.value}: A={len(mesh_a.faces)} faces, B={len(mesh_b.faces)} faces")
        logger.warning(f"  A watertight={mesh_a.is_watertight}, volume={mesh_a.is_volume}, bounds={mesh_a.bounds.tolist()}")
        logger.warning(f"  B watertight={mesh_b.is_watertight}, volume={mesh_b.is_volume}, bounds={mesh_b.bounds.tolist()}")

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

        try:
            man_a = trimesh_to_manifold(mesh_a)
            man_b = trimesh_to_manifold(mesh_b)
        except Exception as e:
            logger.warning(f"  Manifold conversion failed: {e}, falling back to trimesh repair")
            # Fallback: try trimesh repair + trimesh boolean
            for label, mesh in [("A", mesh_a), ("B", mesh_b)]:
                if not mesh.is_volume:
                    trimesh.repair.fill_holes(mesh)
                    trimesh.repair.fix_winding(mesh)
                    trimesh.repair.fix_normals(mesh)
                    mesh.merge_vertices()
            man_a = trimesh_to_manifold(mesh_a)
            man_b = trimesh_to_manifold(mesh_b)

        # Perform boolean operation via manifold3d
        if operation == BooleanOperation.UNION:
            result_man = man_a + man_b
        elif operation == BooleanOperation.DIFFERENCE:
            result_man = man_a - man_b
        elif operation == BooleanOperation.INTERSECTION:
            result_man = man_a ^ man_b
        else:
            return False, f"Unknown operation: {operation}"

        result = manifold_to_trimesh(result_man)

        # Check result
        if result is None or (hasattr(result, 'is_empty') and result.is_empty):
            return False, "Boolean operation resulted in empty mesh"

        logger.warning(f"  Result: {len(result.faces)} faces, watertight={result.is_watertight}")

        # Export result
        result.export(str(output_path))
        return True, None

    except Exception as e:
        import traceback
        err = f"Boolean operation failed: {str(e)}\n{traceback.format_exc()}"
        print(err, flush=True)
        return False, err


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
    success, error = await loop.run_in_executor(
        None, boolean_operation, mesh_a_path, mesh_b_path, operation, output_path
    )

    if not success:
        return OperationResult(
            success=False,
            operation=OperationType.BOOLEAN,
            job_id=job_id,
            error=error,
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
