"""
Tests for the three /execute, /generate-supports, /export-support-points
entry points returning 422 (not 500) on an invalid SLAConfig — Tasks 4.1/4.3
(add-support-param-validation).

Before this change all three wrapped their `_convert_v2_config_to_sla()` /
`_build_sla_config()` call in `except APIError: raise` / `except Exception:
raise internal_error(...)`, so a pydantic ValidationError (e.g. pad_wall_slope
outside the engine's 45-90 degree range — proposal.md's "death zone" bug,
since the frontend slider allowed 30) fell into the generic branch and came
back as HTTP 500 + retryable:true. A config value is never fixed by retrying.

Drives the real endpoint functions directly (not via TestClient/multipart
upload) with a minimal single-triangle ASCII STL, matching this module's
existing `_save_model_to_job` / `_validate_stl_bytes` contract.
"""

import asyncio

import pytest
from fastapi import BackgroundTasks

from agent import api_v2, jobs
from agent.errors import APIError

_MINIMAL_STL = (
    b"solid test\n"
    b"facet normal 0 0 1\nouter loop\n"
    b"vertex 0 0 0\nvertex 1 0 0\nvertex 0 1 0\n"
    b"endloop\nendfacet\n"
    b"endsolid test\n"
)


@pytest.fixture
def pending_job(tmp_path, monkeypatch):
    """A pending job with one valid model and an invalid pad_wall_slope,
    isolated the same way as test_run_support_generation.py."""
    monkeypatch.setattr(jobs, "JOBS_DIR", tmp_path)
    job_id = "job-422"
    api_v2._pending_jobs[job_id] = {
        "config": {"pad_wall_slope": 35},  # outside the engine's legal 45-90 range
        "models": [{"stl_data": _MINIMAL_STL}],
        "status": "created",
    }
    yield job_id
    api_v2._pending_jobs.pop(job_id, None)


def _run(coro):
    return asyncio.run(coro)


class TestExecuteReturns422(object):
    def test_invalid_pad_wall_slope_returns_422_not_500(self, pending_job):
        with pytest.raises(APIError) as exc_info:
            _run(api_v2.execute_slice_job(pending_job, BackgroundTasks()))
        assert exc_info.value.http_status == 422
        assert exc_info.value.retryable is False
        assert "pad_wall_slope" in exc_info.value.message


class TestGenerateSupportsReturns422:
    def test_invalid_pad_wall_slope_returns_422_not_500(self, pending_job):
        with pytest.raises(APIError) as exc_info:
            _run(api_v2.generate_supports_only(pending_job, BackgroundTasks()))
        assert exc_info.value.http_status == 422
        assert exc_info.value.retryable is False
        assert "pad_wall_slope" in exc_info.value.message


class TestExportSupportPointsReturns422:
    def test_invalid_pad_wall_slope_returns_422_not_500(self, pending_job):
        with pytest.raises(APIError) as exc_info:
            _run(api_v2.export_support_points_only(pending_job, BackgroundTasks()))
        assert exc_info.value.http_status == 422
        assert exc_info.value.retryable is False
        assert "pad_wall_slope" in exc_info.value.message


class TestLegalConfigStillWorks:
    """Sanity: the new except branch must not swallow legal configs."""

    def test_execute_with_legal_config_still_starts(self, tmp_path, monkeypatch):
        monkeypatch.setattr(jobs, "JOBS_DIR", tmp_path)
        job_id = "job-ok"
        api_v2._pending_jobs[job_id] = {
            "config": {"pad_wall_slope": 90},
            "models": [{"stl_data": _MINIMAL_STL}],
            "status": "created",
        }
        try:
            result = _run(api_v2.execute_slice_job(job_id, BackgroundTasks()))
            assert result.success is True
        finally:
            api_v2._pending_jobs.pop(job_id, None)
