"""
Regression tests for clean_input_for_manifold()'s boundary-edge scan.

``clean_input_for_manifold()`` used to find boundary vertices with
``np.unique(edges_sorted, axis=0, return_counts=True)`` followed by a
``count == 1`` filter, even though nothing downstream ever reads the full
unique-edge/count arrays -- only the flattened, deduplicated vertex set
(``bd_verts``) is used. The optimization replaces that with
``trimesh.grouping.group_rows(edges_sorted, require_count=1)``, an existing
public trimesh API that computes only the boundary-edge indices directly.

These tests pin two things:
  - the *unit-level* boundary-edge classification itself (same vertex set,
    dtype, and ascending order as the pre-optimization algorithm), because
    ``bd_verts`` ordering feeds the KD-tree weld's pair indices, connected-
    component member order, and per-component representative-vertex choice,
    and is not observable from ``clean_input_for_manifold()``'s public
    return value (a ``stats`` dict only); and
  - full end-to-end equivalence of the real, imported production function
    against a test-only oracle copy of the pre-optimization implementation
    (repair/weld trigger, stats, and the final exported mesh).

The oracle below is a verbatim copy of the pre-optimization
``clean_input_for_manifold()`` body. It exists only so these tests have a
pre-optimization behavior to diff against; it is never imported by
production code and must not be promoted to one.
"""

import struct
from collections import defaultdict

import numpy as np
import pytest
import trimesh
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import connected_components
from scipy.spatial import cKDTree

from agent.ortho_pipeline import clean_input_for_manifold


def _reference_boundary_scan(edges_sorted):
    """Oracle for the boundary-edge scan itself: pre-optimization one-liner.
    Test-only; never used by production."""
    ue, c = np.unique(edges_sorted, axis=0, return_counts=True)
    return np.unique(ue[c == 1])


def _production_boundary_scan(edges_sorted):
    """The exact call now used inside clean_input_for_manifold() -- exercised
    directly here (not via a new production helper) so bd_verts itself, which
    clean_input_for_manifold() does not expose in its return value, can be
    compared against the oracle."""
    boundary_idx = trimesh.grouping.group_rows(edges_sorted, require_count=1)
    return np.unique(edges_sorted[boundary_idx])


def _reference_boundary_edges(edges_sorted):
    """Oracle for the boundary EDGE set itself (not just the flattened,
    deduplicated vertex set). Needed because comparing only ``bd_verts`` is
    not sufficient: for edge_count_3/edge_count_4plus, the vertices of the
    over-shared edge coincide with the endpoints of the mesh's real boundary
    edges, so an implementation that wrongly selected the count==3/4 edge as
    "boundary" could still flatten to the exact same ``bd_verts`` set. This
    oracle returns the actual occurrence==1 edges (canonical lexicographic
    order, since np.unique(axis=0) sorts rows ascending)."""
    ue, counts = np.unique(edges_sorted, axis=0, return_counts=True)
    return ue[counts == 1]


def _production_boundary_edges(edges_sorted):
    """The boundary edges actually selected by group_rows(require_count=1),
    re-sorted into the same canonical lexicographic order as the oracle
    (group_rows itself makes no ordering promise for the *edges* it returns,
    only bd_verts's final np.unique() does) so the two edge sets can be
    diffed directly."""
    boundary_idx = trimesh.grouping.group_rows(edges_sorted, require_count=1)
    return np.unique(edges_sorted[boundary_idx], axis=0)


def _reference_clean_input_for_manifold(in_path, out_path, weld_tol=0.5):
    """Oracle: verbatim copy of clean_input_for_manifold() as it existed
    before this optimization (np.unique(axis=0) based boundary scan).
    Test-only oracle; must never be imported by production code."""
    mesh = trimesh.load(str(in_path))
    if isinstance(mesh, trimesh.Scene):
        mesh = trimesh.util.concatenate(mesh.dump())

    stats = {"zero_area_dropped": 0, "merged_verts": 0, "boundary_welded": 0}

    keep = mesh.area_faces > 1e-9
    if not keep.all():
        stats["zero_area_dropped"] = int((~keep).sum())
        mesh.update_faces(keep)
        mesh.remove_unreferenced_vertices()

    before = len(mesh.vertices)
    mesh.merge_vertices(digits_vertex=3)
    stats["merged_verts"] = before - len(mesh.vertices)

    edges_sorted = mesh.edges_sorted
    ue, c = np.unique(edges_sorted, axis=0, return_counts=True)
    bd_verts = np.unique(ue[c == 1])
    if len(bd_verts) > 0:
        pos = mesh.vertices[bd_verts]
        pairs = cKDTree(pos).query_pairs(r=weld_tol)
        if pairs:
            i = np.array([p[0] for p in pairs])
            j = np.array([p[1] for p in pairs])
            n_bd = len(bd_verts)
            g = csr_matrix(
                (np.ones(len(i) * 2), (np.r_[i, j], np.r_[j, i])),
                shape=(n_bd, n_bd),
            )
            _, lab = connected_components(g, directed=False)
            groups = defaultdict(list)
            for idx, l in enumerate(lab):
                groups[l].append(idx)
            remap = np.arange(len(mesh.vertices))
            welded = 0
            for members in groups.values():
                if len(members) < 2:
                    continue
                rep = bd_verts[members[0]]
                for m in members[1:]:
                    remap[bd_verts[m]] = rep
                    welded += 1
            new_faces = remap[mesh.faces]
            valid = (
                (new_faces[:, 0] != new_faces[:, 1])
                & (new_faces[:, 1] != new_faces[:, 2])
                & (new_faces[:, 0] != new_faces[:, 2])
            )
            new_faces = new_faces[valid]
            mesh = trimesh.Trimesh(vertices=mesh.vertices, faces=new_faces, process=True)
            mesh.remove_unreferenced_vertices()
            stats["boundary_welded"] = welded

    mesh.export(str(out_path))
    return stats


def _write_empty_binary_stl(path):
    """A minimal, well-formed 0-triangle binary STL (trimesh cannot export a
    Trimesh with zero faces directly for every case, so this is built by
    hand to exercise the empty-mesh/Scene load path faithfully)."""
    with open(path, "wb") as f:
        f.write(b"\x00" * 80)
        f.write(struct.pack("<I", 0))


def _prep_mesh_for_scan(vertices, faces):
    """Reproduce clean_input_for_manifold()'s prelude (zero-area filter +
    merge_vertices(digits_vertex=3)) so unit-level scan tests exercise the
    same edges_sorted production actually scans."""
    mesh = trimesh.Trimesh(
        vertices=np.asarray(vertices, dtype=np.float64),
        faces=np.asarray(faces, dtype=np.int64),
        process=False,
    )
    keep = mesh.area_faces > 1e-9
    if not keep.all():
        mesh.update_faces(keep)
        mesh.remove_unreferenced_vertices()
    mesh.merge_vertices(digits_vertex=3)
    return mesh


# ---------------------------------------------------------------------------
# Synthetic cases: (name, vertices, faces)
# ---------------------------------------------------------------------------

def _icosphere_case():
    ico = trimesh.creation.icosphere(subdivisions=1)
    return ico.vertices, ico.faces


CASES = {
    "watertight_closed": _icosphere_case(),
    "open_boundary": (
        [[0, 0, 0], [1, 0, 0], [0, 1, 0]],
        [[0, 1, 2]],
    ),
    "duplicate_face": (
        [[0, 0, 0], [1, 0, 0], [0, 1, 0]],
        [[0, 1, 2], [0, 1, 2]],
    ),
    "reversed_duplicate_face": (
        [[0, 0, 0], [1, 0, 0], [0, 1, 0]],
        [[0, 1, 2], [0, 2, 1]],
    ),
    "edge_count_2": (
        [[0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0]],
        [[0, 1, 2], [1, 3, 2]],
    ),
    "edge_count_3": (
        [[0, 0, 0], [0, 0, 1], [1, 0, 0], [-1, 0, 0], [0, 1, 0]],
        [[0, 1, 2], [0, 1, 3], [0, 1, 4]],
    ),
    "edge_count_4plus": (
        [[0, 0, 0], [0, 0, 1], [1, 0, 0], [-1, 0, 0], [0, 1, 0], [0, -1, 0]],
        [[0, 1, 2], [0, 1, 3], [0, 1, 4], [0, 1, 5]],
    ),
    "repeated_index_direct": (
        [[0, 0, 0], [1, 0, 0], [0, 1, 0]],
        [[0, 0, 1], [0, 1, 2]],
    ),
    "repeated_index_via_merge": (
        # Two corners of the same triangle are distinct pre-merge (area >
        # 1e-9, survives the zero-area filter) but quantize to the same
        # digits_vertex=3 bucket, producing a (v, v) self-loop edge that the
        # single upfront zero-area filter (which runs before merge_vertices)
        # never re-checks.
        [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [1.0, 0.0000001, 0.0]],
        [[0, 1, 2]],
    ),
    "disconnected_components": (
        [[0, 0, 0], [1, 0, 0], [0, 1, 0], [10, 10, 0], [11, 10, 0], [10, 11, 0]],
        [[0, 1, 2], [3, 4, 5]],
    ),
    "weld_positive": (
        # Two disconnected open triangles whose boundary vertices include a
        # pair, [0,0,0] and [0.1,0,0], that is:
        #   - farther apart than the merge_vertices(digits_vertex=3) bucket
        #     size (0.001), so they are NOT merged into one vertex there, but
        #   - closer than weld_tol=0.5, so the KD-tree weld step DOES pair
        #     them, exercising query_pairs -> connected_components ->
        #     representative-vertex selection -> remap -> invalid-face
        #     filtering -> Trimesh(process=True) rebuild end-to-end (every
        #     other case in this file has zero pairs within weld_tol, so
        #     none of them actually exercises this branch).
        [
            [0.0, 0.0, 0.0],
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [0.1, 0.0, 0.0],
            [-1.0, 0.0, 0.0],
            [0.0, -1.0, 0.0],
        ],
        [
            [0, 1, 2],
            [3, 4, 5],
        ],
    ),
}


@pytest.mark.parametrize("name", sorted(CASES.keys()))
def test_boundary_scan_matches_reference(name):
    """Unit-level: the production scan call (group_rows) must yield the
    exact same bd_verts (value, dtype, ascending order) as the pre-
    optimization np.unique(axis=0) oracle, on the same edges_sorted.

    This also compares the boundary EDGE sets directly (not just bd_verts),
    because for edge_count_3/edge_count_4plus the over-shared edge's
    endpoints coincide with the endpoints of the mesh's genuine boundary
    edges -- an implementation that wrongly classified the count==3/4 edge
    as boundary could still flatten to the same bd_verts set, so bd_verts
    equality alone would not catch that failure mode."""
    vertices, faces = CASES[name]
    mesh = _prep_mesh_for_scan(vertices, faces)
    edges_sorted = mesh.edges_sorted

    # Sanity: confirm each case actually forms the occurrence count its name
    # promises, post-preprocessing -- otherwise a topology change upstream
    # (e.g. a different zero-area/merge_vertices interaction) could silently
    # turn e.g. "edge_count_3" into a case that no longer has any count==3
    # edge, and the test would still pass for the wrong reason.
    _, occurrence_counts = np.unique(edges_sorted, axis=0, return_counts=True)
    if name == "edge_count_3":
        assert 3 in occurrence_counts, (
            "edge_count_3 case must actually contain an edge with "
            f"occurrence count 3 after preprocessing; got counts {sorted(occurrence_counts.tolist())}"
        )
    if name == "edge_count_4plus":
        assert any(c >= 4 for c in occurrence_counts), (
            "edge_count_4plus case must actually contain an edge with "
            f"occurrence count >=4 after preprocessing; got counts {sorted(occurrence_counts.tolist())}"
        )

    ref_edges = _reference_boundary_edges(edges_sorted)
    new_edges = _production_boundary_edges(edges_sorted)

    assert new_edges.dtype == ref_edges.dtype
    assert new_edges.shape == ref_edges.shape
    assert np.array_equal(new_edges, ref_edges), (
        "boundary-edge arrays (canonical lexicographic order) must match exactly"
    )
    # canonical lexicographic ordering: ascending by (col0, col1), same
    # ordering np.unique(axis=0) itself produces
    if len(new_edges) > 1:
        lexsorted_idx = np.lexsort((new_edges[:, 1], new_edges[:, 0]))
        assert np.array_equal(lexsorted_idx, np.arange(len(new_edges))), (
            "boundary-edge array must already be in ascending lexicographic order"
        )

    ref = _reference_boundary_scan(edges_sorted)
    new = _production_boundary_scan(edges_sorted)

    assert new.dtype == ref.dtype
    assert np.array_equal(new, ref)
    assert list(new) == sorted(new.tolist()), "bd_verts must be ascending"


def test_boundary_scan_matches_reference_empty_mesh():
    """Empty mesh (zero faces): both algorithms must agree edges_sorted is
    empty and bd_verts is an empty, correctly-dtyped array."""
    mesh = _prep_mesh_for_scan(np.zeros((0, 3)), np.zeros((0, 3), dtype=np.int64))
    edges_sorted = mesh.edges_sorted

    ref = _reference_boundary_scan(edges_sorted)
    new = _production_boundary_scan(edges_sorted)

    assert len(ref) == 0
    assert len(new) == 0
    assert new.dtype == ref.dtype


@pytest.mark.parametrize("name", sorted(CASES.keys()))
def test_end_to_end_matches_reference(tmp_path, name):
    """Full clean_input_for_manifold() (the real, imported production
    function) vs. the pre-optimization oracle, driven through the same
    production-shaped path: STL load -> zero-area filter ->
    merge_vertices(digits_vertex=3) -> boundary scan -> KD-tree weld ->
    connected components -> remap/face-filter -> Trimesh(process=True)
    rebuild -> export."""
    vertices, faces = CASES[name]
    in_path = tmp_path / f"{name}_in.stl"
    m = trimesh.Trimesh(
        vertices=np.asarray(vertices, dtype=np.float64),
        faces=np.asarray(faces, dtype=np.int64),
        process=False,
    )
    m.export(str(in_path))

    ref_out = tmp_path / f"{name}_ref_out.stl"
    new_out = tmp_path / f"{name}_new_out.stl"

    ref_stats = _reference_clean_input_for_manifold(in_path, ref_out)
    new_stats = clean_input_for_manifold(in_path, new_out)

    assert new_stats == ref_stats

    if name == "weld_positive":
        # This case exists specifically to force the KD-tree weld branch to
        # actually run (query_pairs -> connected_components -> remap ->
        # invalid-face filtering -> Trimesh(process=True) rebuild). A bare
        # `new_stats == ref_stats` would also pass if both sides trivially
        # welded nothing, so assert the positive count directly.
        assert ref_stats["boundary_welded"] > 0, (
            "weld_positive case must actually trigger welding on the reference "
            f"oracle; got stats {ref_stats}"
        )
        assert new_stats["boundary_welded"] == ref_stats["boundary_welded"]

    mesh_ref = trimesh.load(str(ref_out))
    mesh_new = trimesh.load(str(new_out))
    assert np.array_equal(mesh_ref.vertices, mesh_new.vertices)
    assert np.array_equal(mesh_ref.faces, mesh_new.faces)


def test_end_to_end_matches_reference_empty_mesh_scene(tmp_path):
    """Empty/degenerate STL: trimesh.load() returns a Scene (no .vertices/
    .faces), exercising clean_input_for_manifold()'s isinstance(Scene)
    branch identically on both sides."""
    in_path = tmp_path / "empty_in.stl"
    _write_empty_binary_stl(in_path)

    ref_out = tmp_path / "empty_ref_out.stl"
    new_out = tmp_path / "empty_new_out.stl"

    ref_stats = _reference_clean_input_for_manifold(in_path, ref_out)
    new_stats = clean_input_for_manifold(in_path, new_out)

    assert new_stats == ref_stats

    mesh_ref = trimesh.load(str(ref_out))
    mesh_new = trimesh.load(str(new_out))
    assert isinstance(mesh_ref, trimesh.Scene) == isinstance(mesh_new, trimesh.Scene)
