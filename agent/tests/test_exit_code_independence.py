"""
Tasks 5.1/5.2 (merge-engine-result-classifiers), design D6/D3.

`classify_slice_result()`'s classification must not depend on `exit_code` —
the fork's `validate()` failures return exit 0 in several paths (`return 1`
inside `bool` functions), so exit code was never a reliable signal to begin
with. This test feeds every known message through both `exit_code=0` and
`exit_code=1` and asserts the same code comes back.

`MODEL_OUT_OF_BOUNDS` and `INVALID_MODEL` (the empty-model marker) used to be
the exception: merge-engine-result-classifiers left them detected only when
`exit_code == 0` (`_LEGACY_EXIT0_ONLY_CODES`) and marked these two cases
`xfail(strict=True)`. engine-error-code-table Section 6 removed that branch,
so they are ordinary assertions now, like every other message here.
"""

import pytest

from agent.engine_rules import ENGINE_RULES, Substring
from agent.slicing_classifier import (
    MODEL_MISMATCH_MARKER,
    _EMPTY_MODEL_CODE,
    _EMPTY_MODEL_MARKER,
    _OUT_OF_BOUNDS_CODE,
    _OUT_OF_BOUNDS_MARKER,
    classify_slice_result,
)

_MODEL = "model.stl"

# Every ENGINE_RULES rule visible to the slice flow — the shared table D3
# requires to be exit-code independent by construction (it has no exit_code
# field at all). Samples are each rule's English needle, found by type:
# engine-error-code-table puts an EngineCode matcher ahead of it.
_SHARED_RULE_SAMPLES = [
    (next(m.text for m in rule.matchers if isinstance(m, Substring)), rule.code)
    for rule in ENGINE_RULES
    if "slice" in rule.flows
]

_NOTHING_TO_PRINT_SAMPLES = [
    (_OUT_OF_BOUNDS_MARKER, _OUT_OF_BOUNDS_CODE),
    (_EMPTY_MODEL_MARKER, _EMPTY_MODEL_CODE),
]


class TestSharedRulesAreExitCodeIndependent:
    @pytest.mark.parametrize("stderr_text,expected_code", _SHARED_RULE_SAMPLES)
    def test_same_code_for_exit_0_and_1(self, stderr_text, expected_code):
        result_0 = classify_slice_result(0, "", stderr_text, _MODEL, False)
        result_1 = classify_slice_result(1, "", stderr_text, _MODEL, False)
        assert result_0 is not None and result_1 is not None
        assert result_0.error_code == result_1.error_code == expected_code


class TestModelMismatchIsExitCodeIndependent:
    @pytest.mark.parametrize("exit_code", [0, 1, 2, -1])
    def test_same_code_regardless_of_exit_code(self, exit_code):
        result = classify_slice_result(exit_code, "", MODEL_MISMATCH_MARKER, _MODEL, False)
        assert result.error_code == "SUPPORT_POINTS_MODEL_MISMATCH"


class TestNothingToPrintIsExitCodeIndependent:
    @pytest.mark.parametrize("stderr_text,expected_code", _NOTHING_TO_PRINT_SAMPLES)
    def test_same_code_for_exit_0_and_1(self, stderr_text, expected_code):
        result_0 = classify_slice_result(0, "", stderr_text, _MODEL, False)
        result_1 = classify_slice_result(1, "", stderr_text, _MODEL, False)
        assert result_0 is not None and result_1 is not None
        assert result_0.error_code == result_1.error_code == expected_code
