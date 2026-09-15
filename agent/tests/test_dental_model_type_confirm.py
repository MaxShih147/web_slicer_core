"""Regression tests for ``confirm_dental_model_type()`` / ``classify_dental_model()``.

Written for the D4 performance change (optimize-auto-process-performance):
``confirm_dental_model_type(mesh, INTRAORAL_SCAN)`` skips the ProjectionShape
feature-extraction group, since source tracing confirmed no branch reachable
for that target reads any ProjectionShape-derived field (see design.md D4 and
``openspec/specs/dental-model-type-confirm/spec.md``).

Two independent guarantees are pinned here:

1. **8-target consistency invariant** (``dental-model-type-confirm`` spec,
   "與完整分類的一致性（無例外）"): for any mesh,
   ``confirm(mesh, t) == (classify(mesh) == t)`` for all 8 ``DentalModelType``
   values, with no exceptions.  Exercised via ``extract_model_features()`` /
   ``detect_drill_holes()`` monkeypatches so the full branch matrix (P0 / P_base
   / P2 / P3 / needs_drill early-return / P5.1 / P5.2 / P5.3) can be driven
   deterministically without needing real STL geometry for every path.  This
   test is written to be indifferent to *how* ``extract_model_features()``
   populates its ProjectionShape fields, so it holds unchanged both before and
   after the ProjectionShape skip is implemented.

2. **ProjectionShape caller boundary**: ``classify_dental_model()`` and
   ``confirm_dental_model_type()`` for every target other than
   ``INTRAORAL_SCAN`` SHALL still invoke ``projection_shape_gap_stats()``;
   only ``confirm_dental_model_type(mesh, INTRAORAL_SCAN)`` SHALL NOT.
   Checked with a call-counting spy on the real function (not by inferring
   from ``ModelFeatures`` fields being ``None``, which can also happen on
   algorithm failure).
"""
import copy

import pytest
import trimesh

import agent.model_classifier as mc


def _features(
    l1=None, l2=None, l3=None,
    loop_mm=0.0, open_ratio=0.0, open_count=0,
    fp_found=False, fp_ratio=None, fp_one_side=None,
    proj_gap=None, proj_contact=None, proj_med=0, proj_large=0,
):
    """Build a raw (pre-drill) ModelFeatures snapshot.

    Mirrors what extract_model_features() would populate for PCA / OpenBoundary
    / FlatPlane / ProjectionShape — deliberately does NOT set any drill_* field
    or drill_detection_skip_reason, since those are derived by the real
    classify_dental_model()/confirm_dental_model_type() orchestration via
    _get_drill_detection_plan(), not supplied as input.
    """
    f = mc.ModelFeatures()
    f.axis_l1_mm, f.axis_l2_mm, f.axis_l3_mm = l1, l2, l3
    f.open_edge_count = open_count
    f.largest_loop_length_mm = loop_mm
    f.largest_open_ratio = open_ratio
    if l1 is None:
        f.flat_plane_candidate_found = None
    else:
        f.flat_plane_candidate_found = True if fp_found else False
        if fp_found:
            f.flat_plane_area_ratio = fp_ratio
            f.flat_plane_one_side = fp_one_side
    if proj_gap is not None:
        f.projection_largest_gap_ratio = proj_gap
        f.projection_largest_gap_contact_mm = proj_contact
        f.projection_medium_holes = proj_med
        f.projection_large_holes = proj_large
    return f


# Each scenario's (needs_drill, skip_reason, expected model_type) was derived
# by actually running these raw features through the real _compute_signals()/
# _get_drill_detection_plan()/_decide_model_type_with_details() — not hand
# simulated — see conversation record for the derivation script. All 8
# DentalModelType values appear as `expected` at least once.
SCENARIOS = [
    pytest.param(
        _features(l1=None),
        None,
        mc.DentalModelType.OTHER,
        id="P0_pca_missing",
    ),
    pytest.param(
        _features(l1=10, l2=8, l3=7, proj_gap=0.1, proj_contact=2.0),
        None,
        mc.DentalModelType.CROWN,
        id="P2_clear_crown",
    ),
    pytest.param(
        _features(l1=60, l2=40, l3=20, fp_found=True, fp_ratio=0.18, fp_one_side=True,
                   proj_gap=0.05, proj_contact=1.0),
        None,
        mc.DentalModelType.DENTAL_MODEL,
        id="Pbase_one_sided_flat_plane_U_low",
    ),
    pytest.param(
        _features(l1=60, l2=40, l3=20, fp_found=True, fp_ratio=0.18, fp_one_side=True,
                   proj_gap=0.45, proj_contact=30.0),
        None,
        mc.DentalModelType.U_SHAPED_DENTAL_MODEL,
        id="Pbase_one_sided_flat_plane_U_high",
    ),
    pytest.param(
        _features(l1=60, l2=40, l3=20, loop_mm=90, open_ratio=1.5, open_count=100,
                   fp_found=True, fp_ratio=0.02, fp_one_side=False,
                   proj_gap=0.1, proj_contact=2.0),
        None,
        mc.DentalModelType.INTRAORAL_SCAN,
        id="P3_large_open_boundary",
    ),
    pytest.param(
        _features(l1=60, l2=40, l3=10, fp_found=False, proj_gap=0.45, proj_contact=30.0),
        {"valid": True, "found": False, "candidate_count": 0},
        mc.DentalModelType.SPLINT,
        id="P5_splint",
    ),
    pytest.param(
        _features(l1=22, l2=8, l3=7, proj_gap=0.1, proj_contact=2.0),
        {"valid": True, "found": False, "candidate_count": 0},
        mc.DentalModelType.BRIDGE,
        id="P5_bridge_elongated",
    ),
    pytest.param(
        _features(l1=13, l2=10, l3=9, proj_gap=0.1, proj_contact=2.0),
        {"valid": True, "found": False, "candidate_count": 0},
        mc.DentalModelType.CROWN,
        id="P5_boundary_ratio_crown",
    ),
    pytest.param(
        _features(l1=16, l2=10, l3=9, fp_found=False, proj_gap=0.1, proj_contact=2.0),
        {"valid": True, "found": False, "candidate_count": 0},
        mc.DentalModelType.BRIDGE,
        id="P5_boundary_ratio_bridge",
    ),
    pytest.param(
        _features(l1=60, l2=40, l3=20, fp_found=False,
                   proj_gap=0.45, proj_contact=30.0, proj_med=2, proj_large=1),
        {"valid": True, "found": True, "candidate_count": 3},
        mc.DentalModelType.SURGICAL_GUIDE,
        id="P5_surgical_guide_drill_found",
    ),
    pytest.param(
        _features(l1=60, l2=40, l3=20, fp_found=True, fp_ratio=0.18, fp_one_side=False,
                   proj_gap=0.1, proj_contact=2.0),
        {"valid": True, "found": False, "candidate_count": 0},
        mc.DentalModelType.SURGICAL_GUIDE,
        id="P5_surgical_guide_non_one_sided_plane",
    ),
    pytest.param(
        _features(l1=60, l2=40, l3=20, fp_found=False, proj_gap=0.45, proj_contact=30.0),
        {"valid": False, "found": None, "candidate_count": None},
        mc.DentalModelType.SURGICAL_GUIDE,
        id="P5_drill_failed_surgical_guide_fallback",
    ),
    pytest.param(
        _features(l1=25, l2=15, l3=8, fp_found=False, proj_gap=0.1, proj_contact=2.0),
        {"valid": False, "found": None, "candidate_count": None},
        mc.DentalModelType.BRIDGE,
        id="P5_drill_failed_bridge_fallback",
    ),
]


@pytest.fixture
def _patched(monkeypatch):
    """Patch extract_model_features()/detect_drill_holes() to serve a scenario's
    canned (features, drill_result) pair.  A fresh deepcopy of the features
    template is returned on every extract_model_features() call so that
    classify_dental_model()'s and confirm_dental_model_type()'s in-place
    mutation of drill_* fields on their own copy never leaks across calls.

    detect_drill_holes() raises if called with no drill_result configured for
    the active scenario — catches an early-return branch incorrectly falling
    through to drill detection.
    """
    state = {"template": None, "drill_result": None}

    def fake_extract(mesh, skip_projection_shape=False):
        assert state["template"] is not None, "scenario not configured"
        return copy.deepcopy(state["template"])

    def fake_detect(mesh):
        if state["drill_result"] is None:
            raise AssertionError(
                "detect_drill_holes() called for a scenario with no drill_result "
                "configured -- an early-return branch fell through unexpectedly"
            )
        return state["drill_result"]

    monkeypatch.setattr(mc, "extract_model_features", fake_extract)
    monkeypatch.setattr(mc, "detect_drill_holes", fake_detect)

    def _configure(template, drill_result):
        state["template"] = template
        state["drill_result"] = drill_result

    return _configure


@pytest.mark.parametrize("template, drill_result, expected_type", SCENARIOS)
def test_confirm_matches_classify_for_all_targets(template, drill_result, expected_type, _patched):
    """confirm(mesh, t) == (classify(mesh) == t) for all 8 targets, no exceptions."""
    _patched(template, drill_result)
    dummy_mesh = object()  # extract_model_features is mocked; mesh is never touched

    actual_type = mc.classify_dental_model(dummy_mesh)
    assert actual_type == expected_type, (
        f"classify_dental_model() expected {expected_type.value}, got {actual_type.value}"
    )

    for target in mc.DentalModelType:
        _patched(template, drill_result)  # fresh features snapshot per confirm() call
        confirmed = mc.confirm_dental_model_type(dummy_mesh, target)
        assert confirmed == (target == expected_type), (
            f"confirm(target={target.value}) = {confirmed}, "
            f"expected {target == expected_type} (classify()={expected_type.value})"
        )


# ---------------------------------------------------------------------------
# ProjectionShape caller boundary — verified with a call-counting spy on the
# real projection_shape_gap_stats(), not by inferring from feature values.
# ---------------------------------------------------------------------------

@pytest.fixture
def _projection_spy(monkeypatch):
    calls = []
    original = mc.projection_shape_gap_stats

    def spy(mesh, pca_axes):
        calls.append((mesh, pca_axes))
        return original(mesh, pca_axes)

    monkeypatch.setattr(mc, "projection_shape_gap_stats", spy)
    return calls


@pytest.fixture
def _simple_mesh():
    # A plain box is enough: PCA succeeds, so extract_model_features() reaches
    # the ProjectionShape block regardless of what the box ultimately classifies as.
    return trimesh.creation.box(extents=[60.0, 40.0, 20.0])


def test_classify_dental_model_calls_projection_shape(_simple_mesh, _projection_spy):
    mc.classify_dental_model(_simple_mesh)
    assert len(_projection_spy) == 1


@pytest.mark.parametrize("target", [t for t in mc.DentalModelType if t != mc.DentalModelType.INTRAORAL_SCAN])
def test_confirm_non_intraoral_scan_calls_projection_shape(target, _simple_mesh, _projection_spy):
    mc.confirm_dental_model_type(_simple_mesh, target)
    assert len(_projection_spy) == 1, (
        f"confirm_dental_model_type(mesh, {target.value}) should still call "
        f"projection_shape_gap_stats() exactly once"
    )


def test_confirm_intraoral_scan_skips_projection_shape(_simple_mesh, _projection_spy):
    """The actual D4 change: once implemented, this SHALL NOT call
    projection_shape_gap_stats() at all. Fails (call count 1) until D4's
    skip_projection_shape wiring lands in confirm_dental_model_type()."""
    mc.confirm_dental_model_type(_simple_mesh, mc.DentalModelType.INTRAORAL_SCAN)
    assert len(_projection_spy) == 0, (
        "confirm_dental_model_type(mesh, INTRAORAL_SCAN) called "
        "projection_shape_gap_stats() -- D4 skip not in effect"
    )
