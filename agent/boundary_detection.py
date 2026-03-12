"""
Dental Mesh Boundary Detection Module

Extracts open boundary edges from dental scan meshes,
chains them into closed loops, and identifies the main
boundary (typically the arch opening).

V1: Detection and visualization only — no smoothing, no base generation.
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
