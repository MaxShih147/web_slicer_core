"""Run a case received from CAMair through the existing slicing pipeline.

This is the seam between the partner protocol and the agent's own machinery: a
case that arrives over gRPC is handed to the same `agent.jobs.run_slicing` the
web slicer uses, and its progress is translated back into the CAMair job-status
vocabulary that Produce polls for.

Slicing runs on one background worker thread with its own event loop, because
`run_slicing` is async while the gRPC servicer is synchronous, and because the
engine is a subprocess we do not want several of at once. Jobs queue behind each
other and report `JobInQueue` while they wait, which is exactly what that status
is for.
"""

from __future__ import annotations

import asyncio
import logging
import queue
import shutil
import threading

from agent import camair  # noqa: F401  — puts _generated on sys.path

import CAMairDataTypes_pb2  # isort: skip

from agent import jobs as agent_jobs
from agent.models import SLAConfig

logger = logging.getLogger(__name__)

JobStatus = CAMairDataTypes_pb2.JobStatus

# How often to sample the slicer's progress while it runs. The engine reports
# far more often than Produce needs; this keeps the status stream readable.
_PROGRESS_POLL_SECONDS = 1.0


class JobProcessor:
    """Serialises accepted cases through the slicer and reports status back."""

    def __init__(self, config: SLAConfig | None = None):
        self._config = config or SLAConfig()
        self._queue: queue.Queue = queue.Queue()
        self._store = None
        self._thread: threading.Thread | None = None

    def bind(self, store) -> None:
        """Attach the JobStore and start the worker.

        Separate from __init__ because the store is created by build_server,
        which needs the processor's submit callback first.
        """
        self._store = store
        self._thread = threading.Thread(target=self._run, name="camair-processor", daemon=True)
        self._thread.start()

    def submit(self, job) -> None:
        self._queue.put(job)
        if not self._queue.empty():
            self._store.advance(job.job_id, JobStatus.JobInQueue, "Queued for slicing")

    # ---------------- worker ----------------

    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        while True:
            job = self._queue.get()
            try:
                loop.run_until_complete(self._process(job))
            except Exception:  # a failed case must not take the worker down
                logger.exception("CAMair job %s failed", job.job_id)
                self._store.advance(job.job_id, JobStatus.JobFailed, "Slicing failed")
            finally:
                self._queue.task_done()

    async def _process(self, job) -> None:
        store = self._store
        store.advance(job.job_id, JobStatus.JobInProgress, "Slicing started", 0)

        # Reuse the agent's own job layout so run_slicing finds what it expects.
        agent_job_id = agent_jobs.create_job(job.job_id)
        shutil.copy(job.stl_path, agent_job_id / "input" / "model.stl")

        slicing = asyncio.ensure_future(agent_jobs.run_slicing(job.job_id, self._config))
        last_percent = -1
        while not slicing.done():
            await asyncio.sleep(_PROGRESS_POLL_SECONDS)
            progress = agent_jobs.get_job_progress(job.job_id)
            if not progress:
                continue
            percent = int(progress.get("percent", 0))
            if percent > last_percent:
                last_percent = percent
                store.advance(
                    job.job_id,
                    JobStatus.JobInProgress,
                    progress.get("stage", "Slicing"),
                    percent,
                )
        await slicing  # surface any exception to _run's handler

        status = agent_jobs.read_job_status(job.job_id)
        state = str(status.get("status", "")).upper()
        if "FAIL" in state or "ERROR" in state:
            store.advance(
                job.job_id,
                JobStatus.JobFailed,
                status.get("error_code") or status.get("message") or "Slicing failed",
            )
            return

        output = agent_jobs.get_job_dir(job.job_id) / "output" / "model.sl1"
        size = output.stat().st_size if output.exists() else 0
        logger.info("CAMair job %s sliced → %s (%d bytes)", job.job_id, output.name, size)
        store.advance(
            job.job_id,
            JobStatus.JobFinishedSuccessfully,
            f"Sliced to {output.name}",
            100,
        )
