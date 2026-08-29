"""CAMair Partner Integration Component.

Serves the whole conversation Produce has with a manufacturing partner:

  CAMairMajorVersionCheck.GetSupportedMajorVersions  — version handshake
  CAMairIntegration.Connect                          — "I am alive, here are my machines"
  CAMairIntegration.GetNeededData                    — which parts of a case we want
  CAMairIntegration.StartJob                         — receive it (bidi stream)
  CAMairIntegration.GetJobStatuses                   — report progress (server stream)

Both the handshake service and the versioned service MUST be served on the same
port — CAMair runs the handshake first over the same channel.

Accepted cases are handed to agent.camair.processing, which runs them through
the agent's normal slicing pipeline. Pass --no-process to accept and store cases
without slicing them, which is what the protocol-level tests use.

See docs/3shape-camair-integration.md in the DS-Online repo for the plan.

Run:  python -m agent.camair.server [--port 30051] [--jobs-root DIR]
"""

from __future__ import annotations

import argparse
import logging
import threading
import uuid
from concurrent import futures
from pathlib import Path

import grpc

from agent import camair  # noqa: F401  — puts _generated on sys.path
from agent.camair.jobs import JobStore

import CAMairProtocol_pb2  # isort: skip
import CAMairProtocol_pb2_grpc  # isort: skip
import CAMairDataTypes_pb2  # isort: skip
import MajorVersionCheck_pb2  # isort: skip
import MajorVersionCheck_pb2_grpc  # isort: skip

logger = logging.getLogger(__name__)

# Major versions of the CAMair protocol this PIC speaks. Only v1 exists today.
SUPPORTED_MAJOR_VERSIONS = [1]

# Shown as the integration's name in the Produce UI.
PIC_DISPLAY_NAME = "Phrozen SlicerGo Dental"

# PROVISIONAL. JobDescription.machineId arrives FROM 3Shape, so Produce has to
# know these identifiers before a user can pick a Phrozen printer — registering
# them is the one thing only 3Shape can do for us (see the integration doc).
# Until they confirm the real values, these mirror src/data/machines/ in
# DS-Online so the shape of the response is exercisable end to end.
MANUFACTURER_ID = "PHROZEN"
MACHINE_MODEL_IDS = [
    "sonic_4k_2022",
    "sonic_cs_plus",
    "sonic_cs_plus_mini_plate",
    "sonic_ls_plus",
    "sonic_ls_plus_large_plate",
    "sonic_mighty_revo_14k",
    "sonic_mighty_revo_16k",
    "sonic_mini_8k_s",
    "sonic_xl_4k",
    "sonic_xl_4k_2022",
    "sonic_xl_4k_plus",
]

# CAMair de-duplicates integration components by this id across its discovery
# methods, so it has to stay stable for a given install — a fresh uuid on every
# restart would make Produce list us repeatedly.
_PIC_ID_FILE = Path(__file__).parent / ".pic_identifier"


def _pic_identifier() -> str:
    try:
        existing = _PIC_ID_FILE.read_text().strip()
        if existing:
            return existing
    except OSError:
        pass
    generated = str(uuid.uuid4())
    try:
        _PIC_ID_FILE.write_text(generated)
    except OSError:
        logger.warning("Could not persist PIC identifier; Produce may list this component more than once")
    return generated


class MajorVersionCheckService(MajorVersionCheck_pb2_grpc.CAMairMajorVersionCheckServicer):
    """Handshake layer. Deliberately trivial — 3Shape guarantees it never changes."""

    def GetSupportedMajorVersions(self, request, context):
        logger.info("CAMair handshake from %s", context.peer())
        return MajorVersionCheck_pb2.GetSupportedMajorVersionsResponse(
            serverSupportedMajorVersions=SUPPORTED_MAJOR_VERSIONS,
        )


class CAMairIntegrationService(CAMairProtocol_pb2_grpc.CAMairIntegrationServicer):
    def __init__(self, pic_identifier: str, jobs: JobStore, on_job_accepted=None):
        self._pic_identifier = pic_identifier
        self._jobs = jobs
        self._on_job_accepted = on_job_accepted

    def Connect(self, request, context):
        """Called when a user opens the Produce module; a reply means "ready for jobs"."""
        logger.info(
            "Connect from %s (client protocol v%s)",
            context.peer(),
            request.clientProtocolVersion,
        )
        return CAMairProtocol_pb2.ConnectResponse(
            serverProtocolVersion=SUPPORTED_MAJOR_VERSIONS[0],
            machineIds=[
                CAMairDataTypes_pb2.MachineIdentifier(
                    manufacturerId=MANUFACTURER_ID,
                    machineModelId=model_id,
                )
                for model_id in MACHINE_MODEL_IDS
            ],
            picCustomName=PIC_DISPLAY_NAME,
            picIdentifier=self._pic_identifier,
        )

    def GetNeededData(self, request, context):
        """Declare the subset of the case we want. CAMair sends only what we ask for.

        Mesh is what we slice. Material and mountDirection are cheap and inform
        the resin profile and the initial orientation. Indication-specific blocks
        and patientData are left off: we have no use for them yet, and not asking
        for patient data is the better default.
        """
        indication = CAMairDataTypes_pb2.IndicationType.Name(
            request.jobDescription.indicationType,
        ) if request.jobDescription.indicationType else "Unknown"
        logger.info("GetNeededData for %s (%s)", request.jobDescription.caseName, indication)
        return CAMairProtocol_pb2.GetNeededDataResponse(
            mesh=True,
            material=True,
            mountDirection=True,
            patientData=False,
        )

    def StartJob(self, request_iterator, context):
        """Receive the case. Bidirectional: each item is answered as it lands.

        Answering per item rather than after the stream closes is what lets
        CAMair start tracking the first job while later items are still in
        flight, and it is why the RPC is a bidi stream rather than unary.
        """
        for request in request_iterator:
            try:
                job = self._jobs.accept(request.key, request.jobData)
            except ValueError as exc:
                logger.error("Rejected item %s: %s", request.key, exc)
                context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(exc))
                return
            logger.info(
                "Accepted %s (%s, UNN %s-%s) → job %s [%s]",
                job.case_name,
                job.indication,
                request.jobData.jobDescription.unnFrom,
                request.jobData.jobDescription.unnTo,
                job.job_id,
                job.stl_path.name,
            )
            if self._on_job_accepted is not None:
                self._on_job_accepted(job)
            yield CAMairProtocol_pb2.StartJobResponse(jobId=job.job_id, key=job.key)

    def GetJobStatuses(self, request, context):
        """Stream this job's status transitions until it reaches a final state."""
        if self._jobs.get(request.jobId) is None:
            context.abort(grpc.StatusCode.NOT_FOUND, f"Unknown jobId {request.jobId}")
            return

        logger.info("Status stream opened for %s", request.jobId)
        stop = threading.Event()
        # CAMair may walk away mid-stream; without this the follow() generator
        # would keep waiting on the condition variable for a job nobody wants.
        context.add_callback(stop.set)

        for event in self._jobs.follow(request.jobId, stop):
            response = CAMairProtocol_pb2.JobStatusResponse(currentStatus=event.status)
            response.timeStamp.FromDatetime(event.at)
            if event.message:
                response.message = event.message
            if event.percentage is not None:
                response.percentageProgress = event.percentage
            logger.info(
                "  %s → %s%s",
                request.jobId,
                CAMairDataTypes_pb2.JobStatus.Name(event.status),
                f" ({event.percentage}%)" if event.percentage is not None else "",
            )
            yield response


DEFAULT_JOBS_ROOT = Path(__file__).parent / "received_jobs"


def build_server(
    port: int,
    jobs_root: Path | None = None,
    max_workers: int = 8,
    on_job_accepted=None,
) -> tuple[grpc.Server, str, JobStore]:
    """Wire both services onto one insecure port and return the unstarted server.

    max_workers has to leave room for the long-lived status streams: each open
    GetJobStatuses occupies a pool thread for the life of the job, so a pool
    sized for unary calls alone would deadlock once a few jobs are in flight.
    """
    pic_identifier = _pic_identifier()
    jobs = JobStore(jobs_root or DEFAULT_JOBS_ROOT)

    server = grpc.server(futures.ThreadPoolExecutor(max_workers=max_workers))
    MajorVersionCheck_pb2_grpc.add_CAMairMajorVersionCheckServicer_to_server(
        MajorVersionCheckService(), server,
    )
    CAMairProtocol_pb2_grpc.add_CAMairIntegrationServicer_to_server(
        CAMairIntegrationService(pic_identifier, jobs, on_job_accepted), server,
    )
    # Plaintext for now. A cloud PIC needs SslCredentials plus an OAuth 2.0
    # token checked per method; a local PIC stays on the LAN.
    bound = server.add_insecure_port(f"127.0.0.1:{port}")
    if bound == 0:
        raise RuntimeError(f"Could not bind port {port}")
    return server, pic_identifier, jobs


def serve(port: int, jobs_root: Path | None = None, process: bool = True) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    on_accepted = None
    if process:
        from agent.camair.processing import JobProcessor

        processor = JobProcessor()
        on_accepted = processor.submit

    server, pic_identifier, jobs = build_server(port, jobs_root, on_job_accepted=on_accepted)
    if on_accepted is not None:
        processor.bind(jobs)

    server.start()
    logger.info(
        "CAMair PIC listening on 127.0.0.1:%d (picIdentifier=%s, jobs=%s)",
        port, pic_identifier, jobs_root or DEFAULT_JOBS_ROOT,
    )
    server.wait_for_termination()


def main() -> None:
    parser = argparse.ArgumentParser(description="3Shape CAMair Partner Integration Component")
    parser.add_argument("--port", type=int, default=30051, help="gRPC port (default: 30051)")
    parser.add_argument("--jobs-root", type=Path, default=None, help="where received cases are written")
    parser.add_argument(
        "--no-process",
        action="store_true",
        help="accept cases but do not run them; jobs stay at JobReceivedSuccessfully",
    )
    args = parser.parse_args()
    serve(args.port, args.jobs_root, process=not args.no_process)


if __name__ == "__main__":
    main()
