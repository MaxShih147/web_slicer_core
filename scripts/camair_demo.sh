#!/usr/bin/env bash
# Live demo: a case designed in 3Shape Dental Desktop arrives over the CAMair
# protocol, gets sliced, and its progress is reported back — end to end.
#
# The PIC is the real one. Only the 3Shape side is simulated, by
# agent.camair.testclient, using the untouched sample cases 3Shape ships in the
# partner package.
#
#   ./scripts/camair_demo.sh                     # Crown, Inlay and Veneer
#   ./scripts/camair_demo.sh Bridge-8-10         # any case from the package
#   ./scripts/camair_demo.sh --list              # what is available
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON:-$REPO_ROOT/.venv/bin/python}"
PORT="${CAMAIR_PORT:-30051}"
JOBS_ROOT="${CAMAIR_JOBS_ROOT:-/tmp/camair_demo_jobs}"
ENGINE="${SLICER_ENGINE_BIN:-$REPO_ROOT/third_party/prusaslicer_build/src/PrusaSlicer}"

cd "$REPO_ROOT"

if [[ "${1:-}" == "--list" ]]; then
  exec "$PYTHON" -m agent.camair.testclient --list
fi

CASES=("$@")
if [[ ${#CASES[@]} -eq 0 ]]; then
  CASES=(Crown-19 Inlay-4 Veneer-5)
fi

if [[ ! -x "$ENGINE" ]]; then
  echo "Slicing engine not found at $ENGINE" >&2
  echo "Build it, or point SLICER_ENGINE_BIN at one." >&2
  exit 1
fi

# A stale listener would make the client talk to the wrong build.
if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN -t >/dev/null 2>&1; then
  echo "Port $PORT is already in use; stopping the old PIC."
  lsof -nP -iTCP:"$PORT" -sTCP:LISTEN -t | xargs kill
  sleep 1
fi

rm -rf "$JOBS_ROOT"
SERVER_LOG="$(mktemp -t camair_pic).log"

echo "── Starting the Partner Integration Component on port $PORT"
SLICER_ENGINE_BIN="$ENGINE" "$PYTHON" -m agent.camair.server \
  --port "$PORT" --jobs-root "$JOBS_ROOT" >"$SERVER_LOG" 2>&1 &
SERVER_PID=$!
trap 'kill "$SERVER_PID" 2>/dev/null || true' EXIT

for _ in $(seq 40); do
  lsof -nP -iTCP:"$PORT" -sTCP:LISTEN -t >/dev/null 2>&1 && break
  sleep 0.25
done

echo "── Simulating 3Shape Produce: ${CASES[*]}"
echo
CLIENT_ARGS=()
for case_name in "${CASES[@]}"; do
  CLIENT_ARGS+=(--case "$case_name")
done
"$PYTHON" -m agent.camair.testclient --port "$PORT" "${CLIENT_ARGS[@]}"

echo
echo "── What the component produced"
for dir in "$JOBS_ROOT"/*/; do
  [[ -d "$dir" ]] || continue
  job_id="$(basename "$dir")"
  indication="$("$PYTHON" -c "import json,sys; print(json.load(open(sys.argv[1]))['indication'])" "$dir/meta.json")"
  sliced="$REPO_ROOT/agent/jobs/$job_id/output/model.sl1"
  printf '  %-12s %s\n' "$indication" "$job_id"
  printf '    received : %s\n' "$(du -h "$dir/model.stl" | cut -f1) STL"
  if [[ -f "$dir/facet_marks.json" ]]; then
    printf '    marks    : %s\n' \
      "$("$PYTHON" -c "import json,sys; print(', '.join(json.load(open(sys.argv[1]))))" "$dir/facet_marks.json")"
  fi
  if [[ -f "$sliced" ]]; then
    layers="$("$PYTHON" -c "import json,sys; print(json.load(open(sys.argv[1])).get('layer_count'))" \
      "$REPO_ROOT/agent/jobs/$job_id/status.json")"
    printf '    sliced   : %s, %s layers\n' "$(du -h "$sliced" | cut -f1)" "$layers"
  fi
done

echo
echo "Server log: $SERVER_LOG"
