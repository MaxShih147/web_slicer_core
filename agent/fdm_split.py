"""
FDM Split — Plane cut & grid cut using manifold3d box intersection.
"""

from __future__ import annotations

import logging
import math
import uuid
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import trimesh

logger = logging.getLogger(__name__)


@dataclass
class PartDescriptor:
    part_id: str
    mesh: trimesh.Trimesh
    mesh_path: str | None
    bbox_mm: tuple
    volume_mm3: float
    side: str  # "positive"/"negative" for plane, "0-1-2" grid coord for grid


@dataclass
class SplitResult:
    parts: list[PartDescriptor]
    axis: str
    position: float
    original_volume: float


@dataclass
class GridSplitResult:
    parts: list[PartDescriptor]
    grid: tuple[int, int, int]  # (nx, ny, nz)
    original_volume: float


def _trimesh_to_manifold(mesh):
    import manifold3d
    verts = np.array(mesh.vertices, dtype=np.float32)
    faces = np.array(mesh.faces, dtype=np.int32)
    return manifold3d.Manifold(manifold3d.Mesh(vert_properties=verts, tri_verts=faces))


def _manifold_to_trimesh(man):
    mesh_out = man.to_mesh()
    verts = np.array(mesh_out.vert_properties[:, :3])
    faces = np.array(mesh_out.tri_verts)
    if len(faces) == 0:
        return None
    return trimesh.Trimesh(vertices=verts, faces=faces, process=False)


def _preprocess_mesh(mesh: trimesh.Trimesh) -> None:
    """Repair mesh in-place for clean manifold3d intersection."""
    mesh.merge_vertices()
    mesh.update_faces(mesh.nondegenerate_faces())
    trimesh.repair.fill_holes(mesh)
    trimesh.repair.fix_winding(mesh)
    trimesh.repair.fix_normals(mesh)
    mesh.merge_vertices()


def run_fdm_split(
    mesh: trimesh.Trimesh,
    axis: str,
    position: float,
    output_dir: Path,
) -> SplitResult:
    """
    Cut mesh with a single axis-aligned plane.
    """
    import manifold3d

    _preprocess_mesh(mesh)

    axis_idx = {"x": 0, "y": 1, "z": 2}[axis]

    bmin = mesh.bounds[0].copy()
    bmax = mesh.bounds[1].copy()
    PAD = 1.0

    try:
        original_volume = abs(mesh.volume)
    except Exception:
        original_volume = 0.0

    logger.info(f"FDM split: axis={axis}, pos={position}, "
                f"bounds=[{bmin[axis_idx]:.1f}, {bmax[axis_idx]:.1f}], "
                f"faces={len(mesh.faces)}")

    man_mesh = _trimesh_to_manifold(mesh)

    parts = []
    for side, (lo, hi) in [
        ("negative", (bmin.copy(), bmax.copy())),
        ("positive", (bmin.copy(), bmax.copy())),
    ]:
        # Pad outer boundary
        lo -= PAD
        hi += PAD

        # Set the cut boundary (exact, no overlap)
        if side == "negative":
            hi[axis_idx] = position
        else:
            lo[axis_idx] = position

        size = hi - lo
        if np.any(size <= 0):
            continue

        box = manifold3d.Manifold.cube(size.tolist()).translate(lo.tolist())

        try:
            result_man = man_mesh ^ box
            result_mesh = _manifold_to_trimesh(result_man)
        except Exception as e:
            logger.warning(f"  {side} intersection failed: {e}")
            continue

        if result_mesh is None or len(result_mesh.faces) < 4:
            continue

        try:
            vol = abs(result_mesh.volume)
        except Exception:
            vol = 0.0

        part_id = str(uuid.uuid4())[:8]
        filename = f"part_{side}.stl"
        result_mesh.export(str(output_dir / filename))

        part_extents = result_mesh.bounding_box.extents
        parts.append(PartDescriptor(
            part_id=part_id,
            mesh=result_mesh,
            mesh_path=filename,
            bbox_mm=tuple(part_extents.tolist()),
            volume_mm3=round(vol, 2),
            side=side,
        ))

    total_vol = sum(p.volume_mm3 for p in parts)
    logger.info(f"FDM split done: {len(parts)} parts, "
                f"volume {total_vol:.0f} / {original_volume:.0f}")

    return SplitResult(
        parts=parts,
        axis=axis,
        position=position,
        original_volume=original_volume,
    )


def run_fdm_grid_split(
    mesh: trimesh.Trimesh,
    build_x: float,
    build_y: float,
    build_z: float,
    output_dir: Path,
) -> GridSplitResult:
    """
    Split mesh into a uniform grid based on build volume dimensions.

    Each cell is ceil(extent / build_volume) per axis.
    """
    import manifold3d

    _preprocess_mesh(mesh)

    bmin = mesh.bounds[0].copy()
    bmax = mesh.bounds[1].copy()
    extents = bmax - bmin
    PAD = 1.0

    try:
        original_volume = abs(mesh.volume)
    except Exception:
        original_volume = 0.0

    # Grid divisions per axis
    nx = max(1, math.ceil(extents[0] / build_x))
    ny = max(1, math.ceil(extents[1] / build_y))
    nz = max(1, math.ceil(extents[2] / build_z))

    logger.info(f"FDM grid split: build_vol=({build_x}, {build_y}, {build_z}), "
                f"extents=({extents[0]:.1f}, {extents[1]:.1f}, {extents[2]:.1f}), "
                f"grid=({nx}, {ny}, {nz}), faces={len(mesh.faces)}")

    # Skip if already fits
    if nx == 1 and ny == 1 and nz == 1:
        part_id = str(uuid.uuid4())[:8]
        filename = "part_0-0-0.stl"
        mesh.export(str(output_dir / filename))
        part_extents = mesh.bounding_box.extents
        parts = [PartDescriptor(
            part_id=part_id,
            mesh=mesh,
            mesh_path=filename,
            bbox_mm=tuple(part_extents.tolist()),
            volume_mm3=round(original_volume, 2),
            side="0-0-0",
        )]
        return GridSplitResult(parts=parts, grid=(1, 1, 1),
                               original_volume=original_volume)

    # Cell sizes (evenly divide the mesh extent)
    cell_x = extents[0] / nx
    cell_y = extents[1] / ny
    cell_z = extents[2] / nz

    man_mesh = _trimesh_to_manifold(mesh)
    parts = []

    for ix in range(nx):
        for iy in range(ny):
            for iz in range(nz):
                lo = np.array([
                    bmin[0] + ix * cell_x,
                    bmin[1] + iy * cell_y,
                    bmin[2] + iz * cell_z,
                ])
                hi = np.array([
                    bmin[0] + (ix + 1) * cell_x,
                    bmin[1] + (iy + 1) * cell_y,
                    bmin[2] + (iz + 1) * cell_z,
                ])

                # Pad only outer boundaries
                if ix == 0:      lo[0] -= PAD
                if ix == nx - 1: hi[0] += PAD
                if iy == 0:      lo[1] -= PAD
                if iy == ny - 1: hi[1] += PAD
                if iz == 0:      lo[2] -= PAD
                if iz == nz - 1: hi[2] += PAD

                size = hi - lo
                if np.any(size <= 0):
                    continue

                box = manifold3d.Manifold.cube(size.tolist()).translate(lo.tolist())

                try:
                    result_man = man_mesh ^ box
                    result_mesh = _manifold_to_trimesh(result_man)
                except Exception as e:
                    logger.warning(f"  grid ({ix},{iy},{iz}) intersection failed: {e}")
                    continue

                if result_mesh is None or len(result_mesh.faces) < 4:
                    continue

                try:
                    vol = abs(result_mesh.volume)
                except Exception:
                    vol = 0.0

                if vol < 1.0:
                    continue

                coord = f"{ix}-{iy}-{iz}"
                part_id = str(uuid.uuid4())[:8]
                filename = f"part_{coord}.stl"
                result_mesh.export(str(output_dir / filename))

                part_extents = result_mesh.bounding_box.extents
                parts.append(PartDescriptor(
                    part_id=part_id,
                    mesh=result_mesh,
                    mesh_path=filename,
                    bbox_mm=tuple(part_extents.tolist()),
                    volume_mm3=round(vol, 2),
                    side=coord,
                ))

    total_vol = sum(p.volume_mm3 for p in parts)
    logger.info(f"FDM grid split done: {len(parts)} parts, "
                f"grid=({nx},{ny},{nz}), "
                f"volume {total_vol:.0f} / {original_volume:.0f}")

    return GridSplitResult(
        parts=parts,
        grid=(nx, ny, nz),
        original_volume=original_volume,
    )
