"""
FDM Split — Plane cut, grid cut, and BSP auto-split using manifold3d.

Auto-split implements a simplified Chopper (Luo 2012) BSP beam search:
  - Generate candidate cutting plane normals (uniform sphere sampling)
  - BSP beam search: iteratively split the largest part using the best plane
  - Score: n_parts + utilization + connector (cross-section area) + fragility
  - manifold3d.split_by_plane for robust mesh cutting
"""

from __future__ import annotations

import copy
import logging
import math
import uuid
from dataclasses import dataclass, field
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


@dataclass
class AutoSplitResult:
    parts: list[PartDescriptor]
    n_cuts: int
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


# ============================================================================
# BSP Auto-Split (Chopper-inspired beam search)
# ============================================================================

def _uniform_normals(n_theta: int = 4, n_phi: int = 4) -> np.ndarray:
    """Generate uniformly distributed normals on the upper hemisphere.

    Based on http://corysimon.github.io/articles/uniformdistn-on-sphere/
    """
    theta = np.arange(0, np.pi, np.pi / n_theta)
    phi = np.arccos(np.arange(0, 1, 1 / n_phi))
    theta, phi = np.meshgrid(theta, phi)
    normals = np.stack((
        np.sin(phi.ravel()) * np.cos(theta.ravel()),
        np.sin(phi.ravel()) * np.sin(theta.ravel()),
        np.cos(phi.ravel()),
    ), axis=1)
    # Deduplicate near-identical normals
    return np.unique(np.round(normals, 3), axis=0)


def _get_candidate_planes(
    verts: np.ndarray,
    normal: np.ndarray,
    plane_spacing: float,
) -> list[tuple[np.ndarray, np.ndarray]]:
    """Generate candidate cutting planes along a given normal direction.

    Args:
        verts: (N, 3) vertex array (or trimesh — .vertices extracted)
        normal: unit normal vector for the planes
        plane_spacing: distance between candidate planes

    Returns list of (origin, normal) tuples.
    """
    if hasattr(verts, 'vertices'):
        verts = verts.vertices
    projection = verts @ normal
    lo, hi = projection.min(), projection.max()
    span = hi - lo
    if span < plane_spacing * 0.5:
        return []

    planes = []
    # Evenly spaced planes (skip boundary)
    for d in np.arange(lo + plane_spacing, hi, plane_spacing):
        planes.append((d * normal, normal.copy()))

    # Always add the middle plane
    mid = (lo + hi) / 2
    mid_origin = mid * normal
    # Don't duplicate if already close to an existing plane
    if not any(abs(np.dot(p[0] - mid_origin, normal)) < plane_spacing * 0.3 for p in planes):
        planes.append((mid_origin, normal.copy()))

    return planes


def _split_by_plane_manifold(
    man_mesh,
    origin: np.ndarray,
    normal: np.ndarray,
) -> tuple[trimesh.Trimesh | None, trimesh.Trimesh | None]:
    """Split a manifold mesh by an arbitrary plane. Returns (positive, negative)."""
    # manifold3d.split_by_plane(normal, originOffset)
    # originOffset = distance from origin along the normal
    offset = float(np.dot(origin, normal))
    normal_list = normal.tolist()

    try:
        pos_man, neg_man = man_mesh.split_by_plane(normal_list, offset)
    except Exception as e:
        logger.warning(f"  split_by_plane failed: {e}")
        return None, None

    pos_mesh = _manifold_to_trimesh(pos_man)
    neg_mesh = _manifold_to_trimesh(neg_man)
    return pos_mesh, neg_mesh


class _BSPNode:
    """Lightweight BSP node — stores only vertices (Nx3 array), no mesh objects.

    During planning, we only need vertex positions to compute bounding boxes
    and split by half-space. No manifold/trimesh operations needed.
    """
    __slots__ = ('verts', 'children', 'path', 'plane', 'n_parts', 'terminated',
                 '_extents', '_volume_approx')

    def __init__(self, verts: np.ndarray, printer_extents: np.ndarray, path: tuple = ()):
        self.verts = verts  # (N, 3) float array
        self.children: list[_BSPNode] = []
        self.path = path
        self.plane: tuple | None = None
        extents = verts.max(axis=0) - verts.min(axis=0)
        self._extents = extents
        self._volume_approx = float(np.prod(extents))  # AABB volume approximation
        self.n_parts = float(np.prod(np.ceil(extents / printer_extents)))
        self.terminated = bool(np.all(extents <= printer_extents))


class _BSPTree:
    """Lightweight BSP tree for planning — vertex-only, no mesh objects."""

    def __init__(self, root: _BSPNode):
        self.root = root
        self.objectives = {'nparts': 1.0, 'utilization': 0.0, 'connector': 0.0, 'fragility': 0.0}

    @property
    def leaves(self) -> list[_BSPNode]:
        result = []
        stack = [self.root]
        while stack:
            node = stack.pop()
            if not node.children:
                result.append(node)
            else:
                stack.extend(node.children)
        return result

    @property
    def terminated(self) -> bool:
        return all(leaf.terminated for leaf in self.leaves)

    @property
    def largest_part(self) -> _BSPNode:
        return max(self.leaves, key=lambda n: n.n_parts)

    @property
    def objective(self) -> float:
        return (self.objectives['nparts']
                + 0.25 * self.objectives['utilization']
                + 1.0  * self.objectives['connector']
                + 1.0  * self.objectives['fragility'])

    def copy(self) -> _BSPTree:
        return copy.deepcopy(self)


def _expand_node(
    tree: _BSPTree,
    path: tuple,
    plane: tuple,
    printer_extents: np.ndarray,
) -> _BSPTree | None:
    """Split a node by vertex half-space test (no mesh split needed).

    Adds synthetic vertices at the cut plane to preserve bounding box accuracy:
    vertices on the opposite side are projected onto the plane so each child's
    bounding box correctly includes the cut surface.
    """
    new_tree = tree.copy()

    node = new_tree.root
    for idx in path:
        node = node.children[idx]

    origin, normal = plane
    normal = normal / np.linalg.norm(normal)
    offset = np.dot(origin, normal)

    # Half-space split: project all vertices onto normal
    projections = node.verts @ normal
    pos_mask = projections >= offset
    neg_mask = ~pos_mask

    pos_count = int(pos_mask.sum())
    neg_count = int(neg_mask.sum())
    if pos_count < 1 or neg_count < 1:
        return None

    # Project opposite-side vertices onto the cut plane to preserve bbox accuracy.
    # P_proj = P + (offset - P·N) * N
    neg_verts = node.verts[neg_mask]
    neg_proj = neg_verts + np.outer(offset - projections[neg_mask], normal)
    pos_verts = node.verts[pos_mask]
    pos_proj = pos_verts + np.outer(offset - projections[pos_mask], normal)

    pos_all = np.vstack([pos_verts, neg_proj])
    neg_all = np.vstack([neg_verts, pos_proj])

    node.plane = plane
    node.children = [
        _BSPNode(pos_all, printer_extents, path=(*node.path, 0)),
        _BSPNode(neg_all, printer_extents, path=(*node.path, 1)),
    ]

    return new_tree


def _evaluate_objectives(
    trees: list[_BSPTree],
    path: tuple,
    printer_extents: np.ndarray,
    theta_0: float,
    plane_spacing: float = 10.0,
):
    """Evaluate nparts + utilization + connector + fragility objectives."""
    V = float(np.prod(printer_extents))

    # Connector / fragility parameters
    connector_margin = plane_spacing * 0.5
    fragility_min_thickness = 5.0  # mm

    for tree in trees:
        node = tree.root
        for idx in path:
            node = node.children[idx]

        # --- nparts ---
        child_nparts = sum(c.n_parts for c in node.children)
        tree.objectives['nparts'] += (child_nparts - node.n_parts) / max(theta_0, 1.0)

        # --- utilization ---
        child_utils = []
        for c in node.children:
            child_utils.append(1.0 - c._volume_approx / max(c.n_parts * V, 1.0))
        tree.objectives['utilization'] = max(
            tree.objectives['utilization'], max(child_utils)
        )

        # --- connector (prefer small cross-section → cut at narrow spots) ---
        # Use parent's ORIGINAL verts (children have projected verts that
        # inflate footprint). Split near-plane verts by side, take min area.
        origin, normal = node.plane if node.plane else (None, None)
        if origin is not None:
            normal_unit = normal / np.linalg.norm(normal)
            offset = np.dot(origin, normal_unit)
            u, v = _plane_basis(normal_unit)
            uv_basis = np.column_stack([u, v])  # (3, 2)

            projections = node.verts @ normal_unit
            # One-sided bands: skip verts exactly on the plane to avoid
            # boundary inflation (e.g. body top face at the limb junction).
            eps = connector_margin * 0.05
            side_areas = []
            for lo, hi in [(offset + eps, offset + connector_margin),
                           (offset - connector_margin, offset - eps)]:
                mask = (projections >= lo) & (projections <= hi)
                side_verts = node.verts[mask]
                if len(side_verts) >= 2:
                    s_2d = side_verts @ uv_basis
                    s_size = s_2d.max(axis=0) - s_2d.min(axis=0)
                    side_areas.append(float(s_size[0] * s_size[1]))

            if not side_areas:
                connector_score = 1.0  # plane barely touches mesh
            else:
                cross_area = min(side_areas)
                parent_ext = sorted(node._extents, reverse=True)
                ref_area = float(parent_ext[0] * parent_ext[1])
                connector_score = cross_area / max(ref_area, 1e-6)

            tree.objectives['connector'] = max(
                tree.objectives['connector'], connector_score
            )

        # --- fragility (thin-wall / narrow-neck rejection) ---
        if origin is not None:
            fragility_score = 0.0
            for c in node.children:
                # Check 1: overall AABB min dimension
                if np.any(c._extents < fragility_min_thickness):
                    fragility_score = float('inf')
                    break

            # Check 2: cross-section width at the cut plane (one-sided bands
            # from parent verts, same as connector, to avoid projected-vertex
            # inflation).
            if fragility_score == 0.0:
                for lo, hi in [(offset + eps, offset + connector_margin),
                               (offset - connector_margin, offset - eps)]:
                    mask = (projections >= lo) & (projections <= hi)
                    side_verts = node.verts[mask]
                    if len(side_verts) >= 2:
                        s_2d = side_verts @ uv_basis
                        s_bbox = s_2d.max(axis=0) - s_2d.min(axis=0)
                        if np.any(s_bbox < fragility_min_thickness):
                            fragility_score = float('inf')
                            break

            tree.objectives['fragility'] = max(
                tree.objectives['fragility'], fragility_score
            )


def _plane_basis(normal: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return two orthonormal basis vectors (u, v) lying on the plane with given normal."""
    n = normal / np.linalg.norm(normal)
    ref = np.array([1.0, 0.0, 0.0]) if abs(n[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    u = np.cross(n, ref)
    u /= np.linalg.norm(u)
    v = np.cross(n, u)
    return u, v


def _planes_are_different(
    plane_a: tuple,
    plane_b: tuple,
    origin_th: float,
    angle_th: float,
) -> bool:
    """Check if two planes are sufficiently different."""
    o_a, n_a = plane_a
    o_b, n_b = plane_b
    dist = abs(np.dot(n_a, o_b - o_a))
    cos_angle = np.clip(np.dot(n_a, n_b), -1.0, 1.0)
    angle = np.arccos(abs(cos_angle))  # symmetric: same plane regardless of normal direction
    return dist > origin_th or angle > angle_th



def _collect_cut_planes(root: _BSPNode) -> list[tuple[np.ndarray, np.ndarray]]:
    """Walk BSP tree and collect all cutting planes in BFS order."""
    planes = []
    queue = [root]
    while queue:
        node = queue.pop(0)
        if node.plane is not None:
            planes.append(node.plane)
        queue.extend(node.children)
    return planes


def _execute_cuts_on_original(
    mesh: trimesh.Trimesh,
    planes: list[tuple[np.ndarray, np.ndarray]],
    output_dir: Path,
    printer_extents: np.ndarray,
) -> list[PartDescriptor]:
    """Apply the planned cut planes to the original full-res mesh.

    Iteratively splits a pool of mesh pieces by each plane.
    """
    import manifold3d

    _preprocess_mesh(mesh)
    man_mesh = _trimesh_to_manifold(mesh)
    # Pool of manifold pieces to split
    pool = [man_mesh]

    for origin, normal in planes:
        offset = float(np.dot(origin, normal))
        normal_list = normal.tolist()
        new_pool = []
        split_done = False
        for piece in pool:
            if split_done:
                new_pool.append(piece)
                continue
            # Only split the largest piece that still exceeds build volume
            piece_tm = _manifold_to_trimesh(piece)
            if piece_tm is None or np.all(piece_tm.bounding_box.extents <= printer_extents):
                new_pool.append(piece)
                continue
            try:
                pos, neg = piece.split_by_plane(normal_list, offset)
                pos_tm = _manifold_to_trimesh(pos)
                neg_tm = _manifold_to_trimesh(neg)
                if pos_tm and len(pos_tm.faces) >= 4 and neg_tm and len(neg_tm.faces) >= 4:
                    new_pool.append(pos)
                    new_pool.append(neg)
                    split_done = True
                else:
                    new_pool.append(piece)
            except Exception:
                new_pool.append(piece)
        pool = new_pool

    # Post-split pass: any piece still oversized gets axis-aligned bisection
    final_pool = []
    for piece in pool:
        _subdivide_oversize(piece, printer_extents, final_pool, depth=0)

    # Export
    parts = []
    for i, man_piece in enumerate(final_pool):
        part_mesh = _manifold_to_trimesh(man_piece)
        if part_mesh is None or len(part_mesh.faces) < 4:
            continue
        try:
            vol = abs(part_mesh.volume)
        except Exception:
            vol = 0.0
        if vol < 1.0:
            continue
        part_id = str(uuid.uuid4())[:8]
        filename = f"part_auto_{i}.stl"
        part_mesh.export(str(output_dir / filename))
        part_extents = part_mesh.bounding_box.extents
        parts.append(PartDescriptor(
            part_id=part_id, mesh=part_mesh, mesh_path=filename,
            bbox_mm=tuple(part_extents.tolist()),
            volume_mm3=round(vol, 2), side=str(i),
        ))
    return parts


def _subdivide_oversize(man_piece, printer_extents: np.ndarray, out: list, depth: int):
    """Recursively bisect oversized manifold pieces along their longest axis."""
    MAX_DEPTH = 6
    tm = _manifold_to_trimesh(man_piece)
    if tm is None or len(tm.faces) < 4:
        out.append(man_piece)
        return
    extents = tm.bounding_box.extents
    if np.all(extents <= printer_extents) or depth >= MAX_DEPTH:
        out.append(man_piece)
        return

    # Find the axis with the largest overshoot
    overshoot = extents - printer_extents
    axis = int(np.argmax(overshoot))
    mid = (tm.bounds[0][axis] + tm.bounds[1][axis]) / 2.0

    normal = [0.0, 0.0, 0.0]
    normal[axis] = 1.0
    try:
        pos, neg = man_piece.split_by_plane(normal, float(mid))
        _subdivide_oversize(pos, printer_extents, out, depth + 1)
        _subdivide_oversize(neg, printer_extents, out, depth + 1)
    except Exception:
        out.append(man_piece)


def _beam_search(
    vertices: np.ndarray,
    printer_extents: np.ndarray,
    normals: np.ndarray,
    plane_spacing: float,
    beam_width: int,
    max_iterations: int,
) -> _BSPTree:
    """Run BSP beam search on vertex data (lightweight, no mesh ops). Returns best tree."""
    origin_th = 0.1 * np.sqrt(np.sum(printer_extents ** 2))
    angle_th = np.pi / 10

    root = _BSPNode(vertices, printer_extents)
    theta_0 = root.n_parts

    tree = _BSPTree(root=root)
    current_trees = [tree]

    n_leaves = 1
    for iteration in range(max_iterations):
        if all(t.terminated for t in current_trees):
            break

        new_trees = []
        trees_to_remove = []

        for t in current_trees:
            if t.terminated or len(t.leaves) != n_leaves:
                continue
            trees_to_remove.append(t)
            largest = t.largest_part

            candidates_for_normal = []
            for normal in normals:
                planes = _get_candidate_planes(largest.verts, normal, plane_spacing)
                batch = []
                for plane in planes:
                    new_t = _expand_node(t, largest.path, plane, printer_extents)
                    if new_t is not None:
                        batch.append(new_t)

                if batch:
                    _evaluate_objectives(batch, largest.path, printer_extents, theta_0, plane_spacing)
                    candidates_for_normal.extend(batch)

            # Deduplicate
            deduped = []
            for candidate in sorted(candidates_for_normal, key=lambda x: x.objective):
                node = candidate.root
                for idx in largest.path:
                    node = node.children[idx]
                if node.plane is None:
                    continue
                is_unique = True
                for existing in deduped:
                    e_node = existing.root
                    for idx in largest.path:
                        e_node = e_node.children[idx]
                    if e_node.plane and not _planes_are_different(
                        node.plane, e_node.plane, origin_th, angle_th
                    ):
                        is_unique = False
                        break
                if is_unique:
                    deduped.append(candidate)

            new_trees.extend(deduped)

        for t in trees_to_remove:
            current_trees.remove(t)

        n_leaves += 1
        current_trees.extend(new_trees)
        current_trees.sort(key=lambda x: x.objective)
        current_trees = current_trees[:beam_width]

        if not current_trees:
            raise RuntimeError("Auto-split: no valid cuts found")

        best = current_trees[0]
        est_parts = sum(l.n_parts for l in best.leaves)
        logger.info(f"  iter {iteration + 1}: leaves={n_leaves}, "
                    f"best_obj={best.objective:.3f}, est_parts={est_parts:.0f}, "
                    f"trees={len(current_trees)}")

    return current_trees[0]


def run_fdm_auto_split(
    mesh: trimesh.Trimesh,
    build_x: float,
    build_y: float,
    build_z: float,
    output_dir: Path,
    *,
    beam_width: int = 3,
    n_theta: int = 3,
    n_phi: int = 3,
    plane_spacing: float = 0.0,
    max_iterations: int = 20,
) -> AutoSplitResult:
    """
    Auto-split mesh using BSP beam search (Chopper algorithm).

    Two-phase approach for performance:
      Phase 1 (plan): Run beam search on a decimated mesh (≤10K faces)
      Phase 2 (execute): Apply found cut planes to the original full-res mesh

    Args:
        mesh: Input mesh to split
        build_x, build_y, build_z: Build volume dimensions (mm)
        beam_width: Number of best trees to keep per iteration
        n_theta, n_phi: Sphere sampling density for candidate normals
        plane_spacing: Distance between candidate planes (0 = auto)
        max_iterations: Safety limit on BSP tree depth
    """
    _preprocess_mesh(mesh)

    printer_extents = np.array([build_x, build_y, build_z])

    try:
        original_volume = abs(mesh.volume)
    except Exception:
        original_volume = 0.0

    mesh_extents = mesh.bounding_box.extents
    logger.info(f"FDM auto-split: build_vol=({build_x}, {build_y}, {build_z}), "
                f"extents=({mesh_extents[0]:.1f}, {mesh_extents[1]:.1f}, {mesh_extents[2]:.1f}), "
                f"faces={len(mesh.faces)}")

    # Check if mesh already fits
    if np.all(mesh_extents <= printer_extents):
        part_id = str(uuid.uuid4())[:8]
        filename = "part_auto_0.stl"
        mesh.export(str(output_dir / filename))
        parts = [PartDescriptor(
            part_id=part_id, mesh=mesh, mesh_path=filename,
            bbox_mm=tuple(mesh_extents.tolist()),
            volume_mm3=round(original_volume, 2), side="0",
        )]
        logger.info("FDM auto-split: mesh already fits build volume")
        return AutoSplitResult(parts=parts, n_cuts=0, original_volume=original_volume)

    # Auto plane_spacing: ~1/5 of the smallest build dimension
    if plane_spacing <= 0:
        plane_spacing = min(build_x, build_y, build_z) / 5.0

    # Generate candidate normals: uniform sphere + axis-aligned
    normals = _uniform_normals(n_theta, n_phi)
    axis_normals = np.array([[1, 0, 0], [0, 1, 0], [0, 0, 1]], dtype=float)
    normals = np.unique(np.round(np.vstack([normals, axis_normals]), 3), axis=0)
    logger.info(f"  candidate normals: {len(normals)}, plane_spacing: {plane_spacing:.1f}")

    # --- Phase 1: Plan using vertex half-space (no mesh splitting) ---
    # Subsample vertices for fast planning (>20K verts → downsample to 20K)
    verts = np.array(mesh.vertices)
    MAX_PLAN_VERTS = 20_000
    if len(verts) > MAX_PLAN_VERTS:
        indices = np.random.default_rng(42).choice(len(verts), MAX_PLAN_VERTS, replace=False)
        plan_verts = verts[indices]
        logger.info(f"  subsampled {len(verts)} → {MAX_PLAN_VERTS} verts for planning")
    else:
        plan_verts = verts
    best_tree = _beam_search(
        plan_verts, printer_extents, normals,
        plane_spacing, beam_width, max_iterations,
    )
    cut_planes = _collect_cut_planes(best_tree.root)
    n_cuts = len(cut_planes)
    logger.info(f"  planning done: {n_cuts} cut planes found")

    if n_cuts == 0:
        # No cuts needed (shouldn't happen since we checked fits above)
        part_id = str(uuid.uuid4())[:8]
        filename = "part_auto_0.stl"
        mesh.export(str(output_dir / filename))
        parts = [PartDescriptor(
            part_id=part_id, mesh=mesh, mesh_path=filename,
            bbox_mm=tuple(mesh_extents.tolist()),
            volume_mm3=round(original_volume, 2), side="0",
        )]
        return AutoSplitResult(parts=parts, n_cuts=0, original_volume=original_volume)

    # --- Phase 2: Execute cuts on original mesh ---
    logger.info(f"  executing {n_cuts} cuts on original mesh ({len(mesh.faces)} faces)...")
    parts = _execute_cuts_on_original(mesh, cut_planes, output_dir, printer_extents)

    total_vol = sum(p.volume_mm3 for p in parts)
    logger.info(f"FDM auto-split done: {len(parts)} parts, {n_cuts} cuts, "
                f"volume {total_vol:.0f} / {original_volume:.0f}")

    return AutoSplitResult(
        parts=parts,
        n_cuts=n_cuts,
        original_volume=original_volume,
    )


def _all_nodes(root: _BSPNode) -> list[_BSPNode]:
    """Collect all nodes in a BSP tree."""
    result = []
    stack = [root]
    while stack:
        node = stack.pop()
        result.append(node)
        stack.extend(node.children)
    return result
