#!/usr/bin/env bash
# macOS PoC: rename + strip + three crash sites + .ips compare
# Usage: ./run_macos_poc.sh [--skip-build] [--static-only]
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../../../.." && pwd)"
BUILD_DIR="$ROOT/third_party/prusaslicer_build"
SRC_BIN_DIR="$BUILD_DIR/src"
POC_DIR="$(cd "$(dirname "$0")" && pwd)"
EVIDENCE="$POC_DIR/evidence"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
RUN_DIR="$EVIDENCE/run-$STAMP"
JOB_STL="${POC_STL:-$ROOT/agent/jobs/5731d266/input/model.stl}"
JOB_INI="${POC_INI:-$ROOT/agent/jobs/5731d266/config.ini}"
DIAG="$HOME/Library/Logs/DiagnosticReports"
SKIP_BUILD=0
STATIC_ONLY=0

for arg in "$@"; do
  case "$arg" in
    --skip-build) SKIP_BUILD=1 ;;
    --static-only) STATIC_ONLY=1 ;;
  esac
done

mkdir -p "$RUN_DIR"/{baseline,poc,ips,scans}
echo "PoC run dir: $RUN_DIR"

scan_binary() {
  local bin="$1" label="$2" out="$3"
  {
    echo "=== label=$label ==="
    echo "path=$bin"
    echo "sha256=$(shasum -a 256 "$bin" | awk '{print $1}')"
    ls -la "$bin"
    file "$bin"
    echo "--- codesign ---"
    codesign -dv --verbose=2 "$bin" 2>&1 || true
    echo "--- nm -gU brand hits ---"
    nm -gU "$bin" 2>/dev/null | rg -i 'slic3r|prusa' | wc -l | awk '{print "global_brand_hits="$1}'
    echo "--- nm -U brand hits ---"
    nm -U "$bin" 2>/dev/null | rg -i 'slic3r|prusa' | wc -l | awk '{print "local_brand_hits="$1}'
    echo "--- sample global ---"
    nm -gU "$bin" 2>/dev/null | rg -i 'slic3r|prusa' | head -15 || true
  } > "$out"
}

wait_ips() {
  local prefix="$1" timeout_s="${2:-20}"
  local started
  started=$(python3 -c 'import time; print(time.time())')
  local deadline=$(( ${started%.*} + timeout_s ))
  while (( $(date +%s) < deadline )); do
    local newest
    newest=$(ls -t "$DIAG"/${prefix}*.ips "$DIAG"/${prefix}*.crash 2>/dev/null | head -1 || true)
    if [[ -n "${newest:-}" ]]; then
      local mtime
      mtime=$(stat -f %m "$newest")
      if (( mtime + 2 >= ${started%.*} )); then
        echo "$newest"
        return 0
      fi
    fi
    sleep 0.4
  done
  return 1
}

scan_ips() {
  local ips="$1" out="$2"
  {
    echo "file=$ips"
    echo "sha256=$(shasum -a 256 "$ips" | awk '{print $1}')"
    echo "--- brand token hits (casefold substring) ---"
    # shellcheck disable=SC2016
    python3 - "$ips" <<'PY'
import re, sys, pathlib
text = pathlib.Path(sys.argv[1]).read_text(errors="replace").casefold()
tokens = [
  "prusaslicer", "prusa-slicer", "prusa3d", "slic3r", "libslic3r",
  "com.prusa3d.slic3r", "slic3r_main", "slic3r_tbb", "prusaslicer_build",
]
for t in tokens:
    print(f"{t}={text.count(t)}")
# show process-ish lines
for line in pathlib.Path(sys.argv[1]).read_text(errors="replace").splitlines():
    if any(k in line for k in ("procName", "procPath", "\"name\"", "codeSigningID", "bundleInfo", "slic3r", "Prusa", "slicer-engine")):
        if len(line) < 400:
            print("LINE:", line)
PY
  } > "$out"
}

run_crash() {
  local bin="$1" mode="$2" label="$3"
  local prefix
  prefix=$(basename "$bin")
  echo "[crash] mode=$mode bin=$bin"
  local log="$RUN_DIR/ips/${label}-${mode}.log"
  # Clear stale sentinel-ish by touching start time via wait_ips
  set +e
  BUNDLE_QA_CRASH_MODE="$mode" \
  BUNDLE_FORCE_PRUSA_STACK_OVERFLOW="$([ "$mode" = overflow ] && echo 1 || echo 0)" \
    "$bin" --export-sla --load "$JOB_INI" "$JOB_STL" >"$log" 2>&1
  local rc=$?
  set -e
  echo "exit=$rc" | tee -a "$log"
  local ips
  if ips=$(wait_ips "$prefix" 25); then
    cp "$ips" "$RUN_DIR/ips/${label}-${mode}.ips"
    scan_ips "$RUN_DIR/ips/${label}-${mode}.ips" "$RUN_DIR/ips/${label}-${mode}.scan.txt"
    echo "[crash] captured $ips"
  else
    echo "[crash] NO .ips for prefix=$prefix mode=$mode (see $log)" | tee "$RUN_DIR/ips/${label}-${mode}.MISSING.txt"
  fi
}

# --- baseline existing PrusaSlicer ---
BASE_BIN="$SRC_BIN_DIR/PrusaSlicer"
if [[ ! -x "$BASE_BIN" ]]; then
  echo "Missing $BASE_BIN — build first"
  exit 1
fi
scan_binary "$BASE_BIN" "baseline-PrusaSlicer" "$RUN_DIR/scans/00-baseline-PrusaSlicer.txt"

# --- optional rebuild with OUTPUT_NAME=slicer-engine + harness ---
POC_BIN="$SRC_BIN_DIR/slicer-engine"
if [[ "$SKIP_BUILD" -eq 0 ]]; then
  echo "[build] incremental cmake --build PrusaSlicer ..."
  CMAKE_BIN="$ROOT/cmake-3.27.9.app/Contents/bin/cmake"
  if [[ ! -x "$CMAKE_BIN" ]]; then
    CMAKE_BIN="$(command -v cmake)"
  fi
  (
    cd "$BUILD_DIR"
    "$CMAKE_BIN" . >/dev/null
    "$CMAKE_BIN" --build . --target PrusaSlicer -j"$(sysctl -n hw.ncpu)"
  )
  # After OUTPUT_NAME change, product is slicer-engine; keep symlink for tools
  if [[ -x "$POC_BIN" ]]; then
    echo "[build] produced $POC_BIN"
  elif [[ -x "$SRC_BIN_DIR/PrusaSlicer" ]]; then
    echo "[build] OUTPUT_NAME may not have applied; using PrusaSlicer and copying"
    cp -f "$SRC_BIN_DIR/PrusaSlicer" "$POC_BIN"
  else
    echo "[build] FAILED to find binary"
    exit 1
  fi
else
  if [[ ! -x "$POC_BIN" ]]; then
    echo "[skip-build] copying PrusaSlicer → slicer-engine for rename PoC"
    cp -f "$BASE_BIN" "$POC_BIN"
  fi
fi

# Ad-hoc sign with neutral identifier
codesign --force --sign - --identifier slicer-engine "$POC_BIN" 2>/dev/null || true
scan_binary "$POC_BIN" "poc-slicer-engine-unstripped" "$RUN_DIR/scans/01-poc-unstripped.txt"

# Strip copy for consumer-like artifact
STRIPPED="$RUN_DIR/poc/slicer-engine.stripped"
cp -f "$POC_BIN" "$STRIPPED"
# Prefer dsymutil then strip if available
if command -v dsymutil >/dev/null; then
  dsymutil "$STRIPPED" -o "$RUN_DIR/poc/slicer-engine.dSYM" 2>/dev/null || true
fi
strip -x "$STRIPPED"
codesign --force --sign - --identifier slicer-engine "$STRIPPED" 2>/dev/null || true
scan_binary "$STRIPPED" "poc-slicer-engine-stripped" "$RUN_DIR/scans/02-poc-stripped.txt"

# Diff brand hit counts
{
  echo "=== brand hit summary ==="
  rg 'brand_hits=' "$RUN_DIR/scans"/*.txt || true
} | tee "$RUN_DIR/scans/SUMMARY.txt"

if [[ "$STATIC_ONLY" -eq 1 ]]; then
  echo "Static-only done: $RUN_DIR"
  exit 0
fi

# Dynamic crashes: prefer stripped consumer-like binary for post evidence;
# also run one baseline overflow on original name if still present.
if [[ -x "$BASE_BIN" ]]; then
  run_crash "$BASE_BIN" overflow "baseline"
fi
for mode in overflow segfault exception; do
  run_crash "$STRIPPED" "$mode" "stripped"
done

# Write report stub
REPORT="$RUN_DIR/REPORT.md"
{
  echo "# macOS PoC run $STAMP"
  echo
  echo "- job stl: \`$JOB_STL\`"
  echo "- job ini: \`$JOB_INI\`"
  echo "- evidence: \`$RUN_DIR\`"
  echo
  echo "## Static brand hits"
  cat "$RUN_DIR/scans/SUMMARY.txt"
  echo
  echo "## Crash artifacts"
  ls -la "$RUN_DIR/ips" || true
} > "$REPORT"

echo "Done. Report: $REPORT"
