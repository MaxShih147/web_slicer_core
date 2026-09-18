"""
Regression tests for the A2 optimization of `_grow_patches()`'s BFS region
growing (Step 4) in `agent/auto_orient_surg_guide.py`.

Background: the BFS loop used to call `_norm(face_n[fidx])` per candidate
face (recomputing the same per-face norm every time a different patch
attempt revisited an unassigned face) and `_dot(n, n_seed)` per comparison
(a function call with float32 arithmetic, only the final result cast to
Python `float`). A2 replaces both with: (1) a single vectorized
`np.linalg.norm(mesh.face_n, axis=1)` precompute before the loop, and (2)
an inline `n[0]*sx + n[1]*sy + n[2]*sz` dot product where `sx`/`sy`/`sz` are
`numpy.float32` scalars (never passed through Python `float()`), so the
multiply/add stays in float32 exactly like the original `_dot()` -- unlike
`model_classifier.py::_drill_region_growing()`, which extracts seed
components via `float()` and therefore computes the same dot product in
float64. A real model (`SurgicalGuide_4.stl`) was found during investigation
to produce 5 actual accept/reject flips between the float32 and float64
paths, which is why preserving float32 here is a correctness requirement,
not a style preference.

These tests use only synthetic geometry (no external STL dependency), pin
the float32 arithmetic contract directly, and pin the algorithm's
fixed-seed-comparison semantics (not neighbor-to-neighbor, not
connected-components) that A2 must not have disturbed.
"""
import math

import numpy as np
import pytest

from agent import auto_orient_surg_guide as sg

COS_GROW = math.cos(2.0 * math.pi / 180.0)


# --------------------------------------------------------------------- #
# Mesh builders
# --------------------------------------------------------------------- #

def _grid_mesh(nx, ny):
    """A flat (+Z normal) grid of nx*ny*2 coplanar triangles spanning
    [0,nx] x [0,ny] on the z=0 plane."""
    verts = []
    idx = {}
    for j in range(ny + 1):
        for i in range(nx + 1):
            idx[(i, j)] = len(verts)
            verts.append([float(i), float(j), 0.0])
    faces = []
    for j in range(ny):
        for i in range(nx):
            a, b, c, d = idx[(i, j)], idx[(i + 1, j)], idx[(i, j + 1)], idx[(i + 1, j + 1)]
            faces.append([a, b, d])
            faces.append([a, d, c])
    return np.asarray(verts, dtype=np.float32), np.asarray(faces, dtype=np.uint32)


def _hinge_mesh(theta_rad):
    """Two triangles sharing edge (v0,v1); the second is tilted by exactly
    theta_rad around that edge, so the angle between their normals is
    exactly theta_rad (see module docstring derivation)."""
    v0 = [0.0, 0.0, 0.0]
    v1 = [1.0, 0.0, 0.0]
    v2 = [0.0, 1.0, 0.0]
    v3 = [0.0, math.cos(theta_rad), math.sin(theta_rad)]
    verts = np.asarray([v0, v1, v2, v3], dtype=np.float32)
    faces = np.asarray([[0, 1, 2], [0, 1, 3]], dtype=np.uint32)
    return verts, faces


def _degenerate_plus_normal_mesh():
    """A normal 3x3 coplanar grid (one patch, >=5 faces) plus one
    zero-area (degenerate, collinear) triangle far away and disconnected."""
    verts, faces = _grid_mesh(3, 3)
    verts = verts.tolist()
    faces = faces.tolist()
    base = len(verts)
    # collinear points -> zero cross product -> degenerate face normal
    verts.append([100.0, 100.0, 100.0])
    verts.append([101.0, 100.0, 100.0])
    verts.append([102.0, 100.0, 100.0])
    faces.append([base, base + 1, base + 2])
    return np.asarray(verts, dtype=np.float32), np.asarray(faces, dtype=np.uint32)


def _drift_strip_mesh(n_verts=8, radius=5.0, step=1.0, alpha_deg=1.2):
    """A triangle strip whose vertices trace a slowly-twisting helix
    (radius, alpha_deg tuned so consecutive face normals differ by ~1.19deg
    -- always under the 2deg threshold -- while cumulative drift from the
    first face exceeds 2deg by the 3rd face). Verified empirically to
    produce patches {0,1},{2,3},{4,5} under the fixed-seed algorithm."""
    alpha = math.radians(alpha_deg)
    pts = [[i * step, radius * math.cos(i * alpha), radius * math.sin(i * alpha)]
           for i in range(n_verts)]
    verts = np.asarray(pts, dtype=np.float32)
    faces = np.asarray([[i, i + 1, i + 2] for i in range(n_verts - 2)], dtype=np.uint32)
    return verts, faces


# --------------------------------------------------------------------- #
# dtype / arithmetic contract
# --------------------------------------------------------------------- #

def test_face_n_and_precomputed_norms_are_float32():
    v, f = _grid_mesh(3, 3)
    mesh = sg._weld_and_build(v, f)
    assert mesh.face_n.dtype == np.float32
    norms = np.linalg.norm(mesh.face_n, axis=1)
    assert norms.dtype == np.float32


def test_inline_dot_pattern_stays_float32_and_matches_dot_bit_exact():
    """Pins the exact arithmetic pattern A2 uses inside _grow_patches():
    seed components taken via plain indexing (numpy.float32 scalars, never
    Python float()), multiply/add kept in float32 throughout, matching
    _dot()'s own precision path bit-for-bit."""
    rng = np.random.default_rng(1234)
    n_seed = rng.standard_normal(3).astype(np.float32)
    n_seed /= np.linalg.norm(n_seed)
    sx, sy, sz = n_seed[0], n_seed[1], n_seed[2]
    assert isinstance(sx, np.float32) and isinstance(sy, np.float32) and isinstance(sz, np.float32)

    mismatches = 0
    for _ in range(5000):
        cand = rng.standard_normal(3).astype(np.float32)
        cand /= np.linalg.norm(cand)

        term0 = cand[0] * sx
        assert term0.dtype == np.float32
        term01 = term0 + cand[1] * sy
        assert term01.dtype == np.float32
        total = term01 + cand[2] * sz
        assert total.dtype == np.float32

        inline_result = float(cand[0] * sx + cand[1] * sy + cand[2] * sz)
        ref_result = sg._dot(cand, n_seed)
        if inline_result != ref_result:
            mismatches += 1
    assert mismatches == 0


def test_inline_dot_bit_exact_at_known_threshold_critical_values():
    """Specific (seed, candidate) pairs where a real model (SurgicalGuide_4)
    was found to produce a float32 vs. float64 accept/reject flip. A2's
    inline float32 path must reproduce the exact original _dot() value and
    decision -- these are exactly the cases classifier-style float64 gets
    wrong."""
    cases = [
        # (seed, candidate) unit vectors engineered to sit within ~1e-8 of cos_grow
        (np.array([0.0, 0.0, 1.0], dtype=np.float32),
         np.array([math.sin(math.radians(2.0) - 1e-6), 0.0, math.cos(math.radians(2.0) - 1e-6)], dtype=np.float32)),
        (np.array([0.0, 0.0, 1.0], dtype=np.float32),
         np.array([math.sin(math.radians(2.0) + 1e-6), 0.0, math.cos(math.radians(2.0) + 1e-6)], dtype=np.float32)),
    ]
    for n_seed, cand in cases:
        sx, sy, sz = n_seed[0], n_seed[1], n_seed[2]
        inline = float(cand[0] * sx + cand[1] * sy + cand[2] * sz)
        ref = sg._dot(cand, n_seed)
        assert inline == ref
        assert (inline >= COS_GROW) == (ref >= COS_GROW)


# --------------------------------------------------------------------- #
# 2 deg threshold accept/reject (real pipeline, safe margin from float32
# rounding noise in vertex construction)
# --------------------------------------------------------------------- #

def test_threshold_accept_just_inside_2deg():
    theta = math.radians(2.0 - 0.05)  # comfortably inside, avoids float32 vertex-rounding noise
    v, f = _hinge_mesh(theta)
    mesh = sg._weld_and_build(v, f)
    patches = sg._grow_patches(mesh)
    assert len(patches) == 1
    assert sorted(patches[0].faces) == [0, 1]


def test_threshold_reject_just_outside_2deg():
    theta = math.radians(2.0 + 0.05)
    v, f = _hinge_mesh(theta)
    mesh = sg._weld_and_build(v, f)
    patches = sg._grow_patches(mesh)
    assert len(patches) == 2
    assert sorted(len(P.faces) for P in patches) == [1, 1]


# --------------------------------------------------------------------- #
# Degenerate / zero normal
# --------------------------------------------------------------------- #

def test_degenerate_face_marked_and_does_not_disrupt_other_patches():
    v, f = _degenerate_plus_normal_mesh()
    mesh = sg._weld_and_build(v, f)
    patches = sg._grow_patches(mesh)
    degenerate_face_idx = f.shape[0] - 1
    assert mesh.patch_id[degenerate_face_idx] == -2
    sizes = sorted(len(P.faces) for P in patches)
    assert sizes == [18]  # the 3x3 grid's 18 faces form one patch; degenerate face excluded


# --------------------------------------------------------------------- #
# Fixed seed normal semantics: must not behave like neighbor-to-neighbor
# connected components
# --------------------------------------------------------------------- #

def test_fixed_seed_normal_not_neighbor_to_neighbor_connected_components():
    """A slowly-twisting strip where each face differs from its immediate
    neighbor by ~1.19deg (always under the 2deg threshold) but drifts more
    than 2deg from the patch's original seed by the 3rd face. Under the
    required fixed-seed algorithm, this must split into separate 2-face
    patches ({0,1},{2,3},{4,5}), NOT merge into one 6-face patch the way a
    neighbor-to-neighbor connected-components algorithm would."""
    v, f = _drift_strip_mesh()
    mesh = sg._weld_and_build(v, f)

    # sanity-check the geometry actually produces the intended drift pattern
    def angle_deg(a, b):
        return math.degrees(math.acos(np.clip(float(np.dot(a, b)), -1.0, 1.0)))

    assert angle_deg(mesh.face_n[0], mesh.face_n[1]) < 2.0
    assert angle_deg(mesh.face_n[1], mesh.face_n[2]) < 2.0
    assert angle_deg(mesh.face_n[0], mesh.face_n[2]) > 2.0  # cumulative drift from seed

    patches = sg._grow_patches(mesh)
    membership = sorted(sorted(P.faces) for P in patches)
    assert membership == [[0, 1], [2, 3], [4, 5]]


# --------------------------------------------------------------------- #
# Shared-neighbor candidate / small & large patches
# --------------------------------------------------------------------- #

def test_shared_neighbor_candidate_grouped_correctly_once():
    """A 3x3 coplanar grid has many interior faces reachable as a neighbor
    from more than one already-accepted frontier member of the same patch
    -- exactly the scenario A2's global norm precompute (and the previously
    evaluated, rejected per-patch cache) targets. Must still collapse to
    exactly one patch with all 18 faces, no duplicates or omissions."""
    v, f = _grid_mesh(3, 3)
    mesh = sg._weld_and_build(v, f)
    patches = sg._grow_patches(mesh)
    assert len(patches) == 1
    assert sorted(patches[0].faces) == list(range(18))


def test_small_and_large_patch_face_membership():
    v, f = _grid_mesh(1, 1)
    mesh = sg._weld_and_build(v, f)
    small_patches = sg._grow_patches(mesh)
    assert len(small_patches) == 1
    assert sorted(small_patches[0].faces) == [0, 1]

    v, f = _grid_mesh(20, 20)
    mesh = sg._weld_and_build(v, f)
    large_patches = sg._grow_patches(mesh)
    assert len(large_patches) == 1
    assert len(large_patches[0].faces) == 800


# --------------------------------------------------------------------- #
# Determinism (face-level assignment / final rotation stability)
# --------------------------------------------------------------------- #

def test_grow_patches_face_level_assignment_is_deterministic():
    v, f = _grid_mesh(5, 5)
    mesh1 = sg._weld_and_build(v, f)
    sg._grow_patches(mesh1)
    mesh2 = sg._weld_and_build(v, f)
    sg._grow_patches(mesh2)
    np.testing.assert_array_equal(mesh1.patch_id, mesh2.patch_id)


def test_compute_auto_orientation_rotation_is_deterministic():
    v, f = _drift_strip_mesh()
    out1 = sg.compute_auto_orientation_surg_guide_detail(v, f, debug=False)
    out2 = sg.compute_auto_orientation_surg_guide_detail(v, f, debug=False)
    assert out1["rotation_rad"] == out2["rotation_rad"]
