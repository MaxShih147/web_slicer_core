"""
Consolidated server-side ortho processing pipeline.

Runs the full orthodontic auto-processing pipeline in a single server-side job:
  1. Generate hollow (PrusaSlicer CLI)
  2. Extend bottom vertices
  3. Align hollow to input model
  4. Generate hex grid (raycast against aligned hollow)
  5. Generate drain holes (hex wall edge cylinders)
  6. Generate side wall drains (2D cross-section approach)
  7. Boolean union(hex_grid, drain_holes)
  8. Flip hollow normals -> Boolean intersection(flipped, step7)
  9. Boolean union(side_wall_drains, step8)
 10. Boolean difference(input_model, step9) -> ortho_result.stl

This eliminates 15+ HTTP round-trips and ~43MB of transfer, replacing them
with a single upload (~2MB) and download (~3.7MB).
"""

import json
import logging
import math
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import trimesh

from .jobs import get_job_dir
from .models import BooleanOperation, JobStatus, SLAConfig
from .sla_operations import (
    boolean_operation,
    generate_drain_holes,
    generate_hex_grid,
    generate_hollow,
    load_trimesh,
)

logger = logging.getLogger(__name__)


# =============================================================================
# 2D Geometry Utilities (ported from geoUtils.js)
# =============================================================================

def poly_area_2d(poly: np.ndarray) -> float:
    """
    Compute signed area of a 2D polygon using the Shoelace formula.

    Args:
        poly: Nx2 numpy array of 2D points

    Returns:
        Signed area (positive = CCW, negative = CW)
    """
    n = len(poly)
    if n < 3:
        return 0.0
    x = poly[:, 0]
    y = poly[:, 1]
    return float(np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y) / 2.0)


def point_in_polygon_2d(poly: np.ndarray, px: float, py: float) -> bool:
    """
    Test if a point is inside a 2D polygon using ray casting.

    Args:
        poly: Nx2 numpy array of 2D points
        px, py: Test point coordinates

    Returns:
        True if point is inside
    """
    n = len(poly)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if ((yi > py) != (yj > py)) and (px < (xj - xi) * (py - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def ray_seg_intersect_2d(
    ox: float, oy: float, dx: float, dy: float,
    ax: float, ay: float, bx: float, by: float,
) -> Optional[float]:
    """
    2D ray-segment intersection test.

    Args:
        ox, oy: Ray origin
        dx, dy: Ray direction (not necessarily normalized)
        ax, ay: Segment start
        bx, by: Segment end

    Returns:
        Parameter t along ray, or None if no intersection
    """
    ex = bx - ax
    ey = by - ay
    denom = dx * ey - dy * ex
    if abs(denom) < 1e-12:
        return None
    t = ((ax - ox) * ey - (ay - oy) * ex) / denom
    u = ((ax - ox) * dy - (ay - oy) * dx) / denom
    if 0 <= u <= 1 and t >= 0:
        return t
    return None


# =============================================================================
# Mesh Slicing (ported from drillService.js sliceMeshAtZ_World)
# =============================================================================

def slice_mesh_at_z(mesh: trimesh.Trimesh, z_world: float, eps: float = 1e-3) -> List[np.ndarray]:
    """
    Slice a mesh at a world-space Z plane, returning 2D polyline loops.

    Iterates all triangles, finds edge-plane intersections at Z level,
    chains segments into closed loops via spatial hashing.

    Args:
        mesh: trimesh.Trimesh to slice
        z_world: Z plane in world coordinates
        eps: Endpoint merge tolerance (mm)

    Returns:
        List of Nx2 numpy arrays (closed 2D polyline loops)
    """
    vertices = mesh.vertices
    faces = mesh.faces
    segments = []

    for face in faces:
        v0, v1, v2 = vertices[face[0]], vertices[face[1]], vertices[face[2]]
        pts = []
        for p0, p1 in [(v0, v1), (v1, v2), (v2, v0)]:
            d0 = p0[2] - z_world
            d1 = p1[2] - z_world
            if d0 * d1 < 0:
                t = d0 / (d0 - d1)
                x = p0[0] + t * (p1[0] - p0[0])
                y = p0[1] + t * (p1[1] - p0[1])
                pts.append((x, y))
        if len(pts) == 2:
            segments.append(pts)

    if not segments:
        return []

    # Chain segments into closed loops using spatial hashing
    eps_key = eps * 2

    def key(x, y):
        return (round(x / eps_key), round(y / eps_key))

    adj: Dict[tuple, list] = {}
    for si, seg in enumerate(segments):
        for ei in range(2):
            k = key(seg[ei][0], seg[ei][1])
            adj.setdefault(k, []).append((si, ei))

    used = [False] * len(segments)
    loops = []

    for start_si in range(len(segments)):
        if used[start_si]:
            continue
        used[start_si] = True
        loop_pts = [segments[start_si][0], segments[start_si][1]]
        cur_key = key(loop_pts[-1][0], loop_pts[-1][1])
        start_key = key(loop_pts[0][0], loop_pts[0][1])

        for _ in range(len(segments)):
            neighbors = adj.get(cur_key)
            if not neighbors:
                break
            found = False
            for si, ei in neighbors:
                if used[si]:
                    continue
                used[si] = True
                other_ei = 1 - ei
                loop_pts.append(segments[si][other_ei])
                cur_key = key(segments[si][other_ei][0], segments[si][other_ei][1])
                found = True
                break
            if not found:
                break
            if cur_key == start_key:
                break

        if len(loop_pts) >= 3:
            loops.append(np.array(loop_pts, dtype=np.float64))

    return loops


# =============================================================================
# Side Wall Drains (ported from drillService.js generateSideWallDrains)
# =============================================================================

def generate_side_wall_drains(
    outer_shell: trimesh.Trimesh,
    inner_shell: trimesh.Trimesh,
    drain_radius: float = 1.5,
    hollow_wall_thickness: float = 3.0,
    bottom_z: float = 0.0,
    hex_cell_radius: float = 5.0,
    hex_wall_thickness: float = 1.0,
) -> Optional[trimesh.Trimesh]:
    """
    Generate side-wall drain cylinders using 2D cross-section approach.

    Algorithm:
    1. Slice outer+inner mesh at Z=0 to get 2D contours
    2. Pick largest loop by area
    3. Resample outer polygon at 360 uniform arc-length samples
    4. Bin into 12 angular sectors, evaluate candidates per bin
    5. Score candidates: surface normal -> ray to inner wall -> hex-wall-hit count
    6. Slide-search +/-5 positions for best score
    7. Enforce min spacing (6mm), build 3D cylinders via trimesh

    Args:
        outer_shell: Outer shell mesh (the original model)
        inner_shell: Inner shell mesh (the hollow)
        drain_radius: Cylinder radius (mm)
        hollow_wall_thickness: Shell thickness T (mm)
        bottom_z: Z position of the print bed
        hex_cell_radius: Hex cell radius for wall-hit scoring
        hex_wall_thickness: Hex wall thickness for wall-hit scoring

    Returns:
        trimesh.Trimesh of merged cylinders, or None if no drains placed
    """
    T = hollow_wall_thickness
    max_holes = 12
    min_spacing = 6.0

    def nearest_hex_center_2d(x: float, y: float) -> Tuple[float, float]:
        s = hex_cell_radius + hex_wall_thickness / 2
        c_step = s * math.sqrt(3)
        r_step = s * 1.5
        r = round(y / r_step)
        x0 = x - ((c_step * 0.5) if (r & 1) else 0)
        q = round(x0 / c_step)
        cx = q * c_step + ((c_step * 0.5) if (r & 1) else 0)
        cy = r * r_step
        return cx, cy

    def wall_hit_score(p_out_x, p_out_y, p_in_x, p_in_y, dir_x, dir_y, r):
        inset = 0.8
        step = 0.4
        perp_x = -dir_y
        perp_y = dir_x
        dx = p_in_x - p_out_x
        dy = p_in_y - p_out_y
        full_len = math.sqrt(dx * dx + dy * dy)
        if full_len < inset * 2 + step:
            return 0
        start_t = inset / full_len
        end_t = 1 - inset / full_len
        hits = 0
        frac = start_t
        while frac <= end_t + 1e-9:
            sx = p_out_x + dx * frac
            sy = p_out_y + dy * frac
            for off in [0, 0.8 * r, -0.8 * r]:
                tx = sx + perp_x * off
                ty = sy + perp_y * off
                hcx, hcy = nearest_hex_center_2d(tx, ty)
                ddx = tx - hcx
                ddy = ty - hcy
                if math.sqrt(ddx * ddx + ddy * ddy) >= hex_cell_radius:
                    hits += 1
            frac += step / full_len
        return hits

    z_drain = bottom_z

    # Slice both meshes
    inner_loops = slice_mesh_at_z(inner_shell, z_drain)

    outer_slice_lift = 1.0
    z_outer_slice = z_drain + outer_slice_lift
    outer_loops = slice_mesh_at_z(outer_shell, z_outer_slice)
    if len(outer_loops) == 0:
        z_outer_slice = z_drain + 0.5
        outer_loops = slice_mesh_at_z(outer_shell, z_outer_slice)
    if len(outer_loops) == 0:
        z_outer_slice = z_drain + 2.0
        outer_loops = slice_mesh_at_z(outer_shell, z_outer_slice)

    if len(outer_loops) == 0 or len(inner_loops) == 0:
        logger.warning(
            f"[SideWallDrains] No valid cross-section. "
            f"outerLoops={len(outer_loops)}, innerLoops={len(inner_loops)}"
        )
        return None

    # Pick largest loop by absolute area
    outer_poly = max(outer_loops, key=lambda lp: abs(poly_area_2d(lp)))
    inner_poly = max(inner_loops, key=lambda lp: abs(poly_area_2d(lp)))

    # Resample outer_poly at uniform arc length
    N_SAMPLES = 360
    n_pts = len(outer_poly)
    diffs = np.roll(outer_poly, -1, axis=0) - outer_poly
    seg_lengths = np.linalg.norm(diffs, axis=1)
    total_len = float(seg_lengths.sum())
    if total_len < 1e-9:
        return None

    seg_step = total_len / N_SAMPLES
    cumulative = np.concatenate([[0], np.cumsum(seg_lengths)])

    samples = []
    for s in range(N_SAMPLES):
        target_dist = s * seg_step
        # Find which segment this falls on
        seg_idx = int(np.searchsorted(cumulative[1:], target_dist, side='right'))
        seg_idx = min(seg_idx, n_pts - 1)
        seg_start_dist = cumulative[seg_idx]
        sl = seg_lengths[seg_idx]
        frac = (target_dist - seg_start_dist) / sl if sl > 1e-9 else 0.0
        frac = min(frac, 1.0)
        p = outer_poly[seg_idx] * (1 - frac) + outer_poly[(seg_idx + 1) % n_pts] * frac
        samples.append((p[0], p[1], seg_idx % n_pts))

    # Compute centroid of outer_poly
    cx_cent = float(outer_poly[:, 0].mean())
    cy_cent = float(outer_poly[:, 1].mean())

    # Assign samples to angular bins
    bins: List[Optional[dict]] = [None] * max_holes
    for si, (sx, sy, seg_idx) in enumerate(samples):
        angle = math.atan2(sy - cy_cent, sx - cx_cent)
        bin_idx = int(((angle + math.pi) / (2 * math.pi)) * max_holes) % max_holes
        if bins[bin_idx] is None:
            bins[bin_idx] = {"px": sx, "py": sy, "angle": angle, "seg_idx": seg_idx, "sample_idx": si}

    # Evaluate a sample index for side-wall drain placement
    N = len(samples)
    p_len = len(outer_poly)
    sample_spacing = total_len / N
    delta_idx_per_step = max(1, round(0.3 / sample_spacing))

    def evaluate_sample_idx(idx):
        sx, sy, seg_i = samples[idx]
        p_prev = outer_poly[(seg_i - 1 + p_len) % p_len]
        p_next = outer_poly[(seg_i + 2) % p_len]
        tx = p_next[0] - p_prev[0]
        ty = p_next[1] - p_prev[1]
        t_len = math.sqrt(tx * tx + ty * ty)
        if t_len < 1e-9:
            return None
        nx = -ty / t_len
        ny = tx / t_len
        # Ensure normal points inward
        if not point_in_polygon_2d(outer_poly, sx + nx * 0.1, sy + ny * 0.1):
            nx = -nx
            ny = -ny
        # Ray to inner wall
        best_t = float('inf')
        for i in range(len(inner_poly)):
            j = (i + 1) % len(inner_poly)
            t = ray_seg_intersect_2d(
                sx, sy, nx, ny,
                inner_poly[i][0], inner_poly[i][1],
                inner_poly[j][0], inner_poly[j][1],
            )
            if t is not None and t > 0.01 and t < best_t:
                best_t = t
        if best_t == float('inf'):
            return None
        if best_t < 0.6 * T or best_t > 3.0 * T:
            return None
        pi_x = sx + nx * best_t
        pi_y = sy + ny * best_t
        score = wall_hit_score(sx, sy, pi_x, pi_y, nx, ny, drain_radius)
        return {
            "p_out_x": sx, "p_out_y": sy,
            "p_in_x": pi_x, "p_in_y": pi_y,
            "dir_x": nx, "dir_y": ny,
            "D2": best_t, "score": score,
        }

    cylinders = []
    placed = []
    skip_reasons = {"no_bin": 0, "no_inner_hit": 0, "too_close": 0}

    for b in range(max_holes):
        cand = bins[b]
        if cand is None:
            skip_reasons["no_bin"] += 1
            continue

        orig_result = evaluate_sample_idx(cand["sample_idx"])
        if orig_result is None:
            skip_reasons["no_inner_hit"] += 1
            continue

        # Slide search +/-5 positions
        best = orig_result
        best_abs_step = 0
        for step in range(1, 6):
            for sign in [1, -1]:
                try_idx = (cand["sample_idx"] + sign * step * delta_idx_per_step) % N
                res = evaluate_sample_idx(try_idx)
                if res is None:
                    continue
                if res["score"] < best["score"] or (res["score"] == best["score"] and step < best_abs_step):
                    best = res
                    best_abs_step = step

        p_out_x = best["p_out_x"]
        p_out_y = best["p_out_y"]
        p_in_x = best["p_in_x"]
        p_in_y = best["p_in_y"]
        dir_x = best["dir_x"]
        dir_y = best["dir_y"]
        D2 = best["D2"]

        center_x = (p_out_x + p_in_x) / 2
        center_y = (p_out_y + p_in_y) / 2

        # Spacing check
        too_close = False
        for prev_cx, prev_cy in placed:
            ddx = center_x - prev_cx
            ddy = center_y - prev_cy
            if math.sqrt(ddx * ddx + ddy * ddy) < min_spacing:
                too_close = True
                break
        if too_close:
            skip_reasons["too_close"] += 1
            continue

        # Build 3D cylinder
        L = D2 + 0.3 + 0.4
        cyl = trimesh.creation.cylinder(
            radius=drain_radius,
            height=L,
            sections=32,
        )
        angle = math.atan2(dir_y, dir_x)
        ry = trimesh.transformations.rotation_matrix(np.pi / 2, [0, 1, 0])
        rz = trimesh.transformations.rotation_matrix(angle, [0, 0, 1])
        transform = rz @ ry
        transform[:3, 3] = [center_x, center_y, z_drain]
        cyl.apply_transform(transform)
        cylinders.append(cyl)
        placed.append((center_x, center_y))

    logger.info(
        f"[SideWallDrains] Placed {len(placed)} cylinders. "
        f"Skipped: no_bin={skip_reasons['no_bin']}, "
        f"no_inner_hit={skip_reasons['no_inner_hit']}, "
        f"too_close={skip_reasons['too_close']}"
    )

    if not cylinders:
        return None

    return trimesh.util.concatenate(cylinders)


# =============================================================================
# Mesh Helpers
# =============================================================================

def flip_mesh_faces(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    """
    Flip all face normals by inverting the mesh.
    Equivalent to JS flipSTLFaces().
    """
    mesh.invert()
    return mesh


def extend_bottom_vertices(
    mesh: trimesh.Trimesh,
    threshold: float = 0.5,
    distance: float = 10.0,
) -> int:
    """
    Extend bottom vertices of a mesh downward.

    Vertices within `threshold` mm of the mesh min Z are moved down by `distance` mm.

    Args:
        mesh: Mesh to modify in-place
        threshold: Z threshold above mesh min to select vertices (mm)
        distance: Distance to extend vertices downward (mm)

    Returns:
        Number of vertices moved
    """
    verts = mesh.vertices
    min_z = float(verts[:, 2].min())
    z_cutoff = min_z + threshold

    mask = verts[:, 2] <= z_cutoff
    count = int(mask.sum())
    verts[mask, 2] -= distance
    mesh.vertices = verts
    return count


# =============================================================================
# Pipeline Orchestrator
# =============================================================================

def _update_progress(job_id: str, step: int, total_steps: int, description: str, status_data: dict):
    """Update job status.json with ortho pipeline progress."""
    status_data["status"] = "processing"
    status_data["ortho_progress"] = {
        "step": step,
        "total_steps": total_steps,
        "description": description,
    }
    status_file = get_job_dir(job_id) / "status.json"
    with open(status_file, "w") as f:
        json.dump(status_data, f)


async def run_ortho_pipeline(
    job_id: str,
    hollowing_min_thickness: float = 3.0,
    hollowing_quality: float = 0.5,
    hollowing_closing_distance: float = 2.0,
    bottom_z_threshold: float = 0.5,
    extension_distance: float = 10.0,
    hex_cell_radius: float = 5.0,
    hex_wall_thickness: float = 1.0,
    hex_grid_count: int = 10,
    hex_pyramid_height: float = 3.0,
    drain_hole_radius: float = 1.5,
):
    """
    Run the full ortho auto-processing pipeline server-side.

    This is the main orchestrator that replaces 15+ frontend HTTP round-trips
    with a single background task.

    Args:
        job_id: Job ID (directory must exist with input/model.stl)
        hollowing_*: PrusaSlicer hollow parameters
        bottom_z_threshold: Z threshold for bottom vertex selection (mm)
        extension_distance: Distance to extend bottom vertices (mm)
        hex_*: Hex grid parameters
        drain_hole_radius: Drain hole cylinder radius (mm)
    """
    import asyncio

    job_dir = get_job_dir(job_id)
    input_path = job_dir / "input" / "model.stl"
    output_dir = job_dir / "output"
    output_dir.mkdir(exist_ok=True)

    total_steps = 10
    status_data: dict = {}

    try:
        # ===== Step 1: Generate hollow =====
        _update_progress(job_id, 1, total_steps, "Generating hollow mesh...", status_data)
        logger.info(f"[ortho_pipeline:{job_id}] Step 1: Generating hollow")

        config = SLAConfig(
            hollowing_enable=True,
            hollowing_min_thickness=hollowing_min_thickness,
            hollowing_quality=hollowing_quality,
            hollowing_closing_distance=hollowing_closing_distance,
        )
        result = await generate_hollow(job_dir, config, input_file=input_path)
        if not result.success:
            raise RuntimeError(f"Step 1: Hollow generation failed: {result.error}")

        hollow_mesh = load_trimesh(result.hollow_mesh_path)

        # ===== Step 2: Extend bottom vertices =====
        _update_progress(job_id, 2, total_steps, "Extending bottom vertices...", status_data)
        logger.info(f"[ortho_pipeline:{job_id}] Step 2: Extending bottom vertices")

        moved = extend_bottom_vertices(hollow_mesh, threshold=bottom_z_threshold, distance=extension_distance)
        logger.info(f"  Extended {moved} vertices by {extension_distance}mm")

        # ===== Step 3: Align hollow to input =====
        _update_progress(job_id, 3, total_steps, "Aligning hollow to input model...", status_data)
        logger.info(f"[ortho_pipeline:{job_id}] Step 3: Aligning hollow")

        input_mesh = load_trimesh(input_path)
        input_center = (input_mesh.bounds[0] + input_mesh.bounds[1]) / 2
        hollow_mesh.apply_translation(input_center)

        # Save aligned hollow for potential debug/reuse
        hollow_aligned_path = output_dir / "model_hollow_aligned.stl"
        hollow_mesh.export(str(hollow_aligned_path))

        # Get bounding box for bottom_z
        bottom_z = float(input_mesh.bounds[0][2])

        # ===== Step 4: Generate hex grid =====
        _update_progress(job_id, 4, total_steps, "Generating hex grid...", status_data)
        logger.info(f"[ortho_pipeline:{job_id}] Step 4: Generating hex grid")

        hex_mesh = generate_hex_grid(
            radius=hex_cell_radius,
            fallback_height=20.0,
            pyramid_height=hex_pyramid_height,
            wall_thickness=hex_wall_thickness,
            grid_count=hex_grid_count,
            bottom_z=bottom_z,
            hollow_mesh=hollow_mesh,
        )
        if hex_mesh is None:
            raise RuntimeError("Step 4: Hex grid generation failed - no cells built")

        hex_path = output_dir / "model_hex_grid.stl"
        hex_mesh.export(str(hex_path))

        # ===== Step 5: Generate drain holes =====
        _update_progress(job_id, 5, total_steps, "Generating drain holes...", status_data)
        logger.info(f"[ortho_pipeline:{job_id}] Step 5: Generating drain holes")

        drain_mesh = generate_drain_holes(
            hex_cell_radius=hex_cell_radius,
            wall_thickness=hex_wall_thickness,
            grid_count=hex_grid_count,
            drain_radius=drain_hole_radius,
            bottom_z=bottom_z,
        )

        drain_path = None
        if drain_mesh is not None:
            drain_path = output_dir / "model_drain_holes.stl"
            drain_mesh.export(str(drain_path))

        # ===== Step 6: Generate side wall drains =====
        _update_progress(job_id, 6, total_steps, "Generating side wall drains...", status_data)
        logger.info(f"[ortho_pipeline:{job_id}] Step 6: Generating side wall drains")

        side_wall_mesh = generate_side_wall_drains(
            outer_shell=input_mesh,
            inner_shell=hollow_mesh,
            drain_radius=drain_hole_radius,
            hollow_wall_thickness=hollowing_min_thickness,
            bottom_z=0,
            hex_cell_radius=hex_cell_radius,
            hex_wall_thickness=hex_wall_thickness,
        )

        if side_wall_mesh is not None:
            side_wall_path = output_dir / "model_side_wall_drains.stl"
            side_wall_mesh.export(str(side_wall_path))

        # ===== Step 7: Boolean union(hex_grid, drain_holes) =====
        _update_progress(job_id, 7, total_steps, "Boolean union: hex grid + drain holes...", status_data)
        logger.info(f"[ortho_pipeline:{job_id}] Step 7: Boolean union(hex, drain)")

        if drain_mesh is not None:
            step7_path = output_dir / "step7_hex_drain_union.stl"
            ok, err = boolean_operation(hex_path, drain_path, BooleanOperation.UNION, step7_path)
            if not ok:
                raise RuntimeError(f"Step 7: Boolean union failed: {err}")
            step7_mesh_path = step7_path
        else:
            step7_mesh_path = hex_path

        # ===== Step 8: Flip hollow -> Boolean intersection =====
        _update_progress(job_id, 8, total_steps, "Boolean intersection with flipped hollow...", status_data)
        logger.info(f"[ortho_pipeline:{job_id}] Step 8: Flip hollow + intersection")

        # Create flipped hollow
        flipped_hollow = hollow_mesh.copy()
        flip_mesh_faces(flipped_hollow)
        flipped_hollow_path = output_dir / "step8_flipped_hollow.stl"
        flipped_hollow.export(str(flipped_hollow_path))

        step8_path = output_dir / "step8_intersection.stl"
        ok, err = boolean_operation(
            flipped_hollow_path, step7_mesh_path,
            BooleanOperation.INTERSECTION, step8_path,
        )
        if not ok:
            raise RuntimeError(f"Step 8: Boolean intersection failed: {err}")

        # ===== Step 9: Boolean union(side_wall_drains, step8) =====
        _update_progress(job_id, 9, total_steps, "Boolean union: side wall drains...", status_data)
        logger.info(f"[ortho_pipeline:{job_id}] Step 9: Union side wall drains")

        if side_wall_mesh is not None:
            side_wall_export_path = output_dir / "model_side_wall_drains.stl"
            step9_path = output_dir / "step9_wall_drain_union.stl"
            ok, err = boolean_operation(
                side_wall_export_path, step8_path,
                BooleanOperation.UNION, step9_path,
            )
            if not ok:
                raise RuntimeError(f"Step 9: Boolean union failed: {err}")
            step9_mesh_path = step9_path
        else:
            step9_mesh_path = step8_path

        # ===== Step 10: Boolean difference(input_model, step9) =====
        _update_progress(job_id, 10, total_steps, "Computing final difference...", status_data)
        logger.info(f"[ortho_pipeline:{job_id}] Step 10: Final boolean difference")

        ortho_result_path = output_dir / "ortho_result.stl"
        ok, err = boolean_operation(
            input_path, step9_mesh_path,
            BooleanOperation.DIFFERENCE, ortho_result_path,
        )
        if not ok:
            raise RuntimeError(f"Step 10: Boolean difference failed: {err}")

        # ===== Done =====
        logger.info(f"[ortho_pipeline:{job_id}] Pipeline completed successfully")

        status_data["status"] = "completed"
        status_data["ortho_progress"] = {
            "step": total_steps,
            "total_steps": total_steps,
            "description": "Complete",
        }
        status_data["has_ortho_result"] = True
        status_file = get_job_dir(job_id) / "status.json"
        with open(status_file, "w") as f:
            json.dump(status_data, f)

    except Exception as e:
        logger.exception(f"[ortho_pipeline:{job_id}] Pipeline failed")
        status_data["status"] = "failed"
        status_data["error"] = str(e)
        status_file = get_job_dir(job_id) / "status.json"
        with open(status_file, "w") as f:
            json.dump(status_data, f)
