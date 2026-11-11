"""agent-large-model-perf, spec boolean-mesh-io (design D5).

Two layers:
1. stl_io: the numpy read + weld gives exactly trimesh.load(process=True)'s
   vertices and faces (order included), and the writer round-trips.
2. boolean_operation: compared with the pre-numpy behaviour. The reference is
   the same function with the numpy reader disabled (so inputs go through
   trimesh.load as before) and the writer replaced by the old
   Trimesh(process=True).export -- i.e. exactly the code paths that changed.
"""

import numpy as np
import pytest
import trimesh

from agent import stl_io
from agent.models import BooleanOperation
from agent.sla_operations import boolean_operation


def _soup(mesh: trimesh.Trimesh) -> np.ndarray:
    return mesh.vertices[mesh.faces].astype(np.float32)


def _write_soup(path, tris):
    tris = np.asarray(tris, dtype=np.float32)
    stl_io.write_binary_stl(path, tris.reshape(-1, 3), np.arange(len(tris) * 3).reshape(-1, 3))
    return path


# ---------------------------------------------------------------------------
# stl_io
# ---------------------------------------------------------------------------


def _assert_same_as_trimesh(path):
    verts, faces = stl_io.merge_triangle_vertices(stl_io.read_binary_stl_triangles(path))
    ref = trimesh.load(str(path))
    assert np.array_equal(verts, ref.vertices)
    assert np.array_equal(faces, ref.faces)


class TestMergeMatchesTrimesh:
    def test_closed_mesh(self, tmp_path):
        _assert_same_as_trimesh(_write_soup(tmp_path / "a.stl", _soup(trimesh.creation.icosphere(3))))

    def test_nan_duplicate_and_degenerate_faces(self, tmp_path):
        tris = _soup(trimesh.creation.icosphere(3))
        tris = np.concatenate([tris, tris[:10], tris[:5][:, [0, 0, 1]]])
        tris[3, 1, 2] = np.nan
        tris[7, 0, 0] = np.inf
        np.random.default_rng(0).shuffle(tris)
        _assert_same_as_trimesh(_write_soup(tmp_path / "a.stl", tris))

    def test_tiny_and_near_duplicate_coordinates(self, tmp_path):
        tris = _soup(trimesh.creation.icosphere(3)) * np.float32(1e-3)
        tris[::2] += np.float32(3e-9)
        _assert_same_as_trimesh(_write_soup(tmp_path / "a.stl", tris))

    def test_hash_collision_falls_back_to_exact_grouping(self, monkeypatch):
        """Force every row onto one hash: the exact path must take over."""
        tris = _soup(trimesh.creation.icosphere(2))
        expected = stl_io.merge_triangle_vertices(tris)
        monkeypatch.setattr(stl_io, "_row_hash", lambda u: np.zeros(len(u), dtype=np.uint64))
        got = stl_io.merge_triangle_vertices(tris)
        assert np.array_equal(got[0], expected[0]) and np.array_equal(got[1], expected[1])

    def test_all_faces_non_finite(self):
        tris = np.full((2, 3, 3), np.nan, dtype=np.float32)
        verts, faces = stl_io.merge_triangle_vertices(tris)
        assert verts.shape == (0, 3) and faces.shape == (0, 3)


class TestReadWrite:
    def test_read_rejects_non_exact_files(self, tmp_path):
        good = _write_soup(tmp_path / "a.stl", _soup(trimesh.creation.box()))
        data = good.read_bytes()
        for name, content in [
            ("padded", data + b"\x00" * 50),
            ("truncated", data[:-50]),
            ("ascii", trimesh.exchange.stl.export_stl_ascii(trimesh.creation.box()).encode()),
            ("zero", data[:80] + b"\x00\x00\x00\x00"),
        ]:
            p = tmp_path / f"{name}.stl"
            p.write_bytes(content)
            assert stl_io.read_binary_stl_triangles(p) is None, name

    def test_write_round_trips_with_correct_normals(self, tmp_path):
        mesh = trimesh.creation.icosphere(2)
        p = tmp_path / "out.stl"
        stl_io.write_binary_stl(p, mesh.vertices, mesh.faces)
        assert p.stat().st_size == 84 + 50 * len(mesh.faces)
        back = trimesh.load(str(p))
        assert len(back.faces) == len(mesh.faces)
        assert np.allclose(back.vertices[back.faces], mesh.vertices[mesh.faces].astype(np.float32), atol=0)
        raw = np.fromfile(p, dtype=stl_io._FACE_DTYPE, offset=84)
        assert np.allclose(raw["normal"], mesh.face_normals, atol=1e-6)

    def test_degenerate_face_gets_zero_normal(self):
        verts = np.array([[0, 0, 0], [1, 0, 0], [2, 0, 0]], dtype=float)
        assert np.array_equal(stl_io.face_normals(verts, np.array([[0, 1, 2]])), np.zeros((1, 3)))


# ---------------------------------------------------------------------------
# boolean_operation vs. the pre-numpy behaviour
# ---------------------------------------------------------------------------


@pytest.fixture
def run_before(monkeypatch):
    """Run boolean_operation through the pre-numpy load and write paths."""

    def run(a, b, op, out):
        with monkeypatch.context() as m:
            m.setattr(stl_io, "read_binary_stl_triangles", lambda path: None)

            def old_write(path, verts, faces, header=b""):
                trimesh.Trimesh(vertices=verts, faces=faces, process=True).export(str(path))

            m.setattr(stl_io, "write_binary_stl", old_write)
            return boolean_operation(a, b, op, out)

    return run


def _scene(tmp_path, a: trimesh.Trimesh, b: trimesh.Trimesh):
    pa = tmp_path / "a.stl"
    pb = tmp_path / "b.stl"
    pa.write_bytes(trimesh.exchange.stl.export_stl(a))
    pb.write_bytes(trimesh.exchange.stl.export_stl(b))
    return pa, pb


def _sorted_triangles(mesh: trimesh.Trimesh) -> np.ndarray:
    tri = mesh.vertices[mesh.faces].astype(np.float32)
    # Canonical start corner per triangle (keeps winding), then sort triangles.
    rolled = np.array([np.roll(t, -int(np.lexsort(t.T[::-1])[0]), axis=0) for t in tri])
    flat = rolled.reshape(len(rolled), 9)
    return flat[np.lexsort(flat.T[::-1])]


def _assert_equivalent(before_path, after_path, same_triangles=True):
    before = trimesh.load(str(before_path))
    after = trimesh.load(str(after_path))
    assert len(after.faces) == len(before.faces)
    assert after.is_watertight == before.is_watertight
    assert after.is_winding_consistent == before.is_winding_consistent
    assert np.sign(after.volume) == np.sign(before.volume)
    assert after.volume == pytest.approx(before.volume, rel=1e-6)
    if same_triangles:
        assert np.array_equal(_sorted_triangles(after), _sorted_triangles(before))


@pytest.mark.parametrize("op", list(BooleanOperation), ids=lambda o: o.value)
def test_closed_inputs_match_before(tmp_path, run_before, op):
    a = trimesh.creation.box(extents=[10, 10, 4])
    b = trimesh.creation.icosphere(subdivisions=3, radius=3.0)
    b.apply_translation([2, 1, 2])
    pa, pb = _scene(tmp_path, a, b)
    assert run_before(pa, pb, op, tmp_path / "before.stl") == (True, None, None)
    assert boolean_operation(pa, pb, op, tmp_path / "after.stl") == (True, None, None)
    _assert_equivalent(tmp_path / "before.stl", tmp_path / "after.stl")
    assert trimesh.load(str(tmp_path / "after.stl")).is_watertight


def test_closed_inputs_never_build_trimesh(tmp_path, monkeypatch):
    a = trimesh.creation.box(extents=[10, 10, 4])
    b = trimesh.creation.icosphere(subdivisions=2, radius=3.0)
    pa, pb = _scene(tmp_path, a, b)

    def forbidden(*args, **kwargs):
        raise AssertionError("trimesh.load must not run on the main path")

    monkeypatch.setattr(trimesh, "load", forbidden)
    assert boolean_operation(pa, pb, BooleanOperation.UNION, tmp_path / "out.stl") == (True, None, None)


def test_ascii_input_matches_before(tmp_path, run_before):
    a = trimesh.creation.box(extents=[10, 10, 4])
    b = trimesh.creation.icosphere(subdivisions=2, radius=3.0)
    pa = tmp_path / "a.stl"
    pb = tmp_path / "b.stl"
    pa.write_text(trimesh.exchange.stl.export_stl_ascii(a))
    pb.write_bytes(trimesh.exchange.stl.export_stl(b))
    assert run_before(pa, pb, BooleanOperation.UNION, tmp_path / "before.stl")[0]
    assert boolean_operation(pa, pb, BooleanOperation.UNION, tmp_path / "after.stl")[0]
    _assert_equivalent(tmp_path / "before.stl", tmp_path / "after.stl")


def test_open_input_takes_the_same_repair_path(tmp_path, run_before, monkeypatch):
    """mesh_a with a hole: not a valid Manifold, so the repair sequence runs."""
    a = trimesh.creation.box(extents=[10, 10, 4])
    a.update_faces(np.arange(len(a.faces)) != 0)
    a.remove_unreferenced_vertices()
    b = trimesh.creation.icosphere(subdivisions=2, radius=3.0)
    pa, pb = _scene(tmp_path, a, b)
    before = run_before(pa, pb, BooleanOperation.UNION, tmp_path / "before.stl")

    loads = []
    real_load = trimesh.load
    monkeypatch.setattr(trimesh, "load", lambda *a, **k: loads.append(a[0]) or real_load(*a, **k))
    after = boolean_operation(pa, pb, BooleanOperation.UNION, tmp_path / "after.stl")
    assert str(pa) in loads, "the repair sequence must get the pre-numpy trimesh object"
    assert after[0] == before[0]
    assert after[2] == before[2]
    if before[0]:
        _assert_equivalent(tmp_path / "before.stl", tmp_path / "after.stl")
    else:
        assert after[1].split("\n")[0] == before[1].split("\n")[0]


def test_empty_result(tmp_path):
    a = trimesh.creation.box(extents=[2, 2, 2])
    b = trimesh.creation.box(extents=[2, 2, 2])
    b.apply_translation([10, 0, 0])
    pa, pb = _scene(tmp_path, a, b)
    out = tmp_path / "out.stl"
    assert boolean_operation(pa, pb, BooleanOperation.INTERSECTION, out) == (
        False,
        "Boolean operation resulted in empty mesh",
        None,
    )
    assert not out.exists()
