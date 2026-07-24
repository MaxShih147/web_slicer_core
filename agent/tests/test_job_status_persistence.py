"""
Tests for status.json persistence of the new fields — Task 4
(add-support-generation-error-codes).

Covers:
  - 4.1: write_job_status persists error_code (on failure) and support_outcome
         (neutral) and they round-trip through read_job_status
  - 4.2: reading an OLD status.json that predates these fields does not raise
         and normalizes the missing keys to None (error_code absent → later
         falls back to JOB_FAILED; support_outcome absent → no neutral hint)

Isolated by monkeypatching agent.jobs.JOBS_DIR to a tmp directory — no mocks of
the functions under test.
"""

import json

import pytest

from agent import jobs
from agent.models import JobStatus


@pytest.fixture
def job(tmp_path, monkeypatch):
    """Point JOBS_DIR at a tmp dir and create one empty job directory."""
    monkeypatch.setattr(jobs, "JOBS_DIR", tmp_path)
    job_id = "job-under-test"
    (tmp_path / job_id).mkdir()
    return job_id


class TestRoundTrip:
    def test_failure_error_code_round_trips(self, job):
        """4.1: error_code written on a FAILED job reads back intact."""
        jobs.write_job_status(
            job,
            JobStatus.FAILED,
            error="pinhead too wide",
            error_code="SUPPORT_HEAD_TOO_WIDE",
        )
        data = jobs.read_job_status(job)

        assert data["status"] == JobStatus.FAILED.value
        assert data["error_code"] == "SUPPORT_HEAD_TOO_WIDE"
        assert data["error"] == "pinhead too wide"
        # neutral field stays None on a failure
        assert data["support_outcome"] is None

    def test_neutral_support_outcome_round_trips(self, job):
        """4.1: support_outcome written on a COMPLETED job reads back intact."""
        jobs.write_job_status(
            job,
            JobStatus.COMPLETED,
            support_outcome="SUPPORT_NOT_NEEDED",
            has_support_mesh=False,
        )
        data = jobs.read_job_status(job)

        assert data["status"] == JobStatus.COMPLETED.value
        assert data["support_outcome"] == "SUPPORT_NOT_NEEDED"
        assert data["has_support_mesh"] is False
        # no error code on a neutral completion
        assert data["error_code"] is None

    def test_real_support_success_round_trips(self, job):
        """4.1: a genuine support mesh success carries neither code nor outcome."""
        jobs.write_job_status(job, JobStatus.COMPLETED, has_support_mesh=True)
        data = jobs.read_job_status(job)

        assert data["has_support_mesh"] is True
        assert data["error_code"] is None
        assert data["support_outcome"] is None


class TestBackwardCompatibility:
    def _write_legacy_status(self, job_id, payload):
        """Write a status.json that lacks the new fields, as an old build would."""
        status_file = jobs.get_job_status_file(job_id)
        with open(status_file, "w") as f:
            json.dump(payload, f)

    def test_legacy_failed_status_reads_without_error(self, job):
        """4.2: an old FAILED status.json with no error_code must not raise and
        normalizes error_code to None (→ generic JOB_FAILED downstream)."""
        self._write_legacy_status(
            job,
            {
                "status": JobStatus.FAILED.value,
                "error": "some old failure",
                "layer_count": None,
                "estimated_print_time": None,
                "resin_volume_ml": None,
                "has_support_mesh": False,
            },
        )

        data = jobs.read_job_status(job)  # must not raise

        assert data["status"] == JobStatus.FAILED.value
        assert data["error_code"] is None
        assert data["support_outcome"] is None
        assert data["error"] == "some old failure"

    def test_legacy_completed_status_has_no_neutral_hint(self, job):
        """4.2: an old COMPLETED status.json normalizes support_outcome to None."""
        self._write_legacy_status(
            job,
            {"status": JobStatus.COMPLETED.value, "has_support_mesh": True},
        )

        data = jobs.read_job_status(job)

        assert data["support_outcome"] is None
        assert data["error_code"] is None
        assert data["has_support_mesh"] is True

    def test_missing_status_file_is_normalized(self, tmp_path, monkeypatch):
        """4.2: when no status.json exists at all, the default dict still carries
        the new keys as None (no KeyError for consumers)."""
        monkeypatch.setattr(jobs, "JOBS_DIR", tmp_path)
        (tmp_path / "fresh-job").mkdir()

        data = jobs.read_job_status("fresh-job")

        assert data["status"] == JobStatus.PENDING
        assert data["error_code"] is None
        assert data["support_outcome"] is None

    def test_get_returns_none_for_missing_keys_on_legacy(self, job):
        """4.2: .get access on legacy data behaves as 'no specific code'."""
        self._write_legacy_status(job, {"status": JobStatus.FAILED.value})
        data = jobs.read_job_status(job)
        # both the explicit key (normalized) and .get agree on None
        assert data.get("error_code") is None
        assert data.get("support_outcome") is None