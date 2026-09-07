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