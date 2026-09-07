"""
Stage-label → STAGE_* enum mapping tests — Task 1.2 / Section 3
(add-slicing-progress).

The engine emits English natural-language stage labels; the backend maps them
to stable identifiers so the frontend never depends on engine wording. The
authoritative enum set lives in
``openspec/changes/add-slicing-progress/specs/slice-progress-reporting/spec.md``.

Section 3 fills this in:
  - 3.1 enum constants + label table (10 engine labels; STAGE_ARCHIVED comes
        from the archive-done marker, not from a label)
  - 3.2 normalization (case, trailing punctuation, whitespace)
  - 3.3 exact match after normalization
  - 3.4 shared-prefix labels must NOT collide (the guard against substring
        matching)
  - 3.5 unknown label degrades to STAGE_SLICING and logs a warning

The production label table (``ENGINE_STAGE_LABEL_MAP``) is pinned against the
fork C++ source by ``test_slice_progress_string_contract.py`` (Task 3.6).
"""

import logging

import pytest

from agent.jobs import (
    ENGINE_STAGE_LABEL_MAP,
    STAGE_ARCHIVED,
    STAGE_ASSEMBLING,
    STAGE_DRILLING,
    STAGE_FINALIZING,
    STAGE_HOLLOWING,
    STAGE_MERGING,
    STAGE_PAD,
    STAGE_RASTERIZING,
    STAGE_SLICING,
    STAGE_SLICING_SUPPORTS,
    STAGE_SUPPORT_POINTS,
    STAGE_SUPPORT_TREE,
    map_stage_label,
    normalize_stage_label,
)

# The full authoritative enum set from the spec: 11 come from engine labels,
# STAGE_ARCHIVED comes from the archive-done marker (Section 4).
ALL_STAGES = (
    STAGE_ASSEMBLING,
    STAGE_HOLLOWING,
    STAGE_DRILLING,
    STAGE_SLICING,
    STAGE_SUPPORT_POINTS,
    STAGE_SUPPORT_TREE,
    STAGE_PAD,
    STAGE_SLICING_SUPPORTS,
    STAGE_MERGING,
    STAGE_RASTERIZING,
    STAGE_FINALIZING,
    STAGE_ARCHIVED,
)


# --- 3.1 enum set + label table -------------------------------------------


def test_spec_defines_twelve_stage_identifiers():
    assert len(ALL_STAGES) == 12
    assert len(set(ALL_STAGES)) == 12, "stage identifiers must be unique"


def test_label_table_covers_eleven_engine_labels():
    """8 object steps + 2 print steps + the terminal "Slicing done"."""
    assert len(ENGINE_STAGE_LABEL_MAP) == 11


def test_archive_stage_is_not_produced_by_any_label():
    """STAGE_ARCHIVED comes from the marker line, never from a stage label."""
    assert STAGE_ARCHIVED not in ENGINE_STAGE_LABEL_MAP.values()


def test_every_label_maps_to_a_known_identifier():
    assert set(ENGINE_STAGE_LABEL_MAP.values()) <= set(ALL_STAGES)


def test_stage_identifiers_are_self_naming():
    """Each constant's value equals its name — keeps the wire format greppable."""
    for stage in ALL_STAGES:
        assert stage == stage.upper()
        assert stage.startswith("STAGE_")


# --- 3.2 normalization ----------------------------------------------------


def test_trailing_period_normalizes_away():
    assert normalize_stage_label("Drilling holes into model.") == normalize_stage_label(
        "Drilling holes into model"
    )


def test_case_is_normalized():
    assert normalize_stage_label("RASTERIZING LAYERS") == normalize_stage_label(
        "Rasterizing layers"
    )


def test_repeated_whitespace_is_collapsed():
    assert normalize_stage_label("Generating   support\ttree") == normalize_stage_label(
        "Generating support tree"
    )


def test_surrounding_whitespace_is_stripped():
    assert normalize_stage_label("  Hollowing model  ") == normalize_stage_label(
        "Hollowing model"
    )


def test_normalization_does_not_collapse_distinct_labels():
    """Normalization must not merge two labels into one key."""
    keys = {normalize_stage_label(label) for label in ENGINE_STAGE_LABEL_MAP}
    assert len(keys) == len(ENGINE_STAGE_LABEL_MAP)


# --- 3.3 exact match after normalization ----------------------------------


@pytest.mark.parametrize(
    "label,expected", sorted(ENGINE_STAGE_LABEL_MAP.items())
)
def test_every_known_label_maps_correctly(label, expected):
    assert map_stage_label(label) == expected


@pytest.mark.parametrize("label", sorted(ENGINE_STAGE_LABEL_MAP))
def test_known_label_maps_regardless_of_case_and_padding(label):
    assert map_stage_label(f"  {label.upper()}  ") == ENGINE_STAGE_LABEL_MAP[label]


# --- 3.4 shared-prefix guard (substring matching is forbidden) -------------

SHARED_PREFIX_CASES = [
    ("Slicing model", STAGE_SLICING),
    ("Slicing supports", STAGE_SLICING_SUPPORTS),
    ("Slicing done", STAGE_FINALIZING),
]


@pytest.mark.parametrize("label,expected", SHARED_PREFIX_CASES)
def test_shared_prefix_labels_map_to_their_own_identifier(label, expected):
    assert map_stage_label(label) == expected


def test_shared_prefix_labels_are_pairwise_distinct():
    """Substring matching on "Slicing" would collapse these three into one."""
    mapped = [map_stage_label(label) for label, _ in SHARED_PREFIX_CASES]
    assert len(set(mapped)) == 3


def test_generating_prefix_labels_are_pairwise_distinct():
    """The other shared prefix: "Generating support points/tree" and "pad"."""
    mapped = [
        map_stage_label("Generating support points"),
        map_stage_label("Generating support tree"),
        map_stage_label("Generating pad"),
    ]
    assert len(set(mapped)) == 3


def test_prefix_of_a_known_label_is_not_accepted():
    """A bare prefix is not a known label — it must degrade, not match."""
    assert map_stage_label("Slicing") == STAGE_SLICING  # degraded, not "Slicing model"
    assert map_stage_label("Generating") == STAGE_SLICING


# --- 3.5 unknown label degrades and warns ---------------------------------


def test_unknown_label_degrades_to_slicing(caplog):
    with caplog.at_level(logging.WARNING, logger="agent.jobs"):
        assert map_stage_label("Polishing the flux capacitor") == STAGE_SLICING


def test_unknown_label_logs_warning_containing_original_label(caplog):
    with caplog.at_level(logging.WARNING, logger="agent.jobs"):
        map_stage_label("Polishing the flux capacitor")

    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert len(warnings) == 1
    assert "Polishing the flux capacitor" in warnings[0].getMessage()


def test_drifted_label_degrades_rather_than_raising(caplog):
    """A de-identification rewrite must not break slicing, only degrade."""
    with caplog.at_level(logging.WARNING, logger="agent.jobs"):
        assert map_stage_label("Rasterising layers") == STAGE_SLICING  # British spelling
        assert map_stage_label("") == STAGE_SLICING


def test_known_label_logs_no_warning(caplog):
    with caplog.at_level(logging.WARNING, logger="agent.jobs"):
        map_stage_label("Rasterizing layers")

    assert [r for r in caplog.records if r.levelno >= logging.WARNING] == []
