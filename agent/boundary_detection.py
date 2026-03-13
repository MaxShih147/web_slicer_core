"""
Dental Mesh Boundary Detection Module

Extracts open boundary edges from dental scan meshes,
chains them into closed loops, and identifies the main
boundary (typically the arch opening).

V2: Detection + boundary smoothing (line-only, does not modify mesh).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Union

import numpy as np
import trimesh


# ---------- Data Structures ----------

@dataclass
class BoundaryLoop:
    """A single closed boundary loop on the mesh."""
    vertex_indices: list[int]
    points: np.ndarray          # shape (N, 3)
    perimeter: float = 0.0
    centroid: np.ndarray = field(default_factory=lambda: np.zeros(3))
    bbox_min: np.ndarray = field(default_factory=lambda: np.zeros(3))
    bbox_max: np.ndarray = field(default_factory=lambda: np.zeros(3))


@dataclass
class BoundaryDetectionResult:
    """Full result of boundary detection."""
    total_boundary_edges: int
    loops: list[BoundaryLoop]
    main_loop_index: int


# ---------- Mesh Loading ----------

def load_mesh(path: str | Path) -> trimesh.Trimesh:
    """Load a mesh file (STL/OBJ/PLY) and return as Trimesh."""
    mesh = trimesh.load(str(path), force="mesh")
    if not isinstance(mesh, trimesh.Trimesh):
        raise ValueError(f"Failed to load as single mesh: {path}")
    if len(mesh.vertices) == 0 or len(mesh.faces) == 0:
        raise ValueError(f"Empty mesh: {path}")
    return mesh


# ---------- Mesh Cleaning ----------

def clean_mesh(mesh: trimesh.Trimesh, min_component_faces: int = 100) -> trimesh.Trimesh:
    """
    Minimal conservative cleaning:
    - Merge duplicate vertices
    - Remove degenerate faces
    - Remove tiny disconnected components

    Does NOT fill holes or modify the main boundary.
    """
    # Merge duplicate vertices
    mesh.merge_vertices()

    # Remove degenerate (zero-area) faces
    mask = mesh.area_faces > 0
    if not mask.all():
        mesh.update_faces(mask)

    return mesh


# ---------- Boundary Extraction ----------

def extract_boundary_edges(mesh: trimesh.Trimesh) -> np.ndarray:
    """
    Find all boundary edges (edges used by exactly one face).

    Returns:
        Array of shape (M, 2) with vertex index pairs for each boundary edge.
    """
    # Vectorized: sort each edge so (min, max), then find unique edges
    # and their counts using numpy
    edges = mesh.edges_sorted  # already sorted per edge
    # Encode each edge as a single int for fast counting
    n_verts = len(mesh.vertices)
    edge_keys = edges[:, 0].astype(np.int64) * n_verts + edges[:, 1].astype(np.int64)
    unique_keys, counts = np.unique(edge_keys, return_counts=True)
    boundary_keys = unique_keys[counts == 1]
    # Decode back to vertex pairs
    v0 = boundary_keys // n_verts
    v1 = boundary_keys % n_verts
    boundary = np.column_stack([v0, v1]).astype(np.int32)
    return boundary


def build_boundary_loops(
    mesh: trimesh.Trimesh,
    boundary_edges: np.ndarray,
) -> list[BoundaryLoop]:
    """
    Chain boundary edges into ordered closed loops.

    Each loop is returned as an ordered sequence of vertex indices
    with computed geometric properties.
    """
    if len(boundary_edges) == 0:
        return []

    # Build adjacency: vertex -> set of connected boundary vertices
    adjacency: dict[int, set[int]] = {}
    for v0, v1 in boundary_edges:
        adjacency.setdefault(v0, set()).add(v1)
        adjacency.setdefault(v1, set()).add(v0)

    visited_edges: set[tuple[int, int]] = set()
    loops: list[BoundaryLoop] = []
    vertices = mesh.vertices

    for start_v in adjacency:
        # Try to start a loop from each unvisited vertex
        for neighbor in adjacency[start_v]:
            edge_key = (min(start_v, neighbor), max(start_v, neighbor))
            if edge_key in visited_edges:
                continue

            # Trace the loop
            chain = [start_v]
            prev = start_v
            current = neighbor
            visited_edges.add(edge_key)

            while current != start_v:
                chain.append(current)
                # Find next vertex (not the one we came from)
                neighbors = adjacency.get(current, set())
                next_candidates = [n for n in neighbors if n != prev]

                if not next_candidates:
                    # Dead end — not a closed loop
                    break

                next_v = next_candidates[0]
                edge_key = (min(current, next_v), max(current, next_v))

                if edge_key in visited_edges:
                    # Already visited — might have hit another loop
                    break

                visited_edges.add(edge_key)
                prev = current
                current = next_v

            if current == start_v and len(chain) >= 3:
                # Valid closed loop
                points = vertices[chain]
                loop = _compute_loop_properties(chain, points)
                loops.append(loop)

    return loops


def _compute_loop_properties(indices: list[int], points: np.ndarray) -> BoundaryLoop:
    """Compute geometric properties for a boundary loop."""
    # Perimeter: sum of edge lengths
    diffs = np.diff(points, axis=0, append=points[:1])
    perimeter = float(np.sum(np.linalg.norm(diffs, axis=1)))

    return BoundaryLoop(
        vertex_indices=indices,
        points=points,
        perimeter=perimeter,
        centroid=points.mean(axis=0),
        bbox_min=points.min(axis=0),
        bbox_max=points.max(axis=0),
    )


# ---------- Boundary Smoothing (line-only) ----------

def smooth_boundary_loop(
    points: np.ndarray,
    iterations: int = 20,
    lam: float = 0.5,
    mu: float = -0.53,
) -> np.ndarray:
    """
    Taubin smoothing on a closed boundary loop (line-only, does not modify mesh).

    Taubin smoothing alternates between a positive (shrinking) step and a
    negative (inflating) step, which prevents the overall shrinkage that
    plain Laplacian smoothing causes.

    Args:
        points: (N, 3) boundary points in order.
        iterations: Number of shrink/inflate cycles.
        lam: Shrink factor (positive, typically 0.3–0.7).
        mu: Inflate factor (negative, |mu| > lam to prevent shrinkage).

    Returns:
        Smoothed (N, 3) points.
    """
    pts = points.copy().astype(np.float64)
    n = len(pts)
    if n < 4:
        return pts

    for _ in range(iterations):
        # Laplacian: average of neighbors minus current point (closed loop)
        prev = np.roll(pts, 1, axis=0)
        nxt = np.roll(pts, -1, axis=0)
        laplacian = (prev + nxt) / 2.0 - pts

        # Shrink step
        pts = pts + lam * laplacian

        # Recompute Laplacian after shrink
        prev = np.roll(pts, 1, axis=0)
        nxt = np.roll(pts, -1, axis=0)
        laplacian = (prev + nxt) / 2.0 - pts

        # Inflate step
        pts = pts + mu * laplacian

    return pts


def smooth_boundary_result(
    result: BoundaryDetectionResult,
    iterations: int = 20,
    lam: float = 0.5,
    mu: float = -0.53,
) -> list[BoundaryLoop]:
    """
    Smooth all boundary loops in a detection result.

    Returns new BoundaryLoop list with smoothed points.
    Original vertex_indices are preserved (for later mesh snapping).
    """
    smoothed = []
    for loop in result.loops:
        new_points = smooth_boundary_loop(loop.points, iterations, lam, mu)
        new_loop = _compute_loop_properties(loop.vertex_indices, new_points)
        smoothed.append(new_loop)
    return smoothed


# ---------- Apply Smoothed Boundary to Mesh ----------

def _build_vertex_adjacency(mesh: trimesh.Trimesh) -> dict[int, set[int]]:
    """Build vertex-to-vertex adjacency from mesh edges."""
    adj: dict[int, set[int]] = {}
    for v0, v1 in mesh.edges_unique:
        adj.setdefault(v0, set()).add(v1)
        adj.setdefault(v1, set()).add(v0)
    return adj


def _find_n_ring_neighbors(
    adjacency: dict[int, set[int]],
    seed_vertices: set[int],
    n_rings: int,
) -> dict[int, int]:
    """
    Find vertices within N edge-rings of seed vertices.

    Returns:
        Dict mapping vertex_index -> ring_distance (1 to n_rings).
        Seed vertices themselves are NOT included.
    """
    ring_map: dict[int, int] = {}
    current_front = seed_vertices.copy()

    for ring in range(1, n_rings + 1):
        next_front: set[int] = set()
        for v in current_front:
            for neighbor in adjacency.get(v, set()):
                if neighbor not in seed_vertices and neighbor not in ring_map:
                    ring_map[neighbor] = ring
                    next_front.add(neighbor)
        current_front = next_front
        if not current_front:
            break

    return ring_map


def apply_boundary_to_mesh(
    mesh_path: str | Path,
    original_points: list[list[float]],
    smoothed_points: list[list[float]],
    falloff_rings: int = 3,
) -> bytes:
    """
    Apply smoothed boundary positions to mesh vertices with gradual falloff.

    1. Load mesh, find boundary vertices matching original_points
    2. Compute displacement = smoothed - original for each boundary vertex
    3. Apply full displacement to boundary vertices
    4. Apply falloff displacement to N-ring neighbors

    Args:
        mesh_path: Path to STL file.
        original_points: Original boundary points [[x,y,z], ...].
        smoothed_points: Smoothed boundary points [[x,y,z], ...].
        falloff_rings: Number of neighbor rings for gradual falloff.

    Returns:
        Modified STL as bytes.
    """
    mesh = load_mesh(mesh_path)
    mesh = clean_mesh(mesh)

    orig = np.array(original_points, dtype=np.float64)
    smooth = np.array(smoothed_points, dtype=np.float64)

    if len(orig) != len(smooth):
        raise ValueError(f"Point count mismatch: {len(orig)} vs {len(smooth)}")

    # Match original points to mesh vertices by nearest distance
    from scipy.spatial import cKDTree
    tree = cKDTree(mesh.vertices)
    distances, vertex_ids = tree.query(orig)

    # Compute displacements
    displacements = smooth - orig  # (N, 3)

    # Build per-vertex displacement map (boundary vertices get full displacement)
    boundary_set = set(int(v) for v in vertex_ids)
    vertex_displacement = {}
    for i, vid in enumerate(vertex_ids):
        vid = int(vid)
        vertex_displacement[vid] = displacements[i]

    # Find N-ring neighbors and apply falloff
    if falloff_rings > 0:
        adjacency = _build_vertex_adjacency(mesh)
        ring_map = _find_n_ring_neighbors(adjacency, boundary_set, falloff_rings)

        # For each neighbor vertex, compute weighted average displacement
        # from nearby boundary vertices
        neighbor_tree = cKDTree(orig)
        for vid, ring_dist in ring_map.items():
            # Weight: linear falloff based on ring distance
            weight = 1.0 - ring_dist / (falloff_rings + 1)
            # Find nearest boundary point to determine displacement direction
            _, nearest_idx = neighbor_tree.query(mesh.vertices[vid])
            vertex_displacement[vid] = displacements[nearest_idx] * weight

    # Apply displacements
    new_vertices = mesh.vertices.copy()
    for vid, disp in vertex_displacement.items():
        new_vertices[vid] += disp

    mesh.vertices = new_vertices

    # Export as binary STL
    return mesh.export(file_type='stl')


# ---------- Auto-Orient ----------

def _compute_boundary_plane_normal(points: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """
    Compute the plane normal of a boundary loop via PCA.

    Returns:
        (normal, centroid) — normal is the eigenvector with smallest eigenvalue.
    """
    centroid = points.mean(axis=0)
    centered = points - centroid
    cov = centered.T @ centered
    eigenvalues, eigenvectors = np.linalg.eigh(cov)
    # Smallest eigenvalue = normal direction
    normal = eigenvectors[:, 0]
    return normal, centroid


def auto_orient_mesh(
    mesh: trimesh.Trimesh,
    boundary_points: np.ndarray,
) -> trimesh.Trimesh:
    """
    Rotate mesh so the main boundary opening faces downward (-Z).

    Uses PCA on boundary loop to find the plane normal, determines
    which side the mesh body is on, then rotates so the opening
    points in -Z direction.

    Args:
        mesh: The mesh to orient.
        boundary_points: (N, 3) main boundary loop points.

    Returns:
        The mesh (modified in-place) after rotation.
    """
    from scipy.spatial.transform import Rotation

    normal, boundary_centroid = _compute_boundary_plane_normal(boundary_points)

    # Normal should point outward (away from mesh body, through the opening).
    # Compare with vector from boundary centroid to mesh centroid.
    mesh_centroid = mesh.vertices.mean(axis=0)
    to_mesh = mesh_centroid - boundary_centroid

    if np.dot(normal, to_mesh) > 0:
        # Normal points toward mesh body — flip it
        normal = -normal

    # Target: opening faces -Z
    target = np.array([0.0, 0.0, -1.0])

    dot = np.dot(normal, target)
    if dot > 0.9999:
        # Already facing down
        return mesh

    if dot < -0.9999:
        # Exactly opposite — rotate 180° around X
        rot = Rotation.from_rotvec([np.pi, 0, 0])
    else:
        axis = np.cross(normal, target)
        axis = axis / np.linalg.norm(axis)
        angle = np.arccos(np.clip(dot, -1.0, 1.0))
        rot = Rotation.from_rotvec(axis * angle)

    # Rotate around mesh centroid so model stays centered
    vertices = mesh.vertices - mesh_centroid
    vertices = rot.apply(vertices)
    vertices += mesh_centroid
    mesh.vertices = vertices

    # Shift so bottom sits on Z=0
    mesh.vertices[:, 2] -= mesh.vertices[:, 2].min()

    return mesh


# ---------- Base Generation ----------

def generate_base(
    mesh_path: str | Path,
    elevation: float = 0.0,
) -> bytes:
    """
    Generate a base for a dental mesh.

    1. Load mesh, detect boundary, auto-orient so opening faces down
    2. Lift mesh by elevation (gap between model bottom and platform)
    3. Re-detect boundary after orientation
    4. Create wall mesh: triangulate between boundary loop and its Z-projection
    5. Create bottom face: earcut triangulate the projected 2D polygon
    6. Merge original + wall + bottom into one mesh

    Args:
        mesh_path: Path to STL file.
        elevation: Distance (mm) between model bottom and platform (min 0.1).

    Returns:
        Combined mesh as STL bytes.
    """
    from mapbox_earcut import triangulate_float64

    mesh = load_mesh(mesh_path)
    mesh = clean_mesh(mesh)

    # Detect boundary for orientation
    boundary_edges = extract_boundary_edges(mesh)
    loops = build_boundary_loops(mesh, boundary_edges)
    if not loops:
        raise ValueError("No boundary loops found on mesh")
    loops.sort(key=lambda l: l.perimeter, reverse=True)

    # Auto-orient using main boundary loop
    mesh = auto_orient_mesh(mesh, loops[0].points)

    # Lift mesh by elevation so boundary points are above Z=0
    effective_elevation = max(elevation, 0.1)
    mesh.vertices[:, 2] += effective_elevation

    # Re-detect boundary on the oriented mesh to get updated points
    boundary_edges = extract_boundary_edges(mesh)
    loops = build_boundary_loops(mesh, boundary_edges)
    if not loops:
        raise ValueError("No boundary loops found after orientation")
    loops.sort(key=lambda l: l.perimeter, reverse=True)
    boundary = loops[0].points

    n = len(boundary)

    # Ensure boundary is CCW in XY so we can use a single winding convention
    signed_area = 0.0
    for i in range(n):
        j = (i + 1) % n
        signed_area += boundary[i, 0] * boundary[j, 1] - boundary[j, 0] * boundary[i, 1]
    if signed_area < 0:
        boundary = boundary[::-1]

    # Project boundary down to Z=0 (mesh was shifted so bottom sits on Z=0)
    bottom = boundary.copy()
    bottom[:, 2] = 0.0

    # --- Wall mesh ---
    # Vertices: boundary (top) + bottom, total 2*n
    wall_verts = np.vstack([boundary, bottom])  # [0..n-1] = top, [n..2n-1] = bottom

    # CCW loop: [i, n+i, j] produces outward-pointing wall normals
    wall_faces = []
    for i in range(n):
        j = (i + 1) % n
        wall_faces.append([i, n + i, j])
        wall_faces.append([j, n + i, n + j])
    wall_faces = np.array(wall_faces, dtype=np.int64)

    wall_mesh = trimesh.Trimesh(vertices=wall_verts, faces=wall_faces, process=False)

    # --- Bottom face ---
    # Earcut on CCW polygon → CCW triangles → normal +Z → flip to -Z (down)
    bottom_2d = bottom[:, :2].copy()
    rings = np.array([n])
    tri_indices = triangulate_float64(bottom_2d, rings)
    bottom_faces = tri_indices.reshape(-1, 3)
    bottom_faces = bottom_faces[:, ::-1]

    bottom_mesh = trimesh.Trimesh(vertices=bottom, faces=bottom_faces, process=False)

    # --- Merge all ---
    combined = trimesh.util.concatenate([mesh, wall_mesh, bottom_mesh])

    return combined.export(file_type='stl')


# ---------- Main Boundary Selection ----------

def select_main_boundary(loops: list[BoundaryLoop]) -> int:
    """
    Select the main boundary loop.

    V1 heuristic: largest perimeter wins.

    Returns:
        Index into the loops list.
    """
    if not loops:
        return -1
    return int(np.argmax([loop.perimeter for loop in loops]))


# ---------- Full Pipeline ----------

def detect_boundary(
    mesh_path: str | Path,
    min_component_faces: int = 100,
) -> BoundaryDetectionResult:
    """
    Full pipeline: load → clean → extract → chain → select.

    Args:
        mesh_path: Path to STL/OBJ/PLY file.
        min_component_faces: Minimum faces for a component to be kept.

    Returns:
        BoundaryDetectionResult with all loops and main loop index.
    """
    mesh = load_mesh(mesh_path)
    mesh = clean_mesh(mesh, min_component_faces=min_component_faces)

    boundary_edges = extract_boundary_edges(mesh)
    loops = build_boundary_loops(mesh, boundary_edges)

    # Sort loops by perimeter (largest first)
    loops.sort(key=lambda l: l.perimeter, reverse=True)

    main_idx = select_main_boundary(loops)

    return BoundaryDetectionResult(
        total_boundary_edges=len(boundary_edges),
        loops=loops,
        main_loop_index=main_idx,
    )


def print_detection_summary(result: BoundaryDetectionResult) -> None:
    """Print a human-readable summary of boundary detection results."""
    print(f"Boundary edges: {result.total_boundary_edges}")
    print(f"Loops found: {len(result.loops)}")
    for i, loop in enumerate(result.loops):
        marker = " ← MAIN" if i == result.main_loop_index else ""
        print(
            f"  Loop {i}: {len(loop.vertex_indices)} vertices, "
            f"perimeter={loop.perimeter:.2f}mm, "
            f"centroid=({loop.centroid[0]:.1f}, {loop.centroid[1]:.1f}, {loop.centroid[2]:.1f})"
            f"{marker}"
        )


# ---------- CLI ----------

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python boundary_detection.py <mesh_file>")
        sys.exit(1)

    result = detect_boundary(sys.argv[1])
    print_detection_summary(result)
