"""
Unit tests for the Z min/max broad-phase filter added to
agent/ortho_pipeline.py::slice_mesh_at_z() (compute_face_z_bounds +
candidate_face_ids). The filter is a necessary-condition test
(face_z_min < z_world < face_z_max) that is mathematically equivalent to
"this face's three edges cannot all satisfy d0*d1<0" when it fails, so it
must never change slice_mesh_at_z()'s output -- only which faces the
unchanged scalar edge loop below it has to visit.
"""
import numpy as np
import trimesh

from agent.ortho_pipeline import compute_face_z_bounds, slice_mesh_at_z


def _mesh_from_triangle(verts):
    return trimesh.Trimesh(
        vertices=np.array(verts, dtype=np.float64),
        faces=np.array([[0, 1, 2]]),
        process=False,
    )


def test_face_all_above_plane_excluded():
    mesh = _mesh_from_triangle([[0, 0, 5], [1, 0, 6], [0, 1, 7]])
    z_min, z_max = compute_face_z_bounds(mesh)
    assert z_min[0] == 5.0 and z_max[0] == 7.0
    candidates = np.flatnonzero((z_min < 0.0) & (z_max > 0.0))
    assert len(candidates) == 0
    assert slice_mesh_at_z(mesh, 0.0) == []


def test_face_all_below_plane_excluded():
    mesh = _mesh_from_triangle([[0, 0, -5], [1, 0, -6], [0, 1, -7]])
    z_min, z_max = compute_face_z_bounds(mesh)
    assert z_min[0] == -7.0 and z_max[0] == -5.0
    candidates = np.flatnonzero((z_min < 0.0) & (z_max > 0.0))
    assert len(candidates) == 0
    assert slice_mesh_at_z(mesh, 0.0) == []


def test_normal_crossing_closes_a_loop():
    """A box has enough shared edges between triangles for the (unchanged)
    chaining step to close a real loop -- confirms the broad-phase filter
    doesn't drop any face the chaining step needs to see."""
    mesh = trimesh.creation.box(extents=[10.0, 10.0, 10.0])  # centered at origin
    loops = slice_mesh_at_z(mesh, 0.0)
    assert len(loops) == 1
    loop = loops[0]
    assert loop.shape[1] == 2
    x = loop[:, 0]
    y = loop[:, 1]
    area = 0.5 * abs(np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y))
    assert abs(area - 100.0) < 1e-6


def test_vertex_exactly_on_plane_matches_pre_existing_zero_segment_behavior():
    """One vertex exactly on the cutting plane, other two straddling it.

    Pre-existing, unrelated-to-this-round quirk: only 1 of 3 edges has
    strict d0*d1<0 (the two edges touching the on-plane vertex give
    d0*d1==0, excluded by the strict test), so only 1 of the 2 points
    needed for a segment is ever found -> 0 segments, both before and
    after this round's filter. This pins that compute_face_z_bounds still
    flags the face as a *candidate* (the filter must never silently drop a
    face the original algorithm would have visited) even though the final
    result is unchanged ([]) because of that pre-existing exactly-2-points
    rule (out of scope to change this round).
    """
    mesh = _mesh_from_triangle([[0, 0, 0], [1, 0, -2], [0, 1, 2]])
    z_min, z_max = compute_face_z_bounds(mesh)
    candidates = np.flatnonzero((z_min < 0.0) & (z_max > 0.0))
    assert len(candidates) == 1  # face_z_min=-2 < 0 < 2=face_z_max
    assert slice_mesh_at_z(mesh, 0.0) == []


def test_coplanar_triangle_excluded():
    mesh = _mesh_from_triangle([[0, 0, 0], [1, 0, 0], [0, 1, 0]])
    z_min, z_max = compute_face_z_bounds(mesh)
    assert z_min[0] == 0.0 and z_max[0] == 0.0
    candidates = np.flatnonzero((z_min < 0.0) & (z_max > 0.0))
    assert len(candidates) == 0  # face_z_min < z_world fails: 0 < 0 is False
    assert slice_mesh_at_z(mesh, 0.0) == []


def test_degenerate_triangle_does_not_crash():
    """Zero-area triangle (two coincident vertex positions) that still
    spans the plane -- the filter must not special-case degeneracy, and
    the unchanged scalar loop below it must not raise."""
    mesh = _mesh_from_triangle([[0, 0, -1], [0, 0, -1], [0, 0, 1]])
    z_min, z_max = compute_face_z_bounds(mesh)
    assert z_min[0] == -1.0 and z_max[0] == 1.0
    result = slice_mesh_at_z(mesh, 0.0)
    assert isinstance(result, list)


def test_empty_mesh_returns_empty_bounds_and_no_loops():
    mesh = trimesh.Trimesh(
        vertices=np.zeros((0, 3)), faces=np.zeros((0, 3), dtype=np.int64), process=False
    )
    z_min, z_max = compute_face_z_bounds(mesh)
    assert z_min.shape == (0,)
    assert z_max.shape == (0,)
    assert slice_mesh_at_z(mesh, 0.0) == []


def test_precomputed_bounds_match_internally_computed_bounds():
    """slice_mesh_at_z(mesh, z, face_z_bounds=...) must be identical to
    slice_mesh_at_z(mesh, z) with bounds computed internally -- this is the
    reuse path generate_side_wall_drains() takes for the outer-shell retry
    lifts."""
    mesh = trimesh.creation.box(extents=[10.0, 10.0, 10.0])
    bounds = compute_face_z_bounds(mesh)
    auto = slice_mesh_at_z(mesh, 1.0)
    precomputed = slice_mesh_at_z(mesh, 1.0, face_z_bounds=bounds)
    assert len(auto) == len(precomputed) == 1
    assert np.array_equal(auto[0], precomputed[0])
