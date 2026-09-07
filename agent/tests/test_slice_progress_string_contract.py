"""
Contract / golden tests for the slice-progress stage labels — Tasks 3.6 / 3.7
(add-slicing-progress).

The stage mapper decides everything from English labels that must appear
verbatim in the PrusaSlicer fork's C++ source. This test pins that contract
directly against the source: every label in ``ENGINE_STAGE_LABEL_MAP`` MUST
still be present in the file that produces it. If de-identification or an
upstream refactor rewrites one of these strings, this test fails loudly at CI
time instead of the mapper silently degrading every stage to STAGE_SLICING at
runtime — the runtime warning alone would only be noticed by whoever happens to
read the log.

Mirrors the established pattern in ``test_support_string_contract.py``.

3.7 negative check: deliberately mutated labels MUST NOT be found in the
source — proving these assertions have teeth (a drifted string would fail).
"""

from pathlib import Path

import pytest

from agent.jobs import ARCHIVE_DONE_MARKER, ENGINE_STAGE_LABEL_MAP

_REPO_ROOT = Path(__file__).resolve().parents[2]
_FORK = _REPO_ROOT / "third_party" / "prusaslicer_fork" / "src"
# OBJ_STEP_LABELS (8) + PRINT_STEP_LABELS (2) live here:
_SLA_PRINT_STEPS_CPP = _FORK / "libslic3r" / "SLAPrintSteps.cpp"
# The terminal "Slicing done" report lives here:
_SLAPRINT_CPP = _FORK / "libslic3r" / "SLAPrint.cpp"
# The archive-done marker (fork-owned, not upstream) lives here:
_PROCESS_ACTIONS_CPP = _FORK / "CLI" / "ProcessActions.cpp"

# Which source file each label is expected to come from.
_STEP_LABELS = (
    "Assembling model from parts",
    "Hollowing model",
    "Drilling holes into model.",
    "Slicing model",
    "Generating support points",
    "Generating support tree",
    "Generating pad",
    "Slicing supports",
    "Merging slices and calculating statistics",
    "Rasterizing layers",
)
_PRINT_LABELS = ("Slicing done",)


def _read_source(path: Path) -> str:
    if not path.exists():
        pytest.skip(f"fork submodule source not checked out: {path}")
    return path.read_text(encoding="utf-8", errors="replace")


@pytest.fixture(scope="module")
def sla_print_steps_src():
    return _read_source(_SLA_PRINT_STEPS_CPP)


@pytest.fixture(scope="module")
def slaprint_src():
    return _read_source(_SLAPRINT_CPP)


@pytest.fixture(scope="module")
def process_actions_src():
    return _read_source(_PROCESS_ACTIONS_CPP)


class TestLabelTableCompleteness:
    def test_expected_labels_match_the_production_table(self):
        """The two source-file buckets must together cover the whole table."""
        assert set(_STEP_LABELS) | set(_PRINT_LABELS) == set(ENGINE_STAGE_LABEL_MAP)

    def test_buckets_do_not_overlap(self):
        assert not set(_STEP_LABELS) & set(_PRINT_LABELS)


class TestStageLabelContract:
    @pytest.mark.parametrize("label", _STEP_LABELS)
    def test_step_label_present_in_source(self, label, sla_print_steps_src):
        """Each step label must still exist verbatim in SLAPrintSteps.cpp."""
        assert label in sla_print_steps_src, (
            f"stage label drifted: {label!r} no longer in SLAPrintSteps.cpp — "
            f"the mapper would silently degrade it to STAGE_SLICING"
        )

    @pytest.mark.parametrize("label", _PRINT_LABELS)
    def test_terminal_label_present_in_source(self, label, slaprint_src):
        assert label in slaprint_src, (
            f"stage label drifted: {label!r} no longer in SLAPrint.cpp"
        )

    def test_labels_are_wrapped_in_the_translation_macro(self, sla_print_steps_src):
        """The labels reach the CLI through _u8L(), whose callback is only
        installed by the GUI module — that is *why* headless output stays
        English and the mapper can rely on it."""
        for label in _STEP_LABELS:
            assert f'_u8L("{label}")' in sla_print_steps_src


class TestArchiveMarkerContract:
    """4.2: the archive-done marker is the only signal telling us the silent
    write-out tail after the engine's own 100% report has finished."""

    def test_marker_present_in_source_verbatim(self, process_actions_src):
        assert f'"{ARCHIVE_DONE_MARKER}"' in process_actions_src, (
            f"archive marker drifted: {ARCHIVE_DONE_MARKER!r} no longer in "
            f"ProcessActions.cpp — the STAGE_ARCHIVED transition would never fire"
        )

    def test_marker_keeps_its_trailing_space(self, process_actions_src):
        """The literal ends with a space because the path is streamed right
        after it; losing that space would break prefix matching."""
        assert ARCHIVE_DONE_MARKER.endswith(" ")
        assert f'"{ARCHIVE_DONE_MARKER}" <<' in process_actions_src

    def test_marker_is_emitted_after_the_preview_zip_export(
        self, process_actions_src
    ):
        """Ordering is the whole point: the marker must come *after*
        export_preview_zip(), otherwise it would not signal completion."""
        export_at = process_actions_src.index("export_preview_zip(")
        marker_at = process_actions_src.index(f'"{ARCHIVE_DONE_MARKER}"')
        assert export_at < marker_at


class TestNegativeCheck:
    """3.7: prove the contract fails when a label drifts."""

    # (original label, a plausible drifted variant that MUST NOT match)
    MUTATIONS = [
        ("Rasterizing layers", "Rasterising layers"),
        ("Drilling holes into model.", "Drilling holes into model"),
        ("Generating support tree", "Generating supports tree"),
        ("Assembling model from parts", "Assembling the model from parts"),
        ("Slicing done", "Slicing complete"),
    ]

    @pytest.mark.parametrize("original,mutated", MUTATIONS)
    def test_mutation_differs_from_original(self, original, mutated):
        """Sanity: the mutated string is genuinely different from the real one."""
        assert mutated != original

    @pytest.mark.parametrize("original,mutated", MUTATIONS)
    def test_mutated_label_is_not_in_source(
        self, original, mutated, sla_print_steps_src, slaprint_src
    ):
        """A drifted label must NOT be found — so the positive contract above
        would fail the moment the real string changed to this form."""
        combined = sla_print_steps_src + slaprint_src
        assert original in combined  # the real one is there
        # Quoted form, so a mutation that is a substring of the original (e.g.
        # dropping a trailing period) is still detected as absent.
        assert f'"{mutated}"' not in combined

    # 4.2: the same teeth for the archive marker.
    MARKER_MUTATIONS = [
        "Preview ZIP exported to",  # trailing space dropped
        "Preview zip exported to ",  # case drift
        "Preview ZIP written to ",
    ]

    @pytest.mark.parametrize("mutated", MARKER_MUTATIONS)
    def test_mutated_archive_marker_is_not_in_source(
        self, mutated, process_actions_src
    ):
        assert f'"{ARCHIVE_DONE_MARKER}"' in process_actions_src
        assert mutated != ARCHIVE_DONE_MARKER
        assert f'"{mutated}"' not in process_actions_src
