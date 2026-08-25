"""
Progress-line parsing samples and tests — Task 1.1 / Section 2
(add-slicing-progress).

The SLA CLI already emits progress on **stdout**; this change consumes it
rather than modifying the fork. The samples below are transcribed verbatim
from the fork so the parser is exercised against the real wire format:

  - Progress lines: ``printf("%3d%s %s\\n", percent, "% =>", text)`` in
    ``src/CLI/ProcessActions.cpp`` (SLA status callback). The ``%3d`` makes
    the percentage RIGHT-ALIGNED to width 3, so single/double digit values
    carry leading spaces — the parser must tolerate them.
  - Stage labels: ``OBJ_STEP_LABELS`` / ``PRINT_STEP_LABELS`` in
    ``src/libslic3r/SLAPrintSteps.cpp`` plus the terminal "Slicing done" in
    ``src/libslic3r/SLAPrint.cpp``.
  - Archive-done marker: the ``Preview ZIP exported to`` line in
    ``src/CLI/ProcessActions.cpp``, printed AFTER the archive and preview zip
    are written — i.e. after the engine already reported 100%.
  - Noise: other ``boost::nowide::cout`` lines from the same CLI path, which
    the parser must silently ignore.

Task 1.1 established the samples; Section 2 adds the parser assertions.
"""

import pytest

from agent.jobs import (
    ARCHIVE_DONE_MARKER,
    STAGE_ARCHIVED,
    STAGE_FINALIZING,
    STAGE_RASTERIZING,
    STAGE_SLICING,
    parse_progress_event,
    parse_progress_line,
)


# --- Progress lines -------------------------------------------------------
# %3d right-alignment: single digit gets two leading spaces, double digit one,
# three digits none. All three widths must parse identically.
PROGRESS_LINE_ONE_DIGIT = "  5% => Slicing model"
PROGRESS_LINE_TWO_DIGIT = " 29% => Generating support tree"
PROGRESS_LINE_THREE_DIGIT = "100% => Slicing done"

# The only stage label carrying a trailing period. Normalization must absorb it.
PROGRESS_LINE_TRAILING_PERIOD = " 26% => Drilling holes into model."

# Three labels sharing the "Slicing" prefix but with entirely different
# semantics. These are the reason substring matching is forbidden.
PROGRESS_LINE_SHARED_PREFIX_MODEL = " 39% => Slicing model"
PROGRESS_LINE_SHARED_PREFIX_SUPPORTS = " 62% => Slicing supports"
PROGRESS_LINE_SHARED_PREFIX_DONE = "100% => Slicing done"

# Every engine stage label, in the order the SLA pipeline emits them.
ENGINE_STAGE_LABELS = (
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
    "Slicing done",
)


# --- Archive-done marker --------------------------------------------------
# Emitted after export_print() + export_preview_zip() complete, i.e. the
# silent tail that follows the engine's own 100% report.
ARCHIVE_DONE_LINE = (
    "Preview ZIP exported to C:\\jobs\\a1b2c3d4\\output\\model_preview.zip"
)


# --- Noise ----------------------------------------------------------------
# Real stdout lines from the same CLI path that are NOT progress events.
NOISE_LINES = (
    "",
    "Slicing result exported to C:\\jobs\\a1b2c3d4\\output\\model.sl1",
    "Support mesh exported to C:\\jobs\\a1b2c3d4\\output\\model_support.stl"
    " (supports only)",
    "No support/pad mesh generated",
    "Nothing to print for out.sl1 . Either the print is empty or no object is"
    " fully inside the print volume.",
    # Shaped like a progress line but malformed — must NOT parse.
    "29 => Slicing model",
    "abc% => Slicing model",
    "% => Slicing model",
)


# --- Combined transcript --------------------------------------------------
# A plausible end-to-end stdout capture: progress interleaved with noise,
# ending with the engine's 100% and then the archive-done marker.
SAMPLE_STDOUT_LINES = (
    "  0% => Assembling model from parts",
    "  5% => Slicing model",
    " 26% => Drilling holes into model.",
    " 29% => Generating support tree",
    " 62% => Slicing supports",
    " 70% => Merging slices and calculating statistics",
    " 73% => Rasterizing layers",
    " 88% => Rasterizing layers",
    "100% => Slicing done",
    "Slicing result exported to C:\\jobs\\a1b2c3d4\\output\\model.sl1",
    ARCHIVE_DONE_LINE,
)

SAMPLE_STDOUT = "\n".join(SAMPLE_STDOUT_LINES) + "\n"


# --- 2.1 standard format --------------------------------------------------


def test_parses_standard_progress_line():
    assert parse_progress_line(PROGRESS_LINE_TWO_DIGIT) == (
        29,
        "Generating support tree",
    )


@pytest.mark.parametrize("label", ENGINE_STAGE_LABELS)
def test_parses_every_engine_stage_label(label):
    """Every label the SLA pipeline emits must survive the parser verbatim."""
    assert parse_progress_line(f" 42% => {label}") == (42, label)


def test_archive_done_line_is_not_a_percent_line():
    """The raw parser only handles "% =>" lines; the archive marker is a
    separate signal picked up by parse_progress_event (Section 4)."""
    assert parse_progress_line(ARCHIVE_DONE_LINE) is None


# --- 2.2 %3d right-alignment ----------------------------------------------


def test_parses_all_three_alignment_widths():
    """%3d pads to width 3, so 1/2/3-digit values arrive with 2/1/0 spaces."""
    assert parse_progress_line(PROGRESS_LINE_ONE_DIGIT) == (5, "Slicing model")
    assert parse_progress_line(PROGRESS_LINE_TWO_DIGIT) == (
        29,
        "Generating support tree",
    )
    assert parse_progress_line(PROGRESS_LINE_THREE_DIGIT) == (100, "Slicing done")


def test_leading_whitespace_does_not_alter_result():
    unpadded = parse_progress_line("29% => Generating support tree")
    assert unpadded == parse_progress_line(PROGRESS_LINE_TWO_DIGIT)


# --- 2.3 line-ending normalization ----------------------------------------


@pytest.mark.parametrize("ending", ["", "\n", "\r\n", "\r"])
def test_line_endings_produce_identical_results(ending):
    assert parse_progress_line(PROGRESS_LINE_TWO_DIGIT + ending) == (
        29,
        "Generating support tree",
    )


def test_trailing_period_label_is_preserved_verbatim():
    """Normalization belongs to the stage mapper (Section 3), not the parser."""
    assert parse_progress_line(PROGRESS_LINE_TRAILING_PERIOD) == (
        26,
        "Drilling holes into model.",
    )


# --- 2.4 non-progress lines -----------------------------------------------


@pytest.mark.parametrize("line", NOISE_LINES)
def test_noise_lines_return_none(line):
    assert parse_progress_line(line) is None


@pytest.mark.parametrize("line", ["   ", "\n", "=> Slicing model", " 29% Slicing model"])
def test_malformed_lines_return_none(line):
    assert parse_progress_line(line) is None


@pytest.mark.parametrize("line", [" 29% => ", " 29% =>", " 29% =>    "])
def test_empty_stage_label_returns_none(line):
    """A progress event without a stage label is not a usable event."""
    assert parse_progress_line(line) is None


def test_noise_never_raises():
    """A malformed line must never interrupt slicing."""
    for line in NOISE_LINES:
        parse_progress_line(line)


def test_sample_transcript_yields_only_real_events():
    """The full transcript must surface the 9 progress lines and nothing else."""
    parsed = [
        result
        for result in (parse_progress_line(line) for line in SAMPLE_STDOUT_LINES)
        if result is not None
    ]
    assert [percent for percent, _ in parsed] == [0, 5, 26, 29, 62, 70, 73, 88, 100]
    assert parsed[0] == (0, "Assembling model from parts")
    assert parsed[-1] == (100, "Slicing done")


# --- 2.5 percentage boundaries --------------------------------------------


@pytest.mark.parametrize("percent", [0, 1, 50, 99, 100])
def test_in_range_percentages_parse(percent):
    assert parse_progress_line(f"{percent:3d}% => Rasterizing layers") == (
        percent,
        "Rasterizing layers",
    )


@pytest.mark.parametrize("line", ["101% => Slicing model", "999% => Slicing model"])
def test_out_of_range_percentage_returns_none(line):
    """Above 100 means our format assumption is wrong — reject, don't clamp."""
    assert parse_progress_line(line) is None


@pytest.mark.parametrize(
    "line",
    [
        "1000% => Slicing model",  # more than three digits
        "-1% => Slicing model",
        "2.5% => Slicing model",
    ],
)
def test_non_three_digit_integer_returns_none(line):
    assert parse_progress_line(line) is None


# --- 4.1 archive-done signal ----------------------------------------------


def test_archive_done_line_yields_archived_stage():
    assert parse_progress_event(ARCHIVE_DONE_LINE) == (100, STAGE_ARCHIVED)


def test_archive_marker_carries_its_trailing_space():
    """The C++ literal ends with a space before the path is appended."""
    assert ARCHIVE_DONE_MARKER.endswith(" ")
    assert ARCHIVE_DONE_LINE.startswith(ARCHIVE_DONE_MARKER)


@pytest.mark.parametrize("ending", ["", "\n", "\r\n"])
def test_archive_marker_tolerates_line_endings(ending):
    assert parse_progress_event(ARCHIVE_DONE_LINE + ending) == (100, STAGE_ARCHIVED)


def test_archive_marker_with_empty_path_still_recognized():
    assert parse_progress_event(ARCHIVE_DONE_MARKER) == (100, STAGE_ARCHIVED)


def test_other_export_lines_are_not_the_archive_signal():
    """"Slicing result exported to ..." looks similar but is NOT the marker."""
    assert (
        parse_progress_event(
            "Slicing result exported to C:\\jobs\\a1b2c3d4\\output\\model.sl1"
        )
        is None
    )


@pytest.mark.parametrize("line", NOISE_LINES)
def test_noise_lines_yield_no_event(line):
    assert parse_progress_event(line) is None


# --- 4.1 progress lines through the event entry point ---------------------


def test_progress_line_yields_mapped_stage():
    assert parse_progress_event(" 73% => Rasterizing layers") == (
        73,
        STAGE_RASTERIZING,
    )


def test_unknown_label_still_yields_an_event_with_degraded_stage():
    """A drifted label must not cost us the percentage."""
    assert parse_progress_event(" 44% => Polishing the flux capacitor") == (
        44,
        STAGE_SLICING,
    )


# --- 4.3 FINALIZING vs ARCHIVED are distinguished by stage alone ----------


def test_engine_done_line_yields_finalizing():
    assert parse_progress_event(PROGRESS_LINE_THREE_DIGIT) == (100, STAGE_FINALIZING)


def test_finalizing_and_archived_share_the_percentage():
    finalizing = parse_progress_event(PROGRESS_LINE_THREE_DIGIT)
    archived = parse_progress_event(ARCHIVE_DONE_LINE)
    assert finalizing[0] == archived[0] == 100


def test_finalizing_and_archived_differ_only_by_stage():
    finalizing = parse_progress_event(PROGRESS_LINE_THREE_DIGIT)
    archived = parse_progress_event(ARCHIVE_DONE_LINE)
    assert finalizing[1] != archived[1]
    assert finalizing[1] == STAGE_FINALIZING
    assert archived[1] == STAGE_ARCHIVED


def test_sample_transcript_ends_finalizing_then_archived():
    """The silent archive tail sits between these two events — that gap is
    exactly what the frontend needs to be able to see."""
    events = [
        event
        for event in (parse_progress_event(line) for line in SAMPLE_STDOUT_LINES)
        if event is not None
    ]
    assert [percent for percent, _ in events] == [0, 5, 26, 29, 62, 70, 73, 88, 100, 100]
    assert events[-2] == (100, STAGE_FINALIZING)
    assert events[-1] == (100, STAGE_ARCHIVED)
