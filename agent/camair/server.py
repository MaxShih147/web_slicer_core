"""Minimal CAMair Partner Integration Component (Stage 1).

Implements the two RPCs CAMair calls before it will show us as an available
manufacturing target:

  CAMairMajorVersionCheck.GetSupportedMajorVersions  — version handshake
  CAMairIntegration.Connect                          — "I am alive, here are my machines"

The data-transfer and job-status RPCs are declared but answer UNIMPLEMENTED for
now; they arrive in Stage 2/3. See docs/3shape-camair-integration.md in the
DS-Online repo for the full plan.

Both the handshake service and the versioned service MUST be served on the same
port — CAMair runs the handshake first over the same channel.

Run:  python -m agent.camair.server [--port 30051]
"""

from __future__ import annotations

import argparse
import logging
import uuid
from concurrent import futures
from pathlib import Path

import grpc

from agent import camair  # noqa: F401  — puts _generated on sys.path

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
    def __init__(self, pic_identifier: str):
        self._pic_identifier = pic_identifier

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
        context.abort(grpc.StatusCode.UNIMPLEMENTED, "GetNeededData arrives in Stage 2")

    def StartJob(self, request_iterator, context):
        context.abort(grpc.StatusCode.UNIMPLEMENTED, "StartJob arrives in Stage 2")

    def GetJobStatuses(self, request, context):
        context.abort(grpc.StatusCode.UNIMPLEMENTED, "GetJobStatuses arrives in Stage 3")


def build_server(port: int, max_workers: int = 4) -> tuple[grpc.Server, str]:
    """Wire both services onto one insecure port and return the unstarted server."""
    pic_identifier = _pic_identifier()
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=max_workers))
    MajorVersionCheck_pb2_grpc.add_CAMairMajorVersionCheckServicer_to_server(
        MajorVersionCheckService(), server,
    )
    CAMairProtocol_pb2_grpc.add_CAMairIntegrationServicer_to_server(
        CAMairIntegrationService(pic_identifier), server,
    )
    # Stage 1 is plaintext. A cloud PIC needs SslCredentials plus an OAuth 2.0
    # token checked per method; a local PIC stays on the LAN.
    bound = server.add_insecure_port(f"127.0.0.1:{port}")
    if bound == 0:
        raise RuntimeError(f"Could not bind port {port}")
    return server, pic_identifier


def serve(port: int) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    server, pic_identifier = build_server(port)
    server.start()
    logger.info("CAMair PIC listening on 127.0.0.1:%d (picIdentifier=%s)", port, pic_identifier)
    server.wait_for_termination()


def main() -> None:
    parser = argparse.ArgumentParser(description="3Shape CAMair Partner Integration Component")
    parser.add_argument("--port", type=int, default=30051, help="gRPC port (default: 30051)")
    serve(parser.parse_args().port)


if __name__ == "__main__":
    main()
