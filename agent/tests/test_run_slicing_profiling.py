"""run_slicing profiling side channel (add-slice-pipeline-profiling, task 1.3).

run_slicing feeds engine stage switches into agent.profiling and adds three
boundary spans (engine-startup, archive-tail, post-process) plus the moment
COMPLETED is written. With the flag off nothing is recorded, and a profiling
failure must never change the slice outcome.

Reuses the stubbed-engine fixture from test_slice_progress_streams.py.
"""

import asyncio
import json

import pytest

from agent import jobs, profiling
from agent.models import JobStatus

from .test_slice_progress_parse import SAMPLE_STDOUT
from .test_slice_progress_streams import JOB, slicing_env  # noqa: F401 (fixture)


@pytest.fixture(autouse=True)
def _reset_profiling():
    profiling.reset_for_tests()
    yield
    profiling.reset_for_tests()


@pytest.fixture
def successful_slice(slicing_env):  # noqa: F811
    job_dir = slicing_env["job_dir"]
    (job_dir / "output" / "model.sl1").write_bytes(b"")
    slicing_env["monkeypatch"].setattr(
        jobs, "parse_sl1_metadata", lambda path: (120, 3600.0, 12.5)
    )
    slicing_env["install"](SAMPLE_STDOUT.encode(), b"", 0)
    return slicing_env


def _status(job_dir):
    return json.loads((job_dir / "status.json").read_text())


def _expected_stage_sequence():
    seq = []
    for line in SAMPLE_STDOUT.splitlines():
        event = jobs.parse_progress_event(line)
        if event and (not seq or seq[-1] != event[1]):
            seq.append(event[1])
    return seq


# --- flag on ------------------------------------------------------------------


def test_success_records_stages_spans_and_completed(successful_slice, monkeypatch):
    monkeypatch.setenv("SLICE_PROFILING", "1")

    asyncio.run(jobs.run_slicing(JOB))

    snap = profiling.snapshot(JOB)
    assert [s for s, _t in snap["stages"]] == _expected_stage_sequence()
    for name in ("engine-startup", "archive-tail", "post-process"):
        assert snap["spans"][name] >= 0.0, name
    assert "completed" in snap["marks"]
    assert snap["marks"]["completed"] >= snap["marks"]["engine-exited"]
    assert profiling.stage_durations(JOB)


def test_archive_tail_spans_finalizing_to_archived(successful_slice, monkeypatch):
    monkeypatch.setenv("SLICE_PROFILING", "1")

    asyncio.run(jobs.run_slicing(JOB))

    snap = profiling.snapshot(JOB)
    stage_t = {s: t for s, t in reversed(snap["stages"])}  # first occurrence wins
    expected = (stage_t["STAGE_ARCHIVED"] - stage_t["STAGE_FINALIZING"]) * 1000.0
    assert snap["spans"]["archive-tail"] == pytest.approx(expected)


def test_engine_startup_ends_at_first_stage(successful_slice, monkeypatch):
    monkeypatch.setenv("SLICE_PROFILING", "1")

    asyncio.run(jobs.run_slicing(JOB))

    snap = profiling.snapshot(JOB)
    first_t = snap["stages"][0][1]
    expected = (first_t - snap["marks"]["engine-spawn"]) * 1000.0
    assert snap["spans"]["engine-startup"] == pytest.approx(expected)


def test_success_writes_profile_json(successful_slice, monkeypatch):
    monkeypatch.setenv("SLICE_PROFILING", "1")

    asyncio.run(jobs.run_slicing(JOB))

    data = json.loads((successful_slice["job_dir"] / "profile.json").read_text())
    assert data["job_id"] == JOB
    assert "post-process" in data["spans"]


def test_status_is_unchanged_by_profiling(successful_slice, monkeypatch):
    monkeypatch.setenv("SLICE_PROFILING", "1")

    asyncio.run(jobs.run_slicing(JOB))

    status = _status(successful_slice["job_dir"])
    assert status["status"] == JobStatus.COMPLETED.value
    assert status["layer_count"] == 120
    assert status["estimated_print_time"] == 3600.0
    assert status["resin_volume_ml"] == 12.5
    assert jobs.get_job_progress(JOB) is None


def test_failure_path_has_no_completed_or_post_process(slicing_env, monkeypatch):  # noqa: F811
    monkeypatch.setenv("SLICE_PROFILING", "1")
    slicing_env["install"](SAMPLE_STDOUT.encode(), b"boom", 1)

    asyncio.run(jobs.run_slicing(JOB))

    snap = profiling.snapshot(JOB)
    assert "completed" not in snap["marks"]
    assert "post-process" not in snap["spans"]
    assert _status(slicing_env["job_dir"])["status"] == JobStatus.FAILED.value
    assert not (slicing_env["job_dir"] / "profile.json").exists()


def test_profiling_errors_never_fail_the_slice(successful_slice, monkeypatch):
    monkeypatch.setenv("SLICE_PROFILING", "1")

    def boom(*args, **kwargs):
        raise RuntimeError("profiling bug")

    for name in ("mark", "measure", "record_stage", "write_profile_json"):
        monkeypatch.setattr(profiling, name, boom)

    asyncio.run(jobs.run_slicing(JOB))

    assert _status(successful_slice["job_dir"])["status"] == JobStatus.COMPLETED.value


# --- flag off -----------------------------------------------------------------


def test_flag_off_records_nothing_and_passes_no_hook(successful_slice, monkeypatch):
    monkeypatch.delenv("SLICE_PROFILING", raising=False)
    hooks = []
    real_drain = jobs._drain_stdout_progress

    def spy(stream, job_id, **kwargs):
        hooks.append(kwargs.get("on_stage"))
        return real_drain(stream, job_id, **kwargs)

    monkeypatch.setattr(jobs, "_drain_stdout_progress", spy)

    asyncio.run(jobs.run_slicing(JOB))

    assert hooks == [None]
    monkeypatch.setenv("SLICE_PROFILING", "1")  # peek at the raw store
    assert profiling.snapshot(JOB) is None
    assert not (successful_slice["job_dir"] / "profile.json").exists()
    assert _status(successful_slice["job_dir"])["status"] == JobStatus.COMPLETED.value
