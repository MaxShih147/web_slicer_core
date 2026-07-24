"""
Tests for dual-stream capture in run_prusa_cli — Task 2
(add-support-generation-error-codes).

Covers:
  - 2.1: run_prusa_cli persists stdout to stdout_file (in addition to stderr)
  - 2.2: caller receives the full raw stdout in the return tuple (never lost)
  - 2.3: with a fake/stub subprocess, BOTH stdout and stderr are captured in
         full and written to their respective log files.

Driven synchronously via asyncio.run() so the test does not depend on
pytest-asyncio (which is not installed in this environment).
"""

import asyncio

import pytest

from agent import sla_operations


class _FakeProc:
    def __init__(self, stdout: bytes, stderr: bytes, returncode: int):
        self._stdout = stdout
        self._stderr = stderr
        self.returncode = returncode
        self.pid = 4242

    async def communicate(self):
        return self._stdout, self._stderr


def _patch_subprocess(monkeypatch, stdout: bytes, stderr: bytes, returncode: int):
    async def fake_exec(*args, **kwargs):
        # Assert the engine is still spawned out-of-process with piped streams.
        assert kwargs.get("stdout") == asyncio.subprocess.PIPE
        assert kwargs.get("stderr") == asyncio.subprocess.PIPE
        return _FakeProc(stdout, stderr, returncode)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)


# Raw bytes intentionally carry the real result markers so we prove the classifier
# will later see them unmodified (2.2). Includes non-ASCII + trailing content.
STDOUT_BYTES = b"Slicing model\n(supports only)\nNo support/pad mesh generated\n\xe2\x9c\x93"
STDERR_BYTES = b"Invalid pinhead diameter: 0.8 mm\nsome warning\xff\n"


class TestRunPrusaCliDualStream:
    def test_both_streams_written_to_log(self, tmp_path, monkeypatch):
        """2.1 + 2.3: stdout_file and stderr_file each receive the exact raw bytes."""
        _patch_subprocess(monkeypatch, STDOUT_BYTES, STDERR_BYTES, 0)
        stdout_file = tmp_path / "stdout.log"
        stderr_file = tmp_path / "stderr.log"

        rc, stdout, stderr = asyncio.run(
            sla_operations.run_prusa_cli(
                ["engine", "--export-support-stl"],
                stderr_file,
                stdout_file,
            )
        )

        assert rc == 0
        # 2.3: files hold the complete, byte-identical streams.
        assert stdout_file.read_bytes() == STDOUT_BYTES
        assert stderr_file.read_bytes() == STDERR_BYTES

    def test_return_tuple_carries_full_raw_stdout(self, tmp_path, monkeypatch):
        """2.2: caller gets the full raw stdout/stderr back for the classifier."""
        _patch_subprocess(monkeypatch, STDOUT_BYTES, STDERR_BYTES, 0)

        rc, stdout, stderr = asyncio.run(
            sla_operations.run_prusa_cli(
                ["engine", "--export-support-stl"],
                tmp_path / "stderr.log",
                tmp_path / "stdout.log",
            )
        )

        assert stdout == STDOUT_BYTES
        assert stderr == STDERR_BYTES
        # markers survive intact for downstream classification
        assert b"(supports only)" in stdout
        assert b"Invalid pinhead diameter" in stderr

    def test_stdout_not_lost_when_only_stderr_file_given(self, tmp_path, monkeypatch):
        """2.2: even without a stdout_file, stdout is still returned (never discarded)."""
        _patch_subprocess(monkeypatch, STDOUT_BYTES, STDERR_BYTES, 1)
        stderr_file = tmp_path / "stderr.log"

        rc, stdout, stderr = asyncio.run(
            sla_operations.run_prusa_cli(
                ["engine", "--export-support-stl"],
                stderr_file,
            )
        )

        assert rc == 1
        assert stdout == STDOUT_BYTES  # returned despite no stdout_file
        assert stderr_file.read_bytes() == STDERR_BYTES

    def test_no_files_still_returns_both_streams(self, monkeypatch):
        """2.2: with no log files at all, both streams still come back in the tuple."""
        _patch_subprocess(monkeypatch, STDOUT_BYTES, STDERR_BYTES, 0)

        rc, stdout, stderr = asyncio.run(
            sla_operations.run_prusa_cli(["engine", "--export-support-stl"])
        )

        assert (rc, stdout, stderr) == (0, STDOUT_BYTES, STDERR_BYTES)