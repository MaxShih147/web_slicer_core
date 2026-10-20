"""
run_prusa_cli(timeout_sec=...) — fix-support-zero-param-engine-hang Phase 3
(task 3.1), covering specs/support-generation-error-codes/spec.md at the
run_prusa_cli level.

A support generation that never ends (the engine's clustering loop at a zero
Max Connector Length) used to hold the serialized engine queue forever, since
run_prusa_cli waited on communicate() with no limit. With a timeout the engine
is killed, reaped, its logs written with a note, and EngineTimeoutError raised.
Without one, the behaviour must be exactly what it was.

Fake processes stand in for the engine, except for one test that spawns a real
sleeping Python child to prove the kill works under the Windows Proactor loop.
Driven synchronously via asyncio.run (no pytest-asyncio in this environment).
"""

import asyncio
import inspect
import logging
import sys
import time

import pytest

from agent import jobs, sla_operations
from agent.models import CutConfig, SLAConfig
from agent.sla_operations import EngineTimeoutError
from agent.tests.test_run_prusa_cli_streams import (
    STDERR_BYTES,
    STDOUT_BYTES,
    _FakeProc,
)


class _HangingProc:
    """An engine that never finishes on its own.

    communicate() blocks until kill(); it then hands back what was still in the
    pipes, as a real killed process would. ``kill_raises`` models the process
    exiting by itself between the timeout and the kill; ``ignores_kill`` models
    one that never goes away even after being killed.
    """

    def __init__(self, *, kill_raises=False, ignores_kill=False, killed_returncode=1):
        self.returncode = None
        self.pid = 4242
        self.kill_calls = 0
        self._kill_raises = kill_raises
        self._ignores_kill = ignores_kill
        self._killed_returncode = killed_returncode
        self._exited = asyncio.Event()

    def kill(self):
        self.kill_calls += 1
        if self._kill_raises:
            self._exited.set()
            raise ProcessLookupError
        if not self._ignores_kill:
            self._exited.set()

    async def communicate(self):
        await self._exited.wait()
        self.returncode = 0 if self._kill_raises else self._killed_returncode
        return b"partial stdout", b"partial stderr"


class _ExitedButUndrainedProc(_HangingProc):
    """Has exited (returncode set) but the first communicate() still blocks,
    e.g. a pipe held open elsewhere. The reap's communicate() returns."""

    def __init__(self):
        super().__init__()
        self._communicate_calls = 0

    async def communicate(self):
        self._communicate_calls += 1
        if self._communicate_calls == 1:
            self.returncode = 0
            await asyncio.Event().wait()
        return b"", b""


def _patch_exec(monkeypatch, proc):
    async def fake_exec(*args, **kwargs):
        return proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)


def _run(cmd, stderr_file=None, stdout_file=None, **kwargs):
    return asyncio.run(
        sla_operations.run_prusa_cli(cmd, stderr_file, stdout_file, **kwargs)
    )


class TestTimeout:
    def test_timeout_kills_logs_and_raises(self, tmp_path, monkeypatch):
        """support-generation-error-codes: 引擎卡住超過 120 秒 / 逾時的 log 可供除錯 /
        不誤報為當機"""
        sentinel = tmp_path / "crash" / "sentinel.json"
        monkeypatch.setenv("BUNDLE_FORCE_PRUSA_STACK_OVERFLOW", "1")
        monkeypatch.setenv("BUNDLE_PRUSA_CRASH_SENTINEL", str(sentinel))
        # -9 is what a kill looks like on macOS: a crash to the sentinel check.
        proc = _HangingProc(killed_returncode=-9)
        _patch_exec(monkeypatch, proc)
        stdout_file = tmp_path / "stdout.log"
        stderr_file = tmp_path / "stderr.log"

        with pytest.raises(EngineTimeoutError) as exc_info:
            _run(["engine"], stderr_file, stdout_file, timeout_sec=0.1)

        assert exc_info.value.timeout_sec == 0.1
        assert proc.kill_calls == 1
        assert stdout_file.read_bytes() == b"partial stdout"
        stderr = stderr_file.read_bytes()
        assert stderr.startswith(b"partial stderr")
        last_line = stderr.rstrip(b"\n").splitlines()[-1]
        assert b"killed after 0.1s" in last_line
        assert not sentinel.exists()

    def test_process_gone_before_kill_is_not_an_error(self, tmp_path, monkeypatch):
        """support-generation-error-codes: 程序剛好在終止前自行結束"""
        proc = _HangingProc(kill_raises=True)
        _patch_exec(monkeypatch, proc)

        with pytest.raises(EngineTimeoutError):
            _run(["engine"], tmp_path / "stderr.log", timeout_sec=0.1)

        assert proc.kill_calls == 1

    def test_already_exited_process_is_not_killed(self, monkeypatch):
        """returncode already set when the timeout lands: no kill at all."""
        proc = _ExitedButUndrainedProc()
        _patch_exec(monkeypatch, proc)

        with pytest.raises(EngineTimeoutError):
            _run(["engine"], timeout_sec=0.1)

        assert proc.kill_calls == 0

    def test_reap_is_bounded(self, tmp_path, monkeypatch, caplog):
        """A process that survives kill() must not hold the caller forever."""
        monkeypatch.setattr(sla_operations, "_REAP_TIMEOUT_SEC", 0.1)
        proc = _HangingProc(ignores_kill=True)
        _patch_exec(monkeypatch, proc)
        stderr_file = tmp_path / "stderr.log"

        with caplog.at_level(logging.ERROR, logger=sla_operations.logger.name):
            with pytest.raises(EngineTimeoutError):
                _run(["engine"], stderr_file, timeout_sec=0.1)

        assert proc.kill_calls == 1
        assert b"killed after 0.1s" in stderr_file.read_bytes()
        assert any("did not exit" in r.getMessage() for r in caplog.records)


class TestCancelled:
    def test_cancel_kills_the_engine_and_propagates(self, monkeypatch):
        """support-generation-error-codes requirement: agent 行程被取消時一併終止引擎"""
        proc = _HangingProc()
        _patch_exec(monkeypatch, proc)

        async def main():
            task = asyncio.create_task(
                sla_operations.run_prusa_cli(["engine"], timeout_sec=60)
            )
            await asyncio.sleep(0.05)
            task.cancel()
            await task

        with pytest.raises(asyncio.CancelledError):
            asyncio.run(main())

        assert proc.kill_calls == 1


class TestNoTimeout:
    def test_without_timeout_behaviour_is_unchanged(self, tmp_path, monkeypatch):
        """timeout_sec omitted: same result as before, and no wait_for around it."""

        async def fake_exec(*args, **kwargs):
            return _FakeProc(STDOUT_BYTES, STDERR_BYTES, 0)

        def no_wait_for(*args, **kwargs):
            raise AssertionError("wait_for must not be used without a timeout")

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
        monkeypatch.setattr(sla_operations.asyncio, "wait_for", no_wait_for)
        stdout_file = tmp_path / "stdout.log"
        stderr_file = tmp_path / "stderr.log"

        result = _run(["engine"], stderr_file, stdout_file)

        assert result == (0, STDOUT_BYTES, STDERR_BYTES)
        assert stdout_file.read_bytes() == STDOUT_BYTES
        assert stderr_file.read_bytes() == STDERR_BYTES

    def test_within_limit_behaviour_is_unchanged(self, tmp_path, monkeypatch):
        """A run that ends inside the limit returns and logs exactly as before."""

        async def fake_exec(*args, **kwargs):
            return _FakeProc(STDOUT_BYTES, STDERR_BYTES, 0)

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
        stderr_file = tmp_path / "stderr.log"

        result = _run(["engine"], stderr_file, timeout_sec=5)

        assert result == (0, STDOUT_BYTES, STDERR_BYTES)
        assert stderr_file.read_bytes() == STDERR_BYTES


class TestRealSubprocess:
    def test_real_child_is_killed_within_two_seconds(self, tmp_path, monkeypatch):
        """A real child under the platform's default loop (Proactor on Windows)
        is actually killed and reaped, not just abandoned."""
        spawned = []
        real_exec = asyncio.create_subprocess_exec

        async def recording_exec(*args, **kwargs):
            proc = await real_exec(*args, **kwargs)
            spawned.append(proc)
            return proc

        monkeypatch.setattr(asyncio, "create_subprocess_exec", recording_exec)

        start = time.monotonic()
        with pytest.raises(EngineTimeoutError):
            _run(
                [sys.executable, "-c", "import time; time.sleep(60)"],
                tmp_path / "stderr.log",
                timeout_sec=1,
            )
        elapsed = time.monotonic() - start

        assert elapsed < 2.0, f"took {elapsed:.2f}s"
        assert len(spawned) == 1
        assert spawned[0].returncode is not None


class _StopAtCli(Exception):
    """Raised by the run_prusa_cli stand-in once the call has been recorded."""


_NOT_PASSED = object()


class TestOtherCliRunsHaveNoTimeout:
    """support-generation-error-codes: 其他 CLI 流程不加逾時 (task 4.2)

    Every engine run except generate_supports() must reach run_prusa_cli
    without a time limit, so it keeps waiting for the engine however long it
    takes. The stand-in records what it was handed and stops the operation
    there; nothing after the engine call matters to this check.
    """

    @pytest.fixture
    def recorded(self, tmp_path, monkeypatch):
        calls = []

        async def recording_run_prusa_cli(cmd, stderr_file=None, stdout_file=None, **kwargs):
            calls.append(kwargs.get("timeout_sec", _NOT_PASSED))
            raise _StopAtCli

        monkeypatch.setattr(sla_operations, "run_prusa_cli", recording_run_prusa_cli)
        (tmp_path / "input").mkdir()
        (tmp_path / "output").mkdir()
        return calls

    @pytest.mark.parametrize(
        "operation",
        [
            lambda job_dir: sla_operations.generate_hollow(job_dir, SLAConfig()),
            lambda job_dir: sla_operations.cut_with_plane(job_dir, CutConfig(cut_height=5)),
            lambda job_dir: sla_operations.export_support_points(job_dir, SLAConfig()),
            lambda job_dir: sla_operations.slice_model(job_dir, SLAConfig()),
        ],
        ids=["hollow", "cut", "export-support-points", "slice-model"],
    )
    def test_engine_call_has_no_timeout(self, tmp_path, recorded, operation):
        with pytest.raises(_StopAtCli):
            asyncio.run(operation(tmp_path))
        assert recorded in ([None], [_NOT_PASSED])

    def test_generate_supports_is_the_one_with_a_limit(self, tmp_path, recorded):
        """The counterpart: the support-only run does get the limit."""
        with pytest.raises(_StopAtCli):
            asyncio.run(sla_operations.generate_supports(tmp_path, SLAConfig()))
        assert recorded == [sla_operations.SUPPORT_GENERATION_TIMEOUT_SEC]

    @pytest.mark.parametrize("name", ["run_slicing", "export_project_3mf"])
    def test_jobs_slicing_subprocesses_have_no_timeout(self, name):
        """The slicing subprocesses in jobs.py spawn the engine themselves and
        must stay without wait_for / a timeout."""
        source = inspect.getsource(inspect.unwrap(getattr(jobs, name)))
        assert "create_subprocess_exec" in source
        assert "wait_for" not in source
        assert "timeout" not in source.lower()
