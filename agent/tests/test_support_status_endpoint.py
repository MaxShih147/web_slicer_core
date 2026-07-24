"""
FastAPI contract tests for the GET status endpoint — Task 6
(add-support-generation-error-codes).

Asserts the API surface of the classifier's verdicts, end to end through
read_job_status → GET /api/v2/slices/{job_id}:

  - a support-specific FAILED job → success:false + the specific error_code
  - a neutral SUPPORT_NOT_NEEDED job → success:true, COMPLETED, supportOutcome
    carried, hasSupportMesh:false (MUST NOT go down the error path)
  - a real support success → success:true, hasSupportMesh:true, no supportOutcome
  - a legacy FAILED job with no error_code → success:false + generic JOB_FAILED

Isolated by monkeypatching agent.jobs.JOBS_DIR to a tmp dir and writing status
via the real write_job_status (job_exists / read_job_status resolve JOBS_DIR at
call time, so the endpoint reads exactly what we persisted).
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent import jobs
from agent.api_v2 import router
from agent.models import JobStatus


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "JOBS_DIR", tmp_path)
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _make_job(job_id):
    """Create a job dir under the (patched) JOBS_DIR so job_exists() is True."""
    (jobs.JOBS_DIR / job_id).mkdir(parents=True, exist_ok=True)
    return job_id


def _get(client, job_id):
    resp = client.get(f"/api/v2/slices/{job_id}")
    assert resp.status_code == 200  # failures ride 200 with success:false
    return resp.json()


def test_support_specific_failure_returns_specific_code(client):
    """SUPPORT_HEAD_TOO_WIDE failure → success:false + the specific code."""
    job = _make_job("job-fail-pinhead")
    jobs.write_job_status(
        job,
        JobStatus.FAILED,
        error="pinhead too wide",
        error_code="SUPPORT_HEAD_TOO_WIDE",
    )

    body = _get(client, job)

    assert body["success"] is False
    assert body["code"] == "SUPPORT_HEAD_TOO_WIDE"
    assert body["data"]["retryable"] is False


def test_neutral_not_needed_is_success_with_outcome(client):
    """SUPPORT_NOT_NEEDED → success:true, COMPLETED, supportOutcome carried,
    hasSupportMesh:false. A neutral result must NOT surface as an error."""
    job = _make_job("job-not-needed")
    jobs.write_job_status(
        job,
        JobStatus.COMPLETED,
        support_outcome="SUPPORT_NOT_NEEDED",
        has_support_mesh=False,
    )

    body = _get(client, job)

    assert body["success"] is True
    assert body["data"]["status"] == JobStatus.COMPLETED.value
    assert body["data"]["supportOutcome"] == "SUPPORT_NOT_NEEDED"
    assert body["data"]["hasSupportMesh"] is False


def test_real_support_success_has_no_outcome(client):
    """A genuine support mesh → success:true, hasSupportMesh:true, no outcome."""
    job = _make_job("job-real-support")
    jobs.write_job_status(job, JobStatus.COMPLETED, has_support_mesh=True)

    body = _get(client, job)

    assert body["success"] is True
    assert body["data"]["hasSupportMesh"] is True
    assert body["data"]["supportOutcome"] is None


def test_legacy_failure_without_code_falls_back_to_job_failed(client):
    """A FAILED job whose error_code is absent (old build) → generic JOB_FAILED."""
    job = _make_job("job-legacy-fail")
    jobs.write_job_status(job, JobStatus.FAILED, error="something broke")

    body = _get(client, job)

    assert body["success"] is False
    assert body["code"] == "JOB_FAILED"