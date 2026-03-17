"""
FDM Split — Plane cut, grid cut & SDF-guided auto split.

Auto split uses a 3-phase pipeline:
  Phase 1: SDF (Shape Diameter Function) pre-computation — per-vertex thickness
  Phase 2: Candidate plane generation — SDF bottleneck clusters + cross-section sweep + uniform fallback
  Phase 3: Iterative greedy split — pick best plane each round until all parts fit build volume
"""

from __future__ import annotations

import logging
import math
import time
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
class CandidatePlane:
    normal: np.ndarray  # unit normal (3,)
    offset: float  # signed distance from origin along normal
    score: float  # lower = better cut location
    source: str  # "sdf" | "cross_section" | "uniform"


@dataclass
class AutoSplitResult:
    parts: list[PartDescriptor]
    n_cuts: int
    planes_used: list[dict]  # [{normal, offset, score, source}, ...]
    original_volume: float


# ============================================================================
# Phase 1: SDF Pre-computation
# ============================================================================

def _compute_vertex_normals(vertices: np.ndarray, faces: np.ndarray) -> np.ndarray:
    """Compute vertex normals via face-normal averaging (pure numpy, no scipy)."""
    v0, v1, v2 = vertices[faces[:, 0]], vertices[faces[:, 1]], vertices[faces[:, 2]]
    fn = np.cross(v1 - v0, v2 - v0)
    fn /= np.maximum(np.linalg.norm(fn, axis=1, keepdims=True), 1e-10)
    vn = np.zeros_like(vertices)
    for i in range(3):
        np.add.at(vn, faces[:, i], fn)
    vn /= np.maximum(np.linalg.norm(vn, axis=1, keepdims=True), 1e-10)
    return vn


def _spatial_subsample(
    vertices: np.ndarray,
    n_samples: int,
    seed: int = 42,
) -> np.ndarray:
    """
    Subsample vertex indices with uniform SPATIAL coverage using 3D grid binning.

    Random vertex sampling is biased toward dense-mesh regions (hair, clothing,
    fine details). This gives uniform coverage in 3D space, so thick regions
    (torso) and thin regions (arms) get proportional representation.
    """
    rng = np.random.RandomState(seed)
    n_verts = len(vertices)

    if n_verts <= n_samples:
        return np.arange(n_verts)

    bmin = vertices.min(axis=0)
    bmax = vertices.max(axis=0)
    extents = bmax - bmin

    # Grid resolution: approximate n_samples cells
    vol = max(np.prod(extents), 1e-6)
    cell_size = max((vol / n_samples) ** (1.0 / 3.0), 1e-6)

    # Grid coordinates for each vertex
    grid_coords = np.floor((vertices - bmin) / cell_size).astype(np.int32)

    # Unique cell keys → pick one random vertex per cell
    # Use structured array for fast unique operation
    keys = grid_coords[:, 0] * 100000 + grid_coords[:, 1] * 1000 + grid_coords[:, 2]

    # Shuffle indices so the "first per cell" is random
    shuffled = rng.permutation(n_verts)
    _, first_indices = np.unique(keys[shuffled], return_index=True)
    selected = shuffled[first_indices]

    # If too few cells were populated, add random extras
    if len(selected) < n_samples:
        remaining = np.setdiff1d(np.arange(n_verts), selected)
        if len(remaining) > 0:
            extra = rng.choice(
                remaining,
                min(n_samples - len(selected), len(remaining)),
                replace=False,
            )
            selected = np.concatenate([selected, extra])

    # If too many, subsample the grid-sampled set
    if len(selected) > n_samples:
        selected = rng.choice(selected, n_samples, replace=False)

    return selected


def compute_vertex_sdf(
    mesh: trimesh.Trimesh,
    n_query: int = 1500,
    n_target: int = 5000,
) -> tuple[trimesh.Trimesh, np.ndarray]:
    """
    Compute per-vertex SDF (local thickness) via vectorized opposite-vertex search.

    Uses SPATIAL subsampling (not random) to avoid bias toward dense-mesh regions
    (hair, clothing). Each spatial grid cell contributes at most one sample,
    giving uniform 3D coverage.

    Returns (planning_mesh, sdf_array) where sdf_array[i] = thickness at vertex i.
    planning_mesh = input mesh (unchanged), sdf has n_query entries.
    """
    t0 = time.time()

    vertices = np.array(mesh.vertices, dtype=np.float64)
    faces = np.array(mesh.faces, dtype=np.int32)
    n_verts = len(vertices)

    # Compute vertex normals (pure numpy)
    vn = _compute_vertex_normals(vertices, faces)

    # Spatially uniform subsampling (avoids hair/clothing density bias)
    n_q = min(n_query, n_verts)
    n_t = min(n_target, n_verts)
    q_idx = _spatial_subsample(vertices, n_q, seed=42)
    t_idx = _spatial_subsample(vertices, n_t, seed=137)

    qv = vertices[q_idx]  # (n_q, 3)
    qn = vn[q_idx]        # (n_q, 3)
    tv = vertices[t_idx]  # (n_t, 3)
    tn = vn[t_idx]        # (n_t, 3)

    # Vectorized pairwise opposite-vertex search
    # diff[i,j] = tv[j] - qv[i], shape (n_q, n_t, 3)
    diff = tv[np.newaxis, :, :] - qv[:, np.newaxis, :]
    dist = np.linalg.norm(diff, axis=2)  # (n_q, n_t)

    # Target must be in -normal direction: dot(diff, -qn) > 0
    proj = np.einsum('ijk,ik->ij', diff, -qn)  # (n_q, n_t)

    # Target must have opposing normal: dot(tn, qn) < -0.3
    normal_dot = np.einsum('jk,ik->ij', tn, qn)  # (n_q, n_t)

    valid = (proj > 0.5) & (normal_dot < -0.3)
    dist_masked = np.where(valid, dist, np.inf)

    sdf = np.min(dist_masked, axis=1)  # (n_q,)
    sdf[sdf == np.inf] = np.nan

    # Fill NaN with median
    nan_mask = np.isnan(sdf)
    miss_count = np.sum(nan_mask)
    if miss_count > 0 and miss_count < n_q:
        sdf[nan_mask] = np.nanmedian(sdf)
    elif miss_count == n_q:
        sdf[:] = 1.0

    # Build a lightweight planning_mesh with only the query vertices + their positions
    planning_mesh = trimesh.Trimesh(
        vertices=vertices[q_idx],
        faces=np.zeros((0, 3), dtype=int),
        process=False,
    )

    dt = time.time() - t0
    logger.info(f"SDF computed: {n_q} samples from {n_verts} verts, "
                f"min={np.min(sdf):.2f} max={np.max(sdf):.2f} "
                f"median={np.median(sdf):.2f}, miss={miss_count}, in {dt:.3f}s")

    return planning_mesh, sdf


# ============================================================================
# Phase 2: Candidate Plane Generation
# ============================================================================

def generate_candidate_planes(
    planning_mesh: trimesh.Trimesh,
    sdf: np.ndarray,
    build_volume: tuple[float, float, float],
    original_mesh: trimesh.Trimesh | None = None,
) -> list[CandidatePlane]:
    """
    Generate candidate cut planes from 3 sources:
      A) SDF bottleneck clusters
      B) Cross-section area sweep
      C) Axis-uniform fallback
    Returns up to 20 planes sorted by score (lower = better).
    """
    t0 = time.time()
    candidates: list[CandidatePlane] = []

    # SDF vertices (subsampled)
    sdf_vertices = np.array(planning_mesh.vertices)

    # Use original mesh vertices for bounds and cross-section sweep
    if original_mesh is not None:
        all_vertices = np.array(original_mesh.vertices)
    else:
        all_vertices = sdf_vertices

    bmin = all_vertices.min(axis=0)
    bmax = all_vertices.max(axis=0)
    extents = bmax - bmin
    max_extent = np.max(extents)

    # --- 2A: SDF Bottleneck Clusters ---
    sdf_candidates = _sdf_bottleneck_clusters(sdf_vertices, sdf, extents, max_extent)
    candidates.extend(sdf_candidates)

    # --- 2B: Cross-Section Area Sweep ---
    cs_candidates = _cross_section_sweep(all_vertices, bmin, bmax, extents)
    candidates.extend(cs_candidates)

    # --- 2C: Axis-Uniform Fallback ---
    uni_candidates = _axis_uniform_planes(bmin, extents)
    candidates.extend(uni_candidates)

    # --- Dedup: merge planes within 10% of extent or 10mm, whichever is larger ---
    dedup_dist = max(10.0, max_extent * 0.10)
    candidates = _dedup_planes(candidates, dist_thresh=dedup_dist, angle_thresh=15.0)

    # Sort by score (lower = better)
    candidates.sort(key=lambda c: c.score)

    # Keep top 20
    candidates = candidates[:20]

    dt = time.time() - t0
    sources = {}
    for c in candidates:
        sources[c.source] = sources.get(c.source, 0) + 1
    logger.info(f"Candidate planes: {len(candidates)} total, "
                f"sources={sources}, in {dt:.3f}s")
    for i, c in enumerate(candidates[:5]):
        logger.info(f"  #{i}: score={c.score:.3f} source={c.source} "
                     f"normal=[{c.normal[0]:.2f},{c.normal[1]:.2f},{c.normal[2]:.2f}] "
                     f"offset={c.offset:.1f}")

    return candidates


def _sdf_bottleneck_clusters(
    vertices: np.ndarray,
    sdf: np.ndarray,
    extents: np.ndarray,
    max_extent: float,
) -> list[CandidatePlane]:
    """
    Find axis-aligned cut planes via SDF sweep with hair/clothing filtering.

    Strategy: sweep along X/Y/Z axes, compute SDF profile (excluding
    extremely thin vertices like hair), find local minima = joint positions.
    Use AXIS-ALIGNED normals (reliable) and let decompose() separate
    natural connected components after cutting.

    For a standing human figure:
    - Z sweep finds waist, neck, ankles (horizontal narrowings)
    - X sweep finds midline and shoulder connections
    - Y sweep finds front-back narrowings
    """
    n = len(vertices)
    if n < 30:
        return []

    # Filter out hair/clothing vertices (extremely thin)
    hair_threshold = max(1.5, np.percentile(sdf, 20))
    valid_mask = sdf >= hair_threshold
    valid_verts = vertices[valid_mask]
    valid_sdf = sdf[valid_mask]

    if len(valid_verts) < 20:
        return []

    bmin = valid_verts.min(axis=0)
    bmax = valid_verts.max(axis=0)

    sdf_max = valid_sdf.max()
    if sdf_max < 1e-6:
        sdf_max = 1.0

    n_bins = 25
    planes = []

    for axis_idx in range(3):
        axis_extent = bmax[axis_idx] - bmin[axis_idx]
        if axis_extent < 1.0:
            continue

        lo = bmin[axis_idx]
        hi = bmax[axis_idx]
        edges = np.linspace(lo, hi, n_bins + 1)
        centers = (edges[:-1] + edges[1:]) / 2.0
        slab_half = axis_extent / n_bins / 2.0

        # Two profiles:
        # 1. avg_sdf: average local thickness per slab (lower = narrower)
        # 2. count: vertex count per slab (lower = less material)
        avg_sdf_profile = np.full(n_bins, np.nan)
        count_profile = np.zeros(n_bins)

        for b in range(n_bins):
            mask = np.abs(valid_verts[:, axis_idx] - centers[b]) < slab_half * 1.5
            count = np.sum(mask)
            count_profile[b] = count
            if count < 3:
                continue
            avg_sdf_profile[b] = np.mean(valid_sdf[mask])

        valid_bins = ~np.isnan(avg_sdf_profile)
        if np.sum(valid_bins) < 5:
            continue
        median_sdf = np.nanmedian(avg_sdf_profile)
        avg_sdf_profile[~valid_bins] = median_sdf

        # Normalize count profile
        max_count = count_profile.max()
        if max_count > 0:
            count_norm = count_profile / max_count
        else:
            count_norm = np.ones(n_bins)

        # Combined weakness score: low SDF + low count = good cut location
        # Normalize SDF profile
        sdf_norm = avg_sdf_profile / np.max(avg_sdf_profile)
        weakness = 0.6 * sdf_norm + 0.4 * count_norm

        # Find local minima: weakness[i] < 0.80 * local average
        for i in range(2, n_bins - 2):
            neighbors = weakness[max(0, i - 2):i + 3]
            neighbor_avg = np.mean(neighbors)
            if neighbor_avg > 0 and weakness[i] < 0.80 * neighbor_avg:
                normal = np.zeros(3)
                normal[axis_idx] = 1.0

                score = weakness[i] * 0.4  # lower = better

                planes.append(CandidatePlane(
                    normal=normal,
                    offset=centers[i],
                    score=score,
                    source="sdf",
                ))

    logger.info(f"SDF sweep (hair-filtered): hair_thresh={hair_threshold:.1f}, "
                f"valid_verts={len(valid_verts)}, planes={len(planes)}")

    return planes


def _cross_section_sweep(
    vertices: np.ndarray,
    bmin: np.ndarray,
    bmax: np.ndarray,
    extents: np.ndarray,
) -> list[CandidatePlane]:
    """Sweep axis-aligned planes and find cross-section area local minima."""
    planes = []
    n_slices = 20

    for axis_idx in range(3):
        if extents[axis_idx] < 1.0:
            continue

        normal = np.zeros(3)
        normal[axis_idx] = 1.0

        # Sample positions (10%..90% of extent)
        positions = np.linspace(
            bmin[axis_idx] + extents[axis_idx] * 0.1,
            bmin[axis_idx] + extents[axis_idx] * 0.9,
            n_slices,
        )

        # Estimate cross-section area using vertex density in thin slabs
        slab_thickness = extents[axis_idx] / n_slices * 0.5
        areas = []
        for pos in positions:
            # Count vertices within slab
            mask = np.abs(vertices[:, axis_idx] - pos) < slab_thickness
            count = np.sum(mask)
            if count < 2:
                areas.append(0.0)
                continue
            # Approximate area from vertex spread in the other two axes
            other_axes = [a for a in range(3) if a != axis_idx]
            slab_verts = vertices[mask]
            spread = slab_verts[:, other_axes].max(axis=0) - slab_verts[:, other_axes].min(axis=0)
            area = spread[0] * spread[1]  # rough bbox area of cross section
            areas.append(area)

        areas = np.array(areas)
        if np.max(areas) < 1e-6:
            continue

        # Find local minima: area[i] < 0.85 * avg(neighbors)
        for i in range(2, len(areas) - 2):
            neighbor_avg = np.mean(areas[max(0, i - 2):i + 3])
            if neighbor_avg > 0 and areas[i] < 0.85 * neighbor_avg:
                # Normalize score: area / max_area
                score = areas[i] / np.max(areas) if np.max(areas) > 0 else 0.5
                planes.append(CandidatePlane(
                    normal=normal.copy(),
                    offset=positions[i],
                    score=score * 0.7,  # cross-section gets moderate priority
                    source="cross_section",
                ))

    return planes


def _axis_uniform_planes(
    bmin: np.ndarray,
    extents: np.ndarray,
) -> list[CandidatePlane]:
    """Generate uniform fallback planes at 20/40/60/80% along each axis."""
    planes = []
    for axis_idx in range(3):
        if extents[axis_idx] < 1.0:
            continue
        normal = np.zeros(3)
        normal[axis_idx] = 1.0
        for frac in [0.2, 0.4, 0.6, 0.8]:
            offset = bmin[axis_idx] + extents[axis_idx] * frac
            planes.append(CandidatePlane(
                normal=normal.copy(),
                offset=offset,
                score=1.0,  # neutral priority
                source="uniform",
            ))
    return planes


def _dedup_planes(
    planes: list[CandidatePlane],
    dist_thresh: float = 5.0,
    angle_thresh: float = 15.0,
) -> list[CandidatePlane]:
    """Remove near-duplicate planes. Keep the one with lower score."""
    if not planes:
        return []

    cos_thresh = math.cos(math.radians(angle_thresh))
    kept = []

    for plane in planes:
        is_dup = False
        for existing in kept:
            # Angle between normals
            cos_angle = abs(np.dot(plane.normal, existing.normal))
            if cos_angle < cos_thresh:
                continue  # different orientation, not a dup

            # Distance between planes (projected offset difference)
            # For same-direction normals, compare offsets directly
            if cos_angle > 0.99:
                dist = abs(plane.offset - existing.offset)
            else:
                dist = abs(plane.offset - existing.offset) / max(cos_angle, 0.01)

            if dist < dist_thresh:
                is_dup = True
                # Keep better score
                if plane.score < existing.score:
                    existing.normal = plane.normal
                    existing.offset = plane.offset
                    existing.score = plane.score
                    existing.source = plane.source
                break

        if not is_dup:
            kept.append(plane)

    return kept


# ============================================================================
# Phase 3: Iterative Greedy Split
# ============================================================================

def _part_exceeds_build_volume(
    mesh: trimesh.Trimesh,
    build_x: float,
    build_y: float,
    build_z: float,
) -> bool:
    """Check if mesh exceeds build volume in any orientation (try 3 axis rotations)."""
    ext = mesh.bounding_box.extents
    dims = sorted(ext)  # ascending
    build = sorted([build_x, build_y, build_z])

    # Best case: smallest dim fits smallest build, etc.
    return any(dims[i] > build[i] for i in range(3))


def _plane_intersects_bbox(plane: CandidatePlane, bmin: np.ndarray, bmax: np.ndarray) -> bool:
    """Check if a plane intersects a bounding box (with 5% margin)."""
    corners_proj = []
    for x in [bmin[0], bmax[0]]:
        for y in [bmin[1], bmax[1]]:
            for z in [bmin[2], bmax[2]]:
                corners_proj.append(np.dot(plane.normal, [x, y, z]))
    proj_min = min(corners_proj)
    proj_max = max(corners_proj)
    margin = (proj_max - proj_min) * 0.05
    return proj_min + margin < plane.offset < proj_max - margin


def _find_part_for_plane(pool, plane: CandidatePlane) -> int:
    """Find which part in the pool this plane best intersects. Returns index or -1."""
    best_idx = -1
    best_vol = 0.0
    for i, (man, tm) in enumerate(pool):
        bmin, bmax = tm.bounds
        if _plane_intersects_bbox(plane, bmin, bmax):
            try:
                vol = abs(tm.volume)
            except Exception:
                vol = 0.0
            if vol > best_vol:
                best_vol = vol
                best_idx = i
    return best_idx


def _split_manifold_by_plane(man, normal: np.ndarray, offset: float):
    """
    Split a manifold3d object by a plane using native split_by_plane().
    Returns (pos_manifold, neg_manifold) or (None, None) on failure.

    pos = side in direction of normal, neg = opposite side.
    """
    try:
        pos_man, neg_man = man.split_by_plane(normal.tolist(), float(offset))
    except Exception:
        return None, None

    # Validate both halves have geometry
    try:
        if pos_man.num_tri() < 4 or neg_man.num_tri() < 4:
            return None, None
    except Exception:
        return None, None

    return pos_man, neg_man


def _manifold_extents(man):
    """Get (dx, dy, dz) extents from a manifold3d object (no trimesh conversion)."""
    bb = man.bounding_box()  # (minx, miny, minz, maxx, maxy, maxz)
    return (bb[3] - bb[0], bb[4] - bb[1], bb[5] - bb[2])


def _sweep_best_cut(target_man, target_vol, min_frag_vol, n_positions=8):
    """
    Sweep axis-aligned planes through a manifold and find the best cut.

    For each of 3 axes × n_positions, splits the manifold via split_by_plane,
    decomposes into connected components, and scores by balance + significance.

    This is robust to hair/clothing because manifold3d split + decompose
    directly measures what matters: which connected pieces result from a cut.
    Hair attached to the head stays with the head after a neck cut.

    Returns (score, axis_idx, position, [(manifold, vol), ...]) or None.
    Score: lower = better.
    """
    bb = target_man.bounding_box()
    best = None

    for axis_idx in range(3):
        lo = bb[axis_idx]
        hi = bb[axis_idx + 3]
        extent = hi - lo
        if extent < 2.0:
            continue

        margin = extent * 0.12
        positions = np.linspace(lo + margin, hi - margin, n_positions)

        normal = np.zeros(3)
        normal[axis_idx] = 1.0

        for pos in positions:
            pos_man, neg_man = _split_manifold_by_plane(target_man, normal, pos)
            if pos_man is None:
                continue

            # Decompose both halves into connected components
            components = []
            for half in (pos_man, neg_man):
                try:
                    decomposed = half.decompose()
                except Exception:
                    decomposed = [half]
                for comp in decomposed:
                    try:
                        vol = abs(comp.volume())
                    except Exception:
                        vol = 0.0
                    if vol >= min_frag_vol and comp.num_tri() >= 4:
                        components.append((comp, vol))

            if len(components) < 2:
                continue

            total = sum(v for _, v in components)
            if total < 1.0:
                continue

            vols = sorted([v for _, v in components], reverse=True)
            largest_frac = vols[0] / total

            n_significant = sum(1 for v in vols if v >= 0.05 * target_vol)
            n_tiny = sum(1 for v in vols if v < 0.02 * target_vol)

            # Lower = better: minimize largest fraction, bonus for more parts
            score = largest_frac - 0.06 * min(n_significant - 1, 3) + 0.04 * n_tiny

            if best is None or score < best[0]:
                best = (score, axis_idx, pos, components)

    return best


def run_fdm_auto_split(
    mesh: trimesh.Trimesh,
    build_x: float,
    build_y: float,
    build_z: float,
    output_dir: Path,
    max_parts: int = 8,
) -> AutoSplitResult:
    """
    Auto split via direct manifold3d plane sweep.

    Instead of predicting bottlenecks via SDF (noisy on models with hair/clothing),
    directly tests cuts at multiple positions along each axis, decomposes results,
    and picks the cut that creates the most balanced components.

    Algorithm:
      1. For the largest component in the pool, sweep N positions × 3 axes
      2. At each position: split_by_plane → decompose → measure component volumes
      3. Score: minimize(largest_component_fraction) + bonus(n_significant) - penalty(fragments)
      4. Apply the best cut, add decomposed components to pool
      5. Repeat until max_parts reached or no useful cut found
    """
    import manifold3d

    t_total = time.time()
    _preprocess_mesh(mesh)

    try:
        original_volume = abs(mesh.volume)
    except Exception:
        original_volume = 0.0

    build_volume = (build_x, build_y, build_z)
    logger.info(f"FDM auto split: build_vol={build_volume}, "
                f"faces={len(mesh.faces)}, vol={original_volume:.0f}")

    man_original = _trimesh_to_manifold(mesh)
    pool = [(man_original, mesh)]
    planes_used = []
    original_vol = max(original_volume, 1.0)

    n_positions = 8

    for cut_round in range(max_parts - 1):
        if len(pool) >= max_parts:
            break

        # Rank pool by volume descending, skip tiny components
        vol_ranked = []
        for i, (man, tm) in enumerate(pool):
            try:
                vol = abs(tm.volume)
            except Exception:
                vol = 0.0
            if vol / original_vol > 0.05 and len(tm.faces) >= 100:
                vol_ranked.append((i, vol, man))
        vol_ranked.sort(key=lambda x: -x[1])

        if not vol_ranked:
            break

        # Try the largest, then 2nd largest
        cut_made = False
        for target_idx, target_vol, target_man in vol_ranked[:2]:
            t_sweep = time.time()
            best = _sweep_best_cut(
                target_man, target_vol,
                min_frag_vol=original_vol * 0.01,
                n_positions=n_positions,
            )
            dt_sweep = time.time() - t_sweep

            if best is None:
                continue

            score, axis_idx, position, components = best

            # Reject if cut is almost useless (> 95% in one piece)
            total_comp_vol = sum(v for _, v in components)
            largest_frac = max(v for _, v in components) / total_comp_vol
            if largest_frac > 0.95:
                logger.info(f"  Round {cut_round+1}: skip (largest={largest_frac:.1%})")
                continue

            # Apply: remove target, add components
            new_pool = [(m, t) for j, (m, t) in enumerate(pool) if j != target_idx]
            for comp_man, comp_vol in components:
                comp_tm = _manifold_to_trimesh(comp_man)
                if comp_tm is not None:
                    new_pool.append((comp_man, comp_tm))
            pool = new_pool

            axis_name = ['x', 'y', 'z'][axis_idx]
            normal = [0.0, 0.0, 0.0]
            normal[axis_idx] = 1.0
            planes_used.append({
                "normal": normal,
                "offset": float(position),
                "score": round(score, 4),
                "source": "sweep",
            })

            vols = sorted([v for _, v in components], reverse=True)
            vol_pcts = [f"{v/original_vol:.1%}" for v in vols]
            logger.info(f"  Round {cut_round+1}: {axis_name}={position:.1f} "
                        f"score={score:.3f} → {len(components)} comps "
                        f"[{', '.join(vol_pcts)}] ({dt_sweep:.2f}s)")
            cut_made = True
            break

        if not cut_made:
            break

    # Export parts
    parts = []
    for i, (man, tm) in enumerate(pool):
        part_id = str(uuid.uuid4())[:8]
        filename = f"part_{i}.stl"
        tm.export(str(output_dir / filename))

        try:
            vol = abs(tm.volume)
        except Exception:
            vol = 0.0

        part_extents = tm.bounding_box.extents
        parts.append(PartDescriptor(
            part_id=part_id,
            mesh=tm,
            mesh_path=filename,
            bbox_mm=tuple(part_extents.tolist()),
            volume_mm3=round(vol, 2),
            side=str(i),
        ))

    total_vol = sum(p.volume_mm3 for p in parts)
    dt_total = time.time() - t_total
    logger.info(f"FDM auto split done: {len(parts)} parts, {len(planes_used)} cuts, "
                f"volume {total_vol:.0f} / {original_volume:.0f}, "
                f"total time {dt_total:.3f}s")

    return AutoSplitResult(
        parts=parts,
        n_cuts=len(planes_used),
        planes_used=planes_used,
        original_volume=original_volume,
    )


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
