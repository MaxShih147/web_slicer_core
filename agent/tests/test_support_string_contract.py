"""
Contract / golden tests for the classifier's string markers — Task 7
(add-support-generation-error-codes).

The classifier decides everything from English substrings that must appear
verbatim in the PrusaSlicer fork's output. This test pins that contract directly
against the fork C++ source: every needle the classifier looks for MUST still be
present in the source string that produces it. If de-identification or an
upstream refactor rewrites one of these strings, this test fails loudly instead
of the classifier silently degrading to fail-closed at runtime.

Also verifies the locale-pinning (design D5 / Task 7.1): the engine env forces
the C locale so validate() messages stay English.

7.3 negative check: a deliberately mutated marker MUST NOT be found in the
source — proving these assertions have teeth (a drifted string would fail).
"""

from pathlib import Path

import pytest

from agent import sla_operations
from agent.support_classifier import (
    HAS_SUPPORT_MARKERS,
    MODEL_MISMATCH_MARKER,
    NONSPECIFIC_VALIDATE_MARKERS,
    NOT_NEEDED_MARKERS,
    OUT_OF_BOUNDS_MARKER,
    VALIDATE_CODE_MAP,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_FORK = _REPO_ROOT / "third_party" / "prusaslicer_fork" / "src"
# validate() messages (stderr, Step 1) live here:
_SLAPRINT_CPP = _FORK / "libslic3r" / "SLAPrint.cpp"
# out-of-bounds + support/pad stdout markers (Steps 2-4) live here:
_PROCESS_ACTIONS_CPP = _FORK / "CLI" / "ProcessActions.cpp"
# the support-point/model mismatch marker (Step 0) is defined here:
_SUPPORT_POINT_IO_HPP = _FORK / "libslic3r" / "SLA" / "SupportPointIO.hpp"


def _read_source(path: Path) -> str:
    if not path.exists():
        pytest.skip(f"fork submodule source not checked out: {path}")
    return path.read_text(encoding="utf-8", errors="replace")


@pytest.fixture(scope="module")
def slaprint_src():
    return _read_source(_SLAPRINT_CPP)


@pytest.fixture(scope="module")
def process_actions_src():
    return _read_source(_PROCESS_ACTIONS_CPP)


@pytest.fixture(scope="module")
def support_point_io_src():
    return _read_source(_SUPPORT_POINT_IO_HPP)


class TestValidateMessageContract:
    @pytest.mark.parametrize("needle,code", VALIDATE_CODE_MAP)
    def test_validate_needle_present_in_source(self, needle, code, slaprint_src):
        """Each support-specific validate() substring must exist in SLAPrint.cpp."""
        assert needle in slaprint_src, (
            f"validate marker for {code} drifted: {needle!r} no longer in SLAPrint.cpp"
        )

    @pytest.mark.parametrize("needle", NONSPECIFIC_VALIDATE_MARKERS)
    def test_nonspecific_validate_needle_present(self, needle, slaprint_src):
        """The non-support validate substrings (exposition / use-tilt) must exist."""
        assert needle in slaprint_src, (
            f"non-specific validate marker drifted: {needle!r} no longer in SLAPrint.cpp"
        )


class TestStdoutMarkerContract:
    def test_out_of_bounds_marker_present(self, process_actions_src):
        assert OUT_OF_BOUNDS_MARKER in process_actions_src

    @pytest.mark.parametrize("needle", NOT_NEEDED_MARKERS)
    def test_not_needed_markers_present(self, needle, process_actions_src):
        assert needle in process_actions_src, (
            f"neutral marker drifted: {needle!r} no longer in ProcessActions.cpp"
        )

    @pytest.mark.parametrize("needle", HAS_SUPPORT_MARKERS)
    def test_has_support_markers_present(self, needle, process_actions_src):
        assert needle in process_actions_src, (
            f"has-support marker drifted: {needle!r} no longer in ProcessActions.cpp"
        )


class TestModelMismatchMarkerContract:
    """8.3: pin the support-point/model mismatch marker (classifier Step 0).

    Same shape as the other contract tests: the Python-side needle is asserted
    against the fork source that produces it, so a rewrite on either side is
    caught here instead of degrading to SUPPORT_GENERATION_FAILED at runtime.
    """

    # The C++ constant that holds the literal, and the exact literal itself.
    CONSTANT_NAME = "support_points_model_mismatch_marker"

    def test_marker_literal_present_in_header(self, support_point_io_src):
        """The classifier needle must appear verbatim in SupportPointIO.hpp."""
        assert MODEL_MISMATCH_MARKER in support_point_io_src, (
            f"mismatch marker drifted: {MODEL_MISMATCH_MARKER!r} no longer in "
            "SupportPointIO.hpp — agent/support_classifier.py MODEL_MISMATCH_MARKER "
            "must be updated to match, or the failure silently becomes "
            "SUPPORT_GENERATION_FAILED"
        )

    def test_marker_defined_as_a_named_constant(self, support_point_io_src):
        """The literal is defined once, under the name the CLI prints."""
        assert self.CONSTANT_NAME in support_point_io_src

    def test_cli_prints_the_constant_not_a_copy(self, process_actions_src):
        """ProcessActions.cpp must emit the shared constant, not its own copy.

        A second hand-written copy of the literal would drift independently and
        this contract would stop protecting the path that actually runs.
        """
        assert self.CONSTANT_NAME in process_actions_src
        assert MODEL_MISMATCH_MARKER not in process_actions_src, (
            "ProcessActions.cpp inlines its own copy of the marker; it should "
            f"print sla::{self.CONSTANT_NAME} instead"
        )

    def test_marker_is_not_wrapped_for_translation(self, support_point_io_src):
        """Spec: the marker MUST NOT be translatable — it is matched in every locale.

        Scans the marker's own definition line rather than the whole file, so an
        unrelated _u8L() elsewhere in the header cannot mask a real regression.
        """
        line = next(
            ln for ln in support_point_io_src.splitlines()
            if MODEL_MISMATCH_MARKER in ln
        )
        assert "_u8L" not in line
        assert "_L(" not in line
        assert "translate" not in line

    def test_marker_carries_the_error_code_verbatim(self):
        """The code the classifier assigns is the marker's own prefix.

        Keeps the human-readable stderr line and the machine code from drifting
        apart: the marker literally starts with the code it maps to.
        """
        from agent.support_classifier import MODEL_MISMATCH_CODE

        assert MODEL_MISMATCH_MARKER.startswith(MODEL_MISMATCH_CODE)

    @pytest.mark.parametrize(
        "mutated",
        [
            "SUPPORT_POINTS_MODEL_MISMATCH: imported support points don't match this model",
            "SUPPORT_POINT_MODEL_MISMATCH: imported support points do not match this model",
            "SUPPORT_POINTS_MODEL_MISMATCH: imported support points do not match the model",
        ],
    )
    def test_drifted_marker_is_not_in_source(self, mutated, support_point_io_src):
        """Teeth: a plausibly-reworded marker must NOT be found.

        Proves the positive assertion above would fail if the string changed.
        """
        assert mutated != MODEL_MISMATCH_MARKER
        assert mutated not in support_point_io_src


class TestNegativeCheck:
    """7.3: prove the contract fails when a marker string drifts."""

    # (original needle, a plausible drifted variant that MUST NOT match)
    MUTATIONS = [
        ("(supports only)", "(supports ONLY)"),
        ("(pad only)", "(pad-only)"),
        ("no object is fully inside the print volume", "no object is fully within the print volume"),
        ("Invalid pinhead diameter", "Invalid pin-head diameter"),
    ]

    @pytest.mark.parametrize("original,mutated", MUTATIONS)
    def test_mutation_differs_from_original(self, original, mutated):
        """Sanity: the mutated string is genuinely different from the real one."""
        assert mutated != original

    @pytest.mark.parametrize("original,mutated", MUTATIONS)
    def test_mutated_marker_is_not_in_source(self, original, mutated, slaprint_src, process_actions_src):
        """A drifted marker must NOT be found — so the positive contract above
        would fail the moment the real string changed to this form."""
        combined = slaprint_src + process_actions_src
        assert original in combined  # the real one is there
        assert mutated not in combined  # the drifted one is not — contract has teeth


class TestLocalePinned:
    """7.1: the engine runs under a pinned English (C) locale (design D5)."""

    def test_engine_locale_env_forces_c_locale(self):
        assert sla_operations.ENGINE_LOCALE_ENV["LC_ALL"] == "C"
        assert sla_operations.ENGINE_LOCALE_ENV["LANG"] == "C"

    def test_english_locale_env_overrides_ambient_locale(self, monkeypatch):
        """Even with a non-English ambient locale, the built env pins C."""
        monkeypatch.setenv("LC_ALL", "zh_TW.UTF-8")
        monkeypatch.setenv("LANG", "zh_TW.UTF-8")
        env = sla_operations._english_locale_env()
        assert env["LC_ALL"] == "C"
        assert env["LANG"] == "C"
        # still carries the rest of the environment (not a blank env)
        assert "PATH" in env or "Path" in env