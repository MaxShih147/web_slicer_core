"""Stand-in for 3Shape's ThreeShape.CAMair.API.TestClient.

Plays the CAMair side of the conversation so the PIC can be exercised without
3Shape's software — and without a .NET toolchain, which their C# client needs.

Walks the same three phases Produce does:

  1. Connection check  — GetSupportedMajorVersions, then Connect
  2. Data transfer     — GetNeededData, then StartJob
  3. Feedback          — GetJobStatuses until the job reaches a final state

Cases come from the partner package's examples/TestData/*.json.zip, whose JSON
is the protobuf JSON mapping of a JobData message, so it parses straight into
the generated type.

Run:  python -m agent.camair.testclient --case Crown-19
      python -m agent.camair.testclient --case Crown-19 --case Inlay-4
      python -m agent.camair.testclient --list
Exits non-zero if any phase fails, so CI can use it as a smoke test.
"""

from __future__ import annotations

import argparse
import sys
import zipfile
from pathlib import Path

import grpc
from google.protobuf import json_format

from agent import camair  # noqa: F401  — puts _generated on sys.path

import CAMairProtocol_pb2  # isort: skip
import CAMairDataTypes_pb2  # isort: skip
import CAMairProtocol_pb2_grpc  # isort: skip
import MajorVersionCheck_pb2  # isort: skip
import MajorVersionCheck_pb2_grpc  # isort: skip

# The partner package lives in the DS-Online checkout beside this repo.
DEFAULT_TESTDATA = (
    Path(__file__).resolve().parents[3]
    / "DS-Online"
    / "partnerPackage-1.6.0.2025_07_18-14_31_35"
    / "examples"
    / "TestData"
)


def load_case(testdata_dir: Path, name: str):
    """Parse one examples/TestData case into a JobData message."""
    archive = testdata_dir / f"{name}.json.zip"
    if not archive.exists():
        raise FileNotFoundError(f"No such case: {archive}")
    with zipfile.ZipFile(archive) as zf:
        raw = zf.read(zf.namelist()[0]).decode("utf-8")
    return json_format.Parse(raw, CAMairProtocol_pb2.JobData())


def _describe(job_data) -> str:
    d = job_data.jobDescription
    indication = CAMairDataTypes_pb2.IndicationType.Name(d.indicationType) if d.indicationType else "?"
    return (
        f"{indication} UNN {d.unnFrom}-{d.unnTo}, "
        f"{len(job_data.mesh.vertices)} verts / {len(job_data.mesh.facets)} facets, "
        f"material {job_data.material.id!r}"
    )


def run(host: str, port: int, testdata_dir: Path, case_names: list[str], follow: bool) -> int:
    target = f"{host}:{port}"
    print(f"→ connecting to {target}")

    with grpc.insecure_channel(target) as channel:
        try:
            grpc.channel_ready_future(channel).result(timeout=5)
        except grpc.FutureTimeoutError:
            print(f"✗ no gRPC server reachable at {target}")
            return 1

        # ---- Phase 1: connection check -------------------------------------
        # CAMair always runs the handshake first, over the same channel and port.
        handshake = MajorVersionCheck_pb2_grpc.CAMairMajorVersionCheckStub(channel)
        versions = handshake.GetSupportedMajorVersions(
            MajorVersionCheck_pb2.GetSupportedMajorVersionsRequest(),
        ).serverSupportedMajorVersions
        print(f"✓ GetSupportedMajorVersions → {list(versions)}")
        if not versions:
            print("✗ server advertises no protocol version; CAMair would abort here")
            return 1
        chosen = max(versions)

        integration = CAMairProtocol_pb2_grpc.CAMairIntegrationStub(channel)
        connected = integration.Connect(
            CAMairProtocol_pb2.ConnectRequest(clientProtocolVersion=chosen),
        )
        print(f"✓ Connect (client v{chosen}) → server v{connected.serverProtocolVersion}")
        print(f"    picCustomName : {connected.picCustomName}")
        print(f"    picIdentifier : {connected.picIdentifier}")
        print(f"    machines      : {len(connected.machineIds)}")
        if not connected.picIdentifier or not connected.machineIds:
            print("✗ Connect reply is missing picIdentifier or machines")
            return 1

        if not case_names:
            print("\nConnection check OK (no cases requested)")
            return 0

        # ---- Phase 2: data transfer ----------------------------------------
        cases = []
        for name in case_names:
            job_data = load_case(testdata_dir, name)
            print(f"\n▸ {name}: {_describe(job_data)}")

            needed = integration.GetNeededData(
                CAMairProtocol_pb2.GetNeededDataRequest(jobDescription=job_data.jobDescription),
            )
            wanted = [f.name for f, v in needed.ListFields() if v is True]
            print(f"✓ GetNeededData → {wanted or ['(nothing)']}")

            # Produce sends only what the component asked for. Mirroring that
            # here is what makes this a real test of GetNeededData rather than a
            # dump of everything we happen to have.
            trimmed = CAMairProtocol_pb2.JobData(jobDescription=job_data.jobDescription)
            if needed.mesh:
                trimmed.mesh.CopyFrom(job_data.mesh)
            if needed.material:
                trimmed.material.CopyFrom(job_data.material)
            if needed.mountDirection:
                trimmed.mountDirection.CopyFrom(job_data.mountDirection)
            if not needed.patientData:
                trimmed.jobDescription.ClearField("patientData")
            cases.append((name, trimmed))

        def requests():
            for name, trimmed in cases:
                yield CAMairProtocol_pb2.StartJobRequest(key=name, jobData=trimmed)

        started = {}
        for reply in integration.StartJob(requests()):
            print(f"✓ StartJob {reply.key} → jobId {reply.jobId}")
            started[reply.jobId] = reply.key
        if len(started) != len(cases):
            print(f"✗ expected {len(cases)} StartJob replies, got {len(started)}")
            return 1

        if not follow:
            print("\nData transfer OK (not following job status)")
            return 0

        # ---- Phase 3: manufacturing feedback -------------------------------
        failed = []
        for job_id, key in started.items():
            print(f"\n▸ status stream for {key} ({job_id})")
            last = None
            for update in integration.GetJobStatuses(
                CAMairProtocol_pb2.JobStatusRequest(clientProtocolVersion=chosen, jobId=job_id),
            ):
                last = update.currentStatus
                name = CAMairDataTypes_pb2.JobStatus.Name(update.currentStatus)
                pct = f" {update.percentageProgress}%" if update.HasField("percentageProgress") else ""
                msg = f" — {update.message}" if update.HasField("message") else ""
                print(f"    {name}{pct}{msg}")
            if last != CAMairDataTypes_pb2.JobStatus.JobFinishedSuccessfully:
                failed.append(key)

        if failed:
            print(f"\n✗ did not finish successfully: {', '.join(failed)}")
            return 1

    print("\nAll phases OK")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="CAMair client simulator")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=30051)
    parser.add_argument("--testdata", type=Path, default=DEFAULT_TESTDATA)
    parser.add_argument(
        "--case", action="append", default=[], metavar="NAME",
        help="case to send, e.g. Crown-19; repeatable. Omit to only run the connection check",
    )
    parser.add_argument("--no-follow", action="store_true", help="skip the job status stream")
    parser.add_argument("--list", action="store_true", help="list available cases and exit")
    args = parser.parse_args()

    if args.list:
        for archive in sorted(args.testdata.glob("*.json.zip")):
            print(archive.name.replace(".json.zip", ""))
        sys.exit(0)

    sys.exit(run(args.host, args.port, args.testdata, args.case, not args.no_follow))


if __name__ == "__main__":
    main()
