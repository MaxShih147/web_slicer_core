"""
Unit tests for the NumPy-vectorized inner-poly ray/segment nearest-hit
search (agent/ortho_pipeline.py::_ray_polygon_nearest_hit_t()) that
replaces the per-edge Python loop inside evaluate_sample_idx() (nested in
generate_side_wall_drains()). ray_seg_intersect_2d() itself is unchanged
and is used directly here (not a frozen copy) to build the test oracle,
since this round does not touch that function.

The oracle below reproduces the exact scalar combination that the loop
used: call the real ray_seg_intersect_2d() once per edge (with b wrapping
from the last polygon point back to the first), keep only t > 0.01, and
track the running minimum with a strict `<` update -- exactly the
pre-change evaluate_sample_idx() ray-search logic.
"""
import warnings

import numpy as np
import pytest

from agent.ortho_pipeline import ray_seg_intersect_2d, _ray_polygon_nearest_hit_t


def _edge_arrays(poly: np.ndarray):
    """Build the (ax, ay, ex, ey) precomputed edge arrays exactly as
    generate_side_wall_drains() does: b wraps last polygon point -> first."""
    ax = poly[:, 0]
    ay = poly[:, 1]
    bx = np.roll(ax, -1)
    by = np.roll(ay, -1)
    ex = bx - ax
    ey = by - ay
    return ax, ay, ex, ey


def _scalar_nearest_hit_t_and_index(poly: np.ndarray, ox, oy, dx, dy):
    """Test oracle: per-edge ray_seg_intersect_2d() calls + the exact
    caller-side selection logic from the pre-change evaluate_sample_idx().
    Also tracks the winning edge index -- production doesn't need to, since
    only the winning t value (not the index) is ever consumed downstream,
    but the index lets tests pin the "lowest index wins ties" semantics."""
    n = len(poly)
    best_t = float('inf')
    best_i = None
    for i in range(n):
        j = (i + 1) % n
        t = ray_seg_intersect_2d(
            ox, oy, dx, dy,
            poly[i][0], poly[i][1],
            poly[j][0], poly[j][1],
        )
        if t is not None and t > 0.01 and t < best_t:
            best_t = t
            best_i = i
    if best_t == float('inf'):
        return None, None
    return best_t, best_i


def _vectorized_t_and_index(poly: np.ndarray, ox, oy, dx, dy):
    """Test-only extension of the production math that also returns the
    winning edge index (via np.argmin's first-occurrence tie-break), purely
    to validate tie-break semantics. Not part of the production API."""
    ax, ay, ex, ey = _edge_arrays(poly)
    denom = dx * ey - dy * ex
    valid = np.abs(denom) >= 1e-12
    safe_denom = np.where(valid, denom, 1.0)
    dax = ax - ox
    day = ay - oy
    t = (dax * ey - day * ex) / safe_denom
    u = (dax * dy - day * dx) / safe_denom
    hit = valid & (u >= 0) & (u <= 1) & (t > 0.01)
    if not np.any(hit):
        return None, None
    t_masked = np.where(hit, t, np.inf)
    idx = int(np.argmin(t_masked))
    return float(t_masked[idx]), idx


def _assert_matches_scalar(poly, ox, oy, dx, dy):
    ref_t, ref_i = _scalar_nearest_hit_t_and_index(poly, ox, oy, dx, dy)
    ax, ay, ex, ey = _edge_arrays(poly)
    got_t = _ray_polygon_nearest_hit_t(ox, oy, dx, dy, ax, ay, ex, ey)
    assert got_t == ref_t, (
        f"mismatch for origin=({ox},{oy}) dir=({dx},{dy}): "
        f"scalar={ref_t} vectorized={got_t}"
    )
    return got_t, ref_i


SQUARE = np.array([[-5.0, -5.0], [5.0, -5.0], [5.0, 5.0], [-5.0, 5.0]])


def test_general_single_hit():
    got, _ = _assert_matches_scalar(SQUARE, -10.0, 0.0, 1.0, 0.0)
    assert got == 5.0


def test_multiple_hits_selects_nearest():
    # Non-convex polygon: ray from inside crosses two edges going the same
    # direction at different distances; nearest one must win.
    poly = np.array([
        [-5.0, -5.0], [5.0, -5.0], [5.0, 5.0], [3.0, 5.0],
        [3.0, -3.0], [-5.0, -3.0], [-5.0, 5.0],
    ])
    got, ref_i = _assert_matches_scalar(poly, -4.0, 0.0, 1.0, 0.0)
    assert got is not None


def test_no_hit_ray_points_away():
    got, _ = _assert_matches_scalar(SQUARE, -10.0, 0.0, -1.0, 0.0)
    assert got is None


def test_empty_inner_polygon_no_crash():
    empty = np.zeros((0, 2))
    ax, ay, ex, ey = _edge_arrays(empty)
    result = _ray_polygon_nearest_hit_t(0.0, 0.0, 1.0, 0.0, ax, ay, ex, ey)
    assert result is None


def test_single_point_inner_polygon_no_crash():
    poly = np.array([[1.0, 1.0]])
    ax, ay, ex, ey = _edge_arrays(poly)
    result = _ray_polygon_nearest_hit_t(0.0, 0.0, 1.0, 0.0, ax, ay, ex, ey)
    assert result is None


def test_parallel_edge_rejected():
    # Ray at y=-5 travels along +x, exactly parallel to the bottom edge.
    got, _ = _assert_matches_scalar(SQUARE, -10.0, -5.0, 1.0, 0.0)
    assert got == 5.0  # hits the vertical left/right edges, not the parallel one


def test_collinear_edge_rejected():
    # Segment lying exactly on the ray's line (not just parallel, but
    # collinear/overlapping) -- same denom=0 rejection as parallel.
    poly = np.array([[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]])
    # Ray travels along y=0, collinear with the bottom edge (0,0)->(1,0).
    got, _ = _assert_matches_scalar(poly, -5.0, 0.0, 1.0, 0.0)
    assert got == 5.0  # hits the vertical edge at x=0, not the collinear one


def test_zero_length_edge_rejected_and_no_crash():
    poly = np.array([
        [-5.0, -5.0], [5.0, -5.0], [5.0, -5.0],  # zero-length edge (dup point)
        [5.0, 5.0], [-5.0, 5.0],
    ])
    got, _ = _assert_matches_scalar(poly, -10.0, 0.0, 1.0, 0.0)
    assert got == 5.0


def test_segment_endpoint_u_equals_0():
    poly = np.array([[1.0, -1.0], [1.0, 1.0], [-1.0, 1.0], [-1.0, -1.0]])
    got, _ = _assert_matches_scalar(poly, 0.0, 0.0, 1.0, -1.0)
    assert got is not None


def test_segment_endpoint_u_equals_1():
    poly = np.array([[1.0, -1.0], [1.0, 1.0], [-1.0, 1.0], [-1.0, -1.0]])
    got, _ = _assert_matches_scalar(poly, 0.0, 0.0, 1.0, 1.0)
    assert got is not None


def _single_edge_result(ax_, ay_, bx_, by_, ox, oy, dx, dy):
    """Isolate a single edge -- rather than embedding it in a closed
    polygon whose *other* edges might also be legitimately hit and mask the
    boundary condition under test -- by calling ray_seg_intersect_2d() and
    _ray_polygon_nearest_hit_t() directly with one-edge arrays."""
    scalar_raw = ray_seg_intersect_2d(ox, oy, dx, dy, ax_, ay_, bx_, by_)
    scalar = scalar_raw if (scalar_raw is not None and scalar_raw > 0.01) else None
    ax = np.array([ax_])
    ay = np.array([ay_])
    ex = np.array([bx_ - ax_])
    ey = np.array([by_ - ay_])
    vec = _ray_polygon_nearest_hit_t(ox, oy, dx, dy, ax, ay, ex, ey)
    assert vec == scalar, f"single-edge mismatch: scalar={scalar} vectorized={vec}"
    return vec


def test_u_outside_0_1_range_rejected():
    # Ray direction chosen so it crosses this edge's infinite line outside
    # the edge's own [0,1] span.
    got = _single_edge_result(1.0, -1.0, 1.0, 1.0, 0.0, 0.0, 1.0, 3.0)
    assert got is None


def test_t_equals_0_rejected():
    got = _single_edge_result(0.0, -1.0, 0.0, 1.0, 0.0, 0.0, 1.0, 0.0)
    assert got is None


def test_t_equals_0_01_rejected_strict_boundary():
    t_target = 0.01
    got = _single_edge_result(t_target, -1.0, t_target, 1.0, 0.0, 0.0, 1.0, 0.0)
    assert got is None


def test_t_just_above_0_01_accepted():
    t_target = 0.01 + 1e-9
    got = _single_edge_result(t_target, -1.0, t_target, 1.0, 0.0, 0.0, 1.0, 0.0)
    assert got == pytest.approx(t_target)


@pytest.mark.parametrize("label,eps", [
    ("below_1e-12", 1e-12 - 1e-15),
    ("exactly_1e-12", 1e-12),
    ("above_1e-12", 1e-12 + 1e-15),
])
def test_denom_threshold_boundary(label, eps):
    # Segment a=(0,0), b=(eps,0); ray straight up through the origin hits
    # this segment at t=1.0, u=0 -- independent of eps -- so the only thing
    # that varies across these three cases is abs(denom) relative to 1e-12.
    got = _single_edge_result(0.0, 0.0, eps, 0.0, 0.0, -1.0, 0.0, 1.0)
    if label == "below_1e-12":
        assert got is None
    else:
        assert got == pytest.approx(1.0)


def test_exact_tie_between_two_edges_lowest_index_wins():
    # Same construction as the earlier PIP/ray investigation: two collinear
    # edges sharing a vertex exactly on the ray, giving an exact tie in t.
    tie_poly = np.array([
        [5.0, -5.0], [5.0, 0.0],   # edge 0: x=5, y in [-5,0]
        [5.0, 5.0],                 # edge 1: x=5, y in [0,5]
        [-5.0, 0.0],                # closes the loop
    ])
    ref_t, ref_i = _scalar_nearest_hit_t_and_index(tie_poly, 0.0, 0.0, 1.0, 0.0)
    got_t, got_i = _vectorized_t_and_index(tie_poly, 0.0, 0.0, 1.0, 0.0)
    assert ref_t == got_t == 5.0
    assert ref_i == got_i == 0  # lowest edge index wins the tie
    # Production helper (only returns t, matching the value both tie
    # candidates share) must agree on the value.
    ax, ay, ex, ey = _edge_arrays(tie_poly)
    prod_t = _ray_polygon_nearest_hit_t(0.0, 0.0, 1.0, 0.0, ax, ay, ex, ey)
    assert prod_t == ref_t


def test_last_point_wraps_to_first():
    # Triangle where only the closing edge (last point -> first point) is
    # hit by the ray; if the wrap were built wrong, this edge simply
    # wouldn't exist in the edge arrays and the hit would be missed.
    poly = np.array([[10.0, 10.0], [10.0, 11.0], [-5.0, 0.0]])
    # Closing edge: (-5,0) -> (10,10). Ray along +x at y=0 should clip it
    # only if geometry crosses y=0 within that edge's span; verify parity
    # with the scalar oracle rather than asserting a specific hit.
    got, _ = _assert_matches_scalar(poly, -10.0, 0.0, 1.0, 0.0)
    # Explicitly confirm the wrap edge participates: build edge arrays and
    # check the last edge is (poly[-1] -> poly[0]).
    ax, ay, ex, ey = _edge_arrays(poly)
    assert ax[-1] == poly[-1][0] and ay[-1] == poly[-1][1]
    assert ax[-1] + ex[-1] == poly[0][0]
    assert ay[-1] + ey[-1] == poly[0][1]


def test_random_polygon_ray_parity_matches_scalar_fixed_seed():
    rng = np.random.default_rng(99)
    mismatches = []
    for _ in range(2000):
        n = int(rng.integers(3, 12))
        poly = rng.uniform(-10, 10, size=(n, 2))
        ox, oy = rng.uniform(-15, 15, size=2)
        dx, dy = rng.uniform(-1, 1, size=2)
        if abs(dx) < 1e-9 and abs(dy) < 1e-9:
            continue
        ref_t, _ = _scalar_nearest_hit_t_and_index(poly, ox, oy, dx, dy)
        ax, ay, ex, ey = _edge_arrays(poly)
        got_t = _ray_polygon_nearest_hit_t(ox, oy, dx, dy, ax, ay, ex, ey)
        if ref_t != got_t:
            mismatches.append((poly, ox, oy, dx, dy, ref_t, got_t))
    assert not mismatches, f"{len(mismatches)} mismatches, first={mismatches[0] if mismatches else None}"


def test_no_new_numpy_runtime_warnings_on_normal_input():
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        ax, ay, ex, ey = _edge_arrays(SQUARE)
        _ray_polygon_nearest_hit_t(-10.0, 0.0, 1.0, 0.0, ax, ay, ex, ey)
        _ray_polygon_nearest_hit_t(-10.0, -5.0, 1.0, 0.0, ax, ay, ex, ey)  # parallel edge
        empty = np.zeros((0, 2))
        eax, eay, eex, eey = _edge_arrays(empty)
        _ray_polygon_nearest_hit_t(0.0, 0.0, 1.0, 0.0, eax, eay, eex, eey)
        zero_len = np.array([[1.0, 1.0], [1.0, 1.0], [2.0, 2.0]])
        zax, zay, zex, zey = _edge_arrays(zero_len)
        _ray_polygon_nearest_hit_t(0.0, 0.0, 1.0, 0.0, zax, zay, zex, zey)


def test_no_new_numpy_runtime_warnings_random_stress():
    rng = np.random.default_rng(321)
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        for _ in range(500):
            n = int(rng.integers(3, 12))
            poly = rng.uniform(-10, 10, size=(n, 2))
            ox, oy = rng.uniform(-15, 15, size=2)
            dx, dy = rng.uniform(-1, 1, size=2)
            ax, ay, ex, ey = _edge_arrays(poly)
            _ray_polygon_nearest_hit_t(ox, oy, dx, dy, ax, ay, ex, ey)


def test_float64_precision_is_not_downcast_internally():
    """Precision-sensitive fixture: an edge 1e-8 wide at magnitude ~1.0,
    below float32's precision there (ULP ~1.19e-7). Downcasting the edge
    arrays to float32 does NOT make the ray miss this edge entirely -- it
    still registers a hit, just at a measurably different t (float64 gives
    t ~= 0.9999999949999991; the same call with the edge arrays downcast to
    float32 gives exactly t = 1.0). So this test checks the *exact* t value
    against the float64 scalar oracle (not merely hit-vs-no-hit), and
    separately proves the fixture is actually sensitive to this precision
    loss via an explicit downcast-control call rather than asserting it by
    reasoning alone.
    """
    ax_, ay_, bx_, by_ = 1.0, -1.0, 1.0 + 1e-8, -1.0
    poly = np.array([[ax_, ay_], [bx_, by_], [10.0, 10.0], [10.0, -10.0]])
    ox, oy, dx, dy = 1.0 + 5e-9, -2.0, 0.0, 1.0

    poly32 = poly.astype(np.float32)
    assert poly32[0, 0] == poly32[1, 0], (
        "fixture no longer precision-sensitive under current NumPy float32 rounding"
    )

    ref_t, _ = _scalar_nearest_hit_t_and_index(poly, ox, oy, dx, dy)
    ax, ay, ex, ey = _edge_arrays(poly)

    # Downcast-control: call the real helper with the edge arrays downcast
    # to float32 (simulating a hypothetical internal-downcast bug), to
    # concretely demonstrate -- not just assert by reasoning -- that this
    # fixture's result changes under that precision loss.
    downcast_result = _ray_polygon_nearest_hit_t(
        ox, oy, dx, dy,
        ax.astype(np.float32), ay.astype(np.float32),
        ex.astype(np.float32), ey.astype(np.float32),
    )
    assert downcast_result != ref_t, (
        "fixture no longer distinguishes float64 precision from a float32 "
        "edge-array downcast (both produced the same t)"
    )
    assert downcast_result is not None  # downcast still hits -- just at a different t

    got_t = _ray_polygon_nearest_hit_t(ox, oy, dx, dy, ax, ay, ex, ey)
    assert got_t == ref_t
    assert got_t is not None


def test_input_arrays_dtype_not_mutated():
    ax, ay, ex, ey = _edge_arrays(SQUARE.astype(np.float64))
    assert ax.dtype == np.float64 and ay.dtype == np.float64
    assert ex.dtype == np.float64 and ey.dtype == np.float64
    _ray_polygon_nearest_hit_t(-10.0, 0.0, 1.0, 0.0, ax, ay, ex, ey)
    assert ax.dtype == np.float64 and ay.dtype == np.float64
    assert ex.dtype == np.float64 and ey.dtype == np.float64
