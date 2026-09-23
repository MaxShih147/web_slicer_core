"""
Unit tests for the NumPy-vectorized point_in_polygon_2d()
(agent/ortho_pipeline.py) -- replaces the per-edge Python scalar loop with
elementwise ops over all polygon edges at once, and must be exactly
equivalent (not just semantically similar) to the pre-change scalar
ray-casting parity test on every input, including boundary/degenerate
polygons and inputs that previously relied on short-circuit evaluation to
avoid a horizontal-edge 0/0 division.

The scalar function below is a frozen copy of the pre-change implementation,
kept here only as a test oracle -- production code no longer contains a
scalar fallback.
"""
import warnings

import numpy as np
import pytest

from agent.ortho_pipeline import point_in_polygon_2d


def _point_in_polygon_2d_scalar_reference(poly: np.ndarray, px: float, py: float) -> bool:
    """Frozen pre-change scalar implementation -- test oracle only."""
    n = len(poly)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if ((yi > py) != (yj > py)) and (px < (xj - xi) * (py - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


SQUARE = np.array([[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0]])
SQUARE_CW = SQUARE[::-1].copy()  # orientation reversed

# Concave (L-shape) polygon
LSHAPE = np.array([
    [0.0, 0.0], [10.0, 0.0], [10.0, 5.0], [5.0, 5.0], [5.0, 10.0], [0.0, 10.0],
])


def _assert_matches_scalar(poly, px, py):
    ref = _point_in_polygon_2d_scalar_reference(poly, px, py)
    got = point_in_polygon_2d(poly, px, py)
    assert got == ref, f"mismatch at ({px},{py}): scalar={ref} vectorized={got}"
    return got


def test_convex_polygon_inside():
    assert _assert_matches_scalar(SQUARE, 5.0, 5.0) is True


def test_convex_polygon_outside():
    assert _assert_matches_scalar(SQUARE, 20.0, 20.0) is False


def test_concave_polygon_inside_main_body():
    assert _assert_matches_scalar(LSHAPE, 2.0, 2.0) is True


def test_concave_polygon_outside_in_notch():
    assert _assert_matches_scalar(LSHAPE, 7.0, 7.0) is False


def test_concave_polygon_reentrant_edge():
    _assert_matches_scalar(LSHAPE, 5.0, 7.0)


def test_polygon_orientation_reversed_matches_scalar():
    for px, py in [(5.0, 5.0), (20.0, 20.0), (0.0, 5.0), (10.0, 5.0)]:
        _assert_matches_scalar(SQUARE_CW, px, py)


@pytest.mark.parametrize("px,py,label", [
    (0.0, 5.0, "left edge"),
    (10.0, 5.0, "right edge"),
    (5.0, 0.0, "bottom edge (horizontal)"),
    (5.0, 10.0, "top edge (horizontal)"),
])
def test_query_on_edge(px, py, label):
    _assert_matches_scalar(SQUARE, px, py)


@pytest.mark.parametrize("px,py", [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)])
def test_query_on_vertex(px, py):
    _assert_matches_scalar(SQUARE, px, py)


def test_horizontal_edge_no_spurious_crossing():
    # Ray at y=0 passes exactly through the horizontal bottom edge (y=0..10
    # at x=0 and x=10 are vertical; the bottom edge y=0 is horizontal).
    _assert_matches_scalar(SQUARE, 5.0, 0.0)
    _assert_matches_scalar(SQUARE, -5.0, 0.0)


def test_vertical_edge():
    _assert_matches_scalar(SQUARE, 0.0, 5.0)
    _assert_matches_scalar(SQUARE, -5.0, 5.0)


def test_repeated_vertex_in_polygon():
    poly = np.array([
        [0.0, 0.0], [10.0, 0.0], [10.0, 0.0],  # repeated vertex
        [10.0, 10.0], [0.0, 10.0],
    ])
    for px, py in [(5.0, 5.0), (20.0, 20.0), (10.0, 5.0)]:
        _assert_matches_scalar(poly, px, py)


def test_zero_length_edge_does_not_crash():
    poly = np.array([
        [0.0, 0.0], [10.0, 0.0], [10.0, 0.0],  # zero-length edge (dup point)
        [10.0, 10.0], [0.0, 10.0],
    ])
    result = point_in_polygon_2d(poly, 5.0, 5.0)
    assert isinstance(result, bool)
    _assert_matches_scalar(poly, 5.0, 5.0)


def test_empty_polygon_returns_false():
    poly = np.zeros((0, 2))
    assert point_in_polygon_2d(poly, 1.0, 1.0) is False
    _assert_matches_scalar(poly, 1.0, 1.0)


def test_degenerate_single_point_polygon():
    poly = np.array([[1.0, 1.0]])
    _assert_matches_scalar(poly, 1.0, 1.0)
    _assert_matches_scalar(poly, 5.0, 5.0)


def test_degenerate_two_point_polygon():
    poly = np.array([[0.0, 0.0], [10.0, 10.0]])
    for px, py in [(5.0, 5.0), (0.0, 0.0), (20.0, 20.0)]:
        _assert_matches_scalar(poly, px, py)


def test_fixed_data_lshape_parity_table():
    """Fixed reference table (not derived at test time) pinning known
    inside/outside results for the L-shape polygon."""
    expected = {
        (2.0, 2.0): True,
        (7.0, 7.0): False,
        (5.0, 5.0): False,
        (8.0, 8.0): False,
        (1.0, 9.0): True,
    }
    for (px, py), expected_val in expected.items():
        assert point_in_polygon_2d(LSHAPE, px, py) == expected_val


def test_random_polygon_query_parity_matches_scalar_fixed_seed():
    rng = np.random.default_rng(42)
    mismatches = []
    for _ in range(2000):
        n = int(rng.integers(3, 12))
        poly = rng.uniform(-10, 10, size=(n, 2))
        px, py = rng.uniform(-15, 15, size=2)
        ref = _point_in_polygon_2d_scalar_reference(poly, px, py)
        got = point_in_polygon_2d(poly, px, py)
        if ref != got:
            mismatches.append((poly, px, py, ref, got))
    assert not mismatches, f"{len(mismatches)} mismatches out of 2000, first={mismatches[0] if mismatches else None}"


def test_no_new_numpy_runtime_warnings_on_normal_input():
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        point_in_polygon_2d(SQUARE, 5.0, 5.0)
        point_in_polygon_2d(SQUARE, 5.0, 0.0)  # horizontal edge query
        point_in_polygon_2d(LSHAPE, 5.0, 7.0)
        point_in_polygon_2d(np.zeros((0, 2)), 1.0, 1.0)
        point_in_polygon_2d(np.array([[1.0, 1.0]]), 1.0, 1.0)


def test_no_new_numpy_runtime_warnings_random_stress():
    rng = np.random.default_rng(123)
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        for _ in range(500):
            n = int(rng.integers(3, 12))
            poly = rng.uniform(-10, 10, size=(n, 2))
            px, py = rng.uniform(-15, 15, size=2)
            point_in_polygon_2d(poly, px, py)


def test_input_dtype_not_mutated():
    """Confirms the caller's array object is not mutated in place. NOTE:
    this alone cannot detect an internal `poly = poly.astype(np.float32)`
    rebind inside the function -- that creates a new local array and never
    touches the caller's object, so this dtype check would still pass even
    if the function computed entirely in float32 internally. See
    test_float64_precision_is_not_downcast_internally() below for a check
    that actually exercises internal precision."""
    poly64 = SQUARE.astype(np.float64)
    assert poly64.dtype == np.float64
    point_in_polygon_2d(poly64, 5.0, 5.0)
    assert poly64.dtype == np.float64


def test_float64_precision_is_not_downcast_internally():
    """Precision-sensitive fixture: a polygon 1e-8 wide at magnitude ~1.0,
    which is below float32's precision there (ULP ~1.19e-7), so casting it
    to float32 collapses the two long edges' x-coordinates onto each other
    and the polygon's width vanishes. If point_in_polygon_2d() ever computed
    internally in float32 (e.g. an accidental `poly.astype(np.float32)`),
    the query point -- which sits exactly at the polygon's float64 midline
    -- would fall outside a collapsed zero-width polygon instead of inside.
    A bare "input dtype unchanged" check (test_input_dtype_not_mutated)
    cannot catch this, since a local rebind never touches the caller's
    array; this test instead exercises the actual computed result.
    """
    poly = np.array([
        [1.0,        0.0],
        [1.0 + 1e-8, 0.0],
        [1.0 + 1e-8, 1.0],
        [1.0,        1.0],
    ], dtype=np.float64)
    px = 1.0 + 5e-9
    py = 0.5

    # Confirm the fixture is actually precision-sensitive under the current
    # NumPy float32 rounding behavior, rather than assuming it by reasoning
    # alone: casting to float32 must collapse the two distinct x-coordinates
    # onto the same value, and re-running the scalar oracle on the
    # float32-collapsed coordinates must disagree with the float64 oracle.
    poly32 = poly.astype(np.float32)
    assert poly32[0, 0] == poly32[1, 0], (
        "fixture no longer precision-sensitive under current NumPy float32 rounding"
    )
    ref64 = _point_in_polygon_2d_scalar_reference(poly, px, py)
    ref32_collapsed = _point_in_polygon_2d_scalar_reference(poly32.astype(np.float64), px, py)
    assert ref64 != ref32_collapsed, (
        "fixture no longer distinguishes float64 precision from a float32 downcast"
    )
    assert ref64 is True

    got = point_in_polygon_2d(poly, px, py)
    assert got == ref64
    assert got is True
