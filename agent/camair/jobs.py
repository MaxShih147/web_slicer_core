"""Job store for cases received from CAMair.

CAMair delivers a case, then polls us for its manufacturing status until the job
reaches a final state. This keeps the two halves of that conversation in one
place: what landed on disk, and where each job is in its lifecycle.

Deliberately in-memory for now. Surviving an agent restart matters for a real
deployment — CAMair keeps polling a jobId it was handed — but that is a Stage 5
concern, and pinning the persistence format before the slicing hand-off exists
would be guessing.
"""

from __future__ import annotations

import json
import threading
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from google.protobuf import json_format

from agent import camair  # noqa: F401  — puts _generated on sys.path

import CAMairProtocol_pb2  # isort: skip
import CAMairDataTypes_pb2  # isort: skip

from agent.camair.mesh import write_facet_marks, write_mesh_as_stl

# Mirrors the protocol's JobStatus enum; imported lazily by name to keep this
# module readable at the call sites.
JobStatus = CAMairDataTypes_pb2.JobStatus


@dataclass
class StatusEvent:
    status: int
    message: str = ""
    percentage: int | None = None
    at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class CamairJob:
    job_id: str
    key: str
    case_name: str
    indication: str
    directory: Path
    stl_path: Path
    facet_marks_path: Path | None
    history: list[StatusEvent]

    @property
    def status(self) -> int:
        return self.history[-1].status

    @property
    def is_final(self) -> bool:
        return self.status in (
            JobStatus.JobFinishedSuccessfully,
            JobStatus.JobFailed,
            JobStatus.JobCancelled,
        )


class JobStore:
    """Thread-safe registry of received jobs and their status history.

    gRPC serves each call on a pool thread, so a StartJob writing a job and a
    GetJobStatuses stream reading it genuinely do overlap.
    """

    def __init__(self, root: Path):
        self._root = root
        self._jobs: dict[str, CamairJob] = {}
        self._lock = threading.Lock()
        # Waiters are notified on every transition so the status stream can push
        # instead of poll.
        self._condition = threading.Condition(self._lock)

    # ---------------- ingest ----------------

    def accept(self, key: str, job_data) -> CamairJob:
        """Land one item from a StartJob stream on disk and register it."""
        job_id = str(uuid.uuid4())
        description = job_data.jobDescription
        case_name = description.caseName or "case"
        indication = CAMairDataTypes_pb2.IndicationType.Name(description.indicationType) \
            if description.indicationType else "Unknown"

        directory = self._root / job_id
        stl_path = write_mesh_as_stl(
            job_data.mesh,
            directory / "model.stl",
            header=f"CAMair {indication} {case_name}"[:79],
        )
        facet_marks_path = write_facet_marks(job_data.mesh, directory / "facet_marks.json")

        # Keep the whole request next to the mesh. Anything we do not consume yet
        # (indication metadata, mount direction, material) is still on disk when
        # Stage 4 needs it, without re-requesting the case.
        (directory / "job_data.json").write_text(
            json_format.MessageToJson(job_data, preserving_proto_field_name=False),
        )
        (directory / "meta.json").write_text(json.dumps({
            "jobId": job_id,
            "key": key,
            "caseName": case_name,
            "indication": indication,
            "unnFrom": description.unnFrom,
            "unnTo": description.unnTo,
            "material": job_data.material.id,
            "machine": {
                "manufacturerId": description.machineId.manufacturerId,
                "machineModelId": description.machineId.machineModelId,
            },
        }, indent=2))

        job = CamairJob(
            job_id=job_id,
            key=key,
            case_name=case_name,
            indication=indication,
            directory=directory,
            stl_path=stl_path,
            facet_marks_path=facet_marks_path,
            history=[StatusEvent(JobStatus.JobReceivedSuccessfully, "Case received")],
        )
        with self._condition:
            self._jobs[job_id] = job
            self._condition.notify_all()
        return job

    # ---------------- status ----------------

    def advance(self, job_id: str, status: int, message: str = "", percentage: int | None = None) -> None:
        with self._condition:
            job = self._jobs.get(job_id)
            if job is None:
                return
            job.history.append(StatusEvent(status, message, percentage))
            self._condition.notify_all()

    def get(self, job_id: str) -> CamairJob | None:
        with self._lock:
            return self._jobs.get(job_id)

    def all(self) -> list[CamairJob]:
        with self._lock:
            return list(self._jobs.values())

    def follow(self, job_id: str, stop_event: threading.Event, timeout: float = 0.5):
        """Yield each status event for a job, ending once it reaches a final state.

        CAMair holds the stream open, so this blocks on the condition variable
        rather than spinning. It ends the stream on a final status — which the
        protocol treats as a legitimate way to terminate the feedback phase.
        """
        emitted = 0
        while not stop_event.is_set():
            with self._condition:
                job = self._jobs.get(job_id)
                if job is None:
                    return
                pending = deque(job.history[emitted:])
                if not pending:
                    if job.is_final:
                        return
                    self._condition.wait(timeout)
                    continue
                emitted += len(pending)
                final = job.is_final
            yield from pending
            if final:
                return
