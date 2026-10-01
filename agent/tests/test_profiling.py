"""Tests for agent.profiling (add-slice-pipeline-profiling, task 1.1)."""
from __future__ import annotations

import json
import re

import pytest

from agent import profiling


@pytest.fixture(autouse=True)
def _reset_profiling():
    profiling.reset_for_tests()
    yield
    profiling.reset_for_tests()


@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setenv("SLICE_PROFILING", "1")


@pytest.fixture
def disabled(monkeypatch):
    monkeypatch.delenv("SLICE_PROFILING", raising=False)


# --- flag -------------------------------------------------------------------


@pytest.mark.parametrize("value", [None, "", "0", "true", "yes"])
def test_is_enabled_only_for_exact_one(monkeypatch, value):
    if value is None:
        monkeypatch.delenv("SLICE_PROFILING", raising=False)
    else:
        monkeypatch.setenv("SLICE_PROFILING", value)
    assert profiling.is_enabled() is False


def test_is_enabled_when_one(enabled):
    assert profiling.is_enabled() is True


def test_disabled_records_nothing_and_writes_nothing(disabled, tmp_path):
    profiling.mark("job-a", "queue-enter")
    profiling.mark("job-a", "queue-acquired")
    profiling.measure("job-a", "queue-wait", "queue-enter", "queue-acquired")
    profiling.add_span("job-a", "post-process", 12.0)
    profiling.record_stage("job-a", "STAGE_SLICING", 1.0)

    assert profiling.snapshot("job-a") is None
    assert profiling.server_timing("job-a") == ""
    assert profiling.write_profile_json("job-a", tmp_path) is None
    assert list(tmp_path.iterdir()) == []


# --- marks / spans ----------------------------------------------------------


def test_mark_uses_perf_counter(enabled, monkeypatch):
    monkeypatch.setattr(profiling.time, "perf_counter", lambda: 42.5)
    profiling.mark("job-a", "queue-enter")
    assert profiling.snapshot("job-a")["marks"]["queue-enter"] == 42.5


def test_measure_turns_two_marks_into_ms_span(enabled):
    profiling.mark("job-a", "queue-enter", 10.0)
    profiling.mark("job-a", "queue-acquired", 10.0031)
    profiling.measure("job-a", "queue-wait", "queue-enter", "queue-acquired")
    assert profiling.snapshot("job-a")["spans"]["queue-wait"] == pytest.approx(3.1)


def test_measure_with_missing_mark_is_skipped(enabled):
    profiling.mark("job-a", "queue-enter", 10.0)
    profiling.measure("job-a", "queue-wait", "queue-enter", "queue-acquired")
    assert "queue-wait" not in profiling.snapshot("job-a")["spans"]


def test_add_span_accumulates_same_name(enabled):
    profiling.add_span("job-a", "srv-handle", 5.0)
    profiling.add_span("job-a", "srv-handle", 2.5)
    assert profiling.snapshot("job-a")["spans"]["srv-handle"] == pytest.approx(7.5)


def test_records_are_keyed_by_job_id(enabled):
    profiling.add_span("job-a", "post-process", 1.0)
    profiling.add_span("job-b", "post-process", 9.0)
    assert profiling.snapshot("job-a")["spans"] == {"post-process": 1.0}
    assert profiling.snapshot("job-b")["spans"] == {"post-process": 9.0}


def test_clear_drops_only_that_job(enabled):
    profiling.add_span("job-a", "post-process", 1.0)
    profiling.add_span("job-b", "post-process", 2.0)
    profiling.clear("job-a")
    assert profiling.snapshot("job-a") is None
    assert profiling.snapshot("job-b") is not None


# --- stage sequence ---------------------------------------------------------


def test_record_stage_only_appends_on_change(enabled):
    profiling.record_stage("job-a", "STAGE_SLICING", 1.0)
    profiling.record_stage("job-a", "STAGE_SLICING", 1.5)
    profiling.record_stage("job-a", "STAGE_PAD", 2.0)
    assert profiling.snapshot("job-a")["stages"] == [
        ["STAGE_SLICING", 1.0],
        ["STAGE_PAD", 2.0],
    ]


def test_same_name_stage_durations_accumulate(enabled):
    profiling.record_stage("job-a", "STAGE_SLICING", 1.0)
    profiling.record_stage("job-a", "STAGE_PAD", 1.2)
    profiling.record_stage("job-a", "STAGE_SLICING", 1.5)
    profiling.record_stage("job-a", "STAGE_ARCHIVED", 2.0)
    durations = profiling.stage_durations("job-a")
    # 200 ms + 500 ms under the same name.
    assert durations["STAGE_SLICING"] == pytest.approx(700.0)
    assert durations["STAGE_PAD"] == pytest.approx(300.0)


def test_last_stage_without_successor_has_no_duration(enabled):
    profiling.record_stage("job-a", "STAGE_FINALIZING", 1.0)
    profiling.record_stage("job-a", "STAGE_ARCHIVED", 2.0)
    assert "STAGE_ARCHIVED" not in profiling.stage_durations("job-a")


def test_absent_stages_are_not_zero_filled(enabled):
    profiling.record_stage("job-a", "STAGE_ASSEMBLING", 1.0)
    profiling.record_stage("job-a", "STAGE_SLICING", 1.1)
    profiling.record_stage("job-a", "STAGE_ARCHIVED", 1.2)
    durations = profiling.stage_durations("job-a")
    assert set(durations) == {"STAGE_ASSEMBLING", "STAGE_SLICING"}
    assert "STAGE_HOLLOWING" not in profiling.server_timing("job-a")


# --- Server-Timing ----------------------------------------------------------

_ENTRY = re.compile(r"^[a-z0-9_-]+(?:-STAGE_[A-Z_]+)?;dur=\d+(?:\.\d+)?$")


def test_server_timing_format(enabled):
    profiling.mark("job-a", "queue-enter", 10.0)
    profiling.mark("job-a", "queue-acquired", 10.0031)
    profiling.measure("job-a", "queue-wait", "queue-enter", "queue-acquired")
    profiling.record_stage("job-a", "STAGE_ASSEMBLING", 11.0)
    profiling.record_stage("job-a", "STAGE_SLICING", 11.0402)
    profiling.record_stage("job-a", "STAGE_ARCHIVED", 12.0)

    header = profiling.server_timing("job-a", extra={"since-complete": 231.04})
    entries = header.split(", ")
    for entry in entries:
        assert _ENTRY.match(entry), entry
    assert entries == [
        "queue-wait;dur=3.1",
        "stage-STAGE_ASSEMBLING;dur=40.2",
        "stage-STAGE_SLICING;dur=959.8",
        "since-complete;dur=231.0",
    ]


def test_server_timing_unknown_job_is_empty(enabled):
    assert profiling.server_timing("nope") == ""


def test_server_timing_extra_only(enabled):
    assert profiling.server_timing("nope", extra={"srv-handle": 4}) == "srv-handle;dur=4.0"


# --- profile.json -----------------------------------------------------------


def test_write_profile_json(enabled, tmp_path):
    profiling.mark("job-a", "completed", 5.0)
    profiling.add_span("job-a", "post-process", 88.5)
    profiling.record_stage("job-a", "STAGE_SLICING", 1.0)
    profiling.record_stage("job-a", "STAGE_ARCHIVED", 1.25)

    path = profiling.write_profile_json("job-a", tmp_path)

    assert path == tmp_path / "profile.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["job_id"] == "job-a"
    assert data["marks"] == {"completed": 5.0}
    assert data["spans"] == {"post-process": 88.5}
    assert data["stages"] == [["STAGE_SLICING", 1.0], ["STAGE_ARCHIVED", 1.25]]
    assert data["stage_durations_ms"] == {"STAGE_SLICING": 250.0}
    assert [p.name for p in tmp_path.iterdir()] == ["profile.json"]


def test_write_profile_json_overwrites(enabled, tmp_path):
    profiling.add_span("job-a", "post-process", 1.0)
    profiling.write_profile_json("job-a", tmp_path)
    profiling.add_span("job-a", "prz-encode", 2.0)
    profiling.write_profile_json("job-a", tmp_path)
    data = json.loads((tmp_path / "profile.json").read_text(encoding="utf-8"))
    assert data["spans"] == {"post-process": 1.0, "prz-encode": 2.0}


def test_write_profile_json_unknown_job_writes_nothing(enabled, tmp_path):
    assert profiling.write_profile_json("nope", tmp_path) is None
    assert list(tmp_path.iterdir()) == []


def test_write_profile_json_never_raises(enabled, tmp_path):
    profiling.add_span("job-a", "post-process", 1.0)
    missing = tmp_path / "does-not-exist"
    assert profiling.write_profile_json("job-a", missing) is None
