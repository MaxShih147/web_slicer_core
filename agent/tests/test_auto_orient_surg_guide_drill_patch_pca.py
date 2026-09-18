"""
Regression tests for the PCA projection/covariance vectorization in
`_is_drill_patch_by_edges()` (`agent/auto_orient_surg_guide.py`).

Background: this function used to build the patch's projected 2D point
cloud via a per-vertex Python loop calling `project_to_plane()`, then fed it
to `np.cov()`. Both were replaced with batched NumPy matrix ops (a single
`(K,3) @ (3,)` matmul per axis for the projection, a direct 2x2 covariance
via dot products instead of `np.cov()`) -- mirroring the already-shipped
equivalent in `model_classifier.py::_drill_is_drill_patch`. The function's
inputs/outputs, orthonormal basis rules, thresholds, eigenvector ordering
semantics, long/short axis logic, early rejection order, and scanline/
turn-angle call sites are all unchanged; only how the intermediate 2D point
cloud and its covariance matrix are computed changed.

These tests pin the diameter/aspect gate's accept/reject boundary against
known rectangle geometry (so a regression in the projection or covariance
math would show up as a wrong gate decision, not just "some numbers
changed"), and directly pin the optimization itself (no `np.cov` call).
"""
from unittest.mock import patch

import numpy as np
import pytest

from agent import auto_orient_surg_guide as sg


def _rect_patch_mesh(width_mm: float, height_mm: float, nx: int, ny: int):
    """A single flat (+Z normal) rectangular grid patch of nx*ny*2 coplanar
    triangles spanning [0, width_mm] x [0, height_mm] on the z=0 plane, with
    no interior hole. Vertex spacing is uniform, so the point cloud's
    principal axes align exactly with global X/Y and the PCA extents equal
    the rectangle's true width/height."""
    dx = width_mm / nx
    dy = height_mm / ny
    verts = []
    idx = {}
    for j in range(ny + 1):
        for i in range(nx + 1):
            idx[(i, j)] = len(verts)
            verts.append([i * dx, j * dy, 0.0])

    faces = []
    for j in range(ny):
        for i in range(nx):
            a = idx[(i, j)]
            b = idx[(i + 1, j)]
            c = idx[(i, j + 1)]
            d = idx[(i + 1, j + 1)]
            faces.append([a, b, d])
            faces.append([a, d, c])

    v = np.asarray(verts, dtype=np.float32)
    f = np.asarray(faces, dtype=np.uint32)
    return v, f


def _single_patch(width_mm, height_mm, nx, ny):
    v, f = _rect_patch_mesh(width_mm, height_mm, nx, ny)
    mesh = sg._weld_and_build(v, f)
    patches = sg._grow_patches(mesh)
    assert len(patches) == 1
    return mesh, patches[0]


def test_rectangle_patch_has_expected_pca_extents_and_reaches_scanline():
    """An 8x6mm solid rectangle (long=8 in [5.5,14], aspect=8/6=1.33<=1.5)
    must pass the diameter/aspect gate -- i.e. the vectorized PCA projection
    and covariance must compute the correct extents for a shape whose true
    dimensions are known exactly (axis-aligned uniform grid: PCA axes align
    with global X/Y, so the extents equal width/height exactly). Reaching
    _patch_has_hole_by_scanlines() is the observable proof the gate passed;
    since the rectangle has no hole, the overall result is still False."""
    mesh, P = _single_patch(8.0, 6.0, 8, 6)
    assert P.area == pytest.approx(48.0, abs=1e-6)
    np.testing.assert_allclose(P.avg_normal, [0.0, 0.0, 1.0], atol=1e-6)

    with patch.object(sg, "_patch_has_hole_by_scanlines", wraps=sg._patch_has_hole_by_scanlines) as mock_scan:
        result = sg._is_drill_patch_by_edges(mesh, P)
        assert mock_scan.called, "gate should have passed and reached the scanline hole test"

    assert result is False  # solid rectangle: scanline correctly finds no hole


def test_undersized_patch_rejected_before_scanline():
    """A 3x2mm rectangle: long_edge=3.0 < RING_OUTER_DIAM_MIN (5.5) must be
    rejected by the diameter gate without ever reaching the scanline test."""
    mesh, P = _single_patch(3.0, 2.0, 3, 2)
    with patch.object(sg, "_patch_has_hole_by_scanlines") as mock_scan:
        result = sg._is_drill_patch_by_edges(mesh, P)
    assert not mock_scan.called
    assert result is False


def test_overly_elongated_patch_rejected_before_scanline():
    """A 12x2mm rectangle: long_edge=12.0 is within [5.5,14] but
    aspect=12/2=6.0 > RING_MAX_ASPECT (1.5) must be rejected by the aspect
    gate without ever reaching the scanline test."""
    mesh, P = _single_patch(12.0, 2.0, 12, 2)
    with patch.object(sg, "_patch_has_hole_by_scanlines") as mock_scan:
        result = sg._is_drill_patch_by_edges(mesh, P)
    assert not mock_scan.called
    assert result is False


def test_is_drill_patch_by_edges_never_calls_np_cov():
    """Direct regression pin for the optimization itself: the PCA covariance
    must be computed via the direct 2x2 dot-product formula, not np.cov()."""
    mesh, P = _single_patch(8.0, 6.0, 8, 6)
    with patch("numpy.cov") as mock_cov:
        sg._is_drill_patch_by_edges(mesh, P)
    assert not mock_cov.called


def test_ignore_angle_quasi_candidate_path_unaffected():
    """_refine_up_with_quasi_candidates() calls this function with
    ignore_angle=True to find shape/size/hole/wall-qualifying patches while
    skipping the 220 deg turn-angle gate; the PCA gate ahead of it must
    behave identically regardless of ignore_angle."""
    mesh, P = _single_patch(3.0, 2.0, 3, 2)
    with patch.object(sg, "_patch_has_hole_by_scanlines") as mock_scan:
        result = sg._is_drill_patch_by_edges(mesh, P, ignore_angle=True)
    assert not mock_scan.called
    assert result is False
