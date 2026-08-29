#!/usr/bin/env bash
# Regenerate the CAMair protobuf/gRPC stubs from the vendored .proto files.
#
# Run this after refreshing agent/camair/proto/ from a new 3Shape partner
# package, or after bumping grpcio — the generated code is tied to the protobuf
# runtime version.
#
# The two passes are deliberate. The v1 protos import each other by bare name
# ("CAMairDataTypes.proto"), so protoc needs proto/v1 on its include path; but
# passing both proto/ and proto/v1/ at once makes every v1 file reachable by two
# paths and protoc rejects it as a duplicate definition.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROTO_DIR="$REPO_ROOT/agent/camair/proto"
OUT_DIR="$REPO_ROOT/agent/camair/_generated"
PYTHON="${PYTHON:-$REPO_ROOT/.venv/bin/python}"

rm -rf "$OUT_DIR"
mkdir -p "$OUT_DIR"

echo "Generating version-independent layer..."
"$PYTHON" -m grpc_tools.protoc \
  -I "$PROTO_DIR" \
  --python_out="$OUT_DIR" --grpc_python_out="$OUT_DIR" \
  "$PROTO_DIR"/*.proto

echo "Generating v1 layer..."
"$PYTHON" -m grpc_tools.protoc \
  -I "$PROTO_DIR/v1" \
  --python_out="$OUT_DIR" --grpc_python_out="$OUT_DIR" \
  "$PROTO_DIR"/v1/*.proto

echo "Done: $(find "$OUT_DIR" -name '*.py' | wc -l | tr -d ' ') files in $OUT_DIR"
