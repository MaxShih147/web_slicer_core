"""
Tests for the five-step support-result classifier — Task 3
(add-support-generation-error-codes).

Covers every step and every validate→code map entry, plus the spec edge cases:
  - validate failure with exit 0 is still FAILED (classifier never sees a
    returncode — proven structurally: the function has no such parameter)
  - "(pad only)" must NOT report has_support_mesh=True
  - write failure with no STL and no positive marker → fail-closed
  - mutually-exclusive markers → fail-closed
  - model out of bounds → MODEL_OUT_OF_BOUNDS
"""

import inspect

import pytest

from agent.models import JobStatus
from agent.support_classifier import (
    FALLBACK_CODE,
    HAS_SUPPORT_MARKERS,
    MODEL_MISMATCH_CODE,
    MODEL_MISMATCH_MARKER,
    NOT_NEEDED_MARKERS,
    SUPPORT_NOT_NEEDED,
    VALIDATE_CODE_MAP,
    classify_support_result,
)


class TestSignature:
    def test_does_not_accept_returncode(self):
        """3.1: classifier must not take returncode as an input at all (design D1)."""
        params = set(inspect.signature(classify_support_result).parameters)
        assert params == {"stdout", "stderr", "support_stl_exists"}
        assert "returncode" not in params


class TestStep0ModelMismatch:
    """8.4: the imported point list does not describe this model.

    The engine aborts before print->apply(), so a real run of this path emits
    the marker on stderr, writes no STL, and prints none of the positive stdout
    markers. Every case below reproduces that shape.
    """

    # What the CLI actually prints on this path: the marker alone on stderr,
    # stdout carrying only the ordinary startup chatter.
    REAL_STDOUT = "Loading model file\n"
    REAL_STDERR = MODEL_MISMATCH_MARKER + "\n"

    def test_attributed_to_the_dedicated_code(self):
        """Spec: FAILED + SUPPORT_POINTS_MODEL_MISMATCH."""
        result = classify_support_result(
            stdout=self.REAL_STDOUT,
            stderr=self.REAL_STDERR,
            support_stl_exists=False,
        )
        assert result.status == JobStatus.FAILED
        assert result.error_code == MODEL_MISMATCH_CODE

    def test_not_flattened_into_the_fallback_code(self):
        """Spec: MUST NOT be SUPPORT_GENERATION_FAILED.

        This is the whole point of the rule — the caller has to be able to tell
        'the model changed' apart from 'support generation failed', because the
        two need different fixes.
        """
        result = classify_support_result(
            stdout=self.REAL_STDOUT,
            stderr=self.REAL_STDERR,
            support_stl_exists=False,
        )
        assert result.error_code != FALLBACK_CODE

    def test_not_mistaken_for_the_neutral_outcome(self):
        """Spec: MUST NOT be SUPPORT_NOT_NEEDED, and hasSupportMesh is false.

        The abort produces no STL and no positive marker — exactly the shape
        that a genuinely self-supporting model produces minus the neutral
        marker. Getting this wrong would report a hard failure as a success.
        """
        result = classify_support_result(
            stdout=self.REAL_STDOUT,
            stderr=self.REAL_STDERR,
            support_stl_exists=False,
        )
        assert result.status != JobStatus.COMPLETED
        assert result.support_outcome != SUPPORT_NOT_NEEDED
        assert result.support_outcome is None
        assert result.has_support_mesh is False

    def test_attribution_does_not_depend_on_exit_code(self):
        """Spec: returncode 0 must still be attributed correctly.

        Structural, not behavioural: the classifier has no returncode parameter
        at all, so a 0 exit cannot reach the decision. TestSignature pins that;
        this asserts the consequence for this specific path.
        """
        params = set(inspect.signature(classify_support_result).parameters)
        assert "returncode" not in params
        # Same call the exit-0 run would produce — still the dedicated code.
        assert (
            classify_support_result(
                stdout=self.REAL_STDOUT,
                stderr=self.REAL_STDERR,
                support_stl_exists=False,
            ).error_code
            == MODEL_MISMATCH_CODE
        )

    def test_wins_over_a_validate_error_on_the_same_stream(self):
        """Ordering: Step 0 runs ahead of Step 1.

        Cannot happen today (the abort precedes validate()), but pins the
        documented precedence so a future reordering is caught.
        """
        result = classify_support_result(
            stdout="",
            stderr=self.REAL_STDERR + "Cannot proceed without support points",
            support_stl_exists=False,
        )
        assert result.error_code == MODEL_MISMATCH_CODE

    def test_wins_over_a_stray_positive_marker(self):
        """Ordering: a leftover success marker must not mask the mismatch."""
        result = classify_support_result(
            stdout="(supports only)",
            stderr=self.REAL_STDERR,
            support_stl_exists=True,
        )
        assert result.status == JobStatus.FAILED
        assert result.error_code == MODEL_MISMATCH_CODE
        assert result.has_support_mesh is False

    def test_marker_on_stdout_is_also_caught(self):
        """Both streams are scanned, so a stream reshuffle cannot downgrade it."""
        result = classify_support_result(
            stdout=self.REAL_STDERR,
            stderr="",
            support_stl_exists=False,
        )
        assert result.error_code == MODEL_MISMATCH_CODE

    def test_accepts_raw_bytes(self):
        """run_prusa_cli hands back bytes, not str."""
        result = classify_support_result(
            stdout=b"",
            stderr=MODEL_MISMATCH_MARKER.encode("utf-8"),
            support_stl_exists=False,
        )
        assert result.error_code == MODEL_MISMATCH_CODE

    def test_detail_carries_both_raw_streams(self):
        """Failures keep the raw output for debugging, like every other path."""
        result = classify_support_result(
            stdout="Loading model file",
            stderr=self.REAL_STDERR,
            support_stl_exists=False,
        )
        assert "Loading model file" in result.detail
        assert MODEL_MISMATCH_MARKER in result.detail

    def test_absent_marker_does_not_trigger_the_code(self):
        """Teeth: an ordinary failure must not pick up this code by accident."""
        result = classify_support_result(
            stdout="Slicing model",
            stderr="Failed to export support mesh",
            support_stl_exists=False,
        )
        assert result.error_code == FALLBACK_CODE

    def test_a_healthy_run_does_not_trigger_the_code(self):
        """Teeth: a normal success stays a success."""
        result = classify_support_result(
            stdout="(supports only)",
            stderr="",
            support_stl_exists=True,
        )
        assert result.status == JobStatus.COMPLETED
        assert result.error_code is None


class TestStep1ValidateErrors:
    # Realistic multi-line validate() messages from SLAPrint.cpp.
    CASES = [
        (
            "Cannot proceed without support points! Add support points or disable support generation.",
            "SUPPORT_POINTS_REQUIRED",
        ),
        (
            "Elevation is too low for object. Use the \"Pad around object\" feature...",
            "SUPPORT_ELEVATION_TOO_LOW",
        ),
        (
            "The endings of the support pillars will be deployed on the gap between the object and the pad.",
            "SUPPORT_PAD_GAP_CONFLICT",
        ),
        (
            "Invalid Head penetration\nHead penetration should not be greater than the Head width.",
            "SUPPORT_HEAD_PENETRATION_INVALID",
        ),
        (
            "Invalid pinhead diameter\nPinhead front diameter should be smaller than the Pillar diameter.",
            "SUPPORT_HEAD_TOO_WIDE",
        ),
    ]

    @pytest.mark.parametrize("stderr_text,expected_code", CASES)
    def test_each_validate_message_maps_to_specific_code(self, stderr_text, expected_code):
        """3.2: each known validate message on stderr → its specific code."""
        result = classify_support_result(stdout="", stderr=stderr_text, support_stl_exists=False)
        assert result.status == JobStatus.FAILED
        assert result.error_code == expected_code
        assert result.has_support_mesh is False

    def test_validate_map_covers_all_five_specific_codes(self):
        """3.2: the map exposes exactly the five support-specific validate codes."""
        codes = {code for _, code in VALIDATE_CODE_MAP}
        assert codes == {
            "SUPPORT_POINTS_REQUIRED",
            "SUPPORT_ELEVATION_TOO_LOW",
            "SUPPORT_PAD_GAP_CONFLICT",
            "SUPPORT_HEAD_PENETRATION_INVALID",
            "SUPPORT_HEAD_TOO_WIDE",
        }

    def test_validate_error_wins_even_with_exit_zero_semantics(self):
        """Spec: validate failure (exit 0 in the fork) is still FAILED — the
        classifier has no returncode input, so it can't be fooled."""
        result = classify_support_result(
            stdout="Some slicing chatter\n",
            stderr="Invalid pinhead diameter\nPinhead front diameter should be smaller...",
            support_stl_exists=False,
        )
        assert result.status == JobStatus.FAILED
        assert result.error_code == "SUPPORT_HEAD_TOO_WIDE"

    def test_validate_error_wins_over_stray_success_marker(self):
        """A known validate error must beat any stray stdout success marker."""
        result = classify_support_result(
            stdout="(supports only)",
            stderr="Invalid pinhead diameter",
            support_stl_exists=True,
        )
        assert result.status == JobStatus.FAILED
        assert result.error_code == "SUPPORT_HEAD_TOO_WIDE"

    @pytest.mark.parametrize(
        "stderr_text",
        [
            "Exposition time is out of printer profile bounds.",
            "Initial exposition time is out of printer profile bounds.",
            "Disabling the 'Use tilt' function causes the object to separate...",
        ],
    )
    def test_nonspecific_validate_falls_back(self, stderr_text):
        """Spec: a non-support validate error → FAILED + fallback, message kept."""
        result = classify_support_result(stdout="", stderr=stderr_text, support_stl_exists=False)
        assert result.status == JobStatus.FAILED
        assert result.error_code == FALLBACK_CODE
        assert result.detail  # original message preserved

    def test_nonspecific_validate_appendix_keeps_both_streams(self):
        """Spec ("失敗時原始輸出可供除錯"): a SUPPORT_GENERATION_FAILED attribution
        MUST carry BOTH raw stdout and stderr in the debug appendix."""
        result = classify_support_result(
            stdout="Slicing model\nSTDOUT_CHATTER_MARKER\n",
            stderr="Exposition time is out of printer profile bounds.\nSTDERR_DETAIL_MARKER",
            support_stl_exists=False,
        )
        assert result.error_code == FALLBACK_CODE
        assert "STDOUT_CHATTER_MARKER" in result.detail  # stdout kept
        assert "STDERR_DETAIL_MARKER" in result.detail  # stderr kept


class TestStep2OutOfBounds:
    def test_marker_on_stdout(self):
        """3.3: model out of bounds marker → MODEL_OUT_OF_BOUNDS."""
        result = classify_support_result(
            stdout="Nothing to print... no object is fully inside the print volume.",
            stderr="",
            support_stl_exists=False,
        )
        assert result.status == JobStatus.FAILED
        assert result.error_code == "MODEL_OUT_OF_BOUNDS"

    def test_out_of_bounds_not_classified_as_not_needed(self):
        """Spec: out-of-bounds MUST NOT be treated as SUPPORT_NOT_NEEDED."""
        result = classify_support_result(
            stdout="no object is fully inside the print volume",
            stderr="",
            support_stl_exists=False,
        )
        assert result.support_outcome != SUPPORT_NOT_NEEDED


class TestStep3NotNeeded:
    @pytest.mark.parametrize("marker", NOT_NEEDED_MARKERS)
    def test_neutral_markers_complete_without_mesh(self, marker):
        """3.4: (pad only) / No support/pad mesh generated → COMPLETED, neutral."""
        result = classify_support_result(stdout=f"...{marker}...", stderr="", support_stl_exists=False)
        assert result.status == JobStatus.COMPLETED
        assert result.support_outcome == SUPPORT_NOT_NEEDED
        assert result.has_support_mesh is False

    def test_pad_only_is_not_reported_as_has_support(self):
        """Spec: '(pad only)' must NOT report has_support_mesh=True even if an
        STL (the pad) was written."""
        result = classify_support_result(stdout="(pad only)", stderr="", support_stl_exists=True)
        assert result.has_support_mesh is False
        assert result.support_outcome == SUPPORT_NOT_NEEDED
        assert result.status == JobStatus.COMPLETED


class TestStep4HasSupport:
    @pytest.mark.parametrize("marker", HAS_SUPPORT_MARKERS)
    def test_support_markers_complete_with_mesh(self, marker):
        """3.5: (supports only) / (includes supports and pad) → COMPLETED, has mesh."""
        result = classify_support_result(stdout=f"...{marker}...", stderr="", support_stl_exists=True)
        assert result.status == JobStatus.COMPLETED
        assert result.has_support_mesh is True
        assert result.error_code is None
        assert result.support_outcome is None

    def test_success_marker_but_missing_stl_fails_closed(self):
        """Defensive: success marker but no STL on disk → fail-closed (never
        upgrade to success on a missing file)."""
        result = classify_support_result(stdout="(supports only)", stderr="", support_stl_exists=False)
        assert result.status == JobStatus.FAILED
        assert result.error_code == FALLBACK_CODE


class TestStep5FailClosed:
    def test_write_failure_no_marker_fails_closed(self):
        """3.6 / spec: 'Failed to export support mesh', no STL, no positive
        marker → FAILED + fallback (NOT SUPPORT_NOT_NEEDED)."""
        result = classify_support_result(
            stdout="Slicing model\n",
            stderr="Failed to export support mesh",
            support_stl_exists=False,
        )
        assert result.status == JobStatus.FAILED
        assert result.error_code == FALLBACK_CODE
        assert result.support_outcome != SUPPORT_NOT_NEEDED

    def test_conflicting_markers_fail_closed(self):
        """3.6 / spec: both a success marker and a not-needed marker → fail-closed."""
        result = classify_support_result(
            stdout="(supports only)\nNo support/pad mesh generated",
            stderr="",
            support_stl_exists=True,
        )
        assert result.status == JobStatus.FAILED
        assert result.error_code == FALLBACK_CODE

    def test_completely_unknown_output_fails_closed(self):
        """3.6: no known marker anywhere → fail-closed with raw streams kept."""
        result = classify_support_result(
            stdout="totally unexpected chatter",
            stderr="weird stuff",
            support_stl_exists=False,
        )
        assert result.status == JobStatus.FAILED
        assert result.error_code == FALLBACK_CODE
        assert "totally unexpected chatter" in result.detail
        assert "weird stuff" in result.detail

    def test_empty_output_fails_closed(self):
        """3.6: empty streams (e.g. a silent crash) → fail-closed."""
        result = classify_support_result(stdout="", stderr="", support_stl_exists=False)
        assert result.status == JobStatus.FAILED
        assert result.error_code == FALLBACK_CODE


class TestByteInputs:
    def test_accepts_raw_bytes_from_cli(self):
        """run_prusa_cli returns bytes; classifier must handle them directly."""
        result = classify_support_result(
            stdout=b"(includes supports and pad)",
            stderr=b"",
            support_stl_exists=True,
        )
        assert result.status == JobStatus.COMPLETED
        assert result.has_support_mesh is True

    def test_handles_invalid_utf8_gracefully(self):
        """Undecodable bytes must not crash the classifier."""
        result = classify_support_result(
            stdout=b"\xff\xfe(pad only)\xff",
            stderr=b"\xff",
            support_stl_exists=False,
        )
        assert result.status == JobStatus.COMPLETED
        assert result.support_outcome == SUPPORT_NOT_NEEDED