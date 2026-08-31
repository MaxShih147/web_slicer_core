"""Regression: run_slicing lost the engine's stdout.

`_drain_stdout_progress` consumed stdout line by line to publish progress and
returned only the finalizing timestamp, so by the time run_slicing called
`classify_slice_result(stdout=stdout, ...)` there was no `stdout` bound at all —
every slice ended in `NameError: name 'stdout' is not defined`, reported to the
caller as a generic failure.

The classifier needs the raw stdout to recognise STL parse errors (F-05), so the
fix is for the drain to accumulate what it reads rather than for the call site
to pass a placeholder.

Driven synchronously via _run() so it does not depend on pytest-asyncio,
matching test_run_prusa_cli_streams.py.
"""

import asyncio

from agent import jobs


def _run(coro):
    """asyncio.run() leaves no current loop behind, which trips the autouse
    fixture's teardown on Python 3.9. Manage the loop explicitly instead."""
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro)
    finally:
        loop.close()
        asyncio.set_event_loop(asyncio.new_event_loop())


class _FakeStream:
    """Minimal asyncio.StreamReader stand-in: readline() until exhausted."""

    def __init__(self, payload: bytes):
        self._lines = payload.splitlines(keepends=True)
        self._index = 0

    async def readline(self) -> bytes:
        if self._index >= len(self._lines):
            return b""
        line = self._lines[self._index]
        self._index += 1
        return line


# Real-shaped engine chatter: progress lines the drain parses, plus the kind of
# diagnostic the classifier looks for and must therefore still receive.
STDOUT_BYTES = (
    b"  0% => Assembling model from parts\n"
    b" 10% => Slicing model\n"
    b" 90% => Rasterizing layers\n"
    b"100% => Slicing done\n"
    b"Error: file model.stl does not contain a valid mesh\n"
)


class TestDrainStdoutProgress:
    def test_returns_the_raw_stdout_alongside_the_finalizing_mark(self):
        finalizing_at, stdout = _run(
            jobs._drain_stdout_progress(_FakeStream(STDOUT_BYTES), "job-1"),
        )

        # The bytes the classifier needs must survive the drain untouched.
        assert stdout == STDOUT_BYTES
        # And the existing return value still works.
        assert finalizing_at is not None

    def test_still_publishes_progress_while_capturing(self):
        _run(jobs._drain_stdout_progress(_FakeStream(STDOUT_BYTES), "job-2"))

        progress = jobs.get_job_progress("job-2")
        assert progress is not None
        assert progress["percent"] == 100
        jobs.clear_job_progress("job-2")

    def test_empty_stream_yields_empty_bytes_not_none(self):
        """A crashed engine produces nothing; the classifier must still get bytes."""
        finalizing_at, stdout = _run(
            jobs._drain_stdout_progress(_FakeStream(b""), "job-3"),
        )

        assert stdout == b""
        assert finalizing_at is None
