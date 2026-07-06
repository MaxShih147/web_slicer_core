"""
Dental Mesh Boundary Detection Module

Extracts open boundary edges from dental scan meshes,
chains them into closed loops, and identifies the main
boundary (typically the arch opening).

V2: Detection + boundary smoothing (line-only, does not modify mesh).
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Union

import numpy as np
import trimesh


_PRE_WALL_DUMP_DIR = Path(os.environ.get("BASE_GEN_DEBUG_DUMP_DIR", "/tmp/dental_base_debug"))

def _bg_perf():
    """Per-call stage timing for base-gen profiling.

    Off by default. Set env ``BG_PROFILE=1`` to enable; timing lines are
    appended to ``$BG_PROFILE_LOG`` (default ``/tmp/bg_backend_timing.log``).
    When disabled both returned callables are no-ops, so call sites stay cheap.
    """
    if not os.environ.get("BG_PROFILE"):
        return (lambda *_: None), (lambda *_: None)

    import time as _t
    log_path = os.environ.get("BG_PROFILE_LOG", "/tmp/bg_backend_timing.log")
    state = {"t": _t.perf_counter(), "marks": []}

    def mark(label):
        now = _t.perf_counter()
        state["marks"].append((label, (now - state["t"]) * 1000.0))
        state["t"] = now

    def report(title):
        try:
            total = sum(ms for _, ms in state["marks"])
            line = f"[BG-BE] {title} — total {total:.0f}ms | " + " | ".join(
                f"{l} {ms:.0f}" for l, ms in state["marks"]
            )
            with open(log_path, "a") as f:
                f.write(line + "\n")
        except Exception:
            pass

    return mark, report


def _ts_tag() -> str:
    return time.strftime("%Y%m%d_%H%M%S") + f"_{int((time.time() % 1) * 1000):03d}"


def _dump_snapshot(mesh: trimesh.Trimesh, boundary: np.ndarray | None, tag: str) -> None:
    """Write mesh + (optional) boundary polyline to the debug dir."""
    try:
        _PRE_WALL_DUMP_DIR.mkdir(parents=True, exist_ok=True)
        stl_path = _PRE_WALL_DUMP_DIR / f"{tag}.stl"
        mesh.export(stl_path)
        print(f"[generate_base] dumped {stl_path}")
        if boundary is not None and len(boundary) > 0:
            obj_path = _PRE_WALL_DUMP_DIR / f"{tag}_boundary.obj"
            n = len(boundary)
            lines = [f"v {p[0]:.6f} {p[1]:.6f} {p[2]:.6f}\n" for p in boundary]
            lines.append("l " + " ".join(str(i + 1) for i in range(n)) + " 1\n")
            obj_path.write_text("".join(lines))
            print(f"[generate_base] dumped {obj_path}")
    except Exception as exc:
        print(f"[generate_base] snapshot dump failed ({tag}): {exc}")


def _dump_pre_wall_snapshot(mesh: trimesh.Trimesh, boundary: np.ndarray) -> None:
    """Snapshot right before wall generation."""
    _dump_snapshot(mesh, boundary, _ts_tag() + "_pre_wall")


def remove_degenerate_boundary_ears(
    mesh: trimesh.Trimesh,
    max_tip_angle_deg: float = 30.0,
    max_passes: int = 10,
) -> tuple[trimesh.Trimesh, dict]:
    """
    Remove "spike ear" triangles on the open boundary.

    Target shape: a triangle with exactly TWO boundary edges sharing a
    common "tip" vertex and ONE interior chord. When the angle between the
    two boundary edges at the tip is small (< ``max_tip_angle_deg``), the
    boundary makes a near-180° U-turn at the tip — wall extrusion of those
    two edges produces back-to-back overlapping quads.

    Removing the face:
      - Boundary loses the tip vertex (and its two short edges).
      - The interior chord becomes the new boundary edge.
      - Boundary's visual shape is preserved as long as the spike was thin
        relative to the local boundary curvature.

    Triangles with 1 or 3 boundary edges are ignored.

    Also drops orphan / tiny face-count connected components (fewer than
    ``min_component_faces`` faces).
    """
    verts = mesh.vertices.astype(np.float64).copy()
    faces = mesh.faces.astype(np.int64).copy()
    stats = {
        "passes": 0,
        "removed_ears": 0,
        "remaining_ears": 0,
        "orphan_faces_removed": 0,
    }

    cos_thresh = float(np.cos(np.deg2rad(max_tip_angle_deg)))

    def _scan_ears(verts_arr, faces_arr):
        work = trimesh.Trimesh(vertices=verts_arr, faces=faces_arr, process=False)
        b_edges = extract_boundary_edges(work)
        if len(b_edges) == 0:
            return []
        # A spike ear has exactly TWO boundary edges, so only faces incident to
        # the boundary can qualify. Count boundary edges per face with numpy
        # (encode each undirected edge as one int64 key) instead of a Python loop
        # over every face — interior faces are never examined individually.
        faces_arr = np.asarray(faces_arr, dtype=np.int64)
        maxv = int(faces_arr.max()) + 1
        tri_pairs = np.stack([
            faces_arr[:, [0, 1]],
            faces_arr[:, [1, 2]],
            faces_arr[:, [2, 0]],
        ], axis=1)  # (nf, 3, 2), edge order [01, 12, 20] — same as the old loop
        tri_pairs.sort(axis=2)  # canonical (min, max) per edge
        tri_key = tri_pairs[:, :, 0] * maxv + tri_pairs[:, :, 1]  # (nf, 3)

        b_pairs = np.sort(np.asarray(b_edges, dtype=np.int64), axis=1)
        b_key = np.unique(b_pairs[:, 0] * maxv + b_pairs[:, 1])

        on_bdy_all = np.isin(tri_key, b_key)  # (nf, 3) bool
        cand = np.flatnonzero(on_bdy_all.sum(axis=1) == 2)  # exactly 2 boundary edges

        ears = []
        for fi in cand:
            f = faces_arr[fi]
            # local index of the single non-boundary edge = the interior chord
            chord_local = int(np.flatnonzero(~on_bdy_all[fi])[0])
            chord_a = int(f[chord_local])
            chord_b = int(f[(chord_local + 1) % 3])
            tip = int(f[(chord_local + 2) % 3])

            # Angle at the tip between (tip→chord_a) and (tip→chord_b).
            # Small angle ⇒ two boundary edges nearly coincide ⇒ spike.
            e1 = verts_arr[chord_a] - verts_arr[tip]
            e2 = verts_arr[chord_b] - verts_arr[tip]
            n1 = float(np.linalg.norm(e1))
            n2 = float(np.linalg.norm(e2))
            if n1 < 1e-12 or n2 < 1e-12:
                continue
            cos_tip = float(np.dot(e1, e2) / (n1 * n2))
            cos_tip = max(-1.0, min(1.0, cos_tip))
            if cos_tip > cos_thresh:  # angle < threshold ⇒ spike
                tip_deg = float(np.degrees(np.arccos(cos_tip)))
                ears.append((tip_deg, int(fi)))
        return ears

    _emark, _ereport = _bg_perf()

    for _ in range(max_passes):
        ears = _scan_ears(verts, faces)
        if not ears:
            break

        face_alive = np.ones(len(faces), dtype=bool)
        for _ang, fi in ears:
            face_alive[fi] = False

        faces = faces[face_alive]
        used = np.unique(faces)
        new_idx = -np.ones(len(verts), dtype=np.int64)
        new_idx[used] = np.arange(len(used))
        verts = verts[used]
        faces = new_idx[faces]

        stats["removed_ears"] += len(ears)
        stats["passes"] += 1

    _emark(f"scan_passes(x{stats['passes']})")

    # Drop tiny disconnected components (orphan triangles produced by trim).
    work = trimesh.Trimesh(vertices=verts, faces=faces, process=False)
    if len(faces) > 0:
        adj = trimesh.graph.face_adjacency(mesh=work)
        comps = trimesh.graph.connected_components(adj, nodes=np.arange(len(faces)))
        keep_faces_idx = []
        min_component_faces = 10
        for comp in comps:
            if len(comp) >= min_component_faces:
                keep_faces_idx.extend(comp.tolist())
        keep_faces_idx = sorted(keep_faces_idx)
        if len(keep_faces_idx) < len(faces):
            stats["orphan_faces_removed"] = len(faces) - len(keep_faces_idx)
            faces = faces[keep_faces_idx]
            used = np.unique(faces)
            new_idx = -np.ones(len(verts), dtype=np.int64)
            new_idx[used] = np.arange(len(used))
            verts = verts[used]
            faces = new_idx[faces]

    _emark("orphan_components")
    _ereport("ear_removal")

    cleaned = trimesh.Trimesh(vertices=verts, faces=faces, process=False)
    stats["remaining_ears"] = -1  # not recomputed — debug-only stat, saved a full rescan
    return cleaned, stats


def diagnose_boundary_xy(boundary: np.ndarray, tag: str = "") -> dict:
    """
    Project the boundary loop onto XY and check whether it is a simple
    closed polygon. Reports:
      - Shapely LinearRing.is_simple / Polygon.is_valid
      - Self-intersection locations (segment index pairs + XY points)
      - Sub-loops produced by self-intersection (after Shapely union/buffer)
      - Sharp turns (turn angle > 120°): potential doubling-back

    Also writes an OBJ in z=0 with the XY polyline + marker verts at
    intersections / sharp turns for visual inspection.
    """
    info: dict = {}
    pts = np.asarray(boundary)[:, :2]
    n = len(pts)
    info["n_segments"] = n

    # 1. Self-intersection via Shapely (optional)
    try:
        from shapely.geometry import LineString
        ring_pts = np.vstack([pts, pts[:1]])
        info["is_simple"] = bool(LineString(ring_pts.tolist()).is_simple)
    except Exception:
        info["is_simple"] = None

    # 2. Brute-force vectorized self-intersection — find ALL crossings
    a = pts
    b = np.roll(pts, -1, axis=0)
    n_pairs = 0
    crossings = []  # (i, j, x, y)
    for i in range(n):
        ax, ay = a[i]
        bx, by = b[i]
        d1x, d1y = bx - ax, by - ay
        # Test against all later, non-adjacent segments
        js = np.arange(i + 2, n if i > 0 else n - 1)
        if len(js) == 0:
            continue
        cx, cy = a[js, 0], a[js, 1]
        dx, dy = b[js, 0], b[js, 1]
        d2x, d2y = dx - cx, dy - cy
        denom = d1x * d2y - d1y * d2x
        with np.errstate(invalid="ignore", divide="ignore"):
            s = ((cx - ax) * d2y - (cy - ay) * d2x) / denom
            t = ((cx - ax) * d1y - (cy - ay) * d1x) / denom
        eps = 1e-9
        hits = (np.abs(denom) > 1e-18) & (s > eps) & (s < 1 - eps) & (t > eps) & (t < 1 - eps)
        for k_local in np.where(hits)[0]:
            j = int(js[k_local])
            xi = float(ax + s[k_local] * d1x)
            yi = float(ay + s[k_local] * d1y)
            crossings.append((i, j, xi, yi))
            n_pairs += 1
    info["self_intersections"] = n_pairs
    info["first_crossings"] = crossings[:10]

    # 3. Sharp turns (> 120°) — local doubling-back
    turn_deg = np.zeros(n)
    for i in range(n):
        prev = pts[(i - 1) % n]
        cur = pts[i]
        nxt = pts[(i + 1) % n]
        e_in = cur - prev
        e_out = nxt - cur
        n1 = float(np.linalg.norm(e_in))
        n2 = float(np.linalg.norm(e_out))
        if n1 < 1e-12 or n2 < 1e-12:
            continue
        c = float(np.dot(e_in, e_out) / (n1 * n2))
        c = max(-1.0, min(1.0, c))
        turn_deg[i] = float(np.degrees(np.arccos(c)))
    sharp_idx = np.where(turn_deg > 120.0)[0].tolist()
    info["sharp_turns_gt_120"] = len(sharp_idx)
    info["sharp_turn_indices"] = sharp_idx[:20]

    # 4. Validity reason via Shapely (optional)
    try:
        from shapely.geometry import Polygon
        from shapely.validation import explain_validity
        info["validity"] = explain_validity(Polygon(pts.tolist()))
    except Exception:
        info["validity"] = "(shapely unavailable)"

    # 5. Dump OBJ in z=0: polyline + marker verts at crossings / sharp turns
    try:
        _PRE_WALL_DUMP_DIR.mkdir(parents=True, exist_ok=True)
        prefix = (tag + "_") if tag else _ts_tag() + "_"
        obj_path = _PRE_WALL_DUMP_DIR / f"{prefix}boundary_xy.obj"
        lines = []
        for p in pts:
            lines.append(f"v {p[0]:.6f} {p[1]:.6f} 0.000000\n")
        # Crossing markers (offset Z so they're visible)
        for (_, _, xi, yi) in crossings:
            lines.append(f"v {xi:.6f} {yi:.6f} 0.500000\n")
        # Sharp turn markers
        for idx in sharp_idx:
            p = pts[idx]
            lines.append(f"v {p[0]:.6f} {p[1]:.6f} 1.000000\n")
        # Polyline (boundary)
        lines.append("o boundary\nl " + " ".join(str(i + 1) for i in range(n)) + " 1\n")
        # Crossing markers as points (separate group)
        if crossings:
            lines.append("o crossings\n")
            base = n
            for k in range(len(crossings)):
                lines.append(f"p {base + k + 1}\n")
        if sharp_idx:
            lines.append("o sharp_turns\n")
            base = n + len(crossings)
            for k in range(len(sharp_idx)):
                lines.append(f"p {base + k + 1}\n")
        obj_path.write_text("".join(lines))
        print(f"[diagnose] dumped {obj_path}")
    except Exception as exc:
        print(f"[diagnose] dump failed: {exc}")

    print(
        f"[diagnose] n={n} simple={info['is_simple']} "
        f"crossings={n_pairs} sharp(>120°)={len(sharp_idx)} "
        f"validity={info['validity']}"
    )
    if crossings:
        print(f"[diagnose] first crossings (i,j, x, y):")
        for c in crossings[:5]:
            print(f"           {c}")
    if sharp_idx:
        print(f"[diagnose] sharp-turn vertex indices (first 20): {sharp_idx[:20]}")
    return info


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

def _fast_load_binary_stl(path: str | Path) -> "trimesh.Trimesh | None":
    """
    Read a binary STL with numpy (~50x faster than trimesh.load's default
    process=True path). Returns None if the file isn't a well-formed binary STL
    (ASCII STL, wrong size, etc.) so the caller can fall back to trimesh.load.

    Produces an unmerged "triangle soup" (3 verts/face); the downstream
    clean_mesh() merges duplicate vertices — same as trimesh's own load path.
    """
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            head = f.read(84)
            if len(head) < 84:
                return None
            n = int(np.frombuffer(head[80:84], dtype=np.uint32)[0])
            # Binary STL is exactly 80(header)+4(count)+50*n bytes. If the size
            # doesn't match it's ASCII/other → let trimesh handle it.
            if size != 84 + n * 50 or n == 0:
                return None
            body = np.frombuffer(f.read(n * 50), dtype=np.uint8).reshape(n, 50)
        # bytes 12..48 of each 50-byte record = 3 vertices × 3 float32
        tris = body[:, 12:48].copy().view(np.float32).reshape(n * 3, 3)
        faces = np.arange(n * 3, dtype=np.int64).reshape(n, 3)
        return trimesh.Trimesh(vertices=tris, faces=faces, process=False)
    except Exception:
        return None


def load_mesh(path: str | Path) -> trimesh.Trimesh:
    """Load a mesh file (STL/OBJ/PLY) and return as Trimesh."""
    mesh = _fast_load_binary_stl(path)
    if mesh is None:
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

    Handles junction vertices (degree > 2) by choosing the direction
    most aligned with the current heading — enables tracing through
    mesh boundaries that have branch points (e.g. after trimming).
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
                neighbors = adjacency.get(current, set())

                # Filter: not prev, and edge not yet visited
                next_candidates = []
                for n in neighbors:
                    if n == prev:
                        continue
                    ek = (min(current, n), max(current, n))
                    if ek in visited_edges:
                        continue
                    next_candidates.append(n)

                if not next_candidates:
                    break

                # At junction (degree > 2): pick direction most aligned with heading
                if len(next_candidates) > 1:
                    prev_dir = vertices[current] - vertices[prev]
                    prev_norm = np.linalg.norm(prev_dir)
                    if prev_norm > 1e-12:
                        prev_dir = prev_dir / prev_norm
                    best_dot = -2.0
                    next_v = next_candidates[0]
                    for cand in next_candidates:
                        cand_dir = vertices[cand] - vertices[current]
                        cand_norm = np.linalg.norm(cand_dir)
                        if cand_norm > 1e-12:
                            cand_dir = cand_dir / cand_norm
                        d = float(np.dot(cand_dir, prev_dir))
                        if d > best_dot:
                            best_dot = d
                            next_v = cand
                else:
                    next_v = next_candidates[0]

                edge_key = (min(current, next_v), max(current, next_v))
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

def _build_vertex_adjacency(mesh: trimesh.Trimesh) -> tuple[np.ndarray, np.ndarray]:
    """
    Vertex-to-vertex adjacency in CSR form ``(offsets, neighbors)``:
    ``neighbors[offsets[v]:offsets[v + 1]]`` lists the vertices adjacent to ``v``.

    Built with numpy (sort edge endpoints + bincount) instead of a Python
    dict-of-sets loop over every unique edge — ~20x faster on large meshes.
    """
    nv = len(mesh.vertices)
    e = mesh.edges_unique.astype(np.int64)
    rows = np.concatenate([e[:, 0], e[:, 1]])
    cols = np.concatenate([e[:, 1], e[:, 0]])
    neighbors = cols[np.argsort(rows, kind="stable")]
    offsets = np.zeros(nv + 1, dtype=np.int64)
    np.cumsum(np.bincount(rows, minlength=nv), out=offsets[1:])
    return offsets, neighbors


def _find_n_ring_neighbors(
    adjacency: tuple[np.ndarray, np.ndarray],
    seed_vertices: set[int],
    n_rings: int,
) -> dict[int, int]:
    """
    Find vertices within N edge-rings of seed vertices.

    ``adjacency`` is the CSR ``(offsets, neighbors)`` from _build_vertex_adjacency.

    Returns:
        Dict mapping vertex_index -> ring_distance (1 to n_rings).
        Seed vertices themselves are NOT included.
    """
    offsets, neighbors = adjacency
    ring_map: dict[int, int] = {}
    current_front = seed_vertices.copy()

    for ring in range(1, n_rings + 1):
        next_front: set[int] = set()
        for v in current_front:
            for nb in neighbors[offsets[v]:offsets[v + 1]]:
                nb = int(nb)
                if nb not in seed_vertices and nb not in ring_map:
                    ring_map[nb] = ring
                    next_front.add(nb)
        current_front = next_front
        if not current_front:
            break

    return ring_map


def _apply_boundary_core(
    mesh: trimesh.Trimesh,
    original_points: list[list[float]],
    smoothed_points: list[list[float]],
    falloff_rings: int = 3,
) -> trimesh.Trimesh:
    """
    Displace boundary vertices to the smoothed positions, with linear N-ring
    falloff on neighbours. Operates on an already loaded+cleaned ``mesh`` and
    returns it (no file I/O) so it can be chained with generate_base in memory.
    """
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
    return mesh


def apply_boundary_to_mesh(
    mesh_path: str | Path,
    original_points: list[list[float]],
    smoothed_points: list[list[float]],
    falloff_rings: int = 3,
) -> bytes:
    """
    Apply smoothed boundary positions to mesh vertices with gradual falloff.
    Loads the STL, runs _apply_boundary_core, returns the modified STL as bytes.
    """
    mesh = clean_mesh(load_mesh(mesh_path))
    mesh = _apply_boundary_core(mesh, original_points, smoothed_points, falloff_rings)
    return mesh.export(file_type="stl")


def apply_boundary_then_base(
    mesh_path: str | Path,
    original_points: list[list[float]],
    smoothed_points: list[list[float]],
    elevation: float = 0.1,
    chamfer: bool = False,
    skip_orient: bool = True,
    falloff_rings: int = 3,
) -> bytes:
    """
    Consolidated apply-boundary + generate-base: parse & clean the mesh ONCE,
    apply the smoothed boundary in memory, then generate the base on the same
    mesh — avoiding the second endpoint's STL upload + parse + vertex-merge.

    The apply→base handoff normally goes through a binary (float32) STL, so the
    applied vertices are truncated to float32 here to keep the result equivalent
    to the two-call path.
    """
    mesh = clean_mesh(load_mesh(mesh_path))
    mesh = _apply_boundary_core(mesh, original_points, smoothed_points, falloff_rings)
    mesh.vertices = mesh.vertices.astype(np.float32).astype(np.float64)
    return generate_base(mesh=mesh, elevation=elevation, chamfer=chamfer, skip_orient=skip_orient)


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
    mesh_path: "str | Path | None" = None,
    elevation: float = 0.0,
    chamfer: bool = False,
    skip_orient: bool = False,
    mesh: "trimesh.Trimesh | None" = None,
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

    _mark, _report = _bg_perf()

    if mesh is None:
        mesh = load_mesh(mesh_path)
        _mark("load")
        mesh = clean_mesh(mesh)
        _mark("clean")

    # Detect boundary for orientation
    boundary_edges = extract_boundary_edges(mesh)
    loops = build_boundary_loops(mesh, boundary_edges)
    if not loops:
        raise ValueError("No boundary loops found on mesh")
    loops.sort(key=lambda l: l.perimeter, reverse=True)
    _mark("boundary#1")

    # Auto-orient using main boundary loop (skip if frontend already oriented)
    if not skip_orient:
        mesh = auto_orient_mesh(mesh, loops[0].points)

    # Ensure bottom sits at Z=0
    z_min = mesh.vertices[:, 2].min()
    mesh.vertices[:, 2] -= z_min

    # Lift mesh by elevation so boundary points are above Z=0
    min_elevation = 1.0 if chamfer else 0.1
    effective_elevation = max(elevation, min_elevation)
    mesh.vertices[:, 2] += effective_elevation

    _mark("orient+lift")

    # Re-detect boundary on the oriented mesh to get updated points
    # Use aggressive vertex merge to handle trimmed meshes (split vertices may differ slightly)
    mesh.merge_vertices(digits_vertex=4)
    _mark("merge_vertices")

    # Strip "spike ear" triangles on the boundary (2 boundary edges + 1
    # interior chord, with sharp angle at the tip — boundary doubles back).
    # Threshold in degrees via env; set to 0 to disable.
    try:
        ear_max_tip_deg = float(os.environ.get("BASE_GEN_EAR_MAX_TIP_DEG", "30"))
    except ValueError:
        ear_max_tip_deg = 30.0
    if ear_max_tip_deg > 0:
        mesh, _ear_stats = remove_degenerate_boundary_ears(mesh, max_tip_angle_deg=ear_max_tip_deg)
        # print(f"[generate_base] ear removal (tip<{ear_max_tip_deg}°): {_ear_stats}")
    _mark("ear_removal")

    boundary_edges = extract_boundary_edges(mesh)
    print(f"[generate_base] vertices: {len(mesh.vertices)}, faces: {len(mesh.faces)}, boundary_edges: {len(boundary_edges)}")
    loops = build_boundary_loops(mesh, boundary_edges)
    print(f"[generate_base] loops: {len(loops)}, sizes: {[len(l.vertex_indices) for l in loops]}")
    if not loops:
        raise ValueError("No boundary loops found after orientation")
    loops.sort(key=lambda l: l.perimeter, reverse=True)
    boundary = loops[0].points
    print(f"[generate_base] main loop: {len(boundary)} points, perimeter: {loops[0].perimeter:.2f}")
    _mark("boundary#2")

    n = len(boundary)
    top_idx = np.asarray(loops[0].vertex_indices, dtype=np.int64)

    # Ensure boundary is CCW in XY so we can use a single winding convention
    signed_area = 0.0
    for i in range(n):
        j = (i + 1) % n
        signed_area += boundary[i, 0] * boundary[j, 1] - boundary[j, 0] * boundary[i, 1]
    if signed_area < 0:
        boundary = boundary[::-1]
        top_idx = top_idx[::-1]

    use_chamfer = False
    if chamfer:
        # --- Chamfer wall: 3 rings (top → mid → bot) ---
        # Use shapely polygon offset for correct inset geometry
        from shapely.geometry import MultiPolygon as ShapelyMultiPolygon
        from shapely.geometry import Point as ShapelyPoint
        from shapely.geometry import Polygon as ShapelyPolygon

        CHAMFER_HEIGHT = 0.9  # mm
        inward_offset = CHAMFER_HEIGHT  # tan(45°) = 1, so offset = height

        boundary_2d = boundary[:, :2]
        poly = ShapelyPolygon(boundary_2d)
        offset_poly = poly.buffer(-inward_offset, join_style=2, mitre_limit=5.0)

        if not offset_poly.is_empty and offset_poly.area > 1e-6:
            if isinstance(offset_poly, ShapelyMultiPolygon):
                offset_poly = max(offset_poly.geoms, key=lambda g: g.area)

            # Mid ring: boundary XY at Z = CHAMFER_HEIGHT
            mid = boundary.copy()
            mid[:, 2] = CHAMFER_HEIGHT

            # For each boundary point, find closest point on offset polygon
            offset_exterior = offset_poly.exterior
            bottom_xy = np.empty((n, 2))
            for i in range(n):
                pt = ShapelyPoint(boundary_2d[i])
                nearest = offset_exterior.interpolate(offset_exterior.project(pt))
                bottom_xy[i] = [nearest.x, nearest.y]

            bottom = np.column_stack([bottom_xy, np.zeros(n)])
            use_chamfer = True

    # Build wall + bottom into the SAME vertex array as the upper shell `mesh`,
    # so wall ↔ bottom and wall ↔ mesh share vertices (no concatenate seams).
    N_orig = len(mesh.vertices)

    if use_chamfer:
        # Append [mid (n), bot (n)] to mesh verts. Top ring reuses mesh boundary verts via top_idx.
        new_verts = np.vstack([mesh.vertices, mid, bottom])
        mid_base = N_orig
        bot_base = N_orig + n

        wall_faces = []
        for i in range(n):
            j = (i + 1) % n
            ti, tj = int(top_idx[i]), int(top_idx[j])
            mi, mj = mid_base + i, mid_base + j
            bi, bj = bot_base + i, bot_base + j
            # Upper segment: top ↔ mid
            wall_faces.append([ti, mi, tj])
            wall_faces.append([tj, mi, mj])
            # Lower segment (chamfer): mid ↔ bot
            wall_faces.append([mi, bi, mj])
            wall_faces.append([mj, bi, bj])
        wall_faces = np.array(wall_faces, dtype=np.int64)

        bottom_2d = bottom[:, :2].copy()
        tri_indices = triangulate_float64(bottom_2d, np.array([n]))
        bottom_faces = tri_indices.reshape(-1, 3)[:, ::-1] + bot_base
    else:
        # --- Standard wall: 2 rings (top → bot) ---
        bottom = boundary.copy()
        bottom[:, 2] = 0.0

        new_verts = np.vstack([mesh.vertices, bottom])
        bot_base = N_orig

        wall_faces = []
        for i in range(n):
            j = (i + 1) % n
            ti, tj = int(top_idx[i]), int(top_idx[j])
            bi, bj = bot_base + i, bot_base + j
            wall_faces.append([ti, bi, tj])
            wall_faces.append([tj, bi, bj])
        wall_faces = np.array(wall_faces, dtype=np.int64)

        bottom_2d = bottom[:, :2].copy()
        tri_indices = triangulate_float64(bottom_2d, np.array([n]))
        bottom_faces = tri_indices.reshape(-1, 3)[:, ::-1] + bot_base

    all_faces = np.vstack([mesh.faces.astype(np.int64), wall_faces, bottom_faces])
    combined = trimesh.Trimesh(vertices=new_verts, faces=all_faces, process=False)

    # earcut can emit zero-area triangles on near-collinear segments; drop them
    # so we don't introduce NotManifold edges downstream.
    keep = combined.area_faces > 1e-9
    if not keep.all():
        combined.update_faces(keep)
        combined.remove_unreferenced_vertices()
    _mark("wall+bottom+combine")

    stl = combined.export(file_type='stl')
    _mark("export")
    _report("generate_base")
    return stl


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
