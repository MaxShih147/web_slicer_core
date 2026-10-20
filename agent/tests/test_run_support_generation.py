"""
End-to-end wiring tests for run_support_generation — Task 5
(add-support-generation-error-codes).

Drives the whole Job-layer path (run_support_generation → generate_supports →
classify_support_result → write_job_status) with a stubbed CLI, then asserts the
persisted status.json fields for each scenario. Proves the two-stage
returncode/exists() judgement was fully replaced by the classifier:

  - real support pillars      → COMPLETED + has_support_mesh, no code/outcome
  - pad-only (neutral)        → COMPLETED + SUPPORT_NOT_NEEDED, has_support_mesh False
  - validate error, exit 0    → FAILED + specific error_code (exit-0 bug survived)
  - model out of bounds       → FAILED + MODEL_OUT_OF_BOUNDS
  - unattributable output     → FAILED + SUPPORT_GENERATION_FAILED (fail-closed)
  - success marker, no STL    → FAILED + SUPPORT_GENERATION_FAILED (fail-closed)

Isolated by monkeypatching agent.jobs.JOBS_DIR to a tmp directory and stubbing
agent.sla_operations.run_prusa_cli — the real slicer binary is never invoked.
Async is driven synchronously via asyncio.run (no pytest-asyncio dependency).
"""

import asyncio

import pytest

from agent import jobs
from agent import sla_operations
from agent.models import JobStatus
from agent.tests.test_run_prusa_cli_streams import _FakeProc


@pytest.fixture
def job(tmp_path, monkeypatch):
    """Point JOBS_DIR at a tmp dir and scaffold one job's input/output dirs."""
    monkeypatch.setattr(jobs, "JOBS_DIR", tmp_path)
    job_id = "support-job"
    (tmp_path / job_id / "input").mkdir(parents=True)
    (tmp_path / job_id / "output").mkdir()
    return job_id


def _stub_cli(monkeypatch, *, stdout=b"", stderr=b"", returncode=0):
    """Replace run_prusa_cli with a fake that writes the given bytes to the log
    files (as the real one does) and returns them, without launching a process."""

    async def fake_run_prusa_cli(cmd, stderr_file=None, stdout_file=None, timeout_sec=None):
        if stdout_file:
            with open(stdout_file, "wb") as f:
                f.write(stdout)
        if stderr_file:
            with open(stderr_file, "wb") as f:
                f.write(stderr)
        return returncode, stdout, stderr

    monkeypatch.setattr(sla_operations, "run_prusa_cli", fake_run_prusa_cli)


def _support_stl(job_id):
    return jobs.get_job_dir(job_id) / "output" / "model_support.stl"


def _run(job_id):
    asyncio.run(jobs.run_support_generation(job_id))
    return jobs.read_job_status(job_id)


class TestRealSupportSuccess:
    def test_supports_only_writes_completed_with_mesh(self, job, monkeypatch):
        """(supports only) + STL on disk → COMPLETED, has_support_mesh, no code."""
        _support_stl(job).write_bytes(b"solid support\n")  # STL landed on disk
        _stub_cli(monkeypatch, stdout=b"Generated (supports only)\n")

        data = _run(job)

        assert data["status"] == JobStatus.COMPLETED.value
        assert data["has_support_mesh"] is True
        assert data["error_code"] is None
        assert data["support_outcome"] is None


class TestNeutralNotNeeded:
    def test_pad_only_writes_completed_neutral(self, job, monkeypatch):
        """(pad only) → COMPLETED + SUPPORT_NOT_NEEDED, has_support_mesh False,
        and crucially NOT a FAILED status (must not block downstream slicing)."""
        _stub_cli(monkeypatch, stdout=b"Exported (pad only)\n")

        data = _run(job)

        assert data["status"] == JobStatus.COMPLETED.value
        assert data["support_outcome"] == "SUPPORT_NOT_NEEDED"
        assert data["has_support_mesh"] is False
        assert data["error_code"] is None

    def test_no_mesh_marker_writes_completed_neutral(self, job, monkeypatch):
        """'No support/pad mesh generated' is also a neutral SUPPORT_NOT_NEEDED."""
        _stub_cli(monkeypatch, stdout=b"No support/pad mesh generated\n")

        data = _run(job)

        assert data["status"] == JobStatus.COMPLETED.value
        assert data["support_outcome"] == "SUPPORT_NOT_NEEDED"
        assert data["has_support_mesh"] is False


class TestValidateFailureExitZero:
    def test_pinhead_validate_error_exit_zero_is_failed_with_code(self, job, monkeypatch):
        """Validate error on stderr WITH exit code 0 (the fork's bug) must still
        write FAILED + the specific code — status is driven by text, not exit."""
        _stub_cli(
            monkeypatch,
            stderr=b"Invalid pinhead diameter\nPinhead front diameter should be smaller than the Pillar diameter.",
            returncode=0,  # the exit-0 bug
        )

        data = _run(job)

        assert data["status"] == JobStatus.FAILED.value
        assert data["error_code"] == "SUPPORT_HEAD_TOO_WIDE"
        assert data["support_outcome"] is None

    def test_points_required_validate_error(self, job, monkeypatch):
        _stub_cli(
            monkeypatch,
            stderr=b"Cannot proceed without support points! Add support points or disable support generation.",
        )

        data = _run(job)

        assert data["status"] == JobStatus.FAILED.value
        assert data["error_code"] == "SUPPORT_POINTS_REQUIRED"


class TestOutOfBounds:
    def test_out_of_bounds_marker_writes_specific_code(self, job, monkeypatch):
        _stub_cli(
            monkeypatch,
            stdout=b"Nothing to print... no object is fully inside the print volume.",
        )

        data = _run(job)

        assert data["status"] == JobStatus.FAILED.value
        assert data["error_code"] == "MODEL_OUT_OF_BOUNDS"


class TestFailClosed:
    def test_unattributable_output_fails_closed(self, job, monkeypatch):
        """No known marker anywhere, no STL → FAILED + fallback (never silently
        treated as 'no supports needed')."""
        _stub_cli(monkeypatch, stdout=b"totally unexpected chatter", stderr=b"weird")

        data = _run(job)

        assert data["status"] == JobStatus.FAILED.value
        assert data["error_code"] == "SUPPORT_GENERATION_FAILED"
        assert data["support_outcome"] is None

    def test_success_marker_but_missing_stl_fails_closed(self, job, monkeypatch):
        """(supports only) marker but NO STL on disk → fail-closed (never upgrade
        to success on a missing file)."""
        _stub_cli(monkeypatch, stdout=b"Generated (supports only)\n")  # no STL created

        data = _run(job)

        assert data["status"] == JobStatus.FAILED.value
        assert data["error_code"] == "SUPPORT_GENERATION_FAILED"
        assert data["has_support_mesh"] is False

class TestEngineTimeout:
    def test_timeout_writes_failed_with_generation_code(self, job, monkeypatch):
        """support-generation-error-codes: 引擎卡住超過 120 秒（job 層）"""
        seen = {}

        async def fake_run_prusa_cli(cmd, stderr_file=None, stdout_file=None, timeout_sec=None):
            seen["timeout_sec"] = timeout_sec
            raise sla_operations.EngineTimeoutError(timeout_sec)

        monkeypatch.setattr(sla_operations, "run_prusa_cli", fake_run_prusa_cli)

        data = _run(job)

        assert seen["timeout_sec"] == sla_operations.SUPPORT_GENERATION_TIMEOUT_SEC == 120
        assert data["status"] == JobStatus.FAILED.value
        assert data["error_code"] == "SUPPORT_GENERATION_FAILED"
        assert "timed out" in data["error"]
        assert "120 seconds" in data["error"]
        assert data["support_outcome"] is None
        assert data["has_support_mesh"] is False


class TestWithinLimitUnchanged:
    """support-generation-error-codes: 時限內完成不受影響 (task 4.3)

    The same engine output is run through the real run_prusa_cli twice: once
    with the limit, once on the old unbounded path (limit None, which takes the
    plain communicate() it always did). status.json - and with it the
    classification - and both logs must come out byte-for-byte the same.
    """

    @pytest.mark.parametrize(
        "stdout, stderr, stl_on_disk",
        [
            (b"Generated (supports only)\n", b"", True),
            (b"Exported (pad only)\n", b"", False),
            (
                b"",
                b"Invalid pinhead diameter\nPinhead front diameter should be smaller than the Pillar diameter.",
                False,
            ),
            (b"totally unexpected chatter", b"weird", False),
        ],
        ids=["supports", "pad-only", "validate-error", "unattributable"],
    )
    def test_same_result_as_unbounded_path(
        self, tmp_path, monkeypatch, stdout, stderr, stl_on_disk
    ):
        monkeypatch.setattr(jobs, "JOBS_DIR", tmp_path)

        async def fake_exec(*cmd, **kwargs):
            return _FakeProc(stdout, stderr, 0)

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

        def run(job_id, limit):
            monkeypatch.setattr(sla_operations, "SUPPORT_GENERATION_TIMEOUT_SEC", limit)
            job_dir = tmp_path / job_id
            (job_dir / "input").mkdir(parents=True)
            (job_dir / "output").mkdir()
            if stl_on_disk:
                (job_dir / "output" / "model_support.stl").write_bytes(b"solid support\n")
            asyncio.run(jobs.run_support_generation(job_id))
            return tuple(
                (job_dir / name).read_bytes()
                for name in ("status.json", "stdout_support.log", "stderr_support.log")
            )

        bounded = run("bounded", 120)
        unbounded = run("unbounded", None)

        assert bounded == unbounded
        assert bounded[1:] == (stdout, stderr)
