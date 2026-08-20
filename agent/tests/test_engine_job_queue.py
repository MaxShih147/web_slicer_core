"""Global FIFO for Prusa / engine jobs (slicer-engine-job-queue)."""
from __future__ import annotations

import asyncio

import pytest

from agent.engine_job_queue import (
    EngineJobQueue,
    get_engine_job_queue,
    reset_engine_job_queue_for_tests,
    serialized_engine_job,
)
from agent.jobs import create_job, read_job_status, write_job_status
from agent.models import JobStatus, JobStatusResponse


@pytest.fixture(autouse=True)
def _reset_queue():
    reset_engine_job_queue_for_tests()
    yield
    reset_engine_job_queue_for_tests()


def test_single_job_runs_to_completion():
    queue = EngineJobQueue()
    seen = []

    async def work():
        seen.append("run")
        return "ok"

    async def main():
        result = await queue.run("job-a", work)
        assert result == "ok"
        assert queue.running_count == 0

    asyncio.run(main())
    assert seen == ["run"]


def test_second_job_stays_pending_until_first_finishes_and_running_count_is_one():
    queue = EngineJobQueue()
    a_started = asyncio.Event()
    a_release = asyncio.Event()
    order = []
    max_running = 0

    async def work_a():
        nonlocal max_running
        order.append("a-run")
        max_running = max(max_running, queue.running_count)
        a_started.set()
        await a_release.wait()
        return "a"

    async def work_b():
        nonlocal max_running
        order.append("b-run")
        max_running = max(max_running, queue.running_count)
        return "b"

    async def main():
        task_a = asyncio.create_task(queue.run("job-a", work_a))
        await a_started.wait()
        assert queue.snapshot()["running_job_id"] == "job-a"
        assert "job-b" not in queue.snapshot()["pending_job_ids"]

        task_b = asyncio.create_task(queue.run("job-b", work_b))
        await asyncio.sleep(0.02)
        snap = queue.snapshot()
        assert snap["running_job_id"] == "job-a"
        assert snap["pending_job_ids"] == ["job-b"]
        assert queue.running_count == 1
        assert "b-run" not in order

        a_release.set()
        results = await asyncio.gather(task_a, task_b)
        assert results == ["a", "b"]
        assert order == ["a-run", "b-run"]
        assert max_running == 1
        assert queue.running_count == 0

    asyncio.run(main())


def test_job_id_results_do_not_cross(tmp_path, monkeypatch):
    monkeypatch.setattr("agent.jobs.JOBS_DIR", tmp_path)
    a_started = asyncio.Event()
    a_release = asyncio.Event()

    @serialized_engine_job
    async def fake_engine(job_id: str, payload: str):
        write_job_status(job_id, JobStatus.PROCESSING)
        if job_id == "job-a":
            a_started.set()
            await a_release.wait()
        (tmp_path / job_id / "output.txt").write_text(payload, encoding="utf-8")
        write_job_status(job_id, JobStatus.COMPLETED)

    async def main():
        create_job("job-a")
        create_job("job-b")
        task_a = asyncio.create_task(fake_engine("job-a", "alpha"))
        await a_started.wait()
        task_b = asyncio.create_task(fake_engine("job-b", "beta"))
        await asyncio.sleep(0.02)
        assert read_job_status("job-a")["status"] == JobStatus.PROCESSING
        assert read_job_status("job-b")["status"] == JobStatus.PENDING
        assert get_engine_job_queue().running_count == 1
        a_release.set()
        await asyncio.gather(task_a, task_b)
        assert read_job_status("job-a")["status"] == JobStatus.COMPLETED
        assert read_job_status("job-b")["status"] == JobStatus.COMPLETED
        assert (tmp_path / "job-a" / "output.txt").read_text(encoding="utf-8") == "alpha"
        assert (tmp_path / "job-b" / "output.txt").read_text(encoding="utf-8") == "beta"

    asyncio.run(main())


def test_job_status_response_has_no_queue_rank_or_cancel_fields():
    fields = set(JobStatusResponse.model_fields)
    assert "queue_position" not in fields
    assert "queue_rank" not in fields
    assert "cancel" not in fields
    assert "cancellable" not in fields
    assert {"job_id", "status"} <= fields
