"""EngineJobQueue queue-wait profiling (add-slice-pipeline-profiling, task 1.4).

EngineJobQueue.run marks queue-enter when a job joins the queue and
queue-acquired once it holds the lock; the difference is the queue-wait span.
Measurement only: FIFO order must be identical with the flag on or off, and a
profiling failure must never break the queue.
"""
from __future__ import annotations

import asyncio

import pytest

from agent import profiling
from agent.engine_job_queue import EngineJobQueue


@pytest.fixture(autouse=True)
def _reset_profiling():
    profiling.reset_for_tests()
    yield
    profiling.reset_for_tests()


def _run_two_jobs() -> list[str]:
    """job-a holds the lock for a while; job-b queues behind it."""
    queue = EngineJobQueue()
    order: list[str] = []

    def make_work(job_id: str, hold: float):
        async def work():
            order.append(f"start:{job_id}")
            await asyncio.sleep(hold)
            order.append(f"end:{job_id}")

        return work

    async def main():
        first = asyncio.create_task(queue.run("job-a", make_work("job-a", 0.05)))
        await asyncio.sleep(0)  # let job-a take the lock first
        second = asyncio.create_task(queue.run("job-b", make_work("job-b", 0)))
        await asyncio.gather(first, second)

    asyncio.run(main())
    return order


def test_second_job_queue_wait_is_positive(monkeypatch):
    monkeypatch.setenv("SLICE_PROFILING", "1")

    _run_two_jobs()

    a = profiling.snapshot("job-a")
    b = profiling.snapshot("job-b")
    assert a["spans"]["queue-wait"] >= 0.0
    assert b["spans"]["queue-wait"] > 0.0
    # job-b waited for job-a's whole run, so its wait dominates.
    assert b["spans"]["queue-wait"] > a["spans"]["queue-wait"]
    for snap in (a, b):
        assert snap["marks"]["queue-acquired"] >= snap["marks"]["queue-enter"]


def test_fifo_order_is_identical_with_and_without_profiling(monkeypatch):
    monkeypatch.delenv("SLICE_PROFILING", raising=False)
    order_off = _run_two_jobs()

    monkeypatch.setenv("SLICE_PROFILING", "1")
    order_on = _run_two_jobs()

    assert order_off == ["start:job-a", "end:job-a", "start:job-b", "end:job-b"]
    assert order_on == order_off


def test_flag_off_records_nothing(monkeypatch):
    monkeypatch.delenv("SLICE_PROFILING", raising=False)

    _run_two_jobs()

    monkeypatch.setenv("SLICE_PROFILING", "1")  # peek at the raw store
    assert profiling.snapshot("job-a") is None
    assert profiling.snapshot("job-b") is None


def test_existing_record_is_kept_while_queueing(monkeypatch):
    monkeypatch.setenv("SLICE_PROFILING", "1")
    profiling.add_span("job-b", "srv-handle", 7.0)

    _run_two_jobs()

    spans = profiling.snapshot("job-b")["spans"]
    assert spans["srv-handle"] == 7.0
    assert "queue-wait" in spans


def test_profiling_errors_never_break_the_queue(monkeypatch):
    monkeypatch.setenv("SLICE_PROFILING", "1")

    def boom(*args, **kwargs):
        raise RuntimeError("profiling bug")

    monkeypatch.setattr(profiling, "mark", boom)
    monkeypatch.setattr(profiling, "measure", boom)

    assert _run_two_jobs() == ["start:job-a", "end:job-a", "start:job-b", "end:job-b"]
