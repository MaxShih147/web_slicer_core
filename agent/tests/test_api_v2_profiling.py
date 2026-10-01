"""Server-Timing on api_v2 responses (add-slice-pipeline-profiling, task 1.5).

With SLICE_PROFILING=1:
  - upload / upload-support / execute / preview.zip / gcode carry
    ``Server-Timing: srv-handle;dur=<ms>``;
  - GET /slices/{id} carries the engine breakdown + since-complete, but ONLY
    when the job is COMPLETED.
Without the flag no response carries the header. Response bodies are
identical either way — timing rides on the header only.
"""
import re
import time

import pytest
import trimesh
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent import api_v2, jobs, profiling
from agent.api_v2 import router
from agent.errors import APIError
from agent.models import JobStatus

SRV_HANDLE = re.compile(r"^srv-handle;dur=\d+\.\d$")


@pytest.fixture(autouse=True)
def _reset_profiling():
    profiling.reset_for_tests()
    yield
    profiling.reset_for_tests()


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "JOBS_DIR", tmp_path)

    async def no_slicing(*args, **kwargs):
        return None

    # execute schedules run_slicing as a background task; never start the engine.
    monkeypatch.setattr(api_v2, "run_slicing", no_slicing)
    app = FastAPI()
    app.include_router(router)
    # Mirror main.py so APIError becomes an error response, not a raised exception.
    app.add_exception_handler(APIError, lambda request, exc: exc.to_response())
    return TestClient(app)


@pytest.fixture
def flag(monkeypatch):
    def set_flag(on: bool):
        if on:
            monkeypatch.setenv("SLICE_PROFILING", "1")
        else:
            monkeypatch.delenv("SLICE_PROFILING", raising=False)

    return set_flag


def _stl() -> bytes:
    return trimesh.creation.box(extents=[2, 2, 2]).export(file_type="stl")


def _new_job(client) -> str:
    resp = client.post("/api/v2/slices", json={})
    assert resp.status_code == 200
    return resp.json()["data"]["jobId"]


def _upload(client, job_id, path="upload"):
    return client.post(
        f"/api/v2/slices/{job_id}/{path}",
        files={"file": ("model.stl", _stl(), "application/octet-stream")},
    )


def _completed_job(job_id="job-done") -> str:
    job_dir = jobs.create_job(job_id)
    (job_dir / "output" / "model.sl1").write_bytes(b"")
    (job_dir / "output" / "model_preview.zip").write_bytes(b"PK\x05\x06" + b"\0" * 18)
    jobs.write_job_status(job_id, JobStatus.COMPLETED, layer_count=10)
    return job_id


def _record_engine_profile(job_id, completed_ago_s=0.2):
    profiling.mark(job_id, "queue-enter", 1.0)
    profiling.mark(job_id, "queue-acquired", 1.01)
    profiling.measure(job_id, "queue-wait", "queue-enter", "queue-acquired")
    profiling.add_span(job_id, "engine-startup", 500.0)
    profiling.record_stage(job_id, "STAGE_SLICING", 2.0)
    profiling.record_stage(job_id, "STAGE_RASTERIZING", 3.0)
    profiling.record_stage(job_id, "STAGE_FINALIZING", 4.0)
    profiling.record_stage(job_id, "STAGE_ARCHIVED", 5.0)
    profiling.add_span(job_id, "archive-tail", 1000.0)
    profiling.add_span(job_id, "post-process", 80.0)
    profiling.mark(job_id, "completed", time.perf_counter() - completed_ago_s)


def _entries(header: str) -> dict:
    out = {}
    for part in header.split(", "):
        name, dur = part.split(";dur=")
        out[name] = float(dur)
    return out


# --- srv-handle ---------------------------------------------------------------


@pytest.mark.parametrize("path", ["upload", "upload-support"])
def test_upload_carries_srv_handle(client, flag, path):
    flag(True)
    resp = _upload(client, _new_job(client), path)
    assert resp.status_code == 200
    assert SRV_HANDLE.match(resp.headers["server-timing"])


def test_execute_carries_srv_handle(client, flag):
    flag(True)
    job_id = _new_job(client)
    _upload(client, job_id)
    resp = client.post(f"/api/v2/slices/{job_id}/execute")
    assert resp.status_code == 200
    assert SRV_HANDLE.match(resp.headers["server-timing"])


@pytest.mark.parametrize("path", ["preview.zip", "gcode"])
def test_completed_job_reads_carry_srv_handle(client, flag, path):
    flag(True)
    job_id = _completed_job()
    resp = client.get(f"/api/v2/slices/{job_id}/{path}")
    assert resp.status_code == 200
    assert SRV_HANDLE.match(resp.headers["server-timing"])


def test_flag_off_no_header_and_same_bodies(client, flag):
    bodies = {}
    for on in (False, True):
        flag(on)
        profiling.reset_for_tests()
        job_id = _new_job(client)
        up = _upload(client, job_id)
        sup = _upload(client, job_id, "upload-support")
        ex = client.post(f"/api/v2/slices/{job_id}/execute")
        done = _completed_job(f"job-done-{on}")
        gc = client.get(f"/api/v2/slices/{done}/gcode")
        pz = client.get(f"/api/v2/slices/{done}/preview.zip")
        responses = [up, sup, ex, gc, pz]
        if not on:
            for r in responses:
                assert "server-timing" not in r.headers
        bodies[on] = [up.json(), sup.json(), ex.json(), gc.json(), pz.content]

    assert bodies[True] == bodies[False]


def test_error_responses_carry_no_header(client, flag):
    flag(True)
    resp = client.post(
        f"/api/v2/slices/{_new_job(client)}/upload",
        files={"file": ("model.txt", b"x", "text/plain")},
    )
    assert resp.status_code != 200
    assert "server-timing" not in resp.headers


# --- GET /slices/{id} ---------------------------------------------------------


def test_completed_status_carries_engine_breakdown(client, flag):
    flag(True)
    job_id = _completed_job()
    _record_engine_profile(job_id, completed_ago_s=0.2)

    resp = client.get(f"/api/v2/slices/{job_id}")

    entries = _entries(resp.headers["server-timing"])
    for name in (
        "queue-wait",
        "engine-startup",
        "stage-STAGE_SLICING",
        "stage-STAGE_RASTERIZING",
        "stage-STAGE_FINALIZING",
        "archive-tail",
        "post-process",
        "since-complete",
    ):
        assert name in entries, name
    assert entries["stage-STAGE_SLICING"] == 1000.0
    assert entries["since-complete"] >= 200.0
    # The last stage has no successor, so it carries no duration.
    assert "stage-STAGE_ARCHIVED" not in entries


def test_processing_status_has_no_header(client, flag):
    flag(True)
    job_id = "job-running"
    jobs.create_job(job_id)
    jobs.write_job_status(job_id, JobStatus.PROCESSING)
    _record_engine_profile(job_id)

    resp = client.get(f"/api/v2/slices/{job_id}")

    assert resp.status_code == 200
    assert "server-timing" not in resp.headers


def test_failed_status_has_no_header(client, flag):
    flag(True)
    job_id = "job-failed"
    jobs.create_job(job_id)
    jobs.write_job_status(job_id, JobStatus.FAILED, error="boom")
    _record_engine_profile(job_id)

    resp = client.get(f"/api/v2/slices/{job_id}")

    assert "server-timing" not in resp.headers


def test_completed_without_profile_record_has_no_header(client, flag):
    """e.g. the job finished before the agent restarted with the flag on."""
    flag(True)
    resp = client.get(f"/api/v2/slices/{_completed_job()}")
    assert resp.status_code == 200
    assert "server-timing" not in resp.headers


def test_completed_without_completed_mark_omits_since_complete(client, flag):
    flag(True)
    job_id = _completed_job()
    profiling.add_span(job_id, "queue-wait", 3.0)

    resp = client.get(f"/api/v2/slices/{job_id}")

    assert _entries(resp.headers["server-timing"]) == {"queue-wait": 3.0}


def test_completed_status_body_is_identical_with_flag_off(client, flag):
    flag(True)
    job_id = _completed_job()
    _record_engine_profile(job_id)

    on = client.get(f"/api/v2/slices/{job_id}")
    flag(False)
    off = client.get(f"/api/v2/slices/{job_id}")

    assert "server-timing" in on.headers
    assert "server-timing" not in off.headers
    assert on.json() == off.json()
