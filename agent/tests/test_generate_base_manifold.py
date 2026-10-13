"""
Regression tests: generate_base() must return a closed, consistently wound
manifold when the open boundary is a simple polygon in XY.

Fixtures are synthetic open-bottom shells (a prism capped on top) whose rim
is a hand-built polygon, so no scan data is involved.
"""

import io

import numpy as np
import pytest

trimesh = pytest.importorskip("trimesh")
mapbox_earcut = pytest.importorskip("mapbox_earcut")

from agent.boundary_detection import _boundary_xy_is_simple, generate_base  # noqa: E402


def _open_shell(poly, z0=2.0, height=3.0):
    """Open-bottom shell over CCW polygon `poly`: side walls plus a top cap."""
    poly = np.asarray(poly, dtype=np.float64)
    n = len(poly)
    bot = np.column_stack([poly, np.full(n, z0)])
    top = np.column_stack([poly, np.full(n, z0 + height)])
    faces = []
    for i in range(n):
        j = (i + 1) % n
        faces.append([i, j, n + j])
        faces.append([i, n + j, n + i])
    cap = mapbox_earcut.triangulate_float64(poly, np.array([n])).reshape(-1, 3) + n
    return trimesh.Trimesh(
        vertices=np.vstack([bot, top]),
        faces=np.vstack([np.array(faces), cap]),
        process=False,
    )


def _rim_with_dense_side(jitter=0.0):
    """CCW rim: 60 closely spaced points along the bottom edge, 4 sparse
    corners elsewhere. Uneven spacing is what fooled the smoothed-tangent wall
    orientation; `jitter` alternately offsets the dense points off the line so
    earcut cuts near-zero-area slivers there."""
    xs = np.linspace(0.0, 6.0, 60, endpoint=False)
    pts = [(x, jitter if i % 2 else 0.0) for i, x in enumerate(xs)]
    pts += [(6.0, 0.0), (6.0, 4.0), (3.0, 6.0), (0.0, 4.0)]
    return pts


def _topology(stl_bytes):
    m = trimesh.Trimesh(**trimesh.exchange.stl.load_stl(io.BytesIO(stl_bytes)), process=False)
    m.merge_vertices()
    _, undirected = np.unique(np.sort(m.edges, axis=1), axis=0, return_counts=True)
    _, directed = np.unique(m.edges, axis=0, return_counts=True)
    return {
        "boundary": int((undirected == 1).sum()),
        "non_manifold": int((undirected > 2).sum()),
        "flipped": int((directed > 1).sum()),
    }


def test_simple_rim_walls_are_not_flipped(monkeypatch):
    # Defect 1: on a simple CCW rim the per-segment orientation heuristic
    # flipped wall quads, giving duplicate halfedges (inconsistent winding).
    monkeypatch.delenv("BASE_GEN_WALL_ORIENT", raising=False)
    shell = _open_shell(_rim_with_dense_side())
    topo = _topology(generate_base(mesh=shell, elevation=0.5, skip_orient=True))
    assert topo == {"boundary": 0, "non_manifold": 0, "flipped": 0}


def test_earcut_slivers_do_not_open_holes(monkeypatch):
    # Defect 2: dropping earcut's near-zero-area bottom triangles left boundary
    # edges at z=0. Wall orientation is disabled to isolate this defect.
    monkeypatch.setenv("BASE_GEN_WALL_ORIENT", "0")
    shell = _open_shell(_rim_with_dense_side(jitter=1e-9))
    topo = _topology(generate_base(mesh=shell, elevation=0.5, skip_orient=True))
    assert topo == {"boundary": 0, "non_manifold": 0, "flipped": 0}


def test_default_env_output_is_closed_manifold(monkeypatch):
    monkeypatch.delenv("BASE_GEN_WALL_ORIENT", raising=False)
    shell = _open_shell(_rim_with_dense_side(jitter=1e-9))
    out = trimesh.Trimesh(
        **trimesh.exchange.stl.load_stl(io.BytesIO(
            generate_base(mesh=shell, elevation=0.5, skip_orient=True)
        )),
        process=False,
    )
    out.merge_vertices()
    assert out.is_watertight
    assert out.is_winding_consistent
    assert out.volume > 0


@pytest.mark.parametrize(
    "pts, expected",
    [
        ([(0, 0), (1, 0), (1, 1), (0, 1)], True),
        (_rim_with_dense_side(), True),
        (_rim_with_dense_side(jitter=1e-9), True),
        # figure eight: edges cross
        ([(0, 0), (1, 1), (1, 0), (0, 1)], False),
        # pinch: the loop touches itself at (1, 1)
        ([(0, 0), (1, 1), (2, 0), (2, 2), (1, 1), (0, 2)], False),
        # zero-width hairpin: (2, 0) -> (2, 1) -> back down the same line
        ([(0, 0), (2, 0), (2, 1), (2, 0.5), (3, 0.5), (3, 2), (0, 2)], False),
        # a vertex lying on a non-adjacent edge (T-touch)
        ([(0, 0), (4, 0), (4, 2), (2, 0), (0, 2)], False),
    ],
)
def test_boundary_xy_is_simple(pts, expected):
    assert _boundary_xy_is_simple(np.asarray(pts, dtype=np.float64)) is expected
