"""
Tests for the cross-flow fixes and new rules added to the shared
`agent.engine_rules.ENGINE_RULES` table by merge-engine-result-classifiers.

Unlike test_support_classifier.py / test_slicing_classifier.py (locked at
their original content — they prove the thin-shell migration was lossless),
this file covers the NEW behavior this change adds: the two previously-missed
cross-flow codes (support gains PAD_CONFIG_INVALID, slice gains
SUPPORT_POINTS_REQUIRED), the explicit fallback_by_design marking of
"Disabling the 'Use tilt' function", and the two brand-new codes
(SUPPORT_POINT_SAMPLING_FAILED, SHRINKAGE_COMPENSATION_INVALID).

Exercised through the public classify_support_result() / classify_slice_result()
functions (the real seam), not by poking at ENGINE_RULES internals directly.
"""

from agent.slicing_classifier import classify_slice_result
from agent.support_classifier import classify_support_result

_MODEL = "model.stl"


class TestSupportGainsPadConfigInvalid:
    """2.1/2.2: the support flow previously had no code for a too-small pad
    brim (it degraded to SUPPORT_GENERATION_FAILED) — the same message the
    slice flow already recognizes as PAD_CONFIG_INVALID."""

    def test_pad_brim_too_small_on_support_path(self):
        result = classify_support_result(
            stdout="",
            stderr="Pad brim size is too small for the current configuration.",
            support_stl_exists=False,
        )
        assert result.error_code == "PAD_CONFIG_INVALID"

    def test_matches_the_slice_flow_for_the_same_message(self):
        """Same stderr, same code, on both flows — proves the fix closes the
        gap rather than opening a new divergence."""
        stderr = "Pad brim size is too small for the current configuration."
        support_result = classify_support_result(stdout="", stderr=stderr, support_stl_exists=False)
        slice_result = classify_slice_result(1, "", stderr, _MODEL, False)
        assert support_result.error_code == slice_result.error_code == "PAD_CONFIG_INVALID"


class TestSliceGainsSupportPointsRequired:
    """2.3: the slice flow previously had no code for missing support points
    (it degraded to bare JOB_FAILED) — the same message the support flow
    already recognizes as SUPPORT_POINTS_REQUIRED."""

    def test_missing_support_points_on_slice_path(self):
        result = classify_slice_result(
            1, "", "Cannot proceed without support points! Add support points.", _MODEL, False
        )
        assert result.error_code == "SUPPORT_POINTS_REQUIRED"

    def test_matches_the_support_flow_for_the_same_message(self):
        stderr = "Cannot proceed without support points! Add support points."
        slice_result = classify_slice_result(1, "", stderr, _MODEL, False)
        support_result = classify_support_result(stdout="", stderr=stderr, support_stl_exists=False)
        assert slice_result.error_code == support_result.error_code == "SUPPORT_POINTS_REQUIRED"


class TestUseTiltIsFallbackByDesign:
    """2.4: 'Disabling the Use tilt function' is a known message with
    deliberately no dedicated code — it must be explicitly flagged
    fallback_by_design in ENGINE_RULES, not merely absent from the table."""

    def test_still_routes_to_the_support_fallback_code(self):
        from agent.support_classifier import FALLBACK_CODE

        result = classify_support_result(
            stdout="",
            stderr="Disabling the 'Use tilt' function causes the object to separate.",
            support_stl_exists=False,
        )
        assert result.error_code == FALLBACK_CODE

    def test_is_marked_fallback_by_design_in_engine_rules(self):
        from agent.engine_rules import find_code

        rule = find_code("support", "Disabling the 'Use tilt' function causes the object to separate.")
        assert rule is not None
        assert rule.fallback_by_design is True


class TestSupportPointSamplingFailed:
    """3.2: the engine's own support-point sampler failure gets a dedicated
    code on both flows, instead of degrading to the generic fallback."""

    MESSAGE = (
        "SLA support point generator has failed."
        "\n\nThe generator was unable to sample an island. You may try to work around "
        "the problem by changing the orientation of the model slightly."
    )

    def test_support_path(self):
        result = classify_support_result(stdout="", stderr=self.MESSAGE, support_stl_exists=False)
        assert result.error_code == "SUPPORT_POINT_SAMPLING_FAILED"
        assert "changing the orientation" in result.detail

    def test_slice_path(self):
        result = classify_slice_result(1, "", self.MESSAGE, _MODEL, False)
        assert result.error_code == "SUPPORT_POINT_SAMPLING_FAILED"
        assert "changing the orientation" in result.error


class TestShrinkageCompensationInvalid:
    """3.3: a non-invertible object transform (zero scale / zero shrinkage
    compensation) gets a dedicated code on both flows."""

    MESSAGE = (
        "error: --export-support-points: the object transform is not invertible "
        "(a zero scale or a zero shrinkage compensation), so support point "
        "coordinates cannot be mapped back to the input model"
    )

    def test_support_path(self):
        result = classify_support_result(stdout="", stderr=self.MESSAGE, support_stl_exists=False)
        assert result.error_code == "SHRINKAGE_COMPENSATION_INVALID"

    def test_slice_path(self):
        result = classify_slice_result(1, "", self.MESSAGE, _MODEL, False)
        assert result.error_code == "SHRINKAGE_COMPENSATION_INVALID"
