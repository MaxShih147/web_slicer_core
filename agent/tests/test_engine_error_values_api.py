"""
engine-error-code-table Task 8.2: the engine's fields and values are stored
with a failed job and come back from GET /api/v2/slices/{job_id}.

  - status.json round-trips error_fields / error_values; an old file without
    them reads as "none"
  - the failure response carries them in `data` (and omits them when there
    are none — test_slice_progress_endpoint pins that shape)
  - run_slicing and run_support_generation store what the engine reported
"""
import asyncio
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent import jobs, sla_operations
from agent.api_v2 import router
from agent.models import JobStatus

from .test_slice_progress_streams import _FakeProc

PAD_FIELDS = ["pad_wall_slope", "pad_wall_thickness", "pad_brim_size"]
PAD_VALUES = {"min_pad_wall_slope": 51.4, "pad_wall_slope": 50}
# What the engine prints for slope 50, thickness 2, brim 1.6
# (agent/tests/data/engine_outputs.json, scenario pad_config_invalid).
PAD_STDOUT = (
    b'PHZ_ERROR {"code":"PAD_CONFIG_INVALID","fields":["pad_wall_slope",'
    b'"pad_wall_thickness","pad_brim_size"],"values":{"min_pad_wall_slope":51.4,'
    b'"pad_wall_slope":50}}\n'
)
PAD_STDERR = b"Pad brim size is too small for the current configuration.\n"


@pytest.fixture
def job(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "JOBS_DIR", tmp_path)
    job_id = "values-job"
    (tmp_path / job_id / "input").mkdir(parents=True)
    (tmp_path / job_id / "output").mkdir()
    return job_id


@pytest.fixture
def client(job):
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


class TestStatusFile:
    def test_fields_and_values_round_trip(self, job):
        jobs.write_job_status(
            job, JobStatus.FAILED, error="pad", error_code="PAD_CONFIG_INVALID",
            error_fields=PAD_FIELDS, error_values=PAD_VALUES,
        )
        data = jobs.read_job_status(job)
        assert data["error_fields"] == PAD_FIELDS
        assert data["error_values"] == PAD_VALUES

    def test_an_old_status_file_reads_as_no_values(self, job):
        jobs.get_job_status_file(job).write_text(
            json.dumps({"status": JobStatus.FAILED.value, "error": "old",
                        "error_code": "PAD_CONFIG_INVALID"})
        )
        data = jobs.read_job_status(job)
        assert data["error_fields"] is None
        assert data["error_values"] is None


class TestEndpoint:
    def test_the_failure_response_carries_fields_and_values(self, job, client):
        jobs.write_job_status(
            job, JobStatus.FAILED, error="pad", error_code="PAD_CONFIG_INVALID",
            error_fields=PAD_FIELDS, error_values=PAD_VALUES,
        )
        body = client.get(f"/api/v2/slices/{job}").json()
        assert body["success"] is False
        assert body["code"] == "PAD_CONFIG_INVALID"
        assert body["data"]["fields"] == PAD_FIELDS
        assert body["data"]["values"] == PAD_VALUES
        assert {"retryable", "traceId"} <= set(body["data"])


class TestRunsStoreWhatTheEngineReported:
    def test_run_slicing(self, job, monkeypatch):
        monkeypatch.setattr(jobs, "notify_launcher_if_prusa_crashed", lambda rc: None)
        proc = _FakeProc(PAD_STDOUT, PAD_STDERR, 1)

        async def fake_exec(*args, **kwargs):
            proc.open_streams()
            return proc

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

        asyncio.run(jobs.run_slicing(job))

        data = jobs.read_job_status(job)
        assert data["error_code"] == "PAD_CONFIG_INVALID"
        assert data["error_fields"] == PAD_FIELDS
        assert data["error_values"] == PAD_VALUES

    def test_run_support_generation(self, job, monkeypatch):
        async def fake_run_prusa_cli(cmd, stderr_file=None, stdout_file=None):
            return 1, PAD_STDOUT, PAD_STDERR

        monkeypatch.setattr(sla_operations, "run_prusa_cli", fake_run_prusa_cli)

        asyncio.run(jobs.run_support_generation(job))

        data = jobs.read_job_status(job)
        assert data["error_code"] == "PAD_CONFIG_INVALID"
        assert data["error_fields"] == PAD_FIELDS
        assert data["error_values"] == PAD_VALUES
