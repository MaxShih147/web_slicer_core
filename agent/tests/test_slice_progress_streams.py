"""
Dual-stream draining tests — Section 6 (add-slicing-progress).

The highest-risk change in this feature: switching run_slicing() from a single
``process.communicate()`` to two concurrently-drained streams. Two failure
modes are guarded here, both of which are silent and hard to diagnose in the
field:

  6.2  stderr read with ``readline()`` raises on a line longer than the
       StreamReader limit, turning a slice that would have succeeded into a
       failure. Chunked ``read(n)`` has no such limit.
  6.5  Draining only stdout deadlocks: the engine keeps writing to stderr, the
       pipe buffer fills, its write blocks, so it stops producing stdout — while
       the parent waits for the next stdout line. No error, no output, forever.

Real ``asyncio.StreamReader`` instances are used rather than hand-rolled fakes
so the limit semantics under test are the genuine ones. Driven synchronously
via ``asyncio.run()`` (pytest-asyncio is not installed), matching
``test_run_prusa_cli_streams.py``.
"""

import asyncio
import logging
import time

import pytest

from agent import jobs
from agent.jobs import (
    STAGE_ARCHIVED,
    STAGE_FINALIZING,
    STAGE_RASTERIZING,
    STAGE_SLICING,
    _drain_stderr,
    _drain_stdout_progress,
    get_job_progress,
    run_slicing,
)
from agent.models import JobStatus

from .test_slice_progress_parse import ARCHIVE_DONE_LINE, SAMPLE_STDOUT

JOB = "a1b2c3d4"


def _reader(payload: bytes) -> asyncio.StreamReader:
    """A real StreamReader pre-loaded with ``payload`` (must be built inside a
    running loop)."""
    stream = asyncio.StreamReader()
    stream.feed_data(payload)
    stream.feed_eof()
    return stream


# --- 6.1 stdout line draining ---------------------------------------------


def test_stdout_drain_records_every_progress_event():
    async def scenario():
        await _drain_stdout_progress(_reader(SAMPLE_STDOUT.encode()), JOB)

    asyncio.run(scenario())
    assert get_job_progress(JOB) == {"percent": 100, "stage": STAGE_ARCHIVED}


def test_stdout_drain_advances_progress_step_by_step():
    """Each line must land as it arrives, not only at the end."""
    seen = []

    async def scenario():
        stream = asyncio.StreamReader()
        for line in ("  5% => Slicing model\n", " 73% => Rasterizing layers\n"):
            stream.feed_data(line.encode())
        stream.feed_eof()

        original = jobs.set_job_progress

        def spy(job_id, percent, stage):
            original(job_id, percent, stage)
            seen.append((percent, stage))

        jobs.set_job_progress = spy
        try:
            await _drain_stdout_progress(stream, JOB)
        finally:
            jobs.set_job_progress = original

    asyncio.run(scenario())
    assert seen == [(5, STAGE_SLICING), (73, STAGE_RASTERIZING)]


def test_stdout_drain_ignores_noise_without_raising():
    async def scenario():
        payload = b"Nothing to print for out.sl1 .\n\n 29% => Slicing model\ngarbage\n"
        await _drain_stdout_progress(_reader(payload), JOB)

    asyncio.run(scenario())
    assert get_job_progress(JOB) == {"percent": 29, "stage": STAGE_SLICING}


def test_stdout_drain_handles_crlf_line_endings():
    async def scenario():
        await _drain_stdout_progress(_reader(b" 62% => Slicing supports\r\n"), JOB)

    asyncio.run(scenario())
    assert get_job_progress(JOB)["percent"] == 62


def test_stdout_drain_on_empty_stream_records_nothing():
    async def scenario():
        await _drain_stdout_progress(_reader(b""), JOB)

    asyncio.run(scenario())
    assert get_job_progress(JOB) is None


def test_stdout_drain_records_archive_stage_last():
    async def scenario():
        payload = ("100% => Slicing done\n" + ARCHIVE_DONE_LINE + "\n").encode()
        await _drain_stdout_progress(_reader(payload), JOB)

    asyncio.run(scenario())
    assert get_job_progress(JOB) == {"percent": 100, "stage": STAGE_ARCHIVED}


# --- 6.2 stderr chunked draining ------------------------------------------

# Comfortably beyond the 64 KiB StreamReader limit, as a SINGLE line.
_OVERLONG_LINE = b"E" * (asyncio.streams._DEFAULT_LIMIT * 3) + b"\n"


def test_stderr_drain_survives_a_line_longer_than_the_stream_limit():
    async def scenario():
        return await _drain_stderr(_reader(_OVERLONG_LINE))

    assert asyncio.run(scenario()) == _OVERLONG_LINE


def test_readline_would_have_raised_on_the_same_payload():
    """Proves the chunked-read choice has teeth: the obvious readline()
    implementation fails on exactly this input."""

    async def scenario():
        with pytest.raises(ValueError):
            await _reader(_OVERLONG_LINE).readline()

    asyncio.run(scenario())


def test_stderr_drain_returns_content_verbatim():
    payload = b"boost log line 1\nboost log line 2\n\xff\xfe binary tail"

    async def scenario():
        return await _drain_stderr(_reader(payload))

    assert asyncio.run(scenario()) == payload


def test_stderr_drain_on_empty_stream_returns_empty_bytes():
    async def scenario():
        return await _drain_stderr(_reader(b""))

    assert asyncio.run(scenario()) == b""


def test_stderr_drain_reassembles_multiple_chunks():
    payload = b"Z" * (jobs._STDERR_CHUNK_SIZE * 2 + 17)

    async def scenario():
        return await _drain_stderr(_reader(payload))

    assert asyncio.run(scenario()) == payload


# --- 6.5 deadlock regression ----------------------------------------------


class _GatedStdout:
    """stdout that stalls until stderr has been consumed past a threshold.

    Mirrors the real pipe coupling: the engine cannot emit more stdout while its
    blocked stderr write is pending. A sequential reader (drain stdout fully,
    *then* stderr) never gets past the gate — the test times out, which is
    exactly the production symptom.
    """

    def __init__(self, lines, gate):
        self._lines = list(lines)
        self._gate = gate
        self._emitted = 0

    async def readline(self):
        if not self._lines:
            return b""
        if self._emitted >= 1:
            await self._gate.wait()
        self._emitted += 1
        return self._lines.pop(0)


class _GatedStderr:
    """stderr that opens the gate once enough bytes have been drained."""

    def __init__(self, payload, gate, threshold):
        self._buf = payload
        self._gate = gate
        self._threshold = threshold
        self._drained = 0

    async def read(self, n):
        if not self._buf:
            return b""
        chunk, self._buf = self._buf[:n], self._buf[n:]
        self._drained += len(chunk)
        if self._drained >= self._threshold:
            self._gate.set()
        return chunk


def test_concurrent_drain_does_not_deadlock_on_a_chatty_stderr():
    lines = [
        b"  5% => Slicing model\n",
        b" 29% => Generating support tree\n",
        b" 73% => Rasterizing layers\n",
        b"100% => Slicing done\n",
    ]
    stderr_payload = b"L" * (jobs._STDERR_CHUNK_SIZE * 4)

    async def scenario():
        gate = asyncio.Event()
        stdout = _GatedStdout(lines, gate)
        stderr = _GatedStderr(stderr_payload, gate, jobs._STDERR_CHUNK_SIZE)

        # A sequential implementation never returns; fail loudly instead of hanging.
        return await asyncio.wait_for(
            asyncio.gather(
                _drain_stdout_progress(stdout, JOB),
                _drain_stderr(stderr),
            ),
            timeout=5,
        )

    _, drained = asyncio.run(scenario())

    assert drained == stderr_payload, "stderr must be recovered in full"
    assert get_job_progress(JOB) == {"percent": 100, "stage": STAGE_FINALIZING}


# --- run_slicing integration (6.3 / 6.4 / 6.7) ----------------------------


class _FakeProc:
    def __init__(self, stdout: bytes, stderr: bytes, returncode: int):
        self._stdout = stdout
        self._stderr = stderr
        self.returncode = returncode
        self.pid = 4242

    def open_streams(self):
        self.stdout = _reader(self._stdout)
        self.stderr = _reader(self._stderr)

    async def wait(self):
        return self.returncode


@pytest.fixture
def slicing_env(tmp_path, monkeypatch):
    """A job dir plus a stubbed engine subprocess and crash notifier."""
    monkeypatch.setattr(jobs, "JOBS_DIR", tmp_path)
    job_dir = tmp_path / JOB
    (job_dir / "input").mkdir(parents=True)
    (job_dir / "output").mkdir()

    notified = []
    monkeypatch.setattr(
        jobs, "notify_launcher_if_prusa_crashed", lambda rc: notified.append(rc)
    )

    def install(stdout: bytes, stderr: bytes, returncode: int) -> _FakeProc:
        proc = _FakeProc(stdout, stderr, returncode)

        async def fake_exec(*args, **kwargs):
            assert kwargs.get("stdout") == asyncio.subprocess.PIPE
            assert kwargs.get("stderr") == asyncio.subprocess.PIPE
            proc.open_streams()
            return proc

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
        return proc

    return {
        "job_dir": job_dir,
        "install": install,
        "notified": notified,
        "monkeypatch": monkeypatch,
    }


def _read_status(job_dir):
    import json

    return json.loads((job_dir / "status.json").read_text())


def test_nonzero_exit_marks_job_failed_and_notifies(slicing_env):
    job_dir = slicing_env["job_dir"]
    slicing_env["install"](b"  5% => Slicing model\n", b"engine exploded", 9)

    asyncio.run(run_slicing(JOB))

    status = _read_status(job_dir)
    assert status["status"] == JobStatus.FAILED.value
    assert "Exit code 9" in status["error"]
    assert "engine exploded" in status["error"]
    assert slicing_env["notified"] == [9]


def test_stderr_is_persisted_in_full(slicing_env):
    job_dir = slicing_env["job_dir"]
    slicing_env["install"](b"", _OVERLONG_LINE, 0)

    asyncio.run(run_slicing(JOB))

    assert (job_dir / "stderr.log").read_bytes() == _OVERLONG_LINE


def test_progress_is_recorded_while_the_engine_runs(slicing_env):
    """The store must have been fed even though it is cleared at the end."""
    job_dir = slicing_env["job_dir"]
    slicing_env["install"](SAMPLE_STDOUT.encode(), b"", 0)

    seen = []
    original = jobs.set_job_progress
    slicing_env["monkeypatch"].setattr(
        jobs,
        "set_job_progress",
        lambda j, p, s: (seen.append((p, s)), original(j, p, s))[1],
    )

    asyncio.run(run_slicing(JOB))

    assert [p for p, _ in seen] == [0, 5, 26, 29, 62, 70, 73, 88, 100, 100]
    assert seen[-1] == (100, STAGE_ARCHIVED)


def test_progress_cleared_after_failure_path(slicing_env):
    slicing_env["install"](b" 29% => Slicing model\n", b"boom", 1)

    asyncio.run(run_slicing(JOB))

    assert get_job_progress(JOB) is None
    assert JOB not in jobs.job_progress


def test_progress_cleared_after_success_path(slicing_env):
    job_dir = slicing_env["job_dir"]
    (job_dir / "output" / "model.sl1").write_bytes(b"")
    slicing_env["monkeypatch"].setattr(
        jobs, "parse_sl1_metadata", lambda path: (120, 3600.0, 12.5)
    )
    slicing_env["install"](SAMPLE_STDOUT.encode(), b"", 0)

    asyncio.run(run_slicing(JOB))

    assert _read_status(job_dir)["status"] == JobStatus.COMPLETED.value
    assert get_job_progress(JOB) is None


def test_success_path_preserves_metadata_statistics(slicing_env):
    """spec R2 / scenario 「成功切片的產物與統計不變」.

    run_slicing() had no test coverage before this change, so the streaming
    rewrite has no pre-existing regression net for the success path. Pin the
    three statistics the frontend consumes: a future edit that drops or
    reorders the metadata write fails here instead of silently shipping a
    slice whose layer count or print-time estimate is missing.
    """
    job_dir = slicing_env["job_dir"]
    (job_dir / "output" / "model.sl1").write_bytes(b"")
    slicing_env["monkeypatch"].setattr(
        jobs, "parse_sl1_metadata", lambda path: (120, 3600.0, 12.5)
    )
    slicing_env["install"](SAMPLE_STDOUT.encode(), b"", 0)

    asyncio.run(run_slicing(JOB))

    status = _read_status(job_dir)
    assert status["status"] == JobStatus.COMPLETED.value
    assert status["layer_count"] == 120
    # No prz_config.json in the job dir, so resolve_estimated_print_time()
    # degrades to the fork's own SL1 estimate — unchanged by this feature.
    assert status["estimated_print_time"] == 3600.0
    assert status["resin_volume_ml"] == 12.5
    assert status["error"] is None


def test_success_path_reports_a_generated_support_mesh(slicing_env):
    """has_support_mesh is derived from the file on disk, not from progress."""
    job_dir = slicing_env["job_dir"]
    (job_dir / "output" / "model.sl1").write_bytes(b"")
    (job_dir / "output" / "model_support.stl").write_bytes(b"solid\n")
    slicing_env["monkeypatch"].setattr(
        jobs, "parse_sl1_metadata", lambda path: (120, 3600.0, 12.5)
    )
    slicing_env["install"](SAMPLE_STDOUT.encode(), b"", 0)

    asyncio.run(run_slicing(JOB))

    assert _read_status(job_dir)["has_support_mesh"] is True


def test_missing_output_file_is_still_a_failure(slicing_env):
    """Exit code 0 with no archive on disk must not read as success."""
    slicing_env["install"](SAMPLE_STDOUT.encode(), b"", 0)

    asyncio.run(run_slicing(JOB))

    status = _read_status(slicing_env["job_dir"])
    assert status["status"] == JobStatus.FAILED.value
    assert "Output file not created" in status["error"]


def test_progress_cleared_when_an_exception_escapes(slicing_env):
    slicing_env["install"](b" 29% => Slicing model\n", b"", 0)
    slicing_env["monkeypatch"].setattr(
        jobs,
        "notify_launcher_if_prusa_crashed",
        lambda rc: (_ for _ in ()).throw(RuntimeError("notifier blew up")),
    )

    asyncio.run(run_slicing(JOB))

    assert _read_status(slicing_env["job_dir"])["status"] == JobStatus.FAILED.value
    assert get_job_progress(JOB) is None


# --- 8.1 the finalizing timestamp -----------------------------------------


def test_drain_returns_a_timestamp_when_the_engine_reports_done():
    async def scenario():
        return await _drain_stdout_progress(
            _reader(b" 88% => Rasterizing layers\n100% => Slicing done\n"), JOB
        )

    finalizing_at = asyncio.run(scenario())
    assert isinstance(finalizing_at, float)


def test_drain_returns_none_when_the_engine_never_reports_done():
    async def scenario():
        return await _drain_stdout_progress(
            _reader(b" 29% => Slicing model\n 88% => Rasterizing layers\n"), JOB
        )

    assert asyncio.run(scenario()) is None


def test_drain_timestamp_precedes_the_archive_marker():
    """The measured window is the silent tail — the marker must land after it."""

    async def scenario():
        payload = ("100% => Slicing done\n" + ARCHIVE_DONE_LINE + "\n").encode()
        finalizing_at = await _drain_stdout_progress(_reader(payload), JOB)
        return finalizing_at, time.monotonic()

    finalizing_at, after = asyncio.run(scenario())
    assert finalizing_at <= after


def test_drain_keeps_the_first_finalizing_timestamp():
    """A repeated 100% line must not restart the measurement."""

    async def scenario():
        payload = b"100% => Slicing done\n100% => Slicing done\n"
        return await _drain_stdout_progress(_reader(payload), JOB)

    assert isinstance(asyncio.run(scenario()), float)


def test_drain_timestamp_survives_an_unrecognized_done_label(caplog):
    """A drifted label degrades to STAGE_SLICING, so no timestamp is taken —
    the measurement is best-effort and must not fabricate one."""

    async def scenario():
        return await _drain_stdout_progress(_reader(b"100% => Slicing finished\n"), JOB)

    with caplog.at_level(logging.WARNING, logger="agent.jobs"):
        assert asyncio.run(scenario()) is None


# --- 8.2 archive-tail duration logging ------------------------------------


def test_archive_tail_duration_is_logged(slicing_env, caplog):
    slicing_env["install"](SAMPLE_STDOUT.encode(), b"", 0)

    with caplog.at_level(logging.INFO, logger="agent.jobs"):
        asyncio.run(run_slicing(JOB))

    records = [r for r in caplog.records if "Archive tail elapsed" in r.getMessage()]
    assert len(records) == 1

    duration = records[0].args[0]
    assert isinstance(duration, float)
    assert duration >= 0.0


def test_archive_tail_duration_logged_on_the_failure_path(slicing_env, caplog):
    """The measurement is about the subprocess, not about success."""
    slicing_env["install"](SAMPLE_STDOUT.encode(), b"boom", 1)

    with caplog.at_level(logging.INFO, logger="agent.jobs"):
        asyncio.run(run_slicing(JOB))

    assert [r for r in caplog.records if "Archive tail elapsed" in r.getMessage()]


def test_no_duration_logged_when_the_engine_never_finished(slicing_env, caplog):
    slicing_env["install"](b" 29% => Slicing model\n", b"died early", 1)

    with caplog.at_level(logging.INFO, logger="agent.jobs"):
        asyncio.run(run_slicing(JOB))

    assert not [r for r in caplog.records if "Archive tail elapsed" in r.getMessage()]


def test_missing_finalizing_line_does_not_raise(slicing_env):
    """No completion line is a normal outcome (crash / cancel), not an error."""
    slicing_env["install"](b"", b"", 1)

    asyncio.run(run_slicing(JOB))

    assert _read_status(slicing_env["job_dir"])["status"] == JobStatus.FAILED.value


def test_terminal_status_is_written_before_progress_is_cleared(slicing_env):
    """Reversing this order opens a window where the job still reads as
    'processing' but its progress has vanished — a visible regression."""
    order = []
    real_write = jobs.write_job_status
    real_clear = jobs.clear_job_progress

    slicing_env["monkeypatch"].setattr(
        jobs,
        "write_job_status",
        lambda job_id, status, **kw: (
            order.append(("write", status.value)),
            real_write(job_id, status, **kw),
        )[1],
    )
    slicing_env["monkeypatch"].setattr(
        jobs,
        "clear_job_progress",
        lambda job_id: (order.append(("clear", job_id)), real_clear(job_id))[1],
    )
    slicing_env["install"](b" 29% => Slicing model\n", b"boom", 1)

    asyncio.run(run_slicing(JOB))

    assert order[-1][0] == "clear", f"clear must come last, got {order}"
    terminal_writes = [i for i, (kind, _) in enumerate(order) if kind == "write"]
    assert terminal_writes, "a terminal status must have been written"
    assert max(terminal_writes) < len(order) - 1
