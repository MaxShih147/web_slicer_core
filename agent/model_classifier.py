"""Dental model type classification service."""

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, List, Optional, Tuple

import math

import numpy as np

if TYPE_CHECKING:
    import trimesh

logger = logging.getLogger(__name__)


class DentalModelType(str, Enum):
    DENTAL_MODEL = "dental_model"
    U_SHAPED_DENTAL_MODEL = "u_shaped_dental_model"
    CROWN = "crown"
    BRIDGE = "bridge"
    SPLINT = "splint"
    SURGICAL_GUIDE = "surgical_guide"
    INTRAORAL_SCAN = "intraoral_scan"
    OTHER = "other"


@dataclass
class ModelFeatures:
    """Extracted features from a dental mesh, used as input to classification.

    A field value of None means the extraction failed or produced no valid result.
    A value of 0 means the feature was successfully computed and equals zero
    (e.g. open_edge_count=0 means the mesh has no open boundaries).
    Derived ratio fields follow the same convention: None when any prerequisite
    is missing or when the denominator is effectively zero.

    flat_plane_candidate_found distinguishes algorithm failure (None) from
    "algorithm ran but found no candidate plane" (False).
    """

    # PCA (convex-hull area-weighted)
    axis_l1_mm: Optional[float] = None   # longest axis (mm)
    axis_l2_mm: Optional[float] = None   # second axis (mm)
    axis_l3_mm: Optional[float] = None   # shortest axis (mm)

    # Open boundary
    open_edge_count: Optional[int] = None
    boundary_loop_count: Optional[int] = None
    total_open_edge_length_mm: Optional[float] = None
    largest_loop_length_mm: Optional[float] = None

    # Flat plane
    flat_plane_candidate_found: Optional[bool] = None  # None=failed, False=no candidate, True=found
    flat_plane_area_mm2: Optional[float] = None
    flat_plane_area_ratio: Optional[float] = None
    flat_plane_face_count: Optional[int] = None
    flat_plane_one_side: Optional[bool] = None
    flat_plane_opposite_ratio: Optional[float] = None
    flat_plane_opposite_depth_mm: Optional[float] = None

    # Projection shape gap
    projection_hull_area_mm2: Optional[float] = None
    projection_occupied_area_mm2: Optional[float] = None
    projection_gap_area_mm2: Optional[float] = None
    projection_largest_gap_area_mm2: Optional[float] = None
    projection_gap_ratio: Optional[float] = None
    projection_largest_gap_ratio: Optional[float] = None
    projection_gap_components: Optional[int] = None
    projection_largest_gap_center_offset_ratio: Optional[float] = None
    projection_largest_gap_contact_mm: Optional[float] = None
    projection_largest_gap_contact_gt10: Optional[bool] = None
    projection_medium_holes: Optional[int] = None
    projection_medium_hole_area: Optional[float] = None
    projection_large_holes: Optional[int] = None
    projection_large_hole_area: Optional[float] = None

    # Derived ratios (computed centrally after all raw extractions)
    elongation_ratio: Optional[float] = None       # L1 / L2
    flatness_ratio: Optional[float] = None         # L2 / L3
    relative_thickness: Optional[float] = None     # L3 / L1
    largest_open_ratio: Optional[float] = None     # largest_loop_mm / L1
    total_open_ratio: Optional[float] = None       # total_open_edge_mm / L1

    # Lazy drill-hole detection (populated by classify_dental_model, not extract_model_features)
    drill_detection_ran: bool = False
    drill_detection_valid: Optional[bool] = None
    drill_hole_found: Optional[bool] = None
    drill_candidate_count: Optional[int] = None
    drill_detection_skip_reason: Optional[str] = None


@dataclass
class FeatureFlags:
    """Semantic flags derived from ModelFeatures for classification rules.

    All fields default to None.  Thresholds have not been calibrated from sample
    data yet — do not populate with guessed values.  Reserved for future use.
    """
    is_small_object: Optional[bool] = None
    is_full_arch_size: Optional[bool] = None
    is_elongated: Optional[bool] = None
    is_flat_object: Optional[bool] = None
    has_large_open_boundary: Optional[bool] = None
    has_strong_outer_flat_plane: Optional[bool] = None
    has_open_u_gap: Optional[bool] = None
    has_multiple_interior_holes: Optional[bool] = None


@dataclass
class ClassificationDecision:
    """Internal classification result including confidence and reasoning.

    Only model_type is exposed externally through classify_dental_model().
    confidence and primary_reasons are for logging and calibration only.
    """
    model_type: DentalModelType
    confidence: Optional[float]          # 0.0–1.0, None when features missing
    primary_reasons: List[str]           # top reasons driving the decision


# ---------------------------------------------------------------------------
# Low-level feature extraction algorithms
# ---------------------------------------------------------------------------

def convex_hull_area_weighted_pca_detail(mesh: "trimesh.Trimesh") -> dict:
    """Convex hull area-weighted PCA. Returns pca_axes alongside axis_lengths.

    Returns {"axis_lengths": (l0, l1, l2), "pca_axes": ndarray (3, 3)} where
    columns of pca_axes are eigenvectors sorted by descending projection range.
    """
    from scipy.spatial import ConvexHull

    verts = np.asarray(mesh.vertices, dtype=np.float64)
    hull = ConvexHull(verts)

    hull_tris = verts[hull.simplices]
    centroids = hull_tris.mean(axis=1)

    e1 = hull_tris[:, 1] - hull_tris[:, 0]
    e2 = hull_tris[:, 2] - hull_tris[:, 0]
    areas = np.linalg.norm(np.cross(e1, e2), axis=1) * 0.5

    total_area = areas.sum()
    if total_area < 1e-12:
        raise ValueError("convex hull has near-zero total area")

    w = areas / total_area
    weighted_mean = (w[:, None] * centroids).sum(axis=0)
    diff = centroids - weighted_mean
    cov = np.einsum("i,ij,ik->jk", w, diff, diff)

    _, eigenvectors = np.linalg.eigh(cov)
    eigenvectors = eigenvectors[:, ::-1]  # descending eigenvalue order

    hull_verts_proj = verts[hull.vertices] @ eigenvectors
    ranges = hull_verts_proj.max(axis=0) - hull_verts_proj.min(axis=0)
    order = np.argsort(ranges)[::-1]  # sort columns by descending projection range

    return {
        "axis_lengths": tuple(float(x) for x in ranges[order]),
        "pca_axes": eigenvectors[:, order],  # columns: axis_1, axis_2, axis_3
    }


def open_boundary_stats(mesh: "trimesh.Trimesh") -> dict:
    """Open-boundary edge statistics.

    Returns open_edge_count, boundary_loop_count,
    total_open_edge_length_mm, largest_loop_length_mm.
    """
    unique_edges = mesh.edges_unique
    counts       = np.bincount(mesh.edges_unique_inverse, minlength=len(unique_edges))
    bd_edges     = unique_edges[counts == 1]  # used by exactly one face → boundary

    open_edge_count = len(bd_edges)
    if open_edge_count == 0:
        return {
            "open_edge_count": 0,
            "boundary_loop_count": 0,
            "total_open_edge_length_mm": 0.0,
            "largest_loop_length_mm": 0.0,
        }

    verts = mesh.vertices
    edge_lens = np.linalg.norm(verts[bd_edges[:, 1]] - verts[bd_edges[:, 0]], axis=1)

    adj: dict = defaultdict(list)
    for i, (a, b) in enumerate(bd_edges):
        adj[int(a)].append(i)
        adj[int(b)].append(i)

    seen = np.zeros(open_edge_count, dtype=bool)
    component_lengths = []
    for start_ei in range(open_edge_count):
        if seen[start_ei]:
            continue
        stack = [start_ei]
        comp_len = 0.0
        while stack:
            ei = stack.pop()
            if seen[ei]:
                continue
            seen[ei] = True
            comp_len += float(edge_lens[ei])
            for v in (int(bd_edges[ei, 0]), int(bd_edges[ei, 1])):
                for nei_ei in adj[v]:
                    if not seen[nei_ei]:
                        stack.append(nei_ei)
        component_lengths.append(comp_len)

    return {
        "open_edge_count": open_edge_count,
        "boundary_loop_count": len(component_lengths),
        "total_open_edge_length_mm": float(edge_lens.sum()),
        "largest_loop_length_mm": max(component_lengths),
    }


def large_outer_flat_plane_stats(mesh: "trimesh.Trimesh") -> dict:
    """Largest near-coplanar face group + one-side vertex check.

    Groups faces by quantized normal and plane offset, finds the largest group
    by area, then checks whether almost all mesh vertices lie on one side.
    Returns an empty dict if no valid candidate is found.
    """
    normals   = mesh.face_normals                          # (M, 3)
    areas     = mesh.area_faces                            # (M,)
    centroids = mesh.vertices[mesh.faces].mean(axis=1)    # (M, 3)
    offsets   = np.einsum("ij,ij->i", normals, centroids) # plane offset per face

    # Quantize for grouping: normal to 2 dp, offset to nearest 0.2 mm
    OFFSET_STEP = 0.2
    qn = np.round(normals, 2)
    qo = np.round(offsets / OFFSET_STEP) * OFFSET_STEP

    weighted_normals   = normals   * areas[:, None]   # (M, 3) — computed once
    weighted_centroids = centroids * areas[:, None]   # (M, 3) — computed once

    # Vectorized grouping: replaces Python for-loop (M dict ops) with NumPy unique+bincount
    keys_matrix = np.column_stack([qn, qo[:, None]])          # (M, 4)
    _, inv, group_counts = np.unique(keys_matrix, axis=0,
                                      return_inverse=True, return_counts=True)
    n_groups = len(group_counts)
    if n_groups > 0:
        group_areas = np.bincount(inv, weights=areas, minlength=n_groups)
        group_wn = np.column_stack([
            np.bincount(inv, weights=weighted_normals[:, d], minlength=n_groups)
            for d in range(3)
        ])
        group_wc = np.column_stack([
            np.bincount(inv, weights=weighted_centroids[:, d], minlength=n_groups)
            for d in range(3)
        ])
        # Preserve first-seen tie-breaking: matches original dict insertion order + max()
        # first_seen[g] = lowest original face index belonging to group g
        first_seen = np.full(n_groups, len(normals), dtype=np.int64)
        np.minimum.at(first_seen, inv, np.arange(len(normals), dtype=np.int64))

    if n_groups == 0:
        return {}

    best_area_val      = float(group_areas.max())
    tie_mask           = group_areas == best_area_val
    tied_group_indices = np.where(tie_mask)[0]
    best_idx           = int(tied_group_indices[first_seen[tied_group_indices].argmin()])

    group_area = best_area_val
    face_count = int(group_counts[best_idx])

    avg_normal   = group_wn[best_idx] / group_area
    avg_centroid = group_wc[best_idx] / group_area
    n_norm = np.linalg.norm(avg_normal)
    if n_norm < 1e-9:
        return {}
    n_unit = avg_normal / n_norm

    # Signed distance of every vertex from the candidate plane
    verts  = mesh.vertices
    signed = (verts - avg_centroid) @ n_unit   # (N,)

    bbox_diag = float(np.linalg.norm(mesh.bounds[1] - mesh.bounds[0]))
    eps = max(0.05, bbox_diag * 0.001)

    n_verts   = len(verts)
    pos_count = int(np.sum(signed >  eps))
    neg_count = int(np.sum(signed < -eps))
    pos_ratio = pos_count / n_verts
    neg_ratio = neg_count / n_verts

    if neg_ratio <= pos_ratio:
        opposite_ratio    = neg_ratio
        opposite_depth_mm = float(max(0.0, -float(signed.min())))
    else:
        opposite_ratio    = pos_ratio
        opposite_depth_mm = float(max(0.0,  float(signed.max())))

    return {
        "area_mm2":         group_area,
        "area_ratio":       group_area / float(mesh.area),
        "face_count":       face_count,
        "one_side":         opposite_ratio <= 0.01,
        "opposite_ratio":   opposite_ratio,
        "opposite_depth_mm": opposite_depth_mm,
    }


def projection_shape_gap_stats(mesh: "trimesh.Trimesh", pca_axes: np.ndarray) -> dict:
    """2D projection gap analysis along the PCA minimum axis.

    Projects mesh onto the plane of axis_1 × axis_2 (two longest PCA axes),
    rasterises triangles and the 2D convex hull, then analyses the gap region
    (hull minus occupied) via 8-neighbour connected components.

    Returns a stats dict, or {"error": str, ...} on failure / safety guard.
    """
    from scipy.spatial import ConvexHull as _Hull2D, Delaunay as _Delaunay
    from scipy.ndimage import label as _label, binary_erosion as _bero, binary_dilation as _bdil

    GRID_SIZE = 0.5       # mm per cell
    MAX_CELLS = 2_000_000

    u = pca_axes[:, 0]   # longest axis  → 2D X
    v = pca_axes[:, 1]   # 2nd axis      → 2D Y

    verts3d = np.asarray(mesh.vertices, dtype=np.float64)
    pts2d = np.column_stack([verts3d @ u, verts3d @ v])  # (N, 2)

    x_min, y_min = pts2d.min(axis=0)
    x_max, y_max = pts2d.max(axis=0)
    width_mm  = x_max - x_min
    height_mm = y_max - y_min

    if width_mm < 1.0 or height_mm < 1.0:
        return {"error": "projection_bbox_too_small"}

    nx = int(np.ceil(width_mm  / GRID_SIZE)) + 2
    ny = int(np.ceil(height_mm / GRID_SIZE)) + 2

    if nx * ny > MAX_CELLS:
        return {"error": "grid_too_large", "cells": nx * ny}

    cx_arr = x_min + (np.arange(nx) + 0.5) * GRID_SIZE   # (nx,) X cell centres
    cy_arr = y_min + (np.arange(ny) + 0.5) * GRID_SIZE   # (ny,) Y cell centres

    # ----- 2D convex hull mask (vectorised via Delaunay) -----
    try:
        hull2d = _Hull2D(pts2d)
    except Exception:
        return {"error": "hull2d_failed"}

    hull_verts2d = pts2d[hull2d.vertices]
    try:
        hull_tri = _Delaunay(hull_verts2d)
    except Exception:
        return {"error": "hull_delaunay_failed"}

    grid_pts = np.column_stack([np.tile(cx_arr, ny), np.repeat(cy_arr, nx)])
    hull_mask = (hull_tri.find_simplex(grid_pts) >= 0).reshape(ny, nx)

    # ----- Occupied mask: tiered by 3D triangle size proxy -----
    # Size proxy = L∞ norm of the longest 3D edge; no sqrt, cheap to compute.
    occupied = np.zeros((ny, nx), dtype=bool)
    tri2d = pts2d[mesh.faces]          # (M, 3, 2)
    tri3d = verts3d[mesh.faces]        # (M, 3, 3)

    _e01 = np.abs(tri3d[:, 1] - tri3d[:, 0]).max(axis=1)
    _e12 = np.abs(tri3d[:, 2] - tri3d[:, 1]).max(axis=1)
    _e20 = np.abs(tri3d[:, 0] - tri3d[:, 2]).max(axis=1)
    tri_size = np.maximum(np.maximum(_e01, _e12), _e20)   # (M,)

    large_mask  = tri_size > 5.0
    medium_mask = (tri_size > 1.0) & ~large_mask
    small_mask  = ~large_mask & ~medium_mask

    n_large  = int(large_mask.sum())
    n_medium = int(medium_mask.sum())
    n_small  = int(small_mask.sum())

    # Small: batch-mark 3 vertices per triangle
    _small_pts = tri2d[small_mask].reshape(-1, 2)

    # Medium: batch-mark 3 vertices + centroid per triangle
    _med_tris = tri2d[medium_mask]
    if len(_med_tris) > 0:
        _med_pts = np.vstack([_med_tris.reshape(-1, 2), _med_tris.mean(axis=1)])
    else:
        _med_pts = np.empty((0, 2), dtype=np.float64)

    # Single vectorised write for all small + medium points
    _batch = np.vstack([_small_pts, _med_pts]) if (len(_small_pts) or len(_med_pts)) \
             else np.empty((0, 2), dtype=np.float64)
    if len(_batch):
        _bxi = np.floor((_batch[:, 0] - x_min) / GRID_SIZE).astype(int)
        _byi = np.floor((_batch[:, 1] - y_min) / GRID_SIZE).astype(int)
        _ok  = (_bxi >= 0) & (_bxi < nx) & (_byi >= 0) & (_byi < ny)
        occupied[_byi[_ok], _bxi[_ok]] = True

    # Large: full per-triangle barycentric rasterise (few triangles, worth it)
    for tri in tri2d[large_mask]:
        gx = (tri[:, 0] - x_min) / GRID_SIZE
        gy = (tri[:, 1] - y_min) / GRID_SIZE
        ci0 = max(0, int(gx.min()) - 1)
        ci1 = min(nx - 1, int(gx.max()) + 2)
        cj0 = max(0, int(gy.min()) - 1)
        cj1 = min(ny - 1, int(gy.max()) + 2)
        if ci0 > ci1 or cj0 > cj1:
            continue
        px, py = np.meshgrid(cx_arr[ci0:ci1 + 1], cy_arr[cj0:cj1 + 1])
        p0, p1, p2 = tri
        d1 = p1 - p0
        d2 = p2 - p0
        denom = d1[0] * d2[1] - d1[1] * d2[0]
        if abs(denom) < 1e-12:
            continue
        inv = 1.0 / denom
        dx = px - p0[0]; dy = py - p0[1]
        s = (dx * d2[1] - dy * d2[0]) * inv
        t = (dy * d1[0] - dx * d1[1]) * inv
        inside = (s >= 0) & (t >= 0) & (s + t <= 1)
        _rr, _cc = np.where(inside)
        occupied[_rr + cj0, _cc + ci0] = True

    # ----- Gap connected components (8-neighbour) -----
    gap_mask = hull_mask & ~occupied
    labeled, n_comp = _label(gap_mask, structure=np.ones((3, 3), dtype=int))

    cell_area      = GRID_SIZE ** 2
    hull_area      = int(hull_mask.sum()) * cell_area
    occupied_area  = int(occupied.sum())  * cell_area
    gap_area       = int(gap_mask.sum())  * cell_area

    # Largest gap component (track id for boundary-contact pass below)
    comp_counts = np.bincount(labeled.ravel())          # index 0 = background
    if n_comp > 0:
        largest_gap_id = int(np.argmax(comp_counts[1:n_comp + 1])) + 1
        largest_cells  = int(comp_counts[largest_gap_id])
    else:
        largest_gap_id = 0
        largest_cells  = 0
    largest_gap_mask = (labeled == largest_gap_id) if largest_gap_id > 0 \
                       else np.zeros_like(labeled, dtype=bool)
    if largest_cells > 0:
        _cj, _ci = np.where(largest_gap_mask)
        largest_cx = float(_ci.mean())
        largest_cy = float(_cj.mean())
    else:
        largest_cx = largest_cy = 0.0

    largest_gap_area = largest_cells * cell_area

    # Hull bbox centre and span for offset normalisation
    _hci = np.flatnonzero(np.any(hull_mask, axis=0))   # columns with hull cells
    _hcj = np.flatnonzero(np.any(hull_mask, axis=1))   # rows    with hull cells
    if len(_hci) > 0:
        hull_cx = (int(_hci[0]) + int(_hci[-1])) / 2.0
        hull_cy = (int(_hcj[0]) + int(_hcj[-1])) / 2.0
        hull_w  = (int(_hci[-1]) - int(_hci[0])) * GRID_SIZE
        hull_h  = (int(_hcj[-1]) - int(_hcj[0])) * GRID_SIZE
    else:
        hull_cx = nx / 2.0; hull_cy = ny / 2.0
        hull_w  = nx * GRID_SIZE; hull_h = ny * GRID_SIZE

    offset_mm = float(np.sqrt((largest_cx - hull_cx) ** 2 + (largest_cy - hull_cy) ** 2)) * GRID_SIZE
    center_offset_ratio = offset_mm / max(hull_w, hull_h, 1.0)

    # ----- Hull boundary contact & hole classification -----
    _structure = np.ones((3, 3), dtype=int)
    hull_boundary_mask = hull_mask & ~_bero(hull_mask, structure=_structure)

    _CONTACT_THRESH_MM = 10.0
    largest_gap_contact_mm = 0.0
    medium_holes = 0;  medium_hole_area = 0.0
    large_holes  = 0;  large_hole_area  = 0.0

    for _cid in range(1, n_comp + 1):
        _comp  = largest_gap_mask if _cid == largest_gap_id else (labeled == _cid)
        _area  = int(comp_counts[_cid]) * cell_area
        # Contact: dilate component 1 cell, intersect with hull boundary
        _contact_cells = int((_bdil(_comp, structure=_structure) & hull_boundary_mask).sum())
        _contact_mm    = _contact_cells * GRID_SIZE

        if _cid == largest_gap_id:
            largest_gap_contact_mm = _contact_mm

        # Only classify as interior hole when fully enclosed (no hull-boundary contact at all)
        is_boundary_connected = _contact_cells > 0
        if not is_boundary_connected:
            if 10.0 <= _area < 50.0:
                medium_holes     += 1
                medium_hole_area += _area
            elif 50.0 <= _area <= 300.0:
                large_holes     += 1
                large_hole_area += _area

    return {
        "hull_area_mm2":                   hull_area,
        "occupied_area_mm2":               occupied_area,
        "gap_area_mm2":                    gap_area,
        "largest_gap_area_mm2":            largest_gap_area,
        "gap_ratio":                       gap_area       / max(hull_area, 1e-9),
        "largest_gap_ratio":               largest_gap_area / max(hull_area, 1e-9),
        "gap_components":                  n_comp,
        "largest_gap_center_offset_ratio": center_offset_ratio,
        "largest_gap_contact_mm":          largest_gap_contact_mm,
        "largest_gap_contact_gt10":        largest_gap_contact_mm >= _CONTACT_THRESH_MM,
        "medium_holes":                    medium_holes,
        "medium_hole_area":                medium_hole_area,
        "large_holes":                     large_holes,
        "large_hole_area":                 large_hole_area,
        "grid_size_mm":                    GRID_SIZE,
        "tri_counts":                      (n_large, n_medium, n_small),
    }


# ---------------------------------------------------------------------------
# Feature aggregation and derived metrics
# ---------------------------------------------------------------------------

def _safe_ratio(num: Optional[float], den: Optional[float]) -> Optional[float]:
    """Return num/den, or None if either operand is missing or den is near zero."""
    if num is None or den is None or abs(den) < 1e-12:
        return None
    return num / den


def _compute_derived_ratios(features: ModelFeatures) -> None:
    """Fill derived ratio fields on features in-place after raw extraction."""
    l1 = features.axis_l1_mm
    l2 = features.axis_l2_mm
    l3 = features.axis_l3_mm
    features.elongation_ratio    = _safe_ratio(l1, l2)
    features.flatness_ratio      = _safe_ratio(l2, l3)
    features.relative_thickness  = _safe_ratio(l3, l1)
    features.largest_open_ratio  = _safe_ratio(features.largest_loop_length_mm, l1)
    features.total_open_ratio    = _safe_ratio(features.total_open_edge_length_mm, l1)



def extract_model_features(mesh: "trimesh.Trimesh") -> ModelFeatures:
    """Run all four feature extraction groups and return a populated ModelFeatures.

    Each extraction group is isolated: a failure in one group does not prevent
    the others from running.  PCA axes are kept as a local variable and passed
    to ProjectionShape; they are not exposed in ModelFeatures.
    Derived ratios are computed centrally after all raw extractions complete.
    """
    features = ModelFeatures()
    _pca_axes = None  # intermediate, required by ProjectionShape; not stored in features

    # ----- PCA -----
    try:
        _pca_detail = convex_hull_area_weighted_pca_detail(mesh)
        _axis_lens = _pca_detail["axis_lengths"]
        _pca_axes  = _pca_detail["pca_axes"]
        features.axis_l1_mm = _axis_lens[0]
        features.axis_l2_mm = _axis_lens[1]
        features.axis_l3_mm = _axis_lens[2]
    except Exception as _exc:
        logger.error("PCA extraction failed: %s", _exc)

    # ----- ProjectionShape -----
    try:
        if _pca_axes is None:
            raise ValueError("PCA axes not available")
        _ps = projection_shape_gap_stats(mesh, _pca_axes)
        if "error" in _ps:
            pass
        else:
            features.projection_hull_area_mm2                   = _ps["hull_area_mm2"]
            features.projection_occupied_area_mm2               = _ps["occupied_area_mm2"]
            features.projection_gap_area_mm2                    = _ps["gap_area_mm2"]
            features.projection_largest_gap_area_mm2            = _ps["largest_gap_area_mm2"]
            features.projection_gap_ratio                       = _ps["gap_ratio"]
            features.projection_largest_gap_ratio               = _ps["largest_gap_ratio"]
            features.projection_gap_components                  = _ps["gap_components"]
            features.projection_largest_gap_center_offset_ratio = _ps["largest_gap_center_offset_ratio"]
            features.projection_largest_gap_contact_mm          = _ps["largest_gap_contact_mm"]
            features.projection_largest_gap_contact_gt10        = _ps["largest_gap_contact_gt10"]
            features.projection_medium_holes                    = _ps["medium_holes"]
            features.projection_medium_hole_area                = _ps["medium_hole_area"]
            features.projection_large_holes                     = _ps["large_holes"]
            features.projection_large_hole_area                 = _ps["large_hole_area"]
    except Exception as _exc:
        logger.error("ProjectionShape extraction failed: %s", _exc)

    # ----- OpenBoundary -----
    try:
        _bd = open_boundary_stats(mesh)
        features.open_edge_count             = _bd["open_edge_count"]
        features.boundary_loop_count         = _bd["boundary_loop_count"]
        features.total_open_edge_length_mm   = _bd["total_open_edge_length_mm"]
        features.largest_loop_length_mm      = _bd["largest_loop_length_mm"]
    except Exception as _exc:
        logger.error("OpenBoundary extraction failed: %s", _exc)

    # ----- FlatPlane -----
    try:
        _fp = large_outer_flat_plane_stats(mesh)
        if _fp:
            features.flat_plane_candidate_found   = True
            features.flat_plane_area_mm2          = _fp["area_mm2"]
            features.flat_plane_area_ratio        = _fp["area_ratio"]
            features.flat_plane_face_count        = _fp["face_count"]
            features.flat_plane_one_side          = _fp["one_side"]
            features.flat_plane_opposite_ratio    = _fp["opposite_ratio"]
            features.flat_plane_opposite_depth_mm = _fp["opposite_depth_mm"]
        else:
            features.flat_plane_candidate_found = False
    except Exception as _exc:
        logger.error("FlatPlane extraction failed: %s", _exc)
        # flat_plane_candidate_found remains None → algorithm failure

    # Derived ratios (centrally computed; safe against missing fields and zero denominators)
    _compute_derived_ratios(features)

    return features


# ---------------------------------------------------------------------------
# FIRST VERSION CLASSIFICATION CALIBRATION CONSTANTS
# Initial values only — must be calibrated from sample data before relying on them.
# ---------------------------------------------------------------------------

# Small object thresholds (mm): full score up to max_value, linear falloff beyond
SMALL_L2_MAX_MM       = 11.0   # L2 ≤ this → full small-object score (1.0)
SMALL_L3_MAX_MM       = 11.0   # L3 ≤ this → full small-object score (1.0)
SMALL_SIZE_FALLOFF_MM =  5.0   # score reaches 0.0 at max + falloff = 16 mm

# Crown / Bridge L1 breakpoints (mm) — piecewise-linear
CROWN_L1_STRONG_MAX_MM   = 12.0  # L1 ≤ this → crown=1.0, bridge=0.0
CROWN_BRIDGE_L1_SPLIT_MM = 15.0  # L1 here  → crown=0.5, bridge=0.5
BRIDGE_L1_STRONG_MIN_MM  = 18.0  # L1 ≥ this → crown=0.0, bridge=1.0

# Bridge elongation (L1/L2 ratio) — unchanged
BRIDGE_ELONGATION_MIN = 1.4   # score ~0.5 at this ratio
BRIDGE_ELONGATION_TOL = 0.4   # score ~1.0 at MIN+TOL = 1.8

# Full arch size: valid range [min, max] with linear falloffs on each side
FULL_ARCH_L1_MIN_MM          = 45.0
FULL_ARCH_L1_MAX_MM          = 100.0
FULL_ARCH_L1_LOW_FALLOFF_MM  =   6.0  # 0.0 at 39 mm, 1.0 at 45 mm
FULL_ARCH_L1_HIGH_FALLOFF_MM =  15.0  # 1.0 at 100 mm, 0.0 at 115 mm

FULL_ARCH_L2_MIN_MM          = 30.0
FULL_ARCH_L2_MAX_MM          = 80.0
FULL_ARCH_L2_LOW_FALLOFF_MM  =  5.0   # 0.0 at 25 mm, 1.0 at 30 mm
FULL_ARCH_L2_HIGH_FALLOFF_MM = 15.0   # 1.0 at 80 mm, 0.0 at 95 mm

FULL_ARCH_L3_MIN_MM          = 12.0
FULL_ARCH_L3_MAX_MM          = 35.0
FULL_ARCH_L3_LOW_FALLOFF_MM  =  3.0   # 0.0 at 9 mm,  1.0 at 12 mm
FULL_ARCH_L3_HIGH_FALLOFF_MM =  5.0   # 1.0 at 35 mm, 0.0 at 40 mm

# Splint L3 range: thinner than a typical dental model base
SPLINT_L3_MIN_MM          =  8.0
SPLINT_L3_MAX_MM          = 12.0
SPLINT_L3_LOW_FALLOFF_MM  =  2.0   # 0.0 at 6 mm, 1.0 at 8 mm
SPLINT_L3_HIGH_FALLOFF_MM =  8.0   # 1.0 at 12 mm, 0.0 at 20 mm

# Base dental model L3 range: deeper than a splint, shallower than very tall arches
BASE_MODEL_L3_MIN_MM          = 20.0
BASE_MODEL_L3_MAX_MM          = 40.0
BASE_MODEL_L3_LOW_FALLOFF_MM  = 10.0  # 0.0 at 10 mm, 1.0 at 20 mm
BASE_MODEL_L3_HIGH_FALLOFF_MM = 15.0  # 1.0 at 40 mm, 0.0 at 55 mm

# Large open boundary thresholds
LARGE_OPEN_LOOP_MIN_MM = 30.0   # largest_loop_length_mm threshold
LARGE_OPEN_LOOP_TOL_MM = 10.0
LARGE_OPEN_RATIO_MIN   =  0.5   # largest_open_ratio threshold
LARGE_OPEN_RATIO_TOL   =  0.2

# Outer flat plane thresholds
FLAT_PLANE_AREA_RATIO_MIN = 0.05  # flat_plane_area_ratio threshold
FLAT_PLANE_AREA_RATIO_TOL = 0.02  # flat_plane_one_side must also be True

# U-shape (projection gap) thresholds
U_GAP_RATIO_MIN      = 0.20   # projection_largest_gap_ratio threshold
U_GAP_RATIO_TOL      = 0.10
U_GAP_CONTACT_MIN_MM = 10.0   # projection_largest_gap_contact_mm threshold
U_GAP_CONTACT_TOL_MM =  5.0

# Decision thresholds
CANDIDATE_GROUP_MIN = 0.55   # minimum score to enter a candidate group
STRONG_SIGNAL_MIN   = 0.65   # minimum score to treat a signal as strong
LOW_FEATURE_MAX     = 0.35   # maximum score to treat a feature as absent
CANDIDATE_MIN_GAP   = 0.10   # minimum margin between winner and runner-up

# Clear crown size: L1 ≤ max → full score; linear falloff beyond
CLEAR_CROWN_L1_MAX_MM    = 15.0
CLEAR_CROWN_L1_FALLOFF_MM =  3.0   # score 0.0 at L1 >= 18 mm

# Bridge size upper bounds (mm)
BRIDGE_L1_MAX_MM          = 45.0
BRIDGE_L1_HIGH_FALLOFF_MM = 10.0   # 1.0 at 45 mm, 0.0 at 55 mm
BRIDGE_L2_MAX_MM          = 45.0
BRIDGE_L2_HIGH_FALLOFF_MM = 10.0
BRIDGE_L3_MAX_MM          = 15.0
BRIDGE_L3_HIGH_FALLOFF_MM =  3.0   # 1.0 at 15 mm, 0.0 at 18 mm

# Strict base-plane exclusion threshold — used ONLY for skipping drill detection.
# Higher than the general flat-plane score threshold; not a replacement for it.
SURGICAL_GUIDE_EXCLUDE_BASE_PLANE_AREA_RATIO_MIN = 0.15

# U-shape split used inside the "confirmed base model" P4 branch
U_SHAPE_CLASSIFICATION_SPLIT = 0.50

# Confidence anchors for drill-detection-based outcomes
SURGICAL_GUIDE_DRILL_FOUND_CONFIDENCE       = 0.90
SURGICAL_GUIDE_DRILL_FAILED_CONFIDENCE      = 0.30
DRILL_FAILED_BRIDGE_CONFIDENCE_MAX          = 0.55
BRIDGE_DRILL_NEGATIVE_FALLBACK_CONFIDENCE          = 0.45
SURGICAL_GUIDE_NON_ONE_SIDED_PLANE_CONFIDENCE      = 0.55

# Crown/Bridge L1/L2 ratio breakpoints (dimensionless, asymmetric)
CROWN_BRIDGE_RATIO_CROWN_FULL_MAX  = 1.20  # ratio ≤ this → crown=1.0, bridge=0.0
CROWN_BRIDGE_RATIO_SPLIT           = 1.35  # ratio here  → crown=0.5, bridge=0.5
CROWN_BRIDGE_RATIO_BRIDGE_FULL_MIN = 1.80  # ratio ≥ this → crown=0.0, bridge=1.0


# ---------------------------------------------------------------------------
# Soft threshold helpers
# ---------------------------------------------------------------------------

def _soft_less_than(value: Optional[float], threshold: float, tolerance: float) -> float:
    """Score for value < threshold.  1.0 well below, 0.5 at threshold, 0.0 well above.
    None → 0.0.
    """
    if value is None:
        return 0.0
    if tolerance <= 0.0:
        return 1.0 if value < threshold else 0.0
    return max(0.0, min(1.0, (threshold + tolerance - value) / (2.0 * tolerance)))


def _soft_greater_than(value: Optional[float], threshold: float, tolerance: float) -> float:
    """Score for value > threshold.  1.0 well above, 0.5 at threshold, 0.0 well below.
    None → 0.0.
    """
    if value is None:
        return 0.0
    if tolerance <= 0.0:
        return 1.0 if value > threshold else 0.0
    return max(0.0, min(1.0, (value - threshold + tolerance) / (2.0 * tolerance)))


def _soft_between(
    value: Optional[float],
    lower: float, upper: float,
    lower_tolerance: float, upper_tolerance: float,
) -> float:
    """Score for lower < value < upper.  1.0 well inside, falls off at both edges.
    None → 0.0.
    """
    if value is None:
        return 0.0
    return min(
        _soft_greater_than(value, lower, lower_tolerance),
        _soft_less_than(value, upper, upper_tolerance),
    )


def _soft_max_with_falloff(value: Optional[float], max_value: float, falloff: float) -> float:
    """Score: 1.0 for value ≤ max_value, linear decay to 0.0 at max_value + falloff.
    None → 0.0.
    """
    if value is None:
        return 0.0
    if value <= max_value:
        return 1.0
    if falloff <= 0.0:
        return 0.0
    return max(0.0, 1.0 - (value - max_value) / falloff)


def _soft_range_with_falloff(
    value: Optional[float],
    lower: float, upper: float,
    lower_falloff: float, upper_falloff: float,
) -> float:
    """Score: 1.0 for lower ≤ value ≤ upper, linear falloff outside that range.
    None → 0.0.
    """
    if value is None:
        return 0.0
    if lower > upper:
        return 0.0
    if lower <= value <= upper:
        return 1.0
    if value < lower:
        if lower_falloff <= 0.0:
            return 0.0
        return max(0.0, 1.0 - (lower - value) / lower_falloff)
    if upper_falloff <= 0.0:
        return 0.0
    return max(0.0, 1.0 - (value - upper) / upper_falloff)


def _crown_bridge_length_scores(value: Optional[float]) -> "tuple[float, float]":
    """Piecewise-linear crown/bridge scores by L1.  None → (0.0, 0.0).

    Breakpoints: CROWN_L1_STRONG_MAX_MM=12 (crown=1, bridge=0),
                 CROWN_BRIDGE_L1_SPLIT_MM=15 (crown=0.5, bridge=0.5),
                 BRIDGE_L1_STRONG_MIN_MM=18 (crown=0, bridge=1).
    """
    if value is None:
        return (0.0, 0.0)
    v = value
    if v <= CROWN_L1_STRONG_MAX_MM:
        return (1.0, 0.0)
    if v >= BRIDGE_L1_STRONG_MIN_MM:
        return (0.0, 1.0)
    if v <= CROWN_BRIDGE_L1_SPLIT_MM:
        t = (v - CROWN_L1_STRONG_MAX_MM) / (CROWN_BRIDGE_L1_SPLIT_MM - CROWN_L1_STRONG_MAX_MM)
        return (max(0.0, 1.0 - 0.5 * t), max(0.0, 0.5 * t))
    t = (v - CROWN_BRIDGE_L1_SPLIT_MM) / (BRIDGE_L1_STRONG_MIN_MM - CROWN_BRIDGE_L1_SPLIT_MM)
    return (max(0.0, 0.5 - 0.5 * t), max(0.0, 0.5 + 0.5 * t))


def _crown_bridge_ratio_scores(value: Optional[float]) -> "tuple[float, float]":
    """Piecewise-linear crown/bridge scores by L1/L2 elongation ratio.  None → (0.0, 0.0).

    Asymmetric breakpoints:
      ratio ≤ 1.20 → crown=1.0, bridge=0.0
      ratio == 1.35 → crown=0.5, bridge=0.5
      ratio ≥ 1.80 → crown=0.0, bridge=1.0
    """
    if value is None:
        return (0.0, 0.0)
    v = value
    if v <= CROWN_BRIDGE_RATIO_CROWN_FULL_MAX:
        return (1.0, 0.0)
    if v >= CROWN_BRIDGE_RATIO_BRIDGE_FULL_MIN:
        return (0.0, 1.0)
    if v <= CROWN_BRIDGE_RATIO_SPLIT:
        t = (v - CROWN_BRIDGE_RATIO_CROWN_FULL_MAX) / (CROWN_BRIDGE_RATIO_SPLIT - CROWN_BRIDGE_RATIO_CROWN_FULL_MAX)
        return (max(0.0, 1.0 - 0.5 * t), max(0.0, 0.5 * t))
    t = (v - CROWN_BRIDGE_RATIO_SPLIT) / (CROWN_BRIDGE_RATIO_BRIDGE_FULL_MIN - CROWN_BRIDGE_RATIO_SPLIT)
    return (max(0.0, 0.5 - 0.5 * t), max(0.0, 0.5 + 0.5 * t))


# ---------------------------------------------------------------------------
# Classification signals
# ---------------------------------------------------------------------------

@dataclass
class _ClassificationSignals:
    """Soft-score signals computed from ModelFeatures, used internally by the classifier."""
    small_object_score: float          # L2 and L3 both small
    full_arch_size_score: float        # L1, L2, L3 all in full-arch range
    crown_length_score: float          # L1 biased toward crown range (small)
    bridge_length_score: float         # L1 biased toward bridge range (larger)
    elongated_score: float             # L1/L2 elongation ratio supports bridge
    large_open_boundary_score: float      # open boundary large in both absolute and relative terms
    flat_plane_size_score: float          # flat plane area score (regardless of one_side)
    one_sided_flat_plane_score: float     # flat_plane_size_score when flat_plane_one_side is True
    non_one_sided_flat_plane_score: float # flat_plane_size_score when flat_plane_one_side is False
    strong_outer_flat_plane_score: float  # alias for one_sided_flat_plane_score (kept for compatibility)
    u_shape_score: float               # projection gap large with hull-boundary contact
    splint_size_score: float           # L1, L2 in full-arch footprint; L3 in splint range
    bridge_size_score: float      # L1 in bridge range, L2/L3 within bridge cross-section
    clear_crown_size_score: float # three axes firmly small AND L1 biased toward crown
    base_model_size_score: float  # L1/L2 full-arch footprint + base-model-specific L3 range
    crown_ratio_score: float      # L1/L2 ratio biased toward crown
    bridge_ratio_score: float     # L1/L2 ratio biased toward bridge
    crown_small_score: float      # combines crown length + ratio, gated by small cross-section
    bridge_small_score: float     # combines bridge length + ratio, gated by small cross-section


def _compute_signals(features: ModelFeatures) -> _ClassificationSignals:
    """Compute all soft-score signals from ModelFeatures."""
    pca_valid            = features.axis_l1_mm is not None
    open_boundary_valid  = features.open_edge_count is not None
    projection_valid     = features.projection_largest_gap_ratio is not None
    flat_plane_ran       = features.flat_plane_candidate_found is not None

    # Small object: both cross-section axes must be small
    if pca_valid:
        _small_l2 = _soft_max_with_falloff(features.axis_l2_mm, SMALL_L2_MAX_MM, SMALL_SIZE_FALLOFF_MM)
        _small_l3 = _soft_max_with_falloff(features.axis_l3_mm, SMALL_L3_MAX_MM, SMALL_SIZE_FALLOFF_MM)
        small_object_score = min(_small_l2, _small_l3)
    else:
        _small_l2 = _small_l3 = 0.0
        small_object_score = 0.0

    # Full arch size / splint size: share L1 and L2 scores, differ in L3
    if pca_valid:
        s_l1 = _soft_range_with_falloff(
            features.axis_l1_mm,
            FULL_ARCH_L1_MIN_MM, FULL_ARCH_L1_MAX_MM,
            FULL_ARCH_L1_LOW_FALLOFF_MM, FULL_ARCH_L1_HIGH_FALLOFF_MM,
        )
        s_l2 = _soft_range_with_falloff(
            features.axis_l2_mm,
            FULL_ARCH_L2_MIN_MM, FULL_ARCH_L2_MAX_MM,
            FULL_ARCH_L2_LOW_FALLOFF_MM, FULL_ARCH_L2_HIGH_FALLOFF_MM,
        )
        s_l3 = _soft_range_with_falloff(
            features.axis_l3_mm,
            FULL_ARCH_L3_MIN_MM, FULL_ARCH_L3_MAX_MM,
            FULL_ARCH_L3_LOW_FALLOFF_MM, FULL_ARCH_L3_HIGH_FALLOFF_MM,
        )
        axis_min = min(s_l1, s_l2, s_l3)
        axis_avg = (s_l1 + s_l2 + s_l3) / 3.0
        full_arch_size_score = axis_min * 0.8 + axis_avg * 0.2

        s_splint_l3 = _soft_range_with_falloff(
            features.axis_l3_mm,
            SPLINT_L3_MIN_MM, SPLINT_L3_MAX_MM,
            SPLINT_L3_LOW_FALLOFF_MM, SPLINT_L3_HIGH_FALLOFF_MM,
        )
        splint_axis_min = min(s_l1, s_l2, s_splint_l3)
        splint_axis_avg = (s_l1 + s_l2 + s_splint_l3) / 3.0
        splint_size_score = splint_axis_min * 0.8 + splint_axis_avg * 0.2

        s_base_l3 = _soft_range_with_falloff(
            features.axis_l3_mm,
            BASE_MODEL_L3_MIN_MM, BASE_MODEL_L3_MAX_MM,
            BASE_MODEL_L3_LOW_FALLOFF_MM, BASE_MODEL_L3_HIGH_FALLOFF_MM,
        )
        base_axis_min = min(s_l1, s_l2, s_base_l3)
        base_axis_avg = (s_l1 + s_l2 + s_base_l3) / 3.0
        base_model_size_score = base_axis_min * 0.8 + base_axis_avg * 0.2
    else:
        full_arch_size_score  = 0.0
        splint_size_score     = 0.0
        base_model_size_score = 0.0

    # Crown / bridge length scores (piecewise-linear by L1), ratio scores, and elongation
    if pca_valid:
        crown_length_score, bridge_length_score = _crown_bridge_length_scores(features.axis_l1_mm)
        crown_ratio_score, bridge_ratio_score = _crown_bridge_ratio_scores(features.elongation_ratio)
        crown_small_score  = min(small_object_score, (crown_length_score  + crown_ratio_score)  / 2.0)
        bridge_small_score = min(small_object_score, (bridge_length_score + bridge_ratio_score) / 2.0)
    else:
        crown_length_score = bridge_length_score = 0.0
        crown_ratio_score = bridge_ratio_score = 0.0
        crown_small_score = bridge_small_score = 0.0
    elongated_score = (
        _soft_greater_than(features.elongation_ratio, BRIDGE_ELONGATION_MIN, BRIDGE_ELONGATION_TOL)
        if pca_valid else 0.0
    )

    # Clear crown size: small cross-section AND L1 firmly in crown territory
    if pca_valid:
        _crown_l1_size = _soft_max_with_falloff(
            features.axis_l1_mm, CLEAR_CROWN_L1_MAX_MM, CLEAR_CROWN_L1_FALLOFF_MM
        )
        clear_crown_size_score = min(_crown_l1_size, _small_l2, _small_l3)
    else:
        clear_crown_size_score = 0.0

    # Bridge size: lower L1 bound from crown/bridge score, upper bound from BRIDGE_L1_MAX_MM
    if pca_valid:
        _bridge_l1_lower = bridge_length_score
        _bridge_l1_upper = _soft_max_with_falloff(
            features.axis_l1_mm, BRIDGE_L1_MAX_MM, BRIDGE_L1_HIGH_FALLOFF_MM
        )
        _bridge_l1 = min(_bridge_l1_lower, _bridge_l1_upper)
        _bridge_l2 = _soft_max_with_falloff(
            features.axis_l2_mm, BRIDGE_L2_MAX_MM, BRIDGE_L2_HIGH_FALLOFF_MM
        )
        _bridge_l3 = _soft_max_with_falloff(
            features.axis_l3_mm, BRIDGE_L3_MAX_MM, BRIDGE_L3_HIGH_FALLOFF_MM
        )
        _bridge_min = min(_bridge_l1, _bridge_l2, _bridge_l3)
        _bridge_avg = (_bridge_l1 + _bridge_l2 + _bridge_l3) / 3.0
        bridge_size_score = _bridge_min * 0.8 + _bridge_avg * 0.2
    else:
        bridge_size_score = 0.0

    # Large open boundary: require both absolute length and relative ratio
    if open_boundary_valid:
        large_open_boundary_score = min(
            _soft_greater_than(features.largest_loop_length_mm, LARGE_OPEN_LOOP_MIN_MM, LARGE_OPEN_LOOP_TOL_MM),
            _soft_greater_than(features.largest_open_ratio,     LARGE_OPEN_RATIO_MIN,   LARGE_OPEN_RATIO_TOL),
        )
    else:
        large_open_boundary_score = 0.0

    # Flat plane: compute area score first, then split by one_side
    if (flat_plane_ran
            and features.flat_plane_candidate_found is True
            and features.flat_plane_area_ratio is not None):
        flat_plane_size_score = _soft_greater_than(
            features.flat_plane_area_ratio, FLAT_PLANE_AREA_RATIO_MIN, FLAT_PLANE_AREA_RATIO_TOL
        )
    else:
        flat_plane_size_score = 0.0
    one_sided_flat_plane_score = (
        flat_plane_size_score if features.flat_plane_one_side is True else 0.0
    )
    non_one_sided_flat_plane_score = (
        flat_plane_size_score if features.flat_plane_one_side is False else 0.0
    )
    strong_outer_flat_plane_score = one_sided_flat_plane_score

    # U-shape: require both gap ratio and hull-boundary contact
    if projection_valid:
        u_shape_score = min(
            _soft_greater_than(features.projection_largest_gap_ratio,      U_GAP_RATIO_MIN,      U_GAP_RATIO_TOL),
            _soft_greater_than(features.projection_largest_gap_contact_mm, U_GAP_CONTACT_MIN_MM, U_GAP_CONTACT_TOL_MM),
        )
    else:
        u_shape_score = 0.0

    return _ClassificationSignals(
        small_object_score=small_object_score,
        full_arch_size_score=full_arch_size_score,
        crown_length_score=crown_length_score,
        bridge_length_score=bridge_length_score,
        elongated_score=elongated_score,
        large_open_boundary_score=large_open_boundary_score,
        flat_plane_size_score=flat_plane_size_score,
        one_sided_flat_plane_score=one_sided_flat_plane_score,
        non_one_sided_flat_plane_score=non_one_sided_flat_plane_score,
        strong_outer_flat_plane_score=strong_outer_flat_plane_score,
        u_shape_score=u_shape_score,
        splint_size_score=splint_size_score,
        bridge_size_score=bridge_size_score,
        clear_crown_size_score=clear_crown_size_score,
        base_model_size_score=base_model_size_score,
        crown_ratio_score=crown_ratio_score,
        bridge_ratio_score=bridge_ratio_score,
        crown_small_score=crown_small_score,
        bridge_small_score=bridge_small_score,
    )


def _is_one_sided_base_candidate(signals: "_ClassificationSignals") -> bool:
    """True when base-model footprint + one-sided flat plane both qualify.

    Used to skip drill detection early and to drive the P_base decision branch.
    Does NOT require absence of open boundary or interior holes.
    """
    return (
        signals.base_model_size_score >= CANDIDATE_GROUP_MIN
        and signals.one_sided_flat_plane_score >= STRONG_SIGNAL_MIN
    )


def _p_base_decide(sig: "_ClassificationSignals") -> "DentalModelType":
    """Return dental_model or u_shaped_dental_model for the P_base / P5.2A branch.

    Shared by _decide_model_type_with_details() and confirm_dental_model_type() so
    both paths always use the same u_shape split logic.
    """
    dental_model_score   = (sig.base_model_size_score + sig.one_sided_flat_plane_score + (1.0 - sig.u_shape_score)) / 3.0
    u_shaped_model_score = (sig.base_model_size_score + sig.one_sided_flat_plane_score + sig.u_shape_score) / 3.0
    if u_shaped_model_score > dental_model_score:
        return DentalModelType.U_SHAPED_DENTAL_MODEL
    return DentalModelType.DENTAL_MODEL


def _get_drill_detection_plan(
    features: ModelFeatures,
    signals: _ClassificationSignals,
) -> "tuple[bool, Optional[str]]":
    """Decide whether drill-hole detection is needed.

    Returns (needs_drill, skip_reason):
      (True, None)       → run detector
      (False, reason)    → skip detector; reason is a human-readable string

    Priority order for skipping:
      1. One-sided base plane + base-model size (takes priority over open boundary)
      2. Clear crown size (L1 outside or inside 12–18 mm boundary zone)
      3. Very large open boundary → intraoral scan
    """
    # Skip 1: one-sided flat plane + base-model footprint → dental model base
    if _is_one_sided_base_candidate(signals):
        return (False, "單側大平面且符合基座尺寸")

    # Skip 2: crown size check — boundary-aware
    _in_ratio_boundary = (
        features.axis_l1_mm is not None
        and CROWN_L1_STRONG_MAX_MM < features.axis_l1_mm < BRIDGE_L1_STRONG_MIN_MM
        and signals.small_object_score >= CANDIDATE_GROUP_MIN
    )
    if _in_ratio_boundary:
        if (signals.crown_small_score >= STRONG_SIGNAL_MIN
                and signals.crown_small_score > signals.bridge_small_score + CANDIDATE_MIN_GAP):
            return (False, "小尺寸交界且比例偏向牙冠")
    else:
        if (signals.clear_crown_size_score >= STRONG_SIGNAL_MIN
                and signals.crown_length_score > signals.bridge_length_score + CANDIDATE_MIN_GAP):
            return (False, "明確牙冠尺寸")

    # Skip 3: very large open boundary → intraoral scan
    if signals.large_open_boundary_score >= STRONG_SIGNAL_MIN:
        return (False, "大型開放邊界")

    return (True, None)


# ---------------------------------------------------------------------------
# Classification decision
# ---------------------------------------------------------------------------

def _decide_model_type_with_details(features: ModelFeatures) -> ClassificationDecision:
    """Heuristic classifier.  Returns ClassificationDecision with model_type, confidence, reasons.

    Expects features with drill_detection_* fields already populated by
    classify_dental_model().  When called directly (e.g. unit tests), set the
    drill fields explicitly on ModelFeatures.  If drill_detection_ran=False and no
    skip_reason is set, the function falls back to SURGICAL_GUIDE with low confidence.
    """
    pca_valid = features.axis_l1_mm is not None

    def _clamp(v: float) -> float:
        return max(0.0, min(1.0, v))

    # ---- P0: PCA required ----
    if not pca_valid:
        return ClassificationDecision(
            model_type=DentalModelType.OTHER,
            confidence=None,
            primary_reasons=["必要特徵缺失 (PCA)", "無法完成可靠分類"],
        )

    sig = _compute_signals(features)

    # ---- P_base: One-sided flat plane + base-model footprint (drill was skipped) ----
    if features.drill_detection_skip_reason == "單側大平面且符合基座尺寸":
        dental_model_score   = (sig.base_model_size_score + sig.one_sided_flat_plane_score + (1.0 - sig.u_shape_score)) / 3.0
        u_shaped_model_score = (sig.base_model_size_score + sig.one_sided_flat_plane_score + sig.u_shape_score) / 3.0
        if _p_base_decide(sig) == DentalModelType.U_SHAPED_DENTAL_MODEL:
            conf = round(_clamp(u_shaped_model_score), 3)
            return ClassificationDecision(
                model_type=DentalModelType.U_SHAPED_DENTAL_MODEL,
                confidence=conf,
                primary_reasons=["單側大平面確認基座", "U 型特徵高", "尺寸符合基座模型範圍"],
            )
        conf = round(_clamp(dental_model_score), 3)
        return ClassificationDecision(
            model_type=DentalModelType.DENTAL_MODEL,
            confidence=conf,
            primary_reasons=["單側大平面確認基座", "U 型特徵低", "尺寸符合基座模型範圍"],
        )

    # ---- P2: Clear crown (drill was skipped for clear crown) ----
    if features.drill_detection_skip_reason == "明確牙冠尺寸":
        conf = round(_clamp(sig.clear_crown_size_score), 3)
        return ClassificationDecision(
            model_type=DentalModelType.CROWN,
            confidence=conf,
            primary_reasons=["三軸為明確小型尺寸", "L1 偏向牙冠範圍", "已排除牙橋尺寸"],
        )
    if features.drill_detection_skip_reason == "小尺寸交界且比例偏向牙冠":
        conf = round(_clamp(sig.crown_small_score), 3)
        return ClassificationDecision(
            model_type=DentalModelType.CROWN,
            confidence=conf,
            primary_reasons=[
                "L2、L3 符合小型尺寸",
                "L1 位於牙冠與牙橋交界範圍",
                "L1/L2 比例偏向牙冠",
            ],
        )

    # ---- P3: Large open boundary (drill was skipped) ----
    if features.drill_detection_skip_reason == "大型開放邊界":
        conf = round(_clamp(sig.large_open_boundary_score), 3)
        return ClassificationDecision(
            model_type=DentalModelType.INTRAORAL_SCAN,
            confidence=conf,
            primary_reasons=["有大型開放邊界", "開放邊界相對比例高"],
        )

    # ---- P5: Drill detection ran ----
    if features.drill_detection_ran:
        if features.drill_detection_valid is True:
            # 5.1 Found drill holes → SURGICAL_GUIDE
            if features.drill_hole_found is True:
                return ClassificationDecision(
                    model_type=DentalModelType.SURGICAL_GUIDE,
                    confidence=SURGICAL_GUIDE_DRILL_FOUND_CONFIDENCE,
                    primary_reasons=[
                        "偵測到導孔候選",
                        f"導孔候選數量：{features.drill_candidate_count}",
                    ],
                )

            # 5.2 Ran but no holes found
            no_holes = (
                features.projection_medium_holes == 0
                and features.projection_large_holes == 0
            )

            # A: Large base dental model (one-sided flat plane + base-model footprint)
            if _is_one_sided_base_candidate(sig):
                dental_model_score   = (sig.base_model_size_score + sig.one_sided_flat_plane_score + (1.0 - sig.u_shape_score)) / 3.0
                u_shaped_model_score = (sig.base_model_size_score + sig.one_sided_flat_plane_score + sig.u_shape_score) / 3.0
                if _p_base_decide(sig) == DentalModelType.U_SHAPED_DENTAL_MODEL:
                    conf = round(_clamp(u_shaped_model_score), 3)
                    return ClassificationDecision(
                        model_type=DentalModelType.U_SHAPED_DENTAL_MODEL,
                        confidence=conf,
                        primary_reasons=[
                            "單側大平面確認基座",
                            "U 型特徵高",
                            "尺寸符合基座模型範圍",
                            "導孔偵測未找到候選",
                        ],
                    )
                conf = round(_clamp(dental_model_score), 3)
                return ClassificationDecision(
                    model_type=DentalModelType.DENTAL_MODEL,
                    confidence=conf,
                    primary_reasons=[
                        "單側大平面確認基座",
                        "U 型特徵低",
                        "尺寸符合基座模型範圍",
                        "導孔偵測未找到候選",
                    ],
                )

            # B: SPLINT
            if (sig.splint_size_score >= CANDIDATE_GROUP_MIN
                    and sig.u_shape_score >= STRONG_SIGNAL_MIN
                    and sig.strong_outer_flat_plane_score <= LOW_FEATURE_MAX
                    and sig.large_open_boundary_score <= LOW_FEATURE_MAX
                    and no_holes):
                conf = round(_clamp((sig.splint_size_score + sig.u_shape_score) / 2), 3)
                return ClassificationDecision(
                    model_type=DentalModelType.SPLINT,
                    confidence=conf,
                    primary_reasons=[
                        "厚度符合咬合板範圍",
                        "U 型特徵高",
                        "無明顯大型外側平面",
                        "導孔偵測未找到候選",
                    ],
                )

            # C: Crown/bridge boundary ratio split (12–18 mm L1 zone)
            if (features.axis_l1_mm is not None
                    and CROWN_L1_STRONG_MAX_MM < features.axis_l1_mm < BRIDGE_L1_STRONG_MIN_MM
                    and sig.small_object_score >= CANDIDATE_GROUP_MIN):
                if sig.crown_small_score > sig.bridge_small_score:
                    conf = round(_clamp(sig.crown_small_score), 3)
                    return ClassificationDecision(
                        model_type=DentalModelType.CROWN,
                        confidence=conf,
                        primary_reasons=[
                            "L2、L3 符合小型尺寸",
                            "L1 位於牙冠與牙橋交界範圍",
                            "尺寸與 L1/L2 比例綜合分數偏向牙冠",
                            "導孔偵測未找到候選",
                        ],
                    )
                conf = round(_clamp(sig.bridge_small_score), 3)
                return ClassificationDecision(
                    model_type=DentalModelType.BRIDGE,
                    confidence=conf,
                    primary_reasons=[
                        "L2、L3 符合小型尺寸",
                        "L1 位於牙冠與牙橋交界範圍",
                        "尺寸與 L1/L2 比例綜合分數偏向牙橋",
                        "導孔偵測未找到候選",
                    ],
                )

            # D-pre: Non-one-sided flat plane → SURGICAL_GUIDE
            if sig.non_one_sided_flat_plane_score >= CANDIDATE_GROUP_MIN:
                return ClassificationDecision(
                    model_type=DentalModelType.SURGICAL_GUIDE,
                    confidence=SURGICAL_GUIDE_NON_ONE_SIDED_PLANE_CONFIDENCE,
                    primary_reasons=[
                        "具有非單側大型平面",
                        "此特徵偏向手術導板而非基座模型",
                        "導孔偵測未找到候選",
                    ],
                )

            # D: BRIDGE
            if sig.bridge_size_score >= CANDIDATE_GROUP_MIN:
                _elong_note = "偏長條" if sig.elongated_score >= STRONG_SIGNAL_MIN else "長條特徵一般"
                conf = round(_clamp(sig.bridge_size_score), 3)
                return ClassificationDecision(
                    model_type=DentalModelType.BRIDGE,
                    confidence=conf,
                    primary_reasons=["尺寸符合牙橋範圍", _elong_note, "導孔偵測未找到候選"],
                )

            # E: BRIDGE low-confidence fallback
            return ClassificationDecision(
                model_type=DentalModelType.BRIDGE,
                confidence=BRIDGE_DRILL_NEGATIVE_FALLBACK_CONFIDENCE,
                primary_reasons=[
                    "導孔偵測正常完成且未找到候選",
                    "現有尺寸未達明確牙橋門檻",
                    "暫以低信心判為牙橋，後續由空腔特徵進一步確認",
                ],
            )

        # 5.3 Drill detection failed
        if sig.bridge_size_score >= CANDIDATE_GROUP_MIN:
            conf = round(min(sig.bridge_size_score, DRILL_FAILED_BRIDGE_CONFIDENCE_MAX), 3)
            return ClassificationDecision(
                model_type=DentalModelType.BRIDGE,
                confidence=conf,
                primary_reasons=["尺寸符合牙橋範圍", "導孔偵測失敗", "依尺寸低信心判為牙橋"],
            )
        return ClassificationDecision(
            model_type=DentalModelType.SURGICAL_GUIDE,
            confidence=SURGICAL_GUIDE_DRILL_FAILED_CONFIDENCE,
            primary_reasons=[
                "導孔偵測失敗",
                "現有低成本特徵無法排除手術導板",
                "低信心回退為手術導板",
            ],
        )

    # ---- Fallback: drill never ran (direct API call without proper orchestration) ----
    return ClassificationDecision(
        model_type=DentalModelType.SURGICAL_GUIDE,
        confidence=SURGICAL_GUIDE_DRILL_FAILED_CONFIDENCE,
        primary_reasons=["導孔偵測尚未執行", "低信心回退為手術導板"],
    )


def decide_model_type(features: ModelFeatures) -> DentalModelType:
    """Public-interface wrapper preserving the original signature.

    Expects features with drill fields populated; see classify_dental_model() for the full orchestration flow.
    Delegates to _decide_model_type_with_details and returns only the type.
    """
    return _decide_model_type_with_details(features).model_type


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def classify_dental_model(mesh: "trimesh.Trimesh") -> DentalModelType:
    """
    Classify a dental STL mesh into one of the known DentalModelType categories.

    This is the single official entry point for model classification.
    Flow:
      mesh → extract_model_features → _compute_signals → _get_drill_detection_plan
           → [optional] detect_drill_holes (once, only when needed)
           → _decide_model_type_with_details → DentalModelType
    """
    features = extract_model_features(mesh)

    # Compute signals; skip if PCA failed (decision will return OTHER at P0)
    if features.axis_l1_mm is not None:
        _sig = _compute_signals(features)
        needs_drill, skip_reason = _get_drill_detection_plan(features, _sig)
    else:
        needs_drill, skip_reason = False, None

    if needs_drill:
        _drill_result = detect_drill_holes(mesh)
        features.drill_detection_ran          = True
        features.drill_detection_skip_reason  = None
        features.drill_detection_valid        = _drill_result["valid"]
        features.drill_hole_found             = _drill_result["found"]
        features.drill_candidate_count        = _drill_result["candidate_count"]
    else:
        features.drill_detection_ran          = False
        features.drill_detection_valid        = None
        features.drill_hole_found             = None
        features.drill_candidate_count        = None
        features.drill_detection_skip_reason  = skip_reason

    decision = _decide_model_type_with_details(features)

    return decision.model_type


def confirm_dental_model_type(mesh: "trimesh.Trimesh", target: DentalModelType) -> bool:
    """Return True if this mesh would be classified as *target* by classify_dental_model().

    Guarantees: confirm(mesh, t) == (classify_dental_model(mesh) == t) for all t,
    with no exceptions.

    Performance: types that can be determined before drill detection (dental_model,
    u_shaped_dental_model, intraoral_scan, other) are short-circuited at the P_base /
    P2 / P3 branches, avoiding the expensive detect_drill_holes() call.  For crown,
    bridge, splint, and surgical_guide the drill step is still required when none of
    those early branches fires.

    Implementation note: when drill detection is required this function reuses the
    already-computed features object and calls _decide_model_type_with_details()
    directly — it does NOT re-invoke classify_dental_model(mesh) from scratch.
    """
    features = extract_model_features(mesh)

    # ---- P0: PCA failed ----
    if features.axis_l1_mm is None:
        return target == DentalModelType.OTHER

    sig = _compute_signals(features)
    needs_drill, skip_reason = _get_drill_detection_plan(features, sig)

    if not needs_drill:
        # ---- P_base ----
        if skip_reason == "單側大平面且符合基座尺寸":
            if target in (DentalModelType.DENTAL_MODEL, DentalModelType.U_SHAPED_DENTAL_MODEL):
                return _p_base_decide(sig) == target
            return False

        # ---- P2 ----
        if skip_reason in ("明確牙冠尺寸", "小尺寸交界且比例偏向牙冠"):
            return target == DentalModelType.CROWN

        # ---- P3 ----
        if skip_reason == "大型開放邊界":
            return target == DentalModelType.INTRAORAL_SCAN

    # needs_drill=True: types that cannot appear in P5 → early false
    if target in (
        DentalModelType.DENTAL_MODEL,
        DentalModelType.U_SHAPED_DENTAL_MODEL,
        DentalModelType.INTRAORAL_SCAN,
        DentalModelType.OTHER,
    ):
        return False

    # ---- P5: run drill detection, then compare (crown / bridge / splint / surgical_guide) ----
    _drill_result = detect_drill_holes(mesh)
    features.drill_detection_ran         = True
    features.drill_detection_skip_reason = None
    features.drill_detection_valid       = _drill_result["valid"]
    features.drill_hole_found            = _drill_result["found"]
    features.drill_candidate_count       = _drill_result["candidate_count"]

    final_type = _decide_model_type_with_details(features).model_type
    return final_type == target


# ---------------------------------------------------------------------------
# Drill hole detection — ported from auto_orient_surg_guide.cpp
# Called conditionally by classify_dental_model() after low-cost exclusion checks.
# May also be called independently by tests or other callers.
# ---------------------------------------------------------------------------

# Drill-hole ring size standards (updated from auto_orient_surg_guide.py).
# Outer diameter is measured on the PCA major axis (not a fixed-axis bbox).
_DRILL_RING_OUTER_DIAM_MIN = 5.5   # mm
_DRILL_RING_OUTER_DIAM_MAX = 14.0  # mm
_DRILL_RING_MAX_ASPECT     = 1.5   # PCA long / short  (true rings ≈ 1)


@dataclass
class _DrillPatchInfo:
    """Flat face-group data for drill-hole candidate search."""
    id: int
    faces: List[int] = field(default_factory=list)
    avg_normal: "np.ndarray" = field(default_factory=lambda: np.zeros(3, dtype=np.float64))
    area: float = 0.0
    max_angle_deg: float = 0.0
    center: "np.ndarray" = field(default_factory=lambda: np.zeros(3, dtype=np.float64))
    fi_arr: "Optional[np.ndarray]" = field(default=None)   # cached by _drill_compute_patch_stats


def _drill_build_orthonormal_basis(n: "np.ndarray") -> "Tuple[np.ndarray, np.ndarray]":
    """Build ex, ey perpendicular to n using scalar math (no intermediate arrays).

    n is expected to be a unit vector; the caller (_drill_is_drill_patch) verifies
    n_len >= 0.5 before calling.  The n_sq < 1e-18 guard handles degenerate input
    from any external caller.
    """
    nx = float(n[0]); ny = float(n[1]); nz = float(n[2])
    n_sq = nx*nx + ny*ny + nz*nz
    if n_sq < 1e-18:
        return np.array([1.0, 0.0, 0.0]), np.array([0.0, 1.0, 0.0])

    # Lightweight scalar normalize (n from _drill_compute_patch_stats is ~unit;
    # one sqrt + 3 mults replaces np.linalg.norm + array division).
    inv_n = 1.0 / math.sqrt(n_sq)
    nx *= inv_n; ny *= inv_n; nz *= inv_n

    # Choose reference vector t to avoid near-parallel with n;
    # compute ex_raw = t × n inline (no np.array allocation, no np.cross call).
    if abs(nz) < 0.9:
        # t = (0, 0, 1)  →  t × n = (-ny, nx, 0)
        ex_x = -ny; ex_y = nx; ex_z = 0.0
    else:
        # t = (0, 1, 0)  →  t × n = (nz, 0, -nx)
        ex_x = nz; ex_y = 0.0; ex_z = -nx

    # Normalise ex with scalar math (no np.linalg.norm, no intermediate array).
    ex_sq = ex_x*ex_x + ex_y*ex_y + ex_z*ex_z
    if ex_sq < 1e-18:
        ex_x = 1.0; ex_y = 0.0; ex_z = 0.0
    else:
        inv_ex = 1.0 / math.sqrt(ex_sq)
        ex_x *= inv_ex; ex_y *= inv_ex; ex_z *= inv_ex

    # ey = n × ex  (right-hand system; scalar cross product, no np.cross call).
    ey_x = ny*ex_z - nz*ex_y
    ey_y = nz*ex_x - nx*ex_z
    ey_z = nx*ex_y - ny*ex_x

    return np.array([ex_x, ex_y, ex_z]), np.array([ey_x, ey_y, ey_z])


def _drill_merge_vertices(verts: "np.ndarray") -> "np.ndarray":
    """Quantize to 1e-4 mm grid; return rep[i] = canonical vertex index (Step 1)."""
    eps = 1e-4
    iq = np.floor(verts / eps + 0.5).astype(np.int64)   # (N, 3) — matches C++ floor(x/eps + 0.5)
    nv = len(verts)
    rep = np.arange(nv, dtype=np.int32)
    vmap: dict = {}
    for i in range(nv):
        key = (int(iq[i, 0]), int(iq[i, 1]), int(iq[i, 2]))
        if key not in vmap:
            vmap[key] = i
        else:
            rep[i] = vmap[key]
    return rep


def _drill_prepare_faces(
    verts: "np.ndarray",
    faces_raw: "np.ndarray",
    rep: "np.ndarray",
) -> "Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]":
    """Build (face_v, face_n, face_c, face_patch_id, face_area) arrays (Step 2)."""
    face_v = rep[faces_raw].astype(np.int32)            # (M, 3) merged indices
    p0 = verts[face_v[:, 0]]
    p1 = verts[face_v[:, 1]]
    p2 = verts[face_v[:, 2]]
    e1 = p1 - p0; e2 = p2 - p0
    crosses = np.cross(e1, e2)                          # (M, 3)
    lengths = np.linalg.norm(crosses, axis=1, keepdims=True)
    face_n = np.where(lengths > 1e-30, crosses / np.maximum(lengths, 1e-30), 0.0)
    face_area = 0.5 * lengths.squeeze(axis=1)           # (M,) — reused in patch stats
    face_c = (p0 + p1 + p2) / 3.0
    face_patch_id = np.full(len(faces_raw), -1, dtype=np.int32)
    return face_v, face_n, face_c, face_patch_id, face_area


def _drill_build_edge_adj(
    face_v: "np.ndarray",
    nfaces: int,
) -> "Tuple[dict, List[List[int]]]":
    """Build edge map {(a,b): [f0,f1?]} and face adjacency list (Step 3)."""
    edge_map: dict = {}
    adj_faces: List[List[int]] = [[] for _ in range(nfaces)]
    for f in range(nfaces):
        vs = face_v[f]
        for e in range(3):
            a = int(vs[e]); b = int(vs[(e + 1) % 3])
            key = (a, b) if a < b else (b, a)
            if key not in edge_map:
                edge_map[key] = [f]
            else:
                ef = edge_map[key]
                if len(ef) == 1:
                    other = ef[0]
                    ef.append(f)
                    adj_faces[f].append(other)
                    adj_faces[other].append(f)
    return edge_map, adj_faces


def _drill_region_growing(
    face_n: "np.ndarray",
    face_patch_id: "np.ndarray",
    adj_faces: "List[List[int]]",
    nfaces: int,
) -> "List[_DrillPatchInfo]":
    """Region growing at 2° threshold to form flat patches (Step 4)."""
    from collections import deque
    COS_GROW = math.cos(2.0 * math.pi / 180.0)
    face_n_norms = np.linalg.norm(face_n, axis=1)
    patches: List[_DrillPatchInfo] = []
    next_pid = 0

    for f0 in range(nfaces):
        if face_patch_id[f0] != -1:
            continue
        if face_n_norms[f0] < 0.5:
            face_patch_id[f0] = -2
            continue

        pid = next_pid; next_pid += 1
        n_seed = face_n[f0]
        sx = float(n_seed[0]); sy = float(n_seed[1]); sz = float(n_seed[2])
        P = _DrillPatchInfo(id=pid)
        q: "deque[int]" = deque([f0])
        face_patch_id[f0] = pid

        while q:
            fidx = q.popleft()
            P.faces.append(fidx)
            for fn in adj_faces[fidx]:
                if face_patch_id[fn] != -1:
                    continue
                if face_n_norms[fn] < 0.5:
                    face_patch_id[fn] = -2
                    continue
                _fn = face_n[fn]
                if _fn[0]*sx + _fn[1]*sy + _fn[2]*sz >= COS_GROW:
                    face_patch_id[fn] = pid
                    q.append(fn)

        patches.append(P)
    return patches


def _drill_compute_patch_stats(
    face_v: "np.ndarray",
    face_n: "np.ndarray",
    face_c: "np.ndarray",
    verts: "np.ndarray",
    patches: "List[_DrillPatchInfo]",
    face_area: "np.ndarray",
) -> None:
    """Fill area, avg_normal, center per patch in-place; cache fi_arr (Step 5).

    Reuses face_area from _drill_prepare_faces to avoid a second cross-product
    computation. max_angle_deg is not computed (unused by caller; field kept).
    """
    for P in patches:
        if not P.faces:
            continue
        fi = np.asarray(P.faces, dtype=np.int32)
        P.fi_arr = fi                                              # cache for later reuse
        areas = face_area[fi]                                      # (K,) — no recompute
        area_sum = float(areas.sum())
        P.area = area_sum
        if area_sum < 1e-12:
            P.avg_normal = np.zeros(3, dtype=np.float64)
            P.center = np.zeros(3, dtype=np.float64)
            continue
        sum_n = (face_n[fi] * areas[:, None]).sum(axis=0)
        n_len = float(np.linalg.norm(sum_n))
        P.avg_normal = sum_n / n_len if n_len > 1e-9 else np.zeros(3)
        P.center = (face_c[fi] * areas[:, None]).sum(axis=0) / area_sum


def _drill_patch_has_hole_by_scanlines(
    u0a: "np.ndarray",
    v0a: "np.ndarray",
    u1a: "np.ndarray",
    v1a: "np.ndarray",
    u2a: "np.ndarray",
    v2a: "np.ndarray",
) -> bool:
    """2D voxel rasterisation + scanline hole test (patch_has_hole_by_scanlines).

    Accepts per-face projected coordinates already computed by the caller,
    avoiding a second projection pass. Thresholds preserved from C++:
      voxelSize=0.3 mm, emptyMinLen=2.4 mm, solidMinLen=0.6 mm.
    """
    if len(u0a) == 0:
        return False

    umin = float(min(u0a.min(), u1a.min(), u2a.min()))
    umax = float(max(u0a.max(), u1a.max(), u2a.max()))
    vmin = float(min(v0a.min(), v1a.min(), v2a.min()))
    vmax = float(max(v0a.max(), v1a.max(), v2a.max()))

    if not (umax > umin and vmax > vmin):
        return False

    VOXEL = 0.3
    pad = VOXEL * 0.5
    ug0 = umin - pad; vg0 = vmin - pad
    ug1 = umax + pad; vg1 = vmax + pad

    nx = int(math.ceil((ug1 - ug0) / VOXEL))
    ny = int(math.ceil((vg1 - vg0) / VOXEL))
    if nx <= 0 or ny <= 0 or nx * ny > 5_000_000:
        return False

    occ = np.zeros((ny, nx), dtype=bool)

    # Rasterise each triangle onto the occupancy grid (vectorised per triangle)
    nf_patch = len(u0a)
    for t in range(nf_patch):
        ax = float(u0a[t]); ay = float(v0a[t])
        bx = float(u1a[t]); by = float(v1a[t])
        cx = float(u2a[t]); cy = float(v2a[t])

        tumin = min(ax, bx, cx); tumax = max(ax, bx, cx)
        tvmin = min(ay, by, cy); tvmax = max(ay, by, cy)

        ix0 = max(0, int(math.floor((tumin - ug0) / VOXEL)) - 1)
        ix1 = min(nx - 1, int(math.floor((tumax - ug0) / VOXEL)) + 1)
        iy0 = max(0, int(math.floor((tvmin - vg0) / VOXEL)) - 1)
        iy1 = min(ny - 1, int(math.floor((tvmax - vg0) / VOXEL)) + 1)
        if ix0 > ix1 or iy0 > iy1:
            continue

        if occ[iy0: iy1 + 1, ix0: ix1 + 1].all():
            continue

        IXs = np.arange(ix0, ix1 + 1, dtype=np.float64)
        IYs = np.arange(iy0, iy1 + 1, dtype=np.float64)
        IX, IY = np.meshgrid(IXs, IYs)       # (H, W)

        x0c = ug0 + IX * VOXEL;  y0c = vg0 + IY * VOXEL
        x1c = x0c + VOXEL;       y1c = y0c + VOXEL
        xcc = x0c + VOXEL * 0.5; ycc = y0c + VOXEL * 0.5

        # Precompute barycentric constants for this triangle
        v0x = bx - ax; v0y = by - ay
        v1x = cx - ax; v1y = cy - ay
        d00 = v0x * v0x + v0y * v0y
        d01 = v0x * v1x + v0y * v1y
        d11 = v1x * v1x + v1y * v1y
        denom = d00 * d11 - d01 * d01
        if abs(denom) < 1e-12:
            continue
        inv = 1.0 / denom
        EPS_TRI = -1e-4

        def _in(px: "np.ndarray", py: "np.ndarray") -> "np.ndarray":
            v2x = px - ax; v2y = py - ay
            d02 = v0x * v2x + v0y * v2y
            d12 = v1x * v2x + v1y * v2y
            u = (d11 * d02 - d01 * d12) * inv
            v = (d00 * d12 - d01 * d02) * inv
            return (u >= EPS_TRI) & (v >= EPS_TRI) & (u + v <= 1.0 - EPS_TRI)

        hit = _in(x0c, y0c) | _in(x1c, y0c) | _in(x0c, y1c) | _in(x1c, y1c) | _in(xcc, ycc)
        occ[iy0: iy1 + 1, ix0: ix1 + 1] |= hit

    # Scanline: detect solid→empty(≥2.4mm)→solid pattern per row and column
    EMPTY_MIN = 2.4
    SOLID_MIN = 0.6
    STEP = VOXEL

    def _scan(cells: "np.ndarray") -> bool:
        state = 0; s1 = e = s2 = 0.0
        for solid in cells:
            if solid:
                if state == 0:   state = 1; s1 = STEP
                elif state == 1: s1 += STEP
                elif state == 2: state = 3; s2 = STEP
                elif state == 3: s2 += STEP
            else:
                if state == 1:   state = 2; e = STEP
                elif state == 2: e += STEP
                elif state == 3:
                    if e >= EMPTY_MIN and s1 >= SOLID_MIN and s2 >= SOLID_MIN:
                        return True
                    state = 0; s1 = e = s2 = 0.0
            if state == 3 and e >= EMPTY_MIN and s1 >= SOLID_MIN and s2 >= SOLID_MIN:
                return True
        return state == 3 and e >= EMPTY_MIN and s1 >= SOLID_MIN and s2 >= SOLID_MIN

    for row in range(ny):
        if _scan(occ[row, :]):
            return True
    for col in range(nx):
        if _scan(occ[:, col]):
            return True
    return False


def _drill_is_drill_patch(
    verts: "np.ndarray",
    face_v: "np.ndarray",
    face_n: "np.ndarray",
    face_patch_id: "np.ndarray",
    edge_map: dict,
    P: "_DrillPatchInfo",
) -> bool:
    """Stage-2 drill patch filter (isDrillPatchByEdges).

    Preserved thresholds:
      perpendicular wall angle: 87° ± 3°  (cos threshold = cos 87°)
      connEdge bbox: minDim ∈ [3,35] mm
      accumulated turn angle threshold: 220°
    """
    if len(P.faces) < 5 or P.area <= 0.0:
        return False

    n_patch = P.avg_normal
    _nx = float(n_patch[0]); _ny = float(n_patch[1]); _nz = float(n_patch[2])
    if _nx*_nx + _ny*_ny + _nz*_nz < 0.25:  # equivalent to np.linalg.norm < 0.5
        return False
    # P.avg_normal is already a unit vector from _drill_compute_patch_stats (when
    # area > 1e-12).  No re-normalisation needed; _drill_build_orthonormal_basis
    # carries its own lightweight scalar normalise as a safety guard.

    ex, ey = _drill_build_orthonormal_basis(n_patch)

    # ---- PCA + diameter/aspect gate ----
    # Per-face inverse mapping (uv_inv, u0a…v2a) is deferred until after the
    # diameter/aspect gate: almost all patches are rejected there, so building
    # the mapping eagerly wastes work for the vast majority of calls.
    fi_arr = P.fi_arr if P.fi_arr is not None else np.asarray(P.faces, dtype=np.int32)
    vids_flat = face_v[fi_arr].reshape(-1)                        # (3*M_patch,)
    vids_unique = np.unique(vids_flat)                            # sorted; return_inverse deferred

    q = (verts[vids_unique] - P.center)
    u_uniq = (q @ ex).astype(np.float64)                         # (K,)
    v_uniq = (q @ ey).astype(np.float64)                         # (K,)
    # PCA-based patch extent — major axis ≈ ring outer diameter.
    # Using PCA rather than a fixed-axis bbox means a tilted ring is measured
    # along its own axes; a rectangular slab cannot slip past the aspect gate.
    pts2d = np.column_stack([u_uniq, v_uniq])                    # (K, 2)
    if pts2d.shape[0] < 3:
        return False

    _centered = pts2d - pts2d.mean(axis=0)
    # Direct 2×2 covariance via dot-products: avoids np.cov overhead (broadcasting /
    # masked-array checks) for this fixed 2D case. Already mean-subtracted so
    # cov[i,j] = dot(col_i, col_j) / (N-1); N >= 3 guaranteed above.
    _cx = _centered[:, 0]; _cy = _centered[:, 1]
    _denom = _centered.shape[0] - 1
    cxx = np.dot(_cx, _cx) / _denom
    cxy = np.dot(_cx, _cy) / _denom
    cyy = np.dot(_cy, _cy) / _denom
    _, _eigvecs = np.linalg.eigh(np.array([[cxx, cxy], [cxy, cyy]]))

    _proj_pca = _centered @ _eigvecs
    _extents = _proj_pca.max(axis=0) - _proj_pca.min(axis=0)
    long_e = float(_extents.max())
    short_e = float(_extents.min())
    if not (long_e > 0.0 and short_e > 0.0):
        return False
    if long_e < _DRILL_RING_OUTER_DIAM_MIN or long_e > _DRILL_RING_OUTER_DIAM_MAX:
        return False
    if long_e > _DRILL_RING_MAX_ASPECT * short_e:
        return False

    # Diameter/aspect gate passed: now build per-face inverse mapping for scanline.
    # vids_unique is already sorted by np.unique, so searchsorted gives the same
    # inverse as np.unique(..., return_inverse=True) would have produced.
    vids_inv = np.searchsorted(vids_unique, vids_flat)
    uv_inv = vids_inv.reshape(-1, 3)                              # (M_patch, 3)
    u0a = u_uniq[uv_inv[:, 0]]; v0a = v_uniq[uv_inv[:, 0]]
    u1a = u_uniq[uv_inv[:, 1]]; v1a = v_uniq[uv_inv[:, 1]]
    u2a = u_uniq[uv_inv[:, 2]]; v2a = v_uniq[uv_inv[:, 2]]

    # ---- Scanline hole test ----
    if not _drill_patch_has_hole_by_scanlines(u0a, v0a, u1a, v1a, u2a, v2a):
        return False

    # ---- Connection-edge collection + bbox check ----

    # Lookup table vid → (u, v) for connection-edge bbox and chain turn-angle
    vid_to_uv: "dict[int, Tuple[float, float]]" = {
        int(vids_unique[i]): (float(u_uniq[i]), float(v_uniq[i]))
        for i in range(len(vids_unique))
    }

    # Collect edges connecting this patch to near-perpendicular neighbour faces
    COS_PERP = math.cos(87.0 * math.pi / 180.0)   # ≈ 0.05234
    conn_edges: List[Tuple[int, int]] = []
    umin_e = vmin_e = float('inf')
    umax_e = vmax_e = float('-inf')
    patch_id = int(P.id)

    for fi in P.faces:
        vs = face_v[fi]
        for e in range(3):
            a = int(vs[e]); b = int(vs[(e + 1) % 3])
            key = (a, b) if a < b else (b, a)
            ef = edge_map.get(key)
            if ef is None:
                continue
            other = -1
            if len(ef) >= 1 and ef[0] == fi:
                if len(ef) >= 2:
                    other = ef[1]
            elif len(ef) >= 2 and ef[1] == fi:
                other = ef[0]
            if other < 0:
                continue
            if int(face_patch_id[other]) == patch_id:
                continue
            nw = face_n[other]
            nw_len = float(np.linalg.norm(nw))
            if nw_len < 0.5:
                continue
            d = abs(float(np.dot(nw / nw_len, n_patch)))
            if d > COS_PERP:
                continue
            conn_edges.append((a, b))
            ua, va = vid_to_uv[a]
            ub, vb = vid_to_uv[b]
            umin_e = min(umin_e, ua, ub); umax_e = max(umax_e, ua, ub)
            vmin_e = min(vmin_e, va, vb); vmax_e = max(vmax_e, va, vb)

    if len(conn_edges) < 4:
        return False

    dx = umax_e - umin_e; dy = vmax_e - vmin_e
    if dx <= 0.0 or dy <= 0.0:
        return False
    min_d = min(dx, dy); max_d = max(dx, dy)
    if min_d < 3.0 or max_d > 35.0:
        return False

    # ---- Turn-angle chain walk ----

    # Walk connected edge chains; accumulate turn angle (≥220° → drill candidate).
    # Pre-build vertex→edge-index map so each step is O(degree) not O(n_edges).
    # Edges are stored in original append order → first-match semantics preserved.
    ANGLE_THR = 220.0 * math.pi / 180.0
    n_edges = len(conn_edges)
    edge_used = [False] * n_edges

    vert_to_edge_idxs: "dict[int, List[int]]" = {}
    for ei, (ea, eb) in enumerate(conn_edges):
        vert_to_edge_idxs.setdefault(ea, []).append(ei)
        vert_to_edge_idxs.setdefault(eb, []).append(ei)

    for start in range(n_edges):
        if edge_used[start]:
            continue

        sv0, sv1 = conn_edges[start]
        seq: List[int] = [sv0, sv1]
        edge_used[start] = True

        # Walk forward from sv1
        cur = sv1
        while True:
            found = -1
            for ei in vert_to_edge_idxs.get(cur, []):
                if edge_used[ei]:
                    continue
                ea, eb = conn_edges[ei]
                nxt = eb if ea == cur else ea
                found = ei
                break
            if found < 0:
                break
            edge_used[found] = True
            seq.append(nxt)
            cur = nxt
            if cur == sv0:
                break  # closed loop

        # Walk backward from sv0
        cur = sv0
        while True:
            found = -1
            for ei in vert_to_edge_idxs.get(cur, []):
                if edge_used[ei]:
                    continue
                ea, eb = conn_edges[ei]
                prv = eb if ea == cur else ea
                found = ei
                break
            if found < 0:
                break
            edge_used[found] = True
            seq.insert(0, prv)
            cur = prv

        if len(seq) < 3:
            continue

        accum = 0.0
        for i in range(len(seq) - 2):
            p0u, p0v = vid_to_uv[seq[i]]
            p1u, p1v = vid_to_uv[seq[i + 1]]
            p2u, p2v = vid_to_uv[seq[i + 2]]
            t0 = np.array([p1u - p0u, p1v - p0v], dtype=np.float64)
            t1 = np.array([p2u - p1u, p2v - p1v], dtype=np.float64)
            l0 = float(np.linalg.norm(t0)); l1 = float(np.linalg.norm(t1))
            if l0 < 1e-4 or l1 < 1e-4:
                continue
            d = float(np.clip(np.dot(t0 / l0, t1 / l1), -1.0, 1.0))
            accum += math.acos(d)

        if accum >= ANGLE_THR:
            return True

    return False


def detect_drill_holes(mesh: "trimesh.Trimesh") -> dict:
    """
    Detect drill hole end-face candidates in a surgical guide mesh.

    Ported from find_guide_direction() / isDrillPatchByEdges() in
    auto_orient_surg_guide.cpp.  Called conditionally by classify_dental_model()
    after low-cost exclusion checks; may also be called independently by tests
    or other callers.

    Returns:
        {
            "found": bool,           # True if at least one candidate found
            "candidate_count": int,  # total number of drill candidates
        }
    """
    try:
        verts = np.asarray(mesh.vertices, dtype=np.float64)
        faces_raw = np.asarray(mesh.faces, dtype=np.int32)
        nv = len(verts); nf = len(faces_raw)
        if nv <= 0 or nf <= 0:
            return {"valid": True, "found": False, "candidate_count": 0}

        # Step 1: merge near-duplicate vertices (1e-4 mm grid)
        rep = _drill_merge_vertices(verts)

        # Step 2: build per-face arrays (merged indices, normals, centroids, areas)
        face_v, face_n, face_c, face_patch_id, face_area = _drill_prepare_faces(verts, faces_raw, rep)

        # Step 3: build edge map and face adjacency
        edge_map, adj_faces = _drill_build_edge_adj(face_v, nf)

        # Step 4: region growing at 2° → flat patches
        patches = _drill_region_growing(face_n, face_patch_id, adj_faces, nf)
        if not patches:
            return {"valid": True, "found": False, "candidate_count": 0}

        # Step 5: compute patch statistics (reuses face_area; caches fi_arr per patch)
        # Pre-filter to ≥5 faces: patches with fewer faces are unconditionally rejected
        # by Step 6, so computing stats for them wastes the majority of this step's time.
        stat_patches = [P for P in patches if len(P.faces) >= 5]
        _drill_compute_patch_stats(face_v, face_n, face_c, verts, stat_patches, face_area)

        # Step 6: filter drill hole candidates
        candidate_count = 0
        for P in stat_patches:
            if len(P.faces) < 5 or P.area <= 0.0:
                continue
            if _drill_is_drill_patch(verts, face_v, face_n, face_patch_id, edge_map, P):
                candidate_count += 1

        return {"valid": True, "found": candidate_count > 0, "candidate_count": candidate_count}

    except Exception as exc:
        logger.error(f"[detect_drill_holes] failed: {exc}")
        return {"valid": False, "found": None, "candidate_count": None}
