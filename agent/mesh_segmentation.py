"""
Mesh Segmentation via Feature-Aware Region Fusion

Faithful implementation of:
  Wu et al. 2023 — "Robust Mesh Segmentation Using Feature-Aware Region Fusion"
  Sensors 2023, 23, 416. https://doi.org/10.3390/s23010416

Two-stage algorithm:
  Stage 1: Adaptive space partition (PCA-based BSP) → connected superfacets
  Stage 2: Feature-aware iterative region fusion
    - Feature vector T(Fi) = [normal, curvature, SDF] (normalized, concatenated)
    - d(Fi, Fj) = ||T(Fi) - T(Fj)||_2  (Eq. 1)
    - D(R) = Average{d(Fi, Fj)} for adjacent Fi, Fj in R  (Eq. 2)
    - Dis(R1, R2) = Average{d(Fi, Fj)} for boundary pairs  (Eq. 3)
    - Fusion condition: Dis(R1,R2) <= Min{D(R1)+t(R1), D(R2)+t(R2)}  (Eq. 4)
    - Threshold: t(R) = m / (1 + e^|R|)  (Eq. 5)
    - Fusion order: sort all inter-region diffs ascending, fuse in order
  Post-processing: small region merging

Output: list of segments, each containing face indices.
For FDM splitting: segment boundaries → PCA-fitted candidate cut planes.
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass

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
    feature_vector: np.ndarray  # normalized, concatenated features T(Fi)
    centroid: np.ndarray  # geometric centroid (3,)
    area: float  # total surface area


@dataclass
class Segment:
    """A merged region of superfacets."""
    superfacet_ids: list[int]
    face_indices: np.ndarray  # all face indices in this segment


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
# Stage 1: Adaptive Space Partition (PCA-based BSP)
# ============================================================================

def _pca_bsp_partition(
    vertices: np.ndarray,
    face_indices: np.ndarray,
    faces: np.ndarray,
    face_centroids: np.ndarray,
    q_max: int,
    sigma_max: float,
    depth: int = 0,
    max_depth: int = 14,
) -> list[np.ndarray]:
    """
    Recursively partition faces via PCA-based BSP (Section 3.1 of Wu et al.).

    The partition plane passes through the centroid of vertices in the current
    subspace, oriented along the eigenvector of greatest variation (largest
    eigenvalue). Recursion stops when:
      - face count <= q_max, AND
      - surface variation σ = λ0/(λ0+λ1+λ2) <= sigma_max
      - or max depth reached

    Args:
        vertices: Full mesh vertex array (n_verts, 3).
        face_indices: Indices into the global face array for this partition.
        faces: Full mesh face array (n_faces, 3).
        face_centroids: Centroids of all faces (n_faces, 3).
        q_max: Max faces per superfacet.
        sigma_max: Max surface variation per superfacet.
    """
    n = len(face_indices)
    if n <= 1 or depth >= max_depth:
        return [face_indices]

    # Collect unique vertices in this partition
    local_faces = faces[face_indices]
    unique_vert_ids = np.unique(local_faces.ravel())
    pts = vertices[unique_vert_ids]

    if len(pts) < 4:
        return [face_indices]

    # Compute covariance matrix of vertex positions (Eq. in Section 3.1)
    centroid = pts.mean(axis=0)
    centered = pts - centroid
    cov = centered.T @ centered / len(pts)

    eigenvalues, eigenvectors = np.linalg.eigh(cov)
    # eigenvalues sorted ascending: λ0 <= λ1 <= λ2

    # Surface variation σ = λ0 / (λ0 + λ1 + λ2)
    total_lambda = eigenvalues.sum()
    if total_lambda > 1e-12:
        sigma = eigenvalues[0] / total_lambda
    else:
        sigma = 0.0

    # Stop if both conditions met: small enough AND flat enough
    if n <= q_max and sigma <= sigma_max:
        return [face_indices]

    # Partition plane: through centroid, normal = v0 (eigenvector of smallest eigenvalue)
    # Split along direction of GREATEST variation = v2 (largest eigenvalue)
    split_dir = eigenvectors[:, 2]  # direction of greatest variation

    # Project face centroids onto split direction
    local_centroids = face_centroids[face_indices]
    projections = (local_centroids - centroid) @ split_dir

    # Split at median projection (balanced split)
    median_proj = np.median(projections)
    left_mask = projections <= median_proj
    right_mask = ~left_mask

    left_count = np.sum(left_mask)
    right_count = np.sum(right_mask)

    # Avoid degenerate splits
    if left_count < 2 or right_count < 2:
        return [face_indices]

    left_indices = face_indices[left_mask]
    right_indices = face_indices[right_mask]

    # Recurse on each half
    left_cells = _pca_bsp_partition(
        vertices, left_indices, faces, face_centroids,
        q_max, sigma_max, depth + 1, max_depth,
    )
    right_cells = _pca_bsp_partition(
        vertices, right_indices, faces, face_centroids,
        q_max, sigma_max, depth + 1, max_depth,
    )

    return left_cells + right_cells


def _split_into_connected_components(
    face_indices: np.ndarray,
    face_adjacency_map: dict[int, set[int]],
) -> list[np.ndarray]:
    """Split a set of face indices into connected components via BFS."""
    face_set = set(face_indices.tolist())
    remaining = face_set.copy()
    components = []

    while remaining:
        start = next(iter(remaining))
        component = set()
        queue = [start]
        component.add(start)

        while queue:
            f = queue.pop()
            for neighbor in face_adjacency_map.get(f, ()):
                if neighbor in remaining and neighbor not in component:
                    component.add(neighbor)
                    queue.append(neighbor)

        remaining -= component
        components.append(np.array(sorted(component)))

    return components


def compute_over_segmentation(
    mesh: trimesh.Trimesh,
    target_superfacet_count: int = 300,
    sigma_max: float = 0.05,
) -> list[np.ndarray]:
    """
    PCA-based adaptive space partition (Section 3.1).

    Each cell is further split into connected components to ensure
    topological connectivity (paper assumes contiguous superfacets).

    Args:
        mesh: Input mesh.
        target_superfacet_count: Approximate number of superfacets.
        sigma_max: Surface variation threshold for stopping recursion.

    Returns:
        List of face index arrays (one per connected superfacet).
    """
    n_faces = len(mesh.faces)
    q_max = max(3, n_faces // target_superfacet_count)

    all_face_indices = np.arange(n_faces)

    cells = _pca_bsp_partition(
        mesh.vertices, all_face_indices, mesh.faces, mesh.triangles_center,
        q_max, sigma_max,
    )

    # Filter empty cells
    cells = [c for c in cells if len(c) > 0]

    # Build face adjacency map for connectivity check
    face_adj_map: dict[int, set[int]] = {}
    for f0, f1 in mesh.face_adjacency:
        face_adj_map.setdefault(f0, set()).add(f1)
        face_adj_map.setdefault(f1, set()).add(f0)

    # Ensure each superfacet is topologically connected
    connected_cells = []
    for cell in cells:
        if len(cell) <= 1:
            connected_cells.append(cell)
            continue
        components = _split_into_connected_components(cell, face_adj_map)
        connected_cells.extend(components)

    logger.debug(f"  PCA-BSP: {len(cells)} cells → "
                 f"{len(connected_cells)} connected superfacets")

    return connected_cells


# ============================================================================
# Feature Computation (Section 3.2.1)
# ============================================================================

def _compute_face_sdf(mesh: trimesh.Trimesh, n_samples: int = 2000) -> np.ndarray:
    """
    Compute per-face SDF (shape diameter function) via ray casting.

    Samples n_samples faces, shoots rays inward (vectorized),
    then interpolates to all faces via nearest-neighbor.
    """
    n_faces = len(mesh.faces)
    face_normals = mesh.face_normals
    face_centroids = mesh.triangles_center

    rng = np.random.RandomState(42)

    # Sample faces
    if n_faces > n_samples:
        sample_idx = rng.choice(n_faces, n_samples, replace=False)
    else:
        sample_idx = np.arange(n_faces)

    n_s = len(sample_idx)

    # Build rays vectorized: 1 ray per sample (inward along -normal)
    normals = face_normals[sample_idx]
    centers = face_centroids[sample_idx]
    all_dirs = -normals
    all_origins = centers + all_dirs * 0.01
    ray_to_sample = np.arange(n_s)

    # Single ray cast
    locations, index_ray, _ = mesh.ray.intersects_location(
        ray_origins=all_origins,
        ray_directions=all_dirs,
    )

    sdf_sampled = np.full(n_s, np.nan)

    if len(locations) > 0:
        hit_distances = np.linalg.norm(locations - all_origins[index_ray], axis=1)
        hit_samples = ray_to_sample[index_ray]

        # For each sample, take median of all hit distances
        for i in range(n_s):
            mask = hit_samples == i
            if mask.any():
                sdf_sampled[i] = np.median(hit_distances[mask])

    # Fill NaN with global median
    nan_mask = np.isnan(sdf_sampled)
    if nan_mask.any() and not nan_mask.all():
        sdf_sampled[nan_mask] = np.nanmedian(sdf_sampled)
    elif nan_mask.all():
        sdf_sampled[:] = 1.0

    # Interpolate to all faces via nearest-neighbor
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
    Compute discrete Gaussian curvature per vertex via angle defect.
    K(v) = 2π - Σ(angles at v)
    """
    n_verts = len(mesh.vertices)
    angle_sum = np.zeros(n_verts)

    v0 = mesh.vertices[mesh.faces[:, 0]]
    v1 = mesh.vertices[mesh.faces[:, 1]]
    v2 = mesh.vertices[mesh.faces[:, 2]]

    for va, vb, vc, col in [(v0, v1, v2, 0), (v1, v0, v2, 1), (v2, v0, v1, 2)]:
        e1 = vb - va
        e2 = vc - va
        cos_a = np.einsum('ij,ij->i', e1, e2) / (
            np.linalg.norm(e1, axis=1) * np.linalg.norm(e2, axis=1) + 1e-10)
        cos_a = np.clip(cos_a, -1, 1)
        np.add.at(angle_sum, mesh.faces[:, col], np.arccos(cos_a))

    return 2.0 * np.pi - angle_sum


def _normalize_feature(values: np.ndarray) -> np.ndarray:
    """Normalize feature to [0, 1] range."""
    vmin, vmax = values.min(), values.max()
    span = vmax - vmin
    if span < 1e-12:
        return np.zeros_like(values)
    return (values - vmin) / span


def build_superfacets(
    mesh: trimesh.Trimesh,
    cell_indices: list[np.ndarray],
    face_sdf: np.ndarray,
    vertex_curvature: np.ndarray,
) -> list[Superfacet]:
    """
    Build Superfacet objects with feature vectors T(Fi) (Section 3.2.1).

    Feature vector = concatenation of normalized [normal(3), curvature(1), SDF(1)].
    """
    face_normals = mesh.face_normals
    face_centroids = mesh.triangles_center
    face_areas = mesh.area_faces

    # Pre-normalize features globally
    all_curvatures = np.zeros(len(cell_indices))
    all_sdfs = np.zeros(len(cell_indices))
    for i, cell in enumerate(cell_indices):
        if len(cell) == 0:
            continue
        face_verts = mesh.faces[cell].ravel()
        all_curvatures[i] = float(np.mean(vertex_curvature[face_verts]))
        all_sdfs[i] = float(np.mean(face_sdf[cell]))

    norm_curvatures = _normalize_feature(all_curvatures)
    norm_sdfs = _normalize_feature(all_sdfs)

    superfacets = []
    for i, cell in enumerate(cell_indices):
        if len(cell) == 0:
            continue

        # Average normal (already unit-ish, normalize to ensure)
        avg_normal = face_normals[cell].mean(axis=0)
        norm = np.linalg.norm(avg_normal)
        if norm > 1e-10:
            avg_normal /= norm
        else:
            avg_normal = np.array([0.0, 0.0, 1.0])

        # Normal is already in [-1, 1] range. Map to [0, 1] for consistent scale.
        norm_normal = (avg_normal + 1.0) / 2.0  # [0, 1]^3

        # Concatenate into feature vector T(Fi)
        # Paper: "concatenate them to form a feature vector T(Fi)"
        feature_vector = np.concatenate([
            norm_normal,               # 3 dims
            [norm_curvatures[i]],      # 1 dim
            [norm_sdfs[i]],            # 1 dim
        ])

        centroid = face_centroids[cell].mean(axis=0)
        area = float(face_areas[cell].sum())

        superfacets.append(Superfacet(
            face_indices=cell,
            feature_vector=feature_vector,
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
    """Build adjacency between superfacets using shared mesh edges."""
    n_faces = len(mesh.faces)
    face_to_sf = np.full(n_faces, -1, dtype=np.int32)
    for sf_id, cell in enumerate(cell_indices):
        face_to_sf[cell] = sf_id

    adjacency: dict[int, set[int]] = {i: set() for i in range(len(cell_indices))}

    for f0, f1 in mesh.face_adjacency:
        sf0 = face_to_sf[f0]
        sf1 = face_to_sf[f1]
        if sf0 != sf1 and sf0 >= 0 and sf1 >= 0:
            adjacency[sf0].add(sf1)
            adjacency[sf1].add(sf0)

    return adjacency


# ============================================================================
# Stage 2: Feature-Aware Region Fusion (Section 3.2.2)
# ============================================================================

def _feature_distance(sf1: Superfacet, sf2: Superfacet) -> float:
    """
    d(Fi, Fj) = ||T(Fi) - T(Fj)||_2  (Eq. 1)
    """
    return float(np.linalg.norm(sf1.feature_vector - sf2.feature_vector))


def _intra_region_diff(
    seg_sf_ids: list[int],
    superfacets: list[Superfacet],
    sf_adjacency: dict[int, set[int]],
) -> float:
    """
    D(R) = Average{d(Fi, Fj)} for adjacent Fi, Fj in R  (Eq. 2)
    """
    sf_set = set(seg_sf_ids)
    diffs = []

    for sf_id in seg_sf_ids:
        for neighbor_id in sf_adjacency.get(sf_id, ()):
            if neighbor_id in sf_set and neighbor_id > sf_id:
                d = _feature_distance(superfacets[sf_id], superfacets[neighbor_id])
                diffs.append(d)

    if not diffs:
        return 0.0  # single superfacet → D(R) = 0

    return float(np.mean(diffs))


def _inter_region_diff(
    seg1_sf_ids: list[int],
    seg2_sf_ids: list[int],
    superfacets: list[Superfacet],
    sf_adjacency: dict[int, set[int]],
) -> float:
    """
    Dis(R1, R2) = Average{d(Fi, Fj)} for boundary pairs  (Eq. 3)
    """
    sf_set2 = set(seg2_sf_ids)
    diffs = []

    for sf_id in seg1_sf_ids:
        for neighbor_id in sf_adjacency.get(sf_id, ()):
            if neighbor_id in sf_set2:
                d = _feature_distance(superfacets[sf_id], superfacets[neighbor_id])
                diffs.append(d)

    if not diffs:
        return float('inf')

    return float(np.mean(diffs))


def _threshold_function(n_superfacets: int, m: float) -> float:
    """
    t(R) = m / (1 + e^|R|)  (Eq. 5)

    Where |R| is the number of superfacets in region R.
    """
    return m / (1.0 + math.exp(n_superfacets))


def region_fusion(
    superfacets: list[Superfacet],
    sf_adjacency: dict[int, set[int]],
    m: float = 0.5,
    min_superfacets_per_segment: int = 3,
) -> list[Segment]:
    """
    Feature-aware region fusion (Section 3.2.2).

    Algorithm:
      1. Initialize: each superfacet = one region
      2. Compute inter-region diff for all adjacent pairs
      3. Sort ascending
      4. For each pair (in order), check fusion condition (Eq. 4):
         Dis(R1,R2) <= Min{D(R1)+t(R1), D(R2)+t(R2)}
      5. If met, fuse. Update diffs with affected neighbors.
      6. Repeat until no more fusions possible.
      7. Post-process: merge small regions into nearest neighbor.

    Args:
        superfacets: List of superfacets with feature vectors.
        sf_adjacency: Adjacency between superfacets.
        m: Threshold parameter (Eq. 5). Higher = more aggressive fusion.
        min_superfacets_per_segment: Post-fusion small region threshold.
    """
    n_sf = len(superfacets)

    # Union-Find for tracking segment membership
    parent = list(range(n_sf))
    rank = [0] * n_sf

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]  # path compression
            x = parent[x]
        return x

    def union(a: int, b: int) -> int:
        """Merge b's tree into a's tree. Return new root."""
        ra, rb = find(a), find(b)
        if ra == rb:
            return ra
        # Union by rank
        if rank[ra] < rank[rb]:
            ra, rb = rb, ra
        parent[rb] = ra
        if rank[ra] == rank[rb]:
            rank[ra] += 1
        return ra

    # Segment data: keyed by root sf_id
    seg_sf_ids: dict[int, list[int]] = {i: [i] for i in range(n_sf)}
    seg_face_indices: dict[int, np.ndarray] = {
        i: superfacets[i].face_indices.copy() for i in range(n_sf)
    }

    # Pre-compute all pairwise inter-region diffs for adjacent pairs
    # and maintain in a sorted structure
    import heapq

    def _compute_pair_diff(r1: int, r2: int) -> float:
        return _inter_region_diff(
            seg_sf_ids[r1], seg_sf_ids[r2],
            superfacets, sf_adjacency,
        )

    # Build initial priority queue: (inter_diff, seg_a, seg_b)
    seen_pairs = set()
    heap = []

    for sf_id in range(n_sf):
        for neighbor_sf in sf_adjacency.get(sf_id, ()):
            ra, rb = find(sf_id), find(neighbor_sf)
            if ra != rb:
                pair = (min(ra, rb), max(ra, rb))
                if pair not in seen_pairs:
                    seen_pairs.add(pair)
                    diff = _compute_pair_diff(pair[0], pair[1])
                    heapq.heappush(heap, (diff, pair[0], pair[1]))

    # Version counter to invalidate stale heap entries
    seg_version: dict[int, int] = {i: 0 for i in range(n_sf)}

    fusions = 0

    while heap:
        inter_diff, s1_id, s2_id = heapq.heappop(heap)

        # Check if this entry is stale
        r1, r2 = find(s1_id), find(s2_id)
        if r1 == r2:
            continue  # already merged
        if r1 not in seg_sf_ids or r2 not in seg_sf_ids:
            continue  # stale

        # Recompute inter_diff if either segment changed since this entry
        # was pushed (lazy deletion approach)
        current_diff = _compute_pair_diff(r1, r2)
        if abs(current_diff - inter_diff) > 1e-8:
            # Re-push with correct diff
            heapq.heappush(heap, (current_diff, r1, r2))
            continue

        # Fusion condition (Eq. 4):
        # Dis(R1, R2) <= Min{D(R1) + t(R1), D(R2) + t(R2)}
        d_r1 = _intra_region_diff(seg_sf_ids[r1], superfacets, sf_adjacency)
        d_r2 = _intra_region_diff(seg_sf_ids[r2], superfacets, sf_adjacency)
        t_r1 = _threshold_function(len(seg_sf_ids[r1]), m)
        t_r2 = _threshold_function(len(seg_sf_ids[r2]), m)

        threshold = min(d_r1 + t_r1, d_r2 + t_r2)

        if inter_diff > threshold:
            continue  # fusion condition not met

        # Fuse: merge r2 into r1
        new_root = union(r1, r2)
        other = r2 if new_root == r1 else r1

        seg_sf_ids[new_root] = seg_sf_ids[new_root] + seg_sf_ids[other]
        seg_face_indices[new_root] = np.concatenate([
            seg_face_indices[new_root], seg_face_indices[other]
        ])

        # Collect neighbors of the removed segment
        neighbor_roots = set()
        for sf_id in seg_sf_ids[other]:
            for neighbor_sf in sf_adjacency.get(sf_id, ()):
                nr = find(neighbor_sf)
                if nr != new_root and nr in seg_sf_ids:
                    neighbor_roots.add(nr)

        del seg_sf_ids[other]
        del seg_face_indices[other]

        # Push updated diffs for new_root's neighbors
        for nr in neighbor_roots:
            diff = _compute_pair_diff(new_root, nr)
            heapq.heappush(heap, (diff, new_root, nr))

        fusions += 1
        if fusions % 50 == 0:
            logger.debug(f"  Fusion step {fusions}: {len(seg_sf_ids)} segments")

    # Post-processing: merge small regions (paper Section 3.2.2, last paragraph)
    small_threshold = min_superfacets_per_segment
    merged_small = True
    while merged_small:
        merged_small = False
        small_segs = [
            sid for sid, sf_ids in seg_sf_ids.items()
            if len(sf_ids) < small_threshold
        ]

        for sid in small_segs:
            if sid not in seg_sf_ids:
                continue

            # Find adjacent segment with smallest inter-region diff
            neighbor_roots = set()
            for sf_id in seg_sf_ids[sid]:
                for neighbor_sf in sf_adjacency.get(sf_id, ()):
                    nr = find(neighbor_sf)
                    if nr != sid and nr in seg_sf_ids:
                        neighbor_roots.add(nr)

            if not neighbor_roots:
                continue

            best_neighbor = None
            best_diff = float('inf')
            for nr in neighbor_roots:
                diff = _inter_region_diff(
                    seg_sf_ids[sid], seg_sf_ids[nr],
                    superfacets, sf_adjacency,
                )
                if diff < best_diff:
                    best_diff = diff
                    best_neighbor = nr

            if best_neighbor is None:
                continue

            # Merge small segment into best neighbor
            new_root = union(best_neighbor, sid)
            other = sid if new_root == best_neighbor else best_neighbor

            seg_sf_ids[new_root] = seg_sf_ids[new_root] + seg_sf_ids[other]
            seg_face_indices[new_root] = np.concatenate([
                seg_face_indices[new_root], seg_face_indices[other]
            ])
            del seg_sf_ids[other]
            del seg_face_indices[other]
            merged_small = True

    # Build final segments
    result = []
    for sid, sf_ids in seg_sf_ids.items():
        result.append(Segment(
            superfacet_ids=sf_ids,
            face_indices=seg_face_indices[sid],
        ))

    return result


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
    and fit a plane via PCA. Filters out degenerate/short boundaries.
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

    seg_sizes = [len(seg.face_indices) for seg in segments]
    min_seg_size = n_faces * 0.01

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
        normal = eigenvectors[:, 0]

        # Ensure consistent normal direction
        if normal[np.argmax(np.abs(normal))] < 0:
            normal = -normal

        offset = float(np.dot(normal, centroid))

        # Planarity: residual distance from fitted plane
        residuals = np.abs(centered @ normal)
        planarity = float(np.mean(residuals))
        boundary_length = len(points)

        # Skip non-planar boundaries
        if planarity > 0.10 * mesh_extent:
            continue

        # Score: planarity-normalized-by-span
        boundary_span = float(np.linalg.norm(pts.max(axis=0) - pts.min(axis=0)))
        span_ratio = boundary_span / mesh_extent
        score = (planarity / mesh_extent) / (span_ratio + 0.1)

        planes.append(CandidateCutPlane(
            normal=normal,
            offset=offset,
            score=score,
            boundary_length=boundary_length,
            seg_pair=(s0, s1),
        ))

    planes.sort(key=lambda p: p.score)

    # Deduplicate near-identical planes (within 5° normal and 2% offset)
    filtered = []
    for plane in planes:
        is_dup = False
        for existing in filtered:
            cos_sim = abs(np.dot(plane.normal, existing.normal))
            offset_diff = abs(plane.offset - existing.offset) / mesh_extent
            if cos_sim > 0.996 and offset_diff < 0.02:
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
    m: float = 200.0,
    sigma_max: float = 0.20,
) -> SegmentationResult:
    """
    Full segmentation pipeline per Wu et al. 2023.

    Args:
        mesh: Input mesh.
        target_superfacets: Approximate superfacet count for BSP.
        m: Threshold parameter for fusion (Eq. 5). Higher = more merging.
        sigma_max: Surface variation threshold for BSP stopping.

    Returns:
        SegmentationResult with segments and metadata.
    """
    t0 = time.time()

    # Stage 1: Over-segmentation (Section 3.1)
    logger.info(f"Segmentation: {len(mesh.faces)} faces, "
                f"target {target_superfacets} superfacets")
    cells = compute_over_segmentation(mesh, target_superfacets, sigma_max)
    logger.info(f"  BSP: {len(cells)} superfacets")

    # Feature computation (Section 3.2.1)
    t_feat = time.time()
    face_sdf = _compute_face_sdf(mesh)
    vertex_curvature = _compute_vertex_curvature(mesh)
    logger.info(f"  Features computed in {time.time() - t_feat:.2f}s")

    # Build superfacets with feature vectors T(Fi)
    superfacets = build_superfacets(mesh, cells, face_sdf, vertex_curvature)

    # Build adjacency
    sf_adjacency = build_superfacet_adjacency(mesh, cells)

    # Stage 2: Region fusion (Section 3.2.2)
    t_fuse = time.time()
    segments = region_fusion(superfacets, sf_adjacency, m)
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
    m: float = 200.0,
    sigma_max: float = 0.20,
    min_boundary_edges: int = 10,
) -> list[CandidateCutPlane]:
    """
    Full pipeline: segment mesh → extract boundary planes.

    Returns candidate cut planes sorted by score (lower = better).
    """
    result = segment_mesh(mesh, target_superfacets, m, sigma_max)
    planes = extract_boundary_planes(mesh, result.segments, min_boundary_edges)

    logger.info(f"Generated {len(planes)} candidate cut planes from "
                f"{result.n_segments} segments")

    return planes
