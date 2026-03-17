"""
Mesh Segmentation via Feature-Aware Region Fusion

Based on: Wu et al. 2023 — "Robust Mesh Segmentation Using Feature-Aware Region Fusion"

Two-stage algorithm:
  Stage 1: Adaptive BSP over-segmentation → superfacets
  Stage 2: Feature-aware iterative region fusion

Shape features used:
  - Face normal
  - Gaussian curvature (discrete, per-vertex → averaged per superfacet)
  - SDF (shape diameter function, local thickness)

Output: list of segments, each containing face indices.
For FDM splitting: segment boundaries → PCA-fitted candidate cut planes.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

import numpy as np
import trimesh

logger = logging.getLogger(__name__)


# ============================================================================
# Data Structures
# ============================================================================

@dataclass
class Superfacet:
    """A group of contiguous mesh faces from BSP partitioning."""
    face_indices: np.ndarray  # indices into mesh.faces
    normal: np.ndarray  # average face normal (3,)
    curvature: float  # average Gaussian curvature
    sdf: float  # average local thickness
    centroid: np.ndarray  # geometric centroid (3,)
    area: float  # total surface area


@dataclass
class Segment:
    """A merged region of superfacets."""
    superfacet_ids: list[int]
    face_indices: np.ndarray  # all face indices in this segment
    neighbors: set[int]  # neighboring segment IDs


@dataclass
class SegmentationResult:
    """Full segmentation output."""
    segments: list[Segment]
    n_superfacets: int
    n_segments: int
    duration: float


@dataclass
class CandidateCutPlane:
    """A cut plane derived from segment boundary."""
    normal: np.ndarray  # unit normal (3,)
    offset: float  # signed distance from origin
    score: float  # lower = better
    boundary_length: int  # number of boundary edges
    seg_pair: tuple[int, int]  # which segments this boundary separates


# ============================================================================
# Stage 1: Adaptive BSP Over-segmentation
# ============================================================================

def _assign_faces_to_cells(
    face_centroids: np.ndarray,
    bmin: np.ndarray,
    bmax: np.ndarray,
    max_faces_per_cell: int,
    depth: int = 0,
    max_depth: int = 12,
) -> list[np.ndarray]:
    """
    Recursively partition faces via BSP along longest axis.

    Returns list of face index arrays (one per leaf cell).
    """
    n = len(face_centroids)
    if n <= max_faces_per_cell or depth >= max_depth:
        return [np.arange(n)]

    # Split along longest axis
    extents = bmax - bmin
    axis = int(np.argmax(extents))
    mid = (bmin[axis] + bmax[axis]) / 2.0

    left_mask = face_centroids[:, axis] <= mid
    right_mask = ~left_mask

    left_count = np.sum(left_mask)
    right_count = np.sum(right_mask)

    # Avoid degenerate splits
    if left_count < 2 or right_count < 2:
        return [np.arange(n)]

    left_indices = np.where(left_mask)[0]
    right_indices = np.where(right_mask)[0]

    # Recurse on each half
    left_bmax = bmax.copy()
    left_bmax[axis] = mid
    right_bmin = bmin.copy()
    right_bmin[axis] = mid

    left_cells = _assign_faces_to_cells(
        face_centroids[left_indices], bmin, left_bmax,
        max_faces_per_cell, depth + 1, max_depth,
    )
    right_cells = _assign_faces_to_cells(
        face_centroids[right_indices], right_bmin, bmax,
        max_faces_per_cell, depth + 1, max_depth,
    )

    # Map local indices back to parent indices
    result = []
    for cell in left_cells:
        result.append(left_indices[cell])
    for cell in right_cells:
        result.append(right_indices[cell])

    return result


def compute_over_segmentation(
    mesh: trimesh.Trimesh,
    target_superfacet_count: int = 300,
) -> list[np.ndarray]:
    """
    Partition mesh faces into superfacets via adaptive BSP.

    Args:
        mesh: Input mesh.
        target_superfacet_count: Approximate number of superfacets.

    Returns:
        List of face index arrays (one per superfacet).
    """
    n_faces = len(mesh.faces)
    max_faces_per_cell = max(3, n_faces // target_superfacet_count)

    face_centroids = mesh.triangles_center

    bmin = face_centroids.min(axis=0)
    bmax = face_centroids.max(axis=0)
    # Small padding to avoid boundary issues
    pad = (bmax - bmin) * 0.001 + 1e-6
    bmin -= pad
    bmax += pad

    cells = _assign_faces_to_cells(
        face_centroids, bmin, bmax, max_faces_per_cell,
    )

    # Filter out empty cells
    cells = [c for c in cells if len(c) > 0]

    return cells


# ============================================================================
# Feature Computation
# ============================================================================

def _compute_face_sdf(
    mesh: trimesh.Trimesh,
    n_samples: int = 2000,
) -> np.ndarray:
    """
    Compute per-face SDF (local thickness) via ray casting.

    Shoots rays inward from face centroids along -normal direction,
    returns distance to opposite surface.
    """
    n_faces = len(mesh.faces)
    face_normals = mesh.face_normals
    face_centroids = mesh.triangles_center

    # Subsample for speed
    if n_faces > n_samples:
        rng = np.random.RandomState(42)
        sample_idx = rng.choice(n_faces, n_samples, replace=False)
    else:
        sample_idx = np.arange(n_faces)

    origins = face_centroids[sample_idx]
    # Offset slightly inward to avoid self-intersection
    directions = -face_normals[sample_idx]
    origins = origins + directions * 0.01

    # Ray cast
    locations, index_ray, _ = mesh.ray.intersects_location(
        ray_origins=origins,
        ray_directions=directions,
    )

    # Compute distances for hits
    sdf_sampled = np.full(len(sample_idx), np.nan)
    if len(locations) > 0:
        hit_distances = np.linalg.norm(locations - origins[index_ray], axis=1)
        # For each ray, take the first hit (closest)
        for i in range(len(sample_idx)):
            hits = hit_distances[index_ray == i]
            if len(hits) > 0:
                sdf_sampled[i] = hits.min()

    # Fill NaN with median
    nan_mask = np.isnan(sdf_sampled)
    if nan_mask.any() and not nan_mask.all():
        sdf_sampled[nan_mask] = np.nanmedian(sdf_sampled)
    elif nan_mask.all():
        sdf_sampled[:] = 1.0

    # Expand back to all faces (nearest sample)
    if n_faces > n_samples:
        from scipy.spatial import cKDTree
        tree = cKDTree(face_centroids[sample_idx])
        _, nearest = tree.query(face_centroids)
        face_sdf = sdf_sampled[nearest]
    else:
        face_sdf = sdf_sampled

    return face_sdf


def _compute_vertex_curvature(mesh: trimesh.Trimesh) -> np.ndarray:
    """
    Compute discrete Gaussian curvature per vertex.

    Uses the angle defect method: K(v) = 2π - Σ(angles at v).
    """
    n_verts = len(mesh.vertices)
    angle_sum = np.zeros(n_verts)

    # Compute angles at each vertex of each face
    v0 = mesh.vertices[mesh.faces[:, 0]]
    v1 = mesh.vertices[mesh.faces[:, 1]]
    v2 = mesh.vertices[mesh.faces[:, 2]]

    # Angles at vertex 0
    e01 = v1 - v0
    e02 = v2 - v0
    cos0 = np.einsum('ij,ij->i', e01, e02) / (
        np.linalg.norm(e01, axis=1) * np.linalg.norm(e02, axis=1) + 1e-10)
    cos0 = np.clip(cos0, -1, 1)
    angles0 = np.arccos(cos0)

    # Angles at vertex 1
    e10 = v0 - v1
    e12 = v2 - v1
    cos1 = np.einsum('ij,ij->i', e10, e12) / (
        np.linalg.norm(e10, axis=1) * np.linalg.norm(e12, axis=1) + 1e-10)
    cos1 = np.clip(cos1, -1, 1)
    angles1 = np.arccos(cos1)

    # Angles at vertex 2
    e20 = v0 - v2
    e21 = v1 - v2
    cos2 = np.einsum('ij,ij->i', e20, e21) / (
        np.linalg.norm(e20, axis=1) * np.linalg.norm(e21, axis=1) + 1e-10)
    cos2 = np.clip(cos2, -1, 1)
    angles2 = np.arccos(cos2)

    np.add.at(angle_sum, mesh.faces[:, 0], angles0)
    np.add.at(angle_sum, mesh.faces[:, 1], angles1)
    np.add.at(angle_sum, mesh.faces[:, 2], angles2)

    # Gaussian curvature = 2π - angle sum (for interior vertices)
    curvature = 2.0 * np.pi - angle_sum

    return curvature


def build_superfacets(
    mesh: trimesh.Trimesh,
    cell_indices: list[np.ndarray],
    face_sdf: np.ndarray,
    vertex_curvature: np.ndarray,
) -> list[Superfacet]:
    """
    Build Superfacet objects with computed features.
    """
    face_normals = mesh.face_normals
    face_centroids = mesh.triangles_center
    face_areas = mesh.area_faces

    superfacets = []
    for cell in cell_indices:
        if len(cell) == 0:
            continue

        # Average normal
        normals = face_normals[cell]
        avg_normal = normals.mean(axis=0)
        norm = np.linalg.norm(avg_normal)
        if norm > 1e-10:
            avg_normal /= norm
        else:
            avg_normal = np.array([0, 0, 1.0])

        # Average curvature (from vertices of faces in this cell)
        face_verts = mesh.faces[cell].ravel()
        avg_curvature = float(np.mean(vertex_curvature[face_verts]))

        # Average SDF
        avg_sdf = float(np.mean(face_sdf[cell]))

        # Centroid and area
        centroid = face_centroids[cell].mean(axis=0)
        area = float(face_areas[cell].sum())

        superfacets.append(Superfacet(
            face_indices=cell,
            normal=avg_normal,
            curvature=avg_curvature,
            sdf=avg_sdf,
            centroid=centroid,
            area=area,
        ))

    return superfacets


# ============================================================================
# Adjacency
# ============================================================================

def build_superfacet_adjacency(
    mesh: trimesh.Trimesh,
    cell_indices: list[np.ndarray],
) -> dict[int, set[int]]:
    """
    Build adjacency between superfacets using shared edges.

    Two superfacets are adjacent if they share at least one mesh edge
    (i.e., they have faces that share an edge).
    """
    n_faces = len(mesh.faces)

    # Map each face → superfacet id
    face_to_sf = np.full(n_faces, -1, dtype=np.int32)
    for sf_id, cell in enumerate(cell_indices):
        face_to_sf[cell] = sf_id

    # Use mesh face adjacency (trimesh provides this)
    adjacency: dict[int, set[int]] = {i: set() for i in range(len(cell_indices))}

    # trimesh.graph.face_adjacency gives pairs of adjacent faces
    face_adj = mesh.face_adjacency
    for f0, f1 in face_adj:
        sf0 = face_to_sf[f0]
        sf1 = face_to_sf[f1]
        if sf0 != sf1 and sf0 >= 0 and sf1 >= 0:
            adjacency[sf0].add(sf1)
            adjacency[sf1].add(sf0)

    return adjacency


# ============================================================================
# Stage 2: Feature-Aware Region Fusion
# ============================================================================

def _feature_distance(sf1: Superfacet, sf2: Superfacet, feature_ranges: dict) -> float:
    """
    Compute weighted feature distance between two superfacets.

    Features are normalized by their global range, then weighted and summed.
    """
    # Normal difference: angle between normals (0 to π, normalized to 0..1)
    cos_angle = np.clip(np.dot(sf1.normal, sf2.normal), -1, 1)
    normal_diff = np.arccos(cos_angle) / np.pi

    # Curvature difference (normalized)
    curv_range = feature_ranges.get('curvature', 1.0)
    curv_diff = abs(sf1.curvature - sf2.curvature) / max(curv_range, 1e-10)

    # SDF difference (normalized)
    sdf_range = feature_ranges.get('sdf', 1.0)
    sdf_diff = abs(sf1.sdf - sf2.sdf) / max(sdf_range, 1e-10)

    # Weighted combination
    # Normal gets highest weight (most reliable for segmentation)
    w_normal = 0.50
    w_curvature = 0.20
    w_sdf = 0.30

    return w_normal * normal_diff + w_curvature * curv_diff + w_sdf * sdf_diff


def _compute_feature_ranges(superfacets: list[Superfacet]) -> dict:
    """Compute global range of each feature for normalization."""
    curvatures = [sf.curvature for sf in superfacets]
    sdfs = [sf.sdf for sf in superfacets]

    return {
        'curvature': max(np.ptp(curvatures), 1e-10),
        'sdf': max(np.ptp(sdfs), 1e-10),
    }


def _compute_intra_region_diff(
    segment: Segment,
    superfacets: list[Superfacet],
    sf_adjacency: dict[int, set[int]],
    feature_ranges: dict,
    tau: float = 0.05,
) -> float:
    """
    Compute intra-region difference for a segment.

    This is the average feature distance between adjacent superfacets
    within the same segment, plus a regularization term τ/|R| that
    prevents trivially small regions from having zero difference.
    """
    sf_set = set(segment.superfacet_ids)
    diffs = []

    for sf_id in segment.superfacet_ids:
        for neighbor_id in sf_adjacency.get(sf_id, set()):
            if neighbor_id in sf_set and neighbor_id > sf_id:
                d = _feature_distance(
                    superfacets[sf_id], superfacets[neighbor_id], feature_ranges)
                diffs.append(d)

    if not diffs:
        return tau / max(len(segment.superfacet_ids), 1)

    return np.mean(diffs) + tau / len(segment.superfacet_ids)


def _compute_inter_region_diff(
    seg1: Segment,
    seg2: Segment,
    superfacets: list[Superfacet],
    sf_adjacency: dict[int, set[int]],
    feature_ranges: dict,
) -> float:
    """
    Compute inter-region difference between two adjacent segments.

    Average feature distance across all boundary superfacet pairs.
    """
    sf_set1 = set(seg1.superfacet_ids)
    sf_set2 = set(seg2.superfacet_ids)
    diffs = []

    for sf_id in seg1.superfacet_ids:
        for neighbor_id in sf_adjacency.get(sf_id, set()):
            if neighbor_id in sf_set2:
                d = _feature_distance(
                    superfacets[sf_id], superfacets[neighbor_id], feature_ranges)
                diffs.append(d)

    if not diffs:
        return float('inf')

    return np.mean(diffs)


def region_fusion(
    superfacets: list[Superfacet],
    sf_adjacency: dict[int, set[int]],
    tau: float = 0.20,
) -> list[Segment]:
    """
    Iterative feature-aware region fusion.

    Fusion condition: two adjacent regions R1, R2 are merged if
        inter(R1, R2) < min(intra(R1), intra(R2))

    Uses Union-Find for correct segment tracking.
    Iterates until no more fusions are possible.
    """
    n_sf = len(superfacets)
    feature_ranges = _compute_feature_ranges(superfacets)

    # Union-Find with path compression
    parent = list(range(n_sf))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> int:
        """Merge b into a, return a."""
        ra, rb = find(a), find(b)
        if ra == rb:
            return ra
        parent[rb] = ra
        return ra

    # Segment data keyed by root superfacet ID
    seg_data: dict[int, Segment] = {}
    for i in range(n_sf):
        seg_data[i] = Segment(
            superfacet_ids=[i],
            face_indices=superfacets[i].face_indices.copy(),
            neighbors=set(),  # will be rebuilt each iteration
        )

    def _rebuild_seg_adjacency() -> dict[int, set[int]]:
        """Rebuild segment-level adjacency from superfacet adjacency."""
        adj: dict[int, set[int]] = {root: set() for root in seg_data}
        for sf_id in range(n_sf):
            seg_root = find(sf_id)
            for neighbor_sf in sf_adjacency.get(sf_id, set()):
                neighbor_root = find(neighbor_sf)
                if neighbor_root != seg_root:
                    adj[seg_root].add(neighbor_root)
                    adj[neighbor_root].add(seg_root)
        return adj

    iteration = 0
    max_iterations = n_sf

    while iteration < max_iterations:
        iteration += 1

        # Rebuild adjacency from scratch each iteration (correct, O(n_sf) cost)
        seg_adj = _rebuild_seg_adjacency()

        # Collect all adjacent segment pairs
        pairs = set()
        for seg_id, neighbors in seg_adj.items():
            for neighbor_id in neighbors:
                pair = (min(seg_id, neighbor_id), max(seg_id, neighbor_id))
                pairs.add(pair)

        if not pairs:
            break

        # Find best fusible pair
        best_pair = None
        best_ratio = float('inf')

        for s1_id, s2_id in pairs:
            if s1_id not in seg_data or s2_id not in seg_data:
                continue

            inter_diff = _compute_inter_region_diff(
                seg_data[s1_id], seg_data[s2_id],
                superfacets, sf_adjacency, feature_ranges,
            )
            intra1 = _compute_intra_region_diff(
                seg_data[s1_id], superfacets, sf_adjacency, feature_ranges, tau,
            )
            intra2 = _compute_intra_region_diff(
                seg_data[s2_id], superfacets, sf_adjacency, feature_ranges, tau,
            )

            min_intra = min(intra1, intra2)
            if min_intra <= 0:
                continue

            ratio = inter_diff / min_intra

            if ratio < 1.0 and ratio < best_ratio:
                best_ratio = ratio
                best_pair = (s1_id, s2_id)

        if best_pair is None:
            break

        # Merge s2 into s1
        s1_id, s2_id = best_pair
        s1 = seg_data[s1_id]
        s2 = seg_data[s2_id]

        union(s1_id, s2_id)  # s2 → s1

        s1.superfacet_ids.extend(s2.superfacet_ids)
        s1.face_indices = np.concatenate([s1.face_indices, s2.face_indices])

        del seg_data[s2_id]

        if iteration % 50 == 0:
            logger.debug(f"  Fusion iteration {iteration}: {len(seg_data)} segments")

    return list(seg_data.values())


# ============================================================================
# Candidate Cut Planes from Segment Boundaries
# ============================================================================

def extract_boundary_planes(
    mesh: trimesh.Trimesh,
    segments: list[Segment],
    min_boundary_edges: int = 10,
) -> list[CandidateCutPlane]:
    """
    Extract candidate cut planes by fitting planes to segment boundaries.

    For each pair of adjacent segments, collect boundary edge midpoints
    and fit a plane via PCA.  Filters out degenerate/short boundaries.
    """
    n_faces = len(mesh.faces)
    mesh_extent = np.linalg.norm(mesh.extents) + 1e-10

    # Build face → segment mapping
    face_to_seg = np.full(n_faces, -1, dtype=np.int32)
    for seg_idx, seg in enumerate(segments):
        face_to_seg[seg.face_indices] = seg_idx

    # Collect boundary edge midpoints between segment pairs
    boundary_points: dict[tuple[int, int], list] = {}
    face_adj = mesh.face_adjacency

    for f0, f1 in face_adj:
        s0 = face_to_seg[f0]
        s1 = face_to_seg[f1]
        if s0 != s1 and s0 >= 0 and s1 >= 0:
            pair = (min(s0, s1), max(s0, s1))
            if pair not in boundary_points:
                boundary_points[pair] = []
            mid = (mesh.triangles_center[f0] + mesh.triangles_center[f1]) / 2.0
            boundary_points[pair].append(mid)

    # Segment sizes (face counts) for filtering
    seg_sizes = [len(seg.face_indices) for seg in segments]
    min_seg_size = n_faces * 0.01  # ignore tiny segments (< 1% of mesh)

    planes = []
    for (s0, s1), points in boundary_points.items():
        if len(points) < min_boundary_edges:
            continue

        # Skip boundaries between tiny segments
        if seg_sizes[s0] < min_seg_size and seg_sizes[s1] < min_seg_size:
            continue

        pts = np.array(points)
        centroid = pts.mean(axis=0)
        centered = pts - centroid

        # PCA: smallest eigenvector = plane normal
        cov = centered.T @ centered
        eigenvalues, eigenvectors = np.linalg.eigh(cov)
        normal = eigenvectors[:, 0]  # smallest eigenvalue

        # Ensure consistent normal direction
        if normal[np.argmax(np.abs(normal))] < 0:
            normal = -normal

        offset = float(np.dot(normal, centroid))

        # Planarity: how well the boundary points fit a plane
        residuals = np.abs(centered @ normal)
        planarity = float(np.mean(residuals))
        boundary_length = len(points)

        # Skip boundaries that are not sufficiently planar
        # (residual > 10% of mesh extent = not a clean cut)
        if planarity > 0.10 * mesh_extent:
            continue

        # Score: combine planarity (lower=better) with boundary extent
        # Prefer: long, planar boundaries between large segments
        boundary_span = float(np.linalg.norm(pts.max(axis=0) - pts.min(axis=0)))
        span_ratio = boundary_span / mesh_extent  # 0..1

        # Bigger span + lower planarity residual = better
        score = (planarity / mesh_extent) / (span_ratio + 0.1)

        planes.append(CandidateCutPlane(
            normal=normal,
            offset=offset,
            score=score,
            boundary_length=boundary_length,
            seg_pair=(s0, s1),
        ))

    # Sort by score (lower = better)
    planes.sort(key=lambda p: p.score)

    # Deduplicate near-identical planes (within 5° normal and 2% offset)
    filtered = []
    for plane in planes:
        is_dup = False
        for existing in filtered:
            cos_sim = abs(np.dot(plane.normal, existing.normal))
            offset_diff = abs(plane.offset - existing.offset) / mesh_extent
            if cos_sim > 0.996 and offset_diff < 0.02:  # ~5° and 2%
                is_dup = True
                break
        if not is_dup:
            filtered.append(plane)

    logger.info(f"  Boundary planes: {len(planes)} → {len(filtered)} after dedup")
    return filtered


# ============================================================================
# Full Pipeline
# ============================================================================

def segment_mesh(
    mesh: trimesh.Trimesh,
    target_superfacets: int = 300,
    tau: float = 0.20,
) -> SegmentationResult:
    """
    Full segmentation pipeline: BSP over-segmentation → feature computation → region fusion.

    Args:
        mesh: Input mesh.
        target_superfacets: Approximate number of superfacets for over-segmentation.
        tau: Regularization parameter for fusion condition.

    Returns:
        SegmentationResult with segments and metadata.
    """
    t0 = time.time()

    # Stage 1: Over-segmentation
    logger.info(f"Segmentation: {len(mesh.faces)} faces, "
                f"target {target_superfacets} superfacets")
    cells = compute_over_segmentation(mesh, target_superfacets)
    logger.info(f"  BSP: {len(cells)} superfacets")

    # Feature computation
    t_feat = time.time()
    face_sdf = _compute_face_sdf(mesh)
    vertex_curvature = _compute_vertex_curvature(mesh)
    logger.info(f"  Features computed in {time.time() - t_feat:.2f}s")

    # Build superfacets with features
    superfacets = build_superfacets(mesh, cells, face_sdf, vertex_curvature)

    # Build adjacency
    sf_adjacency = build_superfacet_adjacency(mesh, cells)

    # Stage 2: Region fusion
    t_fuse = time.time()
    segments = region_fusion(superfacets, sf_adjacency, tau)
    logger.info(f"  Fusion: {len(superfacets)} → {len(segments)} segments "
                f"in {time.time() - t_fuse:.2f}s")

    duration = time.time() - t0
    logger.info(f"Segmentation complete: {len(segments)} segments in {duration:.2f}s")

    return SegmentationResult(
        segments=segments,
        n_superfacets=len(superfacets),
        n_segments=len(segments),
        duration=duration,
    )


def generate_cut_planes_from_segmentation(
    mesh: trimesh.Trimesh,
    target_superfacets: int = 300,
    tau: float = 0.20,
    min_boundary_edges: int = 10,
) -> list[CandidateCutPlane]:
    """
    Full pipeline: segment mesh → extract boundary planes.

    Returns candidate cut planes sorted by score (lower = better).
    """
    result = segment_mesh(mesh, target_superfacets, tau)
    planes = extract_boundary_planes(mesh, result.segments, min_boundary_edges)

    logger.info(f"Generated {len(planes)} candidate cut planes from "
                f"{result.n_segments} segments")

    return planes
