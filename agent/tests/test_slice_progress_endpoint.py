"""
FastAPI contract tests for the progress field — Section 7
(add-slicing-progress).

Asserts the API surface of the in-memory progress store end to end through
GET /api/v2/slices/{job_id}:

  - a running job with recorded progress → percent + STAGE_* identifier
  - a running job with no progress yet → the field is OMITTED, not 0 / null
  - a not-yet-executed (pending) job → unaffected
  - every pre-existing field keeps its name, meaning and type

The omit-vs-placeholder rule is the load-bearing one: a polling client applies
its own monotonic guard, so a 0 placeholder would read as the progress jumping
backwards, and a null would force it to handle two spellings of "no progress".

Isolated the same way as test_support_status_endpoint.py: agent.jobs.JOBS_DIR is
monkeypatched to a tmp dir and status is written through the real
write_job_status, so the endpoint reads exactly what we persisted. The progress
store itself is reset around every test by the autouse fixture in conftest.py.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent import jobs
from agent.api_v2 import router
from agent.jobs import (
    STAGE_ARCHIVED,
    STAGE_FINALIZING,
    STAGE_RASTERIZING,
    STAGE_SLICING,
    set_job_progress,
)
from agent.models import JobStatus


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "JOBS_DIR", tmp_path)
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _make_job(job_id):
    (jobs.JOBS_DIR / job_id).mkdir(parents=True, exist_ok=True)
    return job_id


def _get(client, job_id):
    resp = client.get(f"/api/v2/slices/{job_id}")
    assert resp.status_code == 200
    return resp.json()


def _running_job(job_id="job-running"):
    job = _make_job(job_id)
    jobs.write_job_status(job, JobStatus.PROCESSING)
    return job


# --- 7.1 progress is exposed while the job runs ---------------------------


def test_running_job_exposes_progress(client):
    job = _running_job()
    set_job_progress(job, 29, STAGE_RASTERIZING)

    data = _get(client, job)["data"]

    assert data["progress"] == {"percent": 29, "stage": STAGE_RASTERIZING}


def test_progress_field_types(client):
    job = _running_job()
    set_job_progress(job, 73, STAGE_RASTERIZING)

    progress = _get(client, job)["data"]["progress"]

    assert isinstance(progress["percent"], int)
    assert isinstance(progress["stage"], str)
    assert progress["stage"].startswith("STAGE_")


@pytest.mark.parametrize("percent", [0, 1, 50, 99, 100])
def test_percent_range_is_carried_verbatim(client, percent):
    """The backend never scales or weights — that is the frontend's job."""
    job = _running_job()
    set_job_progress(job, percent, STAGE_SLICING)

    assert _get(client, job)["data"]["progress"]["percent"] == percent


def test_progress_reflects_the_latest_event(client):
    job = _running_job()
    set_job_progress(job, 29, STAGE_SLICING)
    set_job_progress(job, 73, STAGE_RASTERIZING)

    assert _get(client, job)["data"]["progress"] == {
        "percent": 73,
        "stage": STAGE_RASTERIZING,
    }


def test_finalizing_and_archived_are_distinguishable_over_the_wire(client):
    """Both sit at 100; only the stage tells the client the archive tail is
    still running — that distinction has to survive serialization."""
    job = _running_job()

    set_job_progress(job, 100, STAGE_FINALIZING)
    finalizing = _get(client, job)["data"]["progress"]

    set_job_progress(job, 100, STAGE_ARCHIVED)
    archived = _get(client, job)["data"]["progress"]

    assert finalizing["percent"] == archived["percent"] == 100
    assert finalizing["stage"] != archived["stage"]


def test_response_is_not_mutated_by_serialization(client):
    """The endpoint hands out a copy — polling must not drain the store."""
    job = _running_job()
    set_job_progress(job, 42, STAGE_SLICING)

    first = _get(client, job)["data"]["progress"]
    second = _get(client, job)["data"]["progress"]

    assert first == second == {"percent": 42, "stage": STAGE_SLICING}


# --- 7.2 omitted when unavailable (never 0 / null) ------------------------


def test_running_job_without_progress_omits_the_field(client):
    job = _running_job()

    data = _get(client, job)["data"]

    assert "progress" not in data


def test_completed_job_omits_the_field(client):
    """run_slicing clears the entry after writing the terminal status."""
    job = _make_job("job-done")
    jobs.write_job_status(job, JobStatus.COMPLETED, layer_count=120)

    data = _get(client, job)["data"]

    assert "progress" not in data


def test_cleared_progress_disappears_from_the_response(client):
    job = _running_job()
    set_job_progress(job, 88, STAGE_RASTERIZING)
    assert "progress" in _get(client, job)["data"]

    jobs.clear_job_progress(job)

    assert "progress" not in _get(client, job)["data"]


def test_progress_of_another_job_does_not_leak(client):
    job = _running_job("job-a")
    other = _running_job("job-b")
    set_job_progress(other, 55, STAGE_SLICING)

    assert "progress" not in _get(client, job)["data"]
    assert _get(client, other)["data"]["progress"]["percent"] == 55


# --- 7.3 pending jobs are unaffected --------------------------------------


def test_pending_job_omits_the_field(client, monkeypatch):
    from agent import api_v2

    monkeypatch.setitem(
        api_v2._pending_jobs,
        "job-pending",
        {"status": "pending", "config": {}, "models": []},
    )

    data = _get(client, "job-pending")["data"]

    assert "progress" not in data
    assert data["status"] == "pending"
    assert data["modelCount"] == 0


def test_pending_job_shape_is_unchanged(client, monkeypatch):
    from agent import api_v2

    monkeypatch.setitem(
        api_v2._pending_jobs,
        "job-pending",
        {"status": "pending", "config": {"a": 1}, "models": ["m.stl"]},
    )

    data = _get(client, "job-pending")["data"]

    assert set(data) == {"jobId", "status", "config", "modelCount"}


# --- 7.4 existing fields are untouched ------------------------------------

_LEGACY_KEYS = {
    "jobId",
    "status",
    "layerCount",
    "estimatedPrintTime",
    "resinVolumeMl",
    "error",
    "supportOutcome",
    "hasSupportMesh",
    "hasHollowMesh",
    "hasCutMesh",
    "hasOrthoResult",
}


def test_all_legacy_keys_still_present_without_progress(client):
    job = _make_job("job-legacy")
    jobs.write_job_status(
        job,
        JobStatus.COMPLETED,
        layer_count=120,
        estimated_print_time=3600.0,
        resin_volume_ml=12.5,
        has_support_mesh=True,
    )

    data = _get(client, job)["data"]

    assert _LEGACY_KEYS <= set(data)
    assert data["layerCount"] == 120
    assert data["estimatedPrintTime"] == 3600.0
    assert data["resinVolumeMl"] == 12.5
    assert data["hasSupportMesh"] is True


def test_all_legacy_keys_still_present_with_progress(client):
    """Adding progress must not displace or rename anything."""
    job = _running_job()
    set_job_progress(job, 29, STAGE_RASTERIZING)

    data = _get(client, job)["data"]

    assert _LEGACY_KEYS <= set(data)
    assert set(data) - _LEGACY_KEYS == {"progress"}


def test_progress_does_not_disturb_the_failure_path(client):
    """FAILED rides 200 with success:false and its own fixed shape."""
    job = _make_job("job-failed")
    jobs.write_job_status(
        job,
        JobStatus.FAILED,
        error="boom",
        error_code="SUPPORT_HEAD_TOO_WIDE",
    )
    set_job_progress(job, 29, STAGE_SLICING)

    body = _get(client, job)

    assert body["success"] is False
    assert body["code"] == "SUPPORT_HEAD_TOO_WIDE"
    assert set(body["data"]) == {"retryable", "traceId"}


def test_ortho_progress_still_rides_alongside(client):
    """The pre-existing orthoProgress field is a separate concern and must
    keep working when slice progress is present."""
    job = _make_job("job-ortho")
    jobs.write_job_status(job, JobStatus.PROCESSING)

    status_file = jobs.get_job_status_file(job)
    import json

    payload = json.loads(status_file.read_text())
    payload["ortho_progress"] = {"step": 3, "total_steps": 10, "description": "x"}
    status_file.write_text(json.dumps(payload))

    set_job_progress(job, 29, STAGE_SLICING)
    data = _get(client, job)["data"]

    assert data["orthoProgress"]["step"] == 3
    assert data["progress"]["percent"] == 29
