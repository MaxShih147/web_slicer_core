"""
Tests for the seven-step SLA slicing result classifier — Task 4.1
(add-slicing-error-codes).

Coverage:
  - Path A (exit_code != 0):
      Step 1  all validate() codes, in declared map order
      Step 2  all process() exception codes
      Step 3  STL parse error via "{filename}:" prefix
      Step 4  unclassified fallback → error_code=None (JOB_FAILED)
  - Path B (exit_code == 0, no output file):
      Step 5  MODEL_OUT_OF_BOUNDS from stdout (and defensively stderr)
      Step 6  INVALID_MODEL from empty-model stderr marker (exit 0 special case)
      Step 7  fallback → error_code=None (JOB_FAILED)
  - Success: exit 0 + output file exists → None
  - Decision ordering: Step 1 beats Step 2 beats Step 3
  - Byte input handling (asyncio subprocess returns bytes)
"""

import pytest

from agent.slicing_classifier import (
    SliceClassification,
    _EMPTY_MODEL_CODE,
    _EMPTY_MODEL_MARKER,
    _INVALID_MODEL_CODE,
    _OUT_OF_BOUNDS_CODE,
    _OUT_OF_BOUNDS_MARKER,
    _PROCESS_CODE_MAP,
    _VALIDATE_CODE_MAP,
    classify_slice_result,
)

_MODEL = "model.stl"


# ─── success ──────────────────────────────────────────────────────────────────

class TestSuccess:
    def test_exit0_with_output_returns_none(self):
        """exit 0 + output present → None; caller walks the success path."""
        assert classify_slice_result(0, b"", b"", _MODEL, True) is None

    def test_exit0_no_output_is_not_success(self):
        """exit 0 but output absent → Path B (failure), never None."""
        result = classify_slice_result(0, b"", b"", _MODEL, False)
        assert result is not None

    def test_nonzero_with_output_is_still_failure(self):
        """Non-zero exit → Path A regardless of whether an output file exists."""
        result = classify_slice_result(1, b"", b"", _MODEL, True)
        assert result is not None


# ─── Path A · Step 1: validate() errors ───────────────────────────────────────

class TestPathAStep1ValidateErrors:
    @pytest.mark.parametrize("needle,expected_code", _VALIDATE_CODE_MAP)
    def test_each_needle_maps_to_its_code(self, needle, expected_code):
        """Step 1: every validate() needle in the map → the declared code."""
        result = classify_slice_result(1, b"", needle, _MODEL, False)
        assert isinstance(result, SliceClassification)
        assert result.error_code == expected_code
        assert result.error  # raw stderr preserved

    def test_validate_map_covers_expected_six_codes(self):
        """Sanity: the validate map declares exactly the six expected codes."""
        codes = {code for _, code in _VALIDATE_CODE_MAP}
        assert codes == {
            "SUPPORT_ELEVATION_TOO_LOW",
            "SUPPORT_PAD_GAP_CONFLICT",
            "PAD_CONFIG_INVALID",
            "EXPOSURE_TIME_OUT_OF_RANGE",
            "SUPPORT_HEAD_PENETRATION_INVALID",
            "SUPPORT_HEAD_TOO_WIDE",
        }

    def test_exposure_time_needle_matches_both_exposition_variants(self):
        """The partial needle 'xposition time is out of...' covers both
        'Exposition time...' (F-12) and 'Initial exposition time...' (F-13)."""
        for full_msg in (
            "Exposition time is out of printer profile bounds.",
            "Initial exposition time is out of printer profile bounds.",
        ):
            result = classify_slice_result(1, b"", full_msg, _MODEL, False)
            assert result.error_code == "EXPOSURE_TIME_OUT_OF_RANGE", full_msg


# ─── Path A · Step 2: process() exceptions ────────────────────────────────────

class TestPathAStep2ProcessErrors:
    @pytest.mark.parametrize("needle,expected_code", _PROCESS_CODE_MAP)
    def test_each_needle_maps_to_its_code(self, needle, expected_code):
        """Step 2: every process() exception needle → the declared code."""
        result = classify_slice_result(1, b"", needle, _MODEL, False)
        assert isinstance(result, SliceClassification)
        assert result.error_code == expected_code

    def test_process_map_covers_expected_three_codes(self):
        """Sanity: the process map declares exactly the three expected codes."""
        codes = {code for _, code in _PROCESS_CODE_MAP}
        assert codes == {
            "MODEL_MESH_UNSLICEABLE",
            "UNPRINTABLE_OBJECT",
            "PAD_GENERATION_FAILED",
        }


# ─── Path A · Step 3: STL parse error ─────────────────────────────────────────

class TestPathAStep3STLParseError:
    def test_filename_colon_prefix_maps_to_invalid_model(self):
        """Step 3: '{input_filename}: <exception.what()>' → INVALID_MODEL."""
        result = classify_slice_result(
            1, b"", f"{_MODEL}: failed to parse STL header", _MODEL, False
        )
        assert isinstance(result, SliceClassification)
        assert result.error_code == _INVALID_MODEL_CODE

    def test_only_exact_input_filename_triggers_step3(self):
        """Step 3 MUST NOT fire on a different filename in stderr.
        Note: the test filename must not be a substring of _MODEL (model.stl),
        so we use 'output.stl' rather than 'other_model.stl' which would contain
        'model.stl' as a suffix and inadvertently trigger Step 3."""
        result = classify_slice_result(
            1, b"", "output.stl: some error", _MODEL, False
        )
        # Falls through to Step 4 (unclassified)
        assert result.error_code is None


# ─── Path A · Step 4: unclassified fallback ───────────────────────────────────

class TestPathAStep4Unclassified:
    def test_unknown_stderr_returns_no_code(self):
        """Step 4: non-zero exit + no known pattern → error_code=None (JOB_FAILED)."""
        result = classify_slice_result(1, b"", "some unknown engine error", _MODEL, False)
        assert isinstance(result, SliceClassification)
        assert result.error_code is None

    def test_unclassified_error_string_includes_exit_code_and_stderr(self):
        """Step 4: error string should carry exit code + raw stderr for debugging."""
        result = classify_slice_result(2, b"", "segfault details", _MODEL, False)
        assert result.error_code is None
        assert "2" in result.error
        assert "segfault details" in result.error

    def test_empty_stderr_nonzero_exit_falls_to_step4(self):
        """Step 4: silent non-zero exit (e.g. crash before any output) → fallback."""
        result = classify_slice_result(1, b"", b"", _MODEL, False)
        assert result is not None
        assert result.error_code is None


# ─── Path B · Step 5: model out of bounds ─────────────────────────────────────

class TestPathBStep5ModelOutOfBounds:
    def test_marker_on_stdout(self):
        """Step 5: MODEL_OUT_OF_BOUNDS marker on stdout → MODEL_OUT_OF_BOUNDS."""
        result = classify_slice_result(
            0, f"...{_OUT_OF_BOUNDS_MARKER}...", b"", _MODEL, False
        )
        assert isinstance(result, SliceClassification)
        assert result.error_code == _OUT_OF_BOUNDS_CODE

    def test_marker_on_stderr_also_detected(self):
        """Step 5: defensive stderr scan (design D3) — marker on stderr also works."""
        result = classify_slice_result(
            0, b"", f"warning: {_OUT_OF_BOUNDS_MARKER}", _MODEL, False
        )
        assert isinstance(result, SliceClassification)
        assert result.error_code == _OUT_OF_BOUNDS_CODE

    def test_out_of_bounds_exit0_is_not_success(self):
        """Spec: exit 0 + MODEL_OUT_OF_BOUNDS marker MUST NOT be treated as success."""
        result = classify_slice_result(0, _OUT_OF_BOUNDS_MARKER, b"", _MODEL, False)
        assert result is not None
        assert result.error_code == _OUT_OF_BOUNDS_CODE


# ─── Path B · Step 6: empty model ─────────────────────────────────────────────

class TestPathBStep6EmptyModel:
    def test_empty_model_marker_in_stderr_maps_to_invalid_model(self):
        """Step 6: 'Error: file is empty:' in stderr (exit 0, no output) → INVALID_MODEL.
        This is F-06: LoadPrintData.cpp writes to stderr then 'continue' (not return),
        so exit code stays 0 even though no output is created."""
        result = classify_slice_result(
            0, b"", f"{_EMPTY_MODEL_MARKER} /path/to/model.stl", _MODEL, False
        )
        assert isinstance(result, SliceClassification)
        assert result.error_code == _EMPTY_MODEL_CODE

    def test_empty_model_exit0_is_not_success(self):
        """Spec: exit 0 + empty-model marker MUST NOT be treated as success."""
        result = classify_slice_result(
            0, b"", _EMPTY_MODEL_MARKER + " model.stl", _MODEL, False
        )
        assert result is not None
        assert result.error_code == _EMPTY_MODEL_CODE


# ─── Path B · Step 7: zero-exit fallback ──────────────────────────────────────

class TestPathBStep7Fallback:
    def test_zero_exit_no_output_no_marker_returns_no_code(self):
        """Step 7: exit 0, no output, no known marker → error_code=None (JOB_FAILED)."""
        result = classify_slice_result(0, b"", b"", _MODEL, False)
        assert isinstance(result, SliceClassification)
        assert result.error_code is None


# ─── decision ordering ────────────────────────────────────────────────────────

class TestOrdering:
    def test_step1_validate_beats_step2_process(self):
        """Step 1 wins over Step 2 when stderr matches both a validate needle
        and a process() needle."""
        combined_stderr = (
            "Elevation is too low for object. Use the Pad around object feature.\n"
            "can not be sliced"
        )
        result = classify_slice_result(1, b"", combined_stderr, _MODEL, False)
        assert result.error_code == "SUPPORT_ELEVATION_TOO_LOW"

    def test_step2_process_beats_step3_stl_parse(self):
        """Step 2 wins over Step 3 when stderr matches both a process() needle
        and the '{filename}:' parse-error prefix."""
        combined_stderr = f"{_MODEL}: some parse detail\ncan not be sliced"
        result = classify_slice_result(1, b"", combined_stderr, _MODEL, False)
        assert result.error_code == "MODEL_MESH_UNSLICEABLE"

    def test_pathb_step5_beats_step6_when_both_present(self):
        """In Path B, Step 5 (MODEL_OUT_OF_BOUNDS) fires before Step 6 (empty model)."""
        result = classify_slice_result(
            0,
            _OUT_OF_BOUNDS_MARKER,
            _EMPTY_MODEL_MARKER + " model.stl",
            _MODEL,
            False,
        )
        assert result.error_code == _OUT_OF_BOUNDS_CODE


# ─── byte/encoding handling ───────────────────────────────────────────────────

class TestByteInputs:
    def test_accepts_bytes_from_asyncio_subprocess(self):
        """asyncio subprocess returns bytes; classifier must handle them directly."""
        result = classify_slice_result(1, b"stdout chatter", b"can not be sliced", _MODEL, False)
        assert result.error_code == "MODEL_MESH_UNSLICEABLE"

    def test_handles_invalid_utf8_in_stderr_gracefully(self):
        """Undecodable bytes in stderr must not crash the classifier."""
        result = classify_slice_result(
            1, b"\xff\xfe", b"\xff Invalid pinhead diameter\xff", _MODEL, False
        )
        assert result.error_code == "SUPPORT_HEAD_TOO_WIDE"

    def test_handles_none_streams_without_crash(self):
        """None stdout/stderr (defensive; should not normally happen) must not raise."""
        result = classify_slice_result(1, None, None, _MODEL, False)
        assert isinstance(result, SliceClassification)
