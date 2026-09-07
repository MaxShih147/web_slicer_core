"""
Contract / golden tests for the slicing classifier's string markers — Task 4.2
(add-slicing-error-codes).

The classifier decides everything from English substrings that must appear
verbatim in the PrusaSlicer fork's output. This test pins that contract directly
against the fork C++ source: every needle the classifier looks for MUST still be
present in the source string that produces it. If de-identification or an
upstream refactor rewrites one of these strings, this test fails loudly instead
of the classifier silently degrading to fail-closed at runtime.

4.2 negative check: a deliberately mutated marker MUST NOT be found in the
source — proving these assertions have teeth (a drifted string would fail).

Source file mapping:
  validate() patterns (Path A, Step 1):
    - SLAPrint.cpp        — most validate() messages
    - SLA/Pad.cpp         — "Pad brim size is too small" (PadConfig::validate())
  process() exception patterns (Path A, Step 2):
    - SLAPrintSteps.cpp   — RuntimeError / SlicingError throw sites
  zero-exit markers (Path B):
    - ProcessActions.cpp  — _OUT_OF_BOUNDS_MARKER (stdout, F-17)
    - LoadPrintData.cpp   — _EMPTY_MODEL_MARKER   (stderr, F-06)

Note: this test does NOT check locale pinning. Unlike run_prusa_cli() (which
calls _english_locale_env()), run_slicing() in jobs.py does not pin locale;
the locale dependency is documented as a deployment requirement (design D5).
"""

from pathlib import Path

import pytest

from agent.slicing_classifier import (
    _EMPTY_MODEL_MARKER,
    _OUT_OF_BOUNDS_MARKER,
    _PROCESS_CODE_MAP,
    _VALIDATE_CODE_MAP,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_FORK = _REPO_ROOT / "third_party" / "prusaslicer_fork" / "src"

_SLAPRINT_CPP      = _FORK / "libslic3r" / "SLAPrint.cpp"
_PAD_CPP           = _FORK / "libslic3r" / "SLA" / "Pad.cpp"
_SLAPRINT_STEPS_CPP = _FORK / "libslic3r" / "SLAPrintSteps.cpp"
_PROCESS_ACTIONS_CPP = _FORK / "CLI" / "ProcessActions.cpp"
_LOAD_PRINT_DATA_CPP = _FORK / "CLI" / "LoadPrintData.cpp"


def _read_source(path: Path) -> str:
    if not path.exists():
        pytest.skip(f"fork submodule source not checked out: {path}")
    return path.read_text(encoding="utf-8", errors="replace")


@pytest.fixture(scope="module")
def slaprint_src():
    return _read_source(_SLAPRINT_CPP)


@pytest.fixture(scope="module")
def pad_src():
    return _read_source(_PAD_CPP)


@pytest.fixture(scope="module")
def validate_src(slaprint_src, pad_src):
    """Combined source for all validate() messages (SLAPrint.cpp + SLA/Pad.cpp)."""
    return slaprint_src + pad_src


@pytest.fixture(scope="module")
def slaprint_steps_src():
    return _read_source(_SLAPRINT_STEPS_CPP)


@pytest.fixture(scope="module")
def process_actions_src():
    return _read_source(_PROCESS_ACTIONS_CPP)


@pytest.fixture(scope="module")
def load_print_data_src():
    return _read_source(_LOAD_PRINT_DATA_CPP)


# ─── validate() needle contract ───────────────────────────────────────────────

class TestValidateMessageContract:
    @pytest.mark.parametrize("needle,code", _VALIDATE_CODE_MAP)
    def test_validate_needle_present_in_source(self, needle, code, validate_src):
        """Each validate() substring must still exist in SLAPrint.cpp or SLA/Pad.cpp.

        'Pad brim size is too small' is in Pad.cpp::PadConfig::validate();
        the remaining five are in SLAPrint.cpp::validate().
        """
        assert needle in validate_src, (
            f"validate marker for {code} drifted: {needle!r} "
            f"no longer found in SLAPrint.cpp or SLA/Pad.cpp"
        )


# ─── process() exception needle contract ──────────────────────────────────────

class TestProcessExceptionContract:
    @pytest.mark.parametrize("needle,code", _PROCESS_CODE_MAP)
    def test_process_needle_present_in_source(self, needle, code, slaprint_steps_src):
        """Each process() exception substring must still exist in SLAPrintSteps.cpp."""
        assert needle in slaprint_steps_src, (
            f"process exception marker for {code} drifted: {needle!r} "
            f"no longer found in SLAPrintSteps.cpp"
        )


# ─── Path B marker contract ────────────────────────────────────────────────────

class TestPathBMarkerContract:
    def test_out_of_bounds_marker_present(self, process_actions_src):
        """F-17 stdout marker must still exist in ProcessActions.cpp."""
        assert _OUT_OF_BOUNDS_MARKER in process_actions_src, (
            f"MODEL_OUT_OF_BOUNDS marker drifted: {_OUT_OF_BOUNDS_MARKER!r} "
            f"no longer in ProcessActions.cpp"
        )

    def test_empty_model_marker_present(self, load_print_data_src):
        """F-06 stderr marker must still exist in LoadPrintData.cpp."""
        assert _EMPTY_MODEL_MARKER in load_print_data_src, (
            f"INVALID_MODEL (empty-model) marker drifted: {_EMPTY_MODEL_MARKER!r} "
            f"no longer in LoadPrintData.cpp"
        )


# ─── negative check ───────────────────────────────────────────────────────────

class TestNegativeCheck:
    """4.2: prove the contract fails when a marker string drifts."""

    # (original needle, a plausible drifted variant that MUST NOT match)
    MUTATIONS = [
        # process() — no-space variant is the single most common auto-fix drift
        ("can not be sliced",          "cannot be sliced"),
        # process() — hyphenation (plausible de-identification rewrite)
        ("There are unprintable objects", "There are non-printable objects"),
        # Path B stdout — preposition swap (same as support contract, proves both)
        ("no object is fully inside the print volume",
         "no object is fully within the print volume"),
        # Path B stderr — punctuation swap (exclamation instead of colon)
        ("Error: file is empty:",      "Error: file is empty!"),
        # validate() — missing "is" in Pad brim message
        ("Pad brim size is too small", "Pad brim size too small"),
        # validate() — hyphenation of pinhead (same as support contract)
        ("Invalid pinhead diameter",   "Invalid pin-head diameter"),
    ]

    @pytest.mark.parametrize("original,mutated", MUTATIONS)
    def test_mutation_differs_from_original(self, original, mutated):
        """Sanity: the mutated string is genuinely different from the real one."""
        assert mutated != original

    @pytest.mark.parametrize("original,mutated", MUTATIONS)
    def test_mutated_marker_is_not_in_any_source(
        self,
        original,
        mutated,
        validate_src,
        slaprint_steps_src,
        process_actions_src,
        load_print_data_src,
    ):
        """A drifted marker must NOT be found in any source file — so the positive
        assertions above would fail the moment the real string changed to this form."""
        all_sources = (
            validate_src + slaprint_steps_src + process_actions_src + load_print_data_src
        )
        assert original in all_sources, (
            f"The original needle {original!r} is no longer in any source file — "
            f"the positive contract test above should have caught this"
        )
        assert mutated not in all_sources, (
            f"Mutated string {mutated!r} was unexpectedly found in source — "
            f"the negative check no longer has teeth"
        )
