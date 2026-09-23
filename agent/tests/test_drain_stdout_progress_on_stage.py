"""`_drain_stdout_progress(..., on_stage=...)` side-channel hook.

add-slice-pipeline-profiling task 1.2: the drain reports each engine stage
switch to an optional callback so profiling can timestamp it. The hook is
measurement only — it must fire after the progress store is updated, only on
a change of stage, and a failing callback must never affect the slice.

Driven synchronously via _run(), matching test_drain_stdout_progress.py.
"""

import asyncio

import pytest

from agent import jobs


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro)
    finally:
        loop.close()
        asyncio.set_event_loop(asyncio.new_event_loop())


class _FakeStream:
    def __init__(self, payload: bytes):
        self._lines = payload.splitlines(keepends=True)
        self._index = 0

    async def readline(self) -> bytes:
        if self._index >= len(self._lines):
            return b""
        line = self._lines[self._index]
        self._index += 1
        return line


STDOUT_BYTES = (
    b"  0% => Assembling model from parts\n"
    b" 10% => Slicing model\n"
    b" 20% => Slicing model\n"
    b"some engine chatter\n"
    b" 90% => Rasterizing layers\n"
    b" 95% => Rasterizing layers\n"
    b"100% => Slicing done\n"
)

EXPECTED_STAGES = [
    "STAGE_ASSEMBLING",
    "STAGE_SLICING",
    "STAGE_RASTERIZING",
    "STAGE_FINALIZING",
]


def _drain(job_id, **kwargs):
    return _run(
        jobs._drain_stdout_progress(_FakeStream(STDOUT_BYTES), job_id, **kwargs)
    )


def test_default_none_keeps_existing_behaviour():
    finalizing_at, stdout = _drain("job-none")
    assert stdout == STDOUT_BYTES
    assert finalizing_at is not None
    assert jobs.get_job_progress("job-none")["stage"] == "STAGE_FINALIZING"


def test_on_stage_is_keyword_only():
    with pytest.raises(TypeError):
        _run(
            jobs._drain_stdout_progress(
                _FakeStream(STDOUT_BYTES), "job-kw", lambda s, t: None
            )
        )


def test_callback_fires_only_on_stage_change():
    seen = []
    _drain("job-a", on_stage=lambda stage, t: seen.append(stage))
    assert seen == EXPECTED_STAGES


def test_callback_gets_perf_counter_time(monkeypatch):
    ticks = iter([1.0, 2.0, 3.0, 4.0])
    monkeypatch.setattr(jobs.time, "perf_counter", lambda: next(ticks))
    seen = []
    _drain("job-t", on_stage=lambda stage, t: seen.append((stage, t)))
    assert seen == list(zip(EXPECTED_STAGES, [1.0, 2.0, 3.0, 4.0]))


def test_callback_runs_after_progress_is_written():
    observed = []

    def on_stage(stage, t):
        observed.append((stage, jobs.get_job_progress("job-order")["stage"]))

    _drain("job-order", on_stage=on_stage)
    assert observed == [(s, s) for s in EXPECTED_STAGES]


def test_raising_callback_is_swallowed():
    calls = []

    def boom(stage, t):
        calls.append(stage)
        raise RuntimeError("profiling bug")

    finalizing_at, stdout = _drain("job-boom", on_stage=boom)

    # Return value and progress are untouched by the failing hook.
    assert stdout == STDOUT_BYTES
    assert finalizing_at is not None
    progress = jobs.get_job_progress("job-boom")
    assert progress["percent"] == 100
    assert progress["stage"] == "STAGE_FINALIZING"
    # One failure does not stop later stage reports.
    assert calls == EXPECTED_STAGES


def test_empty_stream_never_calls_back():
    seen = []
    _run(
        jobs._drain_stdout_progress(
            _FakeStream(b""), "job-empty", on_stage=lambda s, t: seen.append(s)
        )
    )
    assert seen == []
