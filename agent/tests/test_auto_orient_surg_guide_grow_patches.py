"""
Regression tests for the Phase 1 `_grow_patches()` per-patch statistics
optimization in `agent/auto_orient_surg_guide.py`.

Background: `_grow_patches()`'s Step 5 (per-patch avgNormal/area/center) used
to run unconditionally for every patch produced by BFS region growing --
including patches with fewer than 5 faces, which every known consumer
(`_find_guide_direction()`'s drill-candidate filter,
`_refine_up_with_quasi_candidates()`'s quasi-candidate scan) rejects before
reading `.area`/`.avg_normal`/`.center` via a `len(P.faces) < 5 or ...`
short-circuit. It also recomputed each face's area from scratch via
`_norm(_cross(...))` instead of reusing `mesh.face_area` (already computed,
with the same formula, by `_weld_and_build()`), and computed `max_angle_deg`,
a field with no reader anywhere in the module.

The optimization (mirroring the already-shipped equivalent in
`model_classifier.py::_drill_compute_patch_stats`) is: skip stats entirely
for patches with < 5 faces (leaving `_Patch` dataclass defaults), reuse
`mesh.face_area`, and stop computing `max_angle_deg` (field kept on the
dataclass for compatibility). These tests pin that behavior and the
invariants that make it safe.
"""

from unittest.mock import patch

import numpy as np
import pytest

from agent import auto_orient_surg_guide as sg


def _grid_patch_mesh():
    """A 3x3 grid of unit squares (18 coplanar triangles, +Z normal, total
    area 9.0, centroid (1.5, 1.5, 0)) plus one isolated triangle far away
    (1 face, its own patch). The two regions share no vertices/edges, so BFS
    region growing must produce exactly two patches: one with 18 faces and
    one with 1 face."""
    verts = []
    idx = {}
    for j in range(4):
        for i in range(4):
            idx[(i, j)] = len(verts)
            verts.append([float(i), float(j), 0.0])

    faces = []
    for j in range(3):
        for i in range(3):
            a = idx[(i, j)]
            b = idx[(i + 1, j)]
            c = idx[(i, j + 1)]
            d = idx[(i + 1, j + 1)]
            faces.append([a, b, d])
            faces.append([a, d, c])

    # isolated single triangle, far from the grid, no shared vertices/edges
    iso0 = len(verts)
    verts.append([1000.0, 1000.0, 1000.0])
    verts.append([1001.0, 1000.0, 1000.0])
    verts.append([1000.0, 1001.0, 1000.0])
    faces.append([iso0, iso0 + 1, iso0 + 2])

    v = np.asarray(verts, dtype=np.float32)
    f = np.asarray(faces, dtype=np.uint32)
    return v, f


def _build_patches():
    v, f = _grid_patch_mesh()
    mesh = sg._weld_and_build(v, f)
    patches = sg._grow_patches(mesh)
    return mesh, patches


def test_grow_patches_produces_expected_two_patches():
    mesh, patches = _build_patches()
    sizes = sorted(len(P.faces) for P in patches)
    assert sizes == [1, 18]


def test_small_patch_keeps_dataclass_defaults():
    """Patches with < 5 faces must not have statistics computed: they keep
    the _Patch dataclass defaults (area=0.0, avg_normal=zeros, center=zeros,
    max_angle_deg=0.0) because every real consumer rejects them first via a
    `len(P.faces) < 5` short-circuit before ever reading these fields."""
    mesh, patches = _build_patches()
    small = [P for P in patches if len(P.faces) == 1]
    assert len(small) == 1
    P = small[0]
    assert P.area == 0.0
    assert np.array_equal(P.avg_normal, np.zeros(3, dtype=np.float32))
    assert np.array_equal(P.center, np.zeros(3, dtype=np.float32))
    assert P.max_angle_deg == 0.0


def test_qualifying_patch_stats_match_expected_geometry():
    """The >=5-face patch (the 3x3 coplanar grid) must get correct area,
    avg_normal, and center -- computed via mesh.face_area reuse, not via a
    fresh per-face cross-product recompute."""
    mesh, patches = _build_patches()
    big = [P for P in patches if len(P.faces) == 18]
    assert len(big) == 1
    P = big[0]

    assert P.area == pytest.approx(9.0, abs=1e-4)
    np.testing.assert_allclose(P.avg_normal, [0.0, 0.0, 1.0], atol=1e-6)
    np.testing.assert_allclose(P.center, [1.5, 1.5, 0.0], atol=1e-4)

    # area must equal the sum of the reused, already-vectorized mesh.face_area
    # for exactly this patch's faces -- pins "reuse, don't recompute"
    expected_area = float(mesh.face_area[np.asarray(P.faces, dtype=np.int64)].sum())
    assert P.area == pytest.approx(expected_area, abs=1e-9)

    # max_angle_deg is no longer computed even for a qualifying patch
    assert P.max_angle_deg == 0.0


def test_grow_patches_never_recomputes_area_via_cross_product():
    """Direct regression pin for the optimization itself: _cross() was only
    ever called (inside _grow_patches) by the old Step 5 area recompute
    (`0.5 * _norm(_cross(p1-p0, p2-p0))`); BFS region growing never calls it.
    With the optimization, _grow_patches() must not call _cross() at all --
    area comes from mesh.face_area (computed via numpy's np.cross in
    _weld_and_build, not the scalar _cross() helper)."""
    v, f = _grid_patch_mesh()
    mesh = sg._weld_and_build(v, f)  # unaffected: uses np.cross, not sg._cross
    with patch.object(sg, "_cross", wraps=sg._cross) as mock_cross:
        sg._grow_patches(mesh)
        assert mock_cross.call_count == 0


def test_max_angle_deg_field_still_exists_for_compatibility():
    """The field itself is kept on _Patch (only its computation was removed),
    matching the precedent in model_classifier.py's _DrillPatchInfo."""
    P = sg._Patch(id=0)
    assert hasattr(P, "max_angle_deg")
    assert P.max_angle_deg == 0.0
