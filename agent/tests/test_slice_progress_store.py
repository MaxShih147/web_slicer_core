"""
In-memory progress store tests — Task 1.2 / Section 5
(add-slicing-progress).

Slice progress is held in a module-level dict in the agent process, never in
``status.json`` (design D3): that file is whole-file overwritten and its read
path has no partial-write tolerance, so sharing it would make status queries
fail mid-slice.

Section 5 fills this in:
  - 5.1 set / get / clear accessors
  - 5.2 monotonic guard on the percentage
  - 5.3 stage still advances at an unchanged percentage
  - 5.4 clear() is idempotent
  - 5.5 reset fixture so tests cannot leak state into each other

Lifecycle ordering (terminal status written to disk BEFORE the progress entry
is cleared) is covered in Section 6 alongside the streaming change.
"""

import pytest

from agent import jobs
from agent.jobs import (
    STAGE_ARCHIVED,
    STAGE_FINALIZING,
    STAGE_RASTERIZING,
    STAGE_SLICING,
    clear_job_progress,
    get_job_progress,
    set_job_progress,
)

JOB = "a1b2c3d4"
OTHER_JOB = "e5f6a7b8"


# --- 5.1 set / get / clear ------------------------------------------------


def test_set_then_get_round_trips():
    set_job_progress(JOB, 29, STAGE_SLICING)
    assert get_job_progress(JOB) == {"percent": 29, "stage": STAGE_SLICING}


def test_unknown_job_reads_back_none():
    assert get_job_progress("never-seen") is None


def test_clear_removes_the_entry():
    set_job_progress(JOB, 29, STAGE_SLICING)
    clear_job_progress(JOB)
    assert get_job_progress(JOB) is None


def test_jobs_are_isolated_from_each_other():
    set_job_progress(JOB, 29, STAGE_SLICING)
    set_job_progress(OTHER_JOB, 73, STAGE_RASTERIZING)

    assert get_job_progress(JOB)["percent"] == 29
    assert get_job_progress(OTHER_JOB)["percent"] == 73

    clear_job_progress(JOB)
    assert get_job_progress(OTHER_JOB) == {"percent": 73, "stage": STAGE_RASTERIZING}


def test_get_returns_a_copy():
    """Callers must not be able to mutate the store through the returned dict."""
    set_job_progress(JOB, 29, STAGE_SLICING)

    snapshot = get_job_progress(JOB)
    snapshot["percent"] = 999

    assert get_job_progress(JOB)["percent"] == 29


def test_progress_is_not_written_to_status_json(tmp_path, monkeypatch):
    """design D3: the store is memory-only — status.json must stay untouched."""
    monkeypatch.setattr(jobs, "JOBS_DIR", tmp_path)
    job_dir = tmp_path / JOB
    job_dir.mkdir(parents=True)

    status_file = jobs.get_job_status_file(JOB)
    status_file.write_text('{"status": "processing"}', encoding="utf-8")
    before = status_file.read_text(encoding="utf-8")

    set_job_progress(JOB, 29, STAGE_SLICING)
    set_job_progress(JOB, 73, STAGE_RASTERIZING)

    assert status_file.read_text(encoding="utf-8") == before


# --- 5.2 monotonic percentage --------------------------------------------


def test_lower_percentage_keeps_the_higher_value():
    set_job_progress(JOB, 73, STAGE_RASTERIZING)
    set_job_progress(JOB, 29, STAGE_SLICING)
    assert get_job_progress(JOB)["percent"] == 73


def test_percentage_never_decreases_across_a_descending_sequence():
    for percent in (10, 40, 35, 70, 12, 88, 0):
        set_job_progress(JOB, percent, STAGE_RASTERIZING)

    assert get_job_progress(JOB)["percent"] == 88


def test_ascending_sequence_advances_normally():
    seen = []
    for percent in (0, 5, 26, 29, 62, 70, 73, 88, 100):
        set_job_progress(JOB, percent, STAGE_RASTERIZING)
        seen.append(get_job_progress(JOB)["percent"])

    assert seen == [0, 5, 26, 29, 62, 70, 73, 88, 100]


def test_first_write_is_accepted_verbatim():
    """No previous value means nothing to clamp against."""
    set_job_progress(JOB, 42, STAGE_SLICING)
    assert get_job_progress(JOB)["percent"] == 42


def test_monotonic_guard_resets_after_clear():
    """A retried job must start from zero, not inherit the old ceiling."""
    set_job_progress(JOB, 88, STAGE_RASTERIZING)
    clear_job_progress(JOB)
    set_job_progress(JOB, 3, STAGE_SLICING)

    assert get_job_progress(JOB)["percent"] == 3


# --- 5.3 stage advances even at an unchanged percentage -------------------


def test_stage_updates_at_the_same_percentage():
    """The archive tail depends on this: FINALIZING → ARCHIVED, both at 100."""
    set_job_progress(JOB, 100, STAGE_FINALIZING)
    set_job_progress(JOB, 100, STAGE_ARCHIVED)

    assert get_job_progress(JOB) == {"percent": 100, "stage": STAGE_ARCHIVED}


def test_stage_updates_even_when_percentage_is_clamped():
    """The guard protects the number the user sees, not the stage label."""
    set_job_progress(JOB, 73, STAGE_RASTERIZING)
    set_job_progress(JOB, 29, STAGE_FINALIZING)

    assert get_job_progress(JOB) == {"percent": 73, "stage": STAGE_FINALIZING}


def test_stage_advances_alongside_a_rising_percentage():
    set_job_progress(JOB, 29, STAGE_SLICING)
    set_job_progress(JOB, 73, STAGE_RASTERIZING)

    assert get_job_progress(JOB) == {"percent": 73, "stage": STAGE_RASTERIZING}


# --- 5.4 clear is idempotent ---------------------------------------------


def test_clearing_an_unknown_job_does_not_raise():
    clear_job_progress("never-seen")


def test_clearing_twice_does_not_raise():
    set_job_progress(JOB, 29, STAGE_SLICING)
    clear_job_progress(JOB)
    clear_job_progress(JOB)

    assert get_job_progress(JOB) is None


def test_clear_before_any_progress_was_recorded():
    """run_slicing clears in a finally — the exception path may reach it
    before a single progress event has landed."""
    clear_job_progress(JOB)
    assert get_job_progress(JOB) is None


# --- 5.5 cross-test isolation --------------------------------------------


@pytest.mark.parametrize("run", [1, 2, 3])
def test_store_starts_empty_in_every_test(run):
    """Proves the autouse fixture in conftest.py resets between tests —
    each parametrized run writes, and each must still start clean."""
    assert jobs.job_progress == {}
    set_job_progress(JOB, 50 + run, STAGE_SLICING)


def test_store_is_empty_after_the_parametrized_writes():
    assert jobs.job_progress == {}
