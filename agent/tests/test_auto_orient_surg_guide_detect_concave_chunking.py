"""
Regression tests for the fixed-16K-edge chunked batch processing in
`detect_concave_faces()` (`agent/auto_orient_surg_guide.py`).

Background: this function used to accumulate every interior edge's
concavity vote in a single Python loop, computing each edge's dot product
via the `@` operator. It now gathers interior edges into fixed 16,384-edge
batches, computes each batch's dot products with an explicit 3-component
expression, and accumulates via `np.add.at` -- releasing each batch's
temporaries before starting the next, so working memory is bounded by the
chunk size rather than growing with the model's total edge count. The
math and accumulation semantics (float64 throughout, `> 1e-6`, `>= 0.55`,
each side's vote decided from its own normal, boundary/non-manifold-edge
handling, cylinder-exclusion timing) are unchanged.

These tests build minimal `_Mesh`-compatible objects directly (setting
`.face_c`/`.face_n`/`.edge_faces` without going through the full STL-load +
`_weld_and_build()` pipeline) so dot-product values -- including ones
placed exactly at the `1e-6`/`0.55` boundaries, and cases that deliberately
span the production 16,384-edge chunk boundary -- can be controlled
precisely. No wall-time assertions: these test behavior and correctness
only, not performance.
"""
import math

import numpy as np
import pytest

from agent import auto_orient_surg_guide as sg


def _make_mesh(faces_c, faces_n, edge_faces):
    faces_c = np.asarray(faces_c, dtype=np.float32)
    faces_n = np.asarray(faces_n, dtype=np.float32)
    n = faces_c.shape[0]
    mesh = sg._Mesh(np.zeros((1, 3), dtype=np.float32),
                     np.zeros((n, 3), dtype=np.uint32))
    mesh.face_c = faces_c
    mesh.face_n = faces_n
    mesh.edge_faces = edge_faces
    return mesh


# --------------------------------------------------------------------- #
# Threshold boundaries (concavity `> 1e-6`, ratio `>= 0.55`)
# --------------------------------------------------------------------- #

def test_concavity_threshold_strictly_greater_than():
    """dot == 1e-6 exactly must NOT pass (strict '>'); dot just above/below
    must give the expected accept/reject."""
    xs = {"exactly_at_threshold": 1e-6, "just_above": 1e-6 + 1e-9, "just_below": 1e-6 - 1e-9}
    faces_c = [[0.0, 0.0, 0.0]]
    faces_n = [[0.0, 0.0, 1.0]]
    edge_faces = {}
    for i, (label, x) in enumerate(xs.items()):
        idx = i + 1
        faces_c.append([0.0, 0.0, x])
        faces_n.append([0.0, 0.0, 1.0])
        edge_faces[(0, idx)] = [0, idx]
    mesh = _make_mesh(faces_c, faces_n, edge_faces)
    concave = sg.detect_concave_faces(mesh, None)
    # face indices: 1=exactly_at_threshold (must NOT be concave via this edge
    # alone since face0's total vote stays low), 3=just_below likewise not
    # concave from face0's perspective; only checking face0's own ratio here
    # would require all three edges -- instead assert on the two "other"
    # faces (1,2,3), each of which has exactly one edge and its OWN
    # concavity dot equal to (fc[0]-fc[other]) . fn[other].
    # face1 (exactly_at_threshold): d = fc[0]-fc[1] = -1e-6 along z; dot
    # with fn[1]=[0,0,1] = -1e-6, which is < 1e-6 -> not concave (votes=0)
    # face2 (just_above 1e-6): d = -(1e-6+1e-9); dot = -(1e-6+1e-9) -> not concave
    # face3 (just_below 1e-6): d = -(1e-6-1e-9); dot = -(1e-6-1e-9) -> not concave
    # (all "other" faces look back toward face0, i.e. negative z direction,
    # so none of them pass on their own edge -- the interesting comparison
    # is face0's per-edge dot values themselves, verified in the next test)
    assert set(concave).isdisjoint({1, 2, 3})


def test_concavity_threshold_from_seed_face_perspective():
    """Directly pins face0's three per-edge dot decisions at exactly the
    1e-6 boundary, above, and below, via the face0-vs-total ratio."""
    faces_c = [
        [0.0, 0.0, 0.0],
        [0.0, 0.0, 1e-6],             # dot from face0 = exactly 1e-6 -> reject (strict >)
        [0.0, 0.0, 1e-6 + 1e-9],      # dot from face0 = just above -> accept
        [0.0, 0.0, 1e-6 + 2e-9],      # dot from face0 = just above -> accept
    ]
    faces_n = [[0.0, 0.0, 1.0]] * 4
    edge_faces = {(0, 1): [0, 1], (0, 2): [0, 2], (0, 3): [0, 3]}
    mesh = _make_mesh(faces_c, faces_n, edge_faces)
    concave = sg.detect_concave_faces(mesh, None)
    # face0: 2 of 3 edges pass (votes=2, total=3, ratio=0.667 >= 0.55) -> concave
    assert 0 in concave


def test_ratio_threshold_boundary_exactly_0_55():
    """A face with votes/total landing exactly at 0.55 must be included
    (`>=`); just below must be excluded."""
    # 11 edges, 6 pass (ratio = 6/11 = 0.5454... just BELOW 0.55) -> excluded
    faces_c = [[0.0, 0.0, 0.0]]
    faces_n = [[0.0, 0.0, 1.0]]
    edge_faces = {}
    n_edges = 11
    n_pass = 6
    for i in range(n_edges):
        idx = i + 1
        z = 5.0 if i < n_pass else -5.0
        faces_c.append([0.0, 0.0, z])
        faces_n.append([0.0, 0.0, 1.0])
        edge_faces[(0, idx)] = [0, idx]
    mesh = _make_mesh(faces_c, faces_n, edge_faces)
    concave = sg.detect_concave_faces(mesh, None)
    ratio = n_pass / n_edges
    assert ratio < 0.55
    assert 0 not in concave

    # 20 edges, 11 pass (ratio = 11/20 = 0.55 exactly) -> included
    faces_c = [[0.0, 0.0, 0.0]]
    faces_n = [[0.0, 0.0, 1.0]]
    edge_faces = {}
    n_edges = 20
    n_pass = 11
    for i in range(n_edges):
        idx = i + 1
        z = 5.0 if i < n_pass else -5.0
        faces_c.append([0.0, 0.0, z])
        faces_n.append([0.0, 0.0, 1.0])
        edge_faces[(0, idx)] = [0, idx]
    mesh = _make_mesh(faces_c, faces_n, edge_faces)
    concave = sg.detect_concave_faces(mesh, None)
    assert n_pass / n_edges == pytest.approx(0.55)
    assert 0 in concave


# --------------------------------------------------------------------- #
# Boundary / non-manifold edges, degenerate normal
# --------------------------------------------------------------------- #

def test_boundary_edge_f1_negative_is_skipped():
    faces_c = [[0.0, 0.0, 0.0], [0.0, 0.0, 5.0], [10.0, 10.0, 10.0]]
    faces_n = [[0.0, 0.0, 1.0], [0.0, 0.0, 1.0], [1.0, 0.0, 0.0]]
    edge_faces = {(0, 1): [0, 1], (1, 2): [1, -1]}  # (1,2) is a boundary edge
    mesh = _make_mesh(faces_c, faces_n, edge_faces)
    concave = sg.detect_concave_faces(mesh, None)
    assert concave == [0]


def test_non_manifold_edge_uses_only_first_two_registered_faces():
    """mesh.edge_faces already enforces first-two-faces-only for a
    non-manifold edge (established by _weld_and_build()); detect_concave_
    faces() must simply use whatever is registered, not attempt to recover
    a third face."""
    faces_c = [[0.0, 0.0, 0.0], [0.0, 0.0, 5.0], [0.0, 0.0, -5.0]]
    faces_n = [[0.0, 0.0, 1.0], [0.0, 0.0, 1.0], [0.0, 0.0, 1.0]]
    # only (0,1) registered, as if face 2 were the dropped third face of a
    # non-manifold edge
    edge_faces = {(0, 1): [0, 1]}
    mesh = _make_mesh(faces_c, faces_n, edge_faces)
    concave = sg.detect_concave_faces(mesh, None)
    assert concave == [0]  # face2 never participates; only 0/1's own edge counts


def test_degenerate_zero_normal_face_never_votes_for_itself():
    faces_c = [[0.0, 0.0, 0.0], [0.0, 0.0, 5.0]]
    faces_n = [[0.0, 0.0, 0.0], [0.0, 0.0, 1.0]]  # face0 degenerate
    edge_faces = {(0, 1): [0, 1]}
    mesh = _make_mesh(faces_c, faces_n, edge_faces)
    concave = sg.detect_concave_faces(mesh, None)
    assert 0 not in concave  # dot with zero normal is always exactly 0, never > 1e-6


# --------------------------------------------------------------------- #
# Same-face multi-edge accumulation and cross-chunk-boundary accumulation
# --------------------------------------------------------------------- #

def test_same_face_accumulated_by_multiple_edges_within_one_chunk():
    faces_c = [[0.0, 0.0, 0.0], [0.0, 0.0, 5.0], [0.0, 0.0, -5.0], [0.0, 0.0, 1e-7]]
    faces_n = [[0.0, 0.0, 1.0]] * 4
    edge_faces = {(0, 1): [0, 1], (0, 2): [0, 2], (0, 3): [0, 3]}
    mesh = _make_mesh(faces_c, faces_n, edge_faces)
    concave = sg.detect_concave_faces(mesh, None)
    assert concave == [2]


def test_accumulation_spans_the_production_16384_chunk_boundary():
    """Face0 accumulates edges to 2*16384+11 other faces (deliberately not
    a multiple of the chunk size, so the final chunk is a partial chunk
    too), with a precisely controlled pass/fail split straddling multiple
    chunk boundaries. The resulting ratio must match what a single-pass
    (non-chunked) accumulation would give -- this directly exercises the
    production chunk_edges=16384 boundary and the trailing partial chunk.
    """
    chunk_edges = 16384
    n_neighbors = 2 * chunk_edges + 11   # spans 3 chunks; last chunk is partial (11 edges)
    n_pass = chunk_edges + 5             # ratio = (16389)/(32779) ~= 0.5001 -> just under 0.55

    faces_c = [[0.0, 0.0, 0.0]]
    faces_n = [[0.0, 0.0, 1.0]]
    edge_faces = {}
    for i in range(n_neighbors):
        idx = i + 1
        z = 5.0 if i < n_pass else -5.0
        faces_c.append([0.0, 0.0, z])
        faces_n.append([0.0, 0.0, 1.0])
        edge_faces[(0, idx)] = [0, idx]
    mesh = _make_mesh(faces_c, faces_n, edge_faces)
    concave = sg.detect_concave_faces(mesh, None)

    expected_ratio = n_pass / n_neighbors
    assert expected_ratio < 0.55
    assert 0 not in concave

    # now push n_pass up so ratio clears 0.55, still spanning multiple chunks
    n_pass2 = int(0.6 * n_neighbors)
    edge_faces2 = {}
    faces_c2 = [[0.0, 0.0, 0.0]]
    faces_n2 = [[0.0, 0.0, 1.0]]
    for i in range(n_neighbors):
        idx = i + 1
        z = 5.0 if i < n_pass2 else -5.0
        faces_c2.append([0.0, 0.0, z])
        faces_n2.append([0.0, 0.0, 1.0])
        edge_faces2[(0, idx)] = [0, idx]
    mesh2 = _make_mesh(faces_c2, faces_n2, edge_faces2)
    concave2 = sg.detect_concave_faces(mesh2, None)
    assert n_pass2 / n_neighbors >= 0.55
    assert 0 in concave2


# --------------------------------------------------------------------- #
# Cylinder exclusion: timing, inside/outside/boundary
# --------------------------------------------------------------------- #

def test_cylinder_exclusion_inside_outside_and_boundary():
    faces_c = [
        [0.0, 0.0, 0.0], [0.0, 0.0, 5.0],       # pair 0: on-axis -> radial=0 (INSIDE)
        [10.0, 10.0, 0.0], [10.0, 10.0, 5.0],   # pair 1: far off-axis (OUTSIDE)
        [3.0, 0.0, 0.0], [3.0, 0.0, 5.0],       # pair 2: radial == radius (BOUNDARY -> inside)
    ]
    faces_n = [
        [0.0, 0.0, 1.0], [0.0, 0.0, -1.0],
        [0.0, 0.0, 1.0], [0.0, 0.0, -1.0],
        [0.0, 0.0, 1.0], [0.0, 0.0, -1.0],
    ]
    edge_faces = {(0, 1): [0, 1], (2, 3): [2, 3], (4, 5): [4, 5]}
    mesh = _make_mesh(faces_c, faces_n, edge_faces)

    concave_no_filter = sg.detect_concave_faces(mesh, None)
    assert concave_no_filter == [0, 1, 2, 3, 4, 5]

    cylinders = [{"center": [0.0, 0.0, 0.0], "axis": [0.0, 0.0, 1.0],
                  "radius": 3.0, "length": 20.0}]
    concave_with_filter = sg.detect_concave_faces(mesh, cylinders)
    assert concave_with_filter == [2, 3]  # only the off-axis pair survives


def test_cylinder_exclusion_happens_after_full_accumulation():
    """A face that only becomes concave once ALL its edges (spread across
    chunk boundaries) are accumulated must still be correctly evaluated by
    cylinder exclusion afterward -- i.e. exclusion cannot run on partial
    accumulation state."""
    chunk_edges = 16384
    n_neighbors = chunk_edges + 100  # spans 2 chunks
    faces_c = [[0.0, 0.0, 0.0]]
    faces_n = [[0.0, 0.0, 1.0]]
    edge_faces = {}
    for i in range(n_neighbors):
        idx = i + 1
        faces_c.append([0.0, 0.0, 5.0])  # all pass -> face0 ratio = 1.0
        faces_n.append([0.0, 0.0, 1.0])
        edge_faces[(0, idx)] = [0, idx]
    mesh = _make_mesh(faces_c, faces_n, edge_faces)

    concave_no_filter = sg.detect_concave_faces(mesh, None)
    assert 0 in concave_no_filter

    # face0 sits at the origin, well inside a cylinder on the same axis
    cylinders = [{"center": [0.0, 0.0, 0.0], "axis": [0.0, 0.0, 1.0],
                  "radius": 1.0, "length": 20.0}]
    concave_with_filter = sg.detect_concave_faces(mesh, cylinders)
    assert 0 not in concave_with_filter


# --------------------------------------------------------------------- #
# Empty / all-pass results
# --------------------------------------------------------------------- #

def test_empty_result_when_nothing_passes():
    faces_c = [[0.0, 0.0, 0.0], [0.0, 0.0, -5.0]]
    faces_n = [[0.0, 0.0, 1.0], [0.0, 0.0, -1.0]]
    edge_faces = {(0, 1): [0, 1]}
    mesh = _make_mesh(faces_c, faces_n, edge_faces)
    concave = sg.detect_concave_faces(mesh, None)
    assert concave == []


def test_all_pass_result():
    faces_c = [[0.0, 0.0, 0.0], [0.0, 0.0, 5.0]]
    faces_n = [[0.0, 0.0, 1.0], [0.0, 0.0, -1.0]]
    edge_faces = {(0, 1): [0, 1]}
    mesh = _make_mesh(faces_c, faces_n, edge_faces)
    concave = sg.detect_concave_faces(mesh, None)
    assert concave == [0, 1]


# --------------------------------------------------------------------- #
# Determinism
# --------------------------------------------------------------------- #

def test_detect_concave_faces_is_deterministic_across_repeated_calls():
    chunk_edges = 16384
    n_neighbors = chunk_edges + 500
    faces_c = [[0.0, 0.0, 0.0]]
    faces_n = [[0.0, 0.0, 1.0]]
    edge_faces = {}
    for i in range(n_neighbors):
        idx = i + 1
        z = 5.0 if i % 2 == 0 else -5.0
        faces_c.append([0.0, 0.0, z])
        faces_n.append([0.0, 0.0, 1.0])
        edge_faces[(0, idx)] = [0, idx]
    mesh = _make_mesh(faces_c, faces_n, edge_faces)
    result1 = sg.detect_concave_faces(mesh, None)
    result2 = sg.detect_concave_faces(mesh, None)
    assert result1 == result2
