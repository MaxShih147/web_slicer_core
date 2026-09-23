"""
Tasks 5.1/5.2 (merge-engine-result-classifiers), design D6/D3.

`classify_slice_result()`'s classification must not depend on `exit_code` —
the fork's `validate()` failures return exit 0 in several paths (`return 1`
inside `bool` functions), so exit code was never a reliable signal to begin
with. This test feeds every known message through both `exit_code=0` and
`exit_code=1` and asserts the same code comes back.

Two codes are a known exception today — `slicing_classifier._LEGACY_EXIT0_ONLY_CODES`
(`MODEL_OUT_OF_BOUNDS`, `INVALID_MODEL` via the empty-model marker) are only
detected in Path B (`exit_code == 0`); Path A has no equivalent check. This is
the "unexploded bomb" design.md describes: once the fork's 15
`return 1`-in-`bool`-function sites are fixed (see the deferred
`engine-error-code-table` change), these same failures will exit 1 and land
unclassified instead. Marked `xfail(strict=True)` rather than skipped, so:
  - this file still proves every OTHER known message is exit-code independent
  - once that future change makes these two independent as well, this test
    starts passing and `strict=True` forces removing the xfail marker here
    instead of it silently staying stale
"""

import pytest

from agent.engine_rules import ENGINE_RULES
from agent.slicing_classifier import (
    MODEL_MISMATCH_MARKER,
    _EMPTY_MODEL_CODE,
    _EMPTY_MODEL_MARKER,
    _LEGACY_EXIT0_ONLY_CODES,
    _OUT_OF_BOUNDS_CODE,
    _OUT_OF_BOUNDS_MARKER,
    classify_slice_result,
)

_MODEL = "model.stl"

# Every ENGINE_RULES rule visible to the slice flow — the shared table D3
# requires to be exit-code independent by construction (it has no exit_code
# field at all).
_SHARED_RULE_SAMPLES = [
    (rule.matchers[0].text, rule.code) for rule in ENGINE_RULES if "slice" in rule.flows
]

_LEGACY_SAMPLES = [
    (_OUT_OF_BOUNDS_MARKER, _OUT_OF_BOUNDS_CODE),
    (_EMPTY_MODEL_MARKER, _EMPTY_MODEL_CODE),
]


def test_legacy_samples_match_the_named_constant():
    """Sanity: this file's xfail scope is exactly _LEGACY_EXIT0_ONLY_CODES,
    not a hand-picked subset that could silently drift from it."""
    assert {code for _, code in _LEGACY_SAMPLES} == set(_LEGACY_EXIT0_ONLY_CODES)


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


class TestLegacyExitCodeDependentCodes:
    @pytest.mark.parametrize("stderr_text,expected_code", _LEGACY_SAMPLES)
    @pytest.mark.xfail(
        strict=True,
        reason=(
            "unexploded bomb: MODEL_OUT_OF_BOUNDS/INVALID_MODEL(empty-model) are "
            "only detected in Path B (exit_code==0); pending the exit-code "
            "decoupling change (engine-error-code-table) that fixes the 15 "
            "return-1-in-bool sites and checks these markers in Path A too"
        ),
    )
    def test_same_code_for_exit_0_and_1(self, stderr_text, expected_code):
        result_0 = classify_slice_result(0, "", stderr_text, _MODEL, False)
        result_1 = classify_slice_result(1, "", stderr_text, _MODEL, False)
        assert result_0 is not None and result_1 is not None
        assert result_0.error_code == result_1.error_code == expected_code
