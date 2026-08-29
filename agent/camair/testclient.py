"""Stand-in for 3Shape's ThreeShape.CAMair.API.TestClient.

Plays the CAMair side of the conversation so the PIC can be exercised without
3Shape's software — and without a .NET toolchain, which their C# client needs.

Right now it covers the Stage 1 surface: the version handshake followed by
Connect. Stage 2/3 add GetNeededData, StartJob and the job-status stream, at
which point this should also learn to load examples/TestData/*.json.zip from the
partner package.

Run:  python -m agent.camair.testclient [--host 127.0.0.1] [--port 30051]
Exits non-zero if any phase fails, so CI can use it as a smoke test.
"""

from __future__ import annotations

import argparse
import sys

import grpc

from agent import camair  # noqa: F401  — puts _generated on sys.path

import CAMairProtocol_pb2  # isort: skip
import CAMairProtocol_pb2_grpc  # isort: skip
import MajorVersionCheck_pb2  # isort: skip
import MajorVersionCheck_pb2_grpc  # isort: skip


def run(host: str, port: int) -> int:
    target = f"{host}:{port}"
    print(f"→ connecting to {target}")

    with grpc.insecure_channel(target) as channel:
        try:
            grpc.channel_ready_future(channel).result(timeout=5)
        except grpc.FutureTimeoutError:
            print(f"✗ no gRPC server reachable at {target}")
            return 1

        # Phase 1 — handshake. CAMair always runs this first to pick a protocol
        # version, over the same channel and port as everything else.
        handshake = MajorVersionCheck_pb2_grpc.CAMairMajorVersionCheckStub(channel)
        versions = handshake.GetSupportedMajorVersions(
            MajorVersionCheck_pb2.GetSupportedMajorVersionsRequest(),
        ).serverSupportedMajorVersions
        print(f"✓ GetSupportedMajorVersions → {list(versions)}")
        if not versions:
            print("✗ server advertises no protocol version; CAMair would abort here")
            return 1

        # CAMair picks the highest version both sides support. We only speak v1.
        chosen = max(versions)

        # Phase 2 — Connect. A successful reply is what makes the component show
        # up as available in the Produce UI.
        integration = CAMairProtocol_pb2_grpc.CAMairIntegrationStub(channel)
        reply = integration.Connect(
            CAMairProtocol_pb2.ConnectRequest(clientProtocolVersion=chosen),
        )
        print(f"✓ Connect (client v{chosen}) → server v{reply.serverProtocolVersion}")
        print(f"    picCustomName : {reply.picCustomName}")
        print(f"    picIdentifier : {reply.picIdentifier}")
        print(f"    machines      : {len(reply.machineIds)}")
        for machine in reply.machineIds:
            print(f"      - {machine.manufacturerId} / {machine.machineModelId}")

        if reply.serverProtocolVersion != chosen:
            print("✗ server answered on a version the client did not offer")
            return 1
        if not reply.picIdentifier:
            print("✗ empty picIdentifier — Produce de-duplicates components by this")
            return 1
        if not reply.machineIds:
            print("✗ no machines advertised; Produce would have nothing to offer")
            return 1

    print("\nStage 1 handshake + Connect OK")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="CAMair client simulator (Stage 1)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=30051)
    args = parser.parse_args()
    sys.exit(run(args.host, args.port))


if __name__ == "__main__":
    main()
