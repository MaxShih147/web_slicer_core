#!/usr/bin/env bash
# M1 close-out: clean-env three crashes + strip + scanner.
# Assumes slicer-engine already built at third_party/prusaslicer_build/src/slicer-engine
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../../../.." && pwd)"
POC="$(cd "$(dirname "$0")" && pwd)"
SRC="$ROOT/third_party/prusaslicer_build/src"
STL="${POC_STL:-$ROOT/agent/jobs/5731d266/input/model.stl}"
INI="${POC_INI:-$ROOT/agent/jobs/5731d266/config.ini}"
DIAG="$HOME/Library/Logs/DiagnosticReports"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
RUN="$POC/evidence/m1-close-$STAMP"
HIDE="/tmp/m1-hide-slicer-$STAMP"
WORK="$RUN/work"
mkdir -p "$RUN/ips" "$WORK" "$HIDE"

BIN_SRC="$SRC/slicer-engine"
if [[ ! -x "$BIN_SRC" ]]; then
  echo "missing $BIN_SRC" >&2
  exit 1
fi

# Consumer-like artifact:
# 1) dSYM from unstripped → archive under $HIDE (never Spotlight-visible during crash)
# 2) strip consumer binary
# 3) patch LC_UUID so ReportCrash cannot reuse CoreSymbolication cache / leftover
#    same-UUID dSYM from earlier PoC runs (2026-07-17: without patch, Slic3r::
#    reappeared even when mdfind reported 0 dSYMs)
# 4) ad-hoc codesign with slicer-engine identifier
cp -f "$BIN_SRC" "$WORK/slicer-engine.unstripped"
cp -f "$BIN_SRC" "$WORK/slicer-engine"
if command -v dsymutil >/dev/null; then
  dsymutil "$WORK/slicer-engine" -o "$WORK/slicer-engine.dSYM" 2>/dev/null || true
  mv "$WORK/slicer-engine.dSYM" "$HIDE/slicer-engine.dSYM" 2>/dev/null || true
fi
strip "$WORK/slicer-engine"
mv "$WORK/slicer-engine.unstripped" "$HIDE/slicer-engine.unstripped"

python3 - "$WORK/slicer-engine" <<'PY'
import struct, sys, uuid
from pathlib import Path
path = Path(sys.argv[1])
data = bytearray(path.read_bytes())
assert data[:4] == b"\xcf\xfa\xed\xfe", "expected thin Mach-O arm64/x64"
ncmds = struct.unpack_from("<I", data, 16)[0]
off = 32
old = new = None
for _ in range(ncmds):
    cmd, cmdsize = struct.unpack_from("<II", data, off)
    if cmd == 0x1B:  # LC_UUID
        old = bytes(data[off + 8 : off + 24])
        new = uuid.uuid4().bytes
        data[off + 8 : off + 24] = new
        break
    off += cmdsize
if new is None:
    raise SystemExit("LC_UUID not found")
path.write_bytes(data)
print(f"uuid_patch {old.hex()} -> {new.hex()}")
PY

codesign --force --sign - --identifier slicer-engine "$WORK/slicer-engine" 2>/dev/null || true
codesign --force --sign - --identifier slicer-engine "$HIDE/slicer-engine.unstripped" 2>/dev/null || true

{
  echo "unstripped_global=$(nm -gU "$HIDE/slicer-engine.unstripped" | rg -ic 'slic3r|prusa' || echo 0)"
  echo "stripped_global=$(nm -gU "$WORK/slicer-engine" | rg -ic 'slic3r|prusa' || echo 0)"
  echo "stripped_local=$(nm -U "$WORK/slicer-engine" | rg -ic 'slic3r|prusa' || echo 0)"
  dwarfdump --uuid "$WORK/slicer-engine" | head -1
} | tee "$RUN/SYMBOLS.txt"

UUID="$(dwarfdump --uuid "$WORK/slicer-engine" | awk '{print $2}' | head -1)"

# Hide sibling binaries / prior evidence that share UUID.
# Do NOT touch $RUN (current work binary / this run's artifacts).
shopt -s nullglob
for p in "$SRC"/slicer-engine "$SRC"/PrusaSlicer \
         "$POC"/evidence/*/bin/slicer-engine* \
         "$POC"/evidence/*/work/slicer-engine* \
         "$POC"/evidence/*/slicer-engine.dSYM; do
  [[ -e "$p" ]] || continue
  case "$p" in
    "$RUN"/*) continue ;;
  esac
  base=$(basename "$p")
  dest="$HIDE/${base}.$(echo "$p" | shasum | awk '{print $1}')"
  mv "$p" "$dest" 2>/dev/null || true
done

# Wait until Spotlight no longer finds a dSYM for this UUID
if [[ -n "${UUID:-}" ]]; then
  for i in $(seq 1 30); do
    hits=$(mdfind "com_apple_xcode_dsym_uuids == $UUID" 2>/dev/null || true)
    [[ -z "${hits}" ]] && break
    # If hits are only under $HIDE, move further or ignore once gone from indexed paths
    only_hide=1
    while IFS= read -r h; do
      [[ -z "$h" ]] && continue
      case "$h" in
        "$HIDE"*) ;;
        *) only_hide=0; echo "WARN still indexed: $h" >&2 ;;
      esac
    done <<< "$hits"
    [[ "$only_hide" -eq 1 && -z "$(echo "$hits" | grep -v "^$HIDE" || true)" ]] && break
    # Force: if anything outside HIDE, we already moved; sleep for index lag
    sleep 0.5
  done
  echo "mdfind_dsym_after_hide=$(mdfind "com_apple_xcode_dsym_uuids == $UUID" 2>/dev/null | wc -l | tr -d ' ')" | tee -a "$RUN/SYMBOLS.txt"
fi

cleanup() {
  mkdir -p "$SRC" "$RUN"
  # Restore build-tree binaries
  for p in "$HIDE"/*; do
    [[ -e "$p" ]] || continue
    name=$(basename "$p")
    if [[ "$name" == slicer-engine.* ]] && [[ "$name" != *.dSYM ]] && [[ "$name" != *unstripped* ]] && [[ ! -e "$SRC/slicer-engine" ]]; then
      # hashed hide names look like slicer-engine.<sha>
      if [[ "$name" =~ ^slicer-engine\.[0-9a-f]{40}$ ]]; then
        mv "$p" "$SRC/slicer-engine" || true
      fi
    elif [[ "$name" == PrusaSlicer.* ]] && [[ ! -e "$SRC/PrusaSlicer" ]]; then
      mv "$p" "$SRC/PrusaSlicer" || true
    fi
  done
  # Archive dSYM + unstripped into evidence AFTER crashes (optional; keep for engineers)
  if [[ -d "$HIDE/slicer-engine.dSYM" ]] && [[ ! -e "$RUN/slicer-engine.dSYM" ]]; then
    mv "$HIDE/slicer-engine.dSYM" "$RUN/slicer-engine.dSYM" || true
  fi
  if [[ -f "$HIDE/slicer-engine.unstripped" ]] && [[ ! -e "$RUN/work/slicer-engine.unstripped" ]]; then
    mkdir -p "$RUN/work"
    mv "$HIDE/slicer-engine.unstripped" "$RUN/work/slicer-engine.unstripped" || true
  fi
}
trap cleanup EXIT

capture() {
  local mode="$1"
  local marker; marker=$(mktemp)
  sleep 1
  set +e
  BUNDLE_QA_CRASH_MODE="$mode" "$WORK/slicer-engine" --export-sla --load "$INI" "$STL" \
    >"$RUN/ips/${mode}.log" 2>&1
  echo exit=$? >>"$RUN/ips/${mode}.log"
  set -e
  local f="" i
  for i in $(seq 1 50); do
    f=$(find "$DIAG" -maxdepth 1 -name 'slicer-engine*.ips' -newer "$marker" 2>/dev/null | head -1 || true)
    [[ -n "${f:-}" ]] && break
    sleep 0.4
  done
  rm -f "$marker"
  if [[ -n "${f:-}" ]]; then
    cp "$f" "$RUN/ips/${mode}.ips"
    echo "OK $mode <- $f"
  else
    echo "MISSING $mode" | tee "$RUN/ips/${mode}.MISSING.txt"
    tail -15 "$RUN/ips/${mode}.log" || true
  fi
}

for mode in overflow segfault exception; do
  capture "$mode"
done

IPS_ARGS=()
for mode in overflow segfault exception; do
  [[ -f "$RUN/ips/${mode}.ips" ]] && IPS_ARGS+=("$RUN/ips/${mode}.ips")
done

set +e
if [[ ${#IPS_ARGS[@]} -gt 0 ]]; then
  "$POC/scan_macos_artifact.sh" "$WORK/slicer-engine" "${IPS_ARGS[@]}" | tee "$RUN/SCAN.json"
else
  "$POC/scan_macos_artifact.sh" "$WORK/slicer-engine" | tee "$RUN/SCAN.json"
fi
SCAN_RC=$?
set -e

# Also scan unstripped for comparison note (still under $HIDE until cleanup)
UNSTRIPPED="$HIDE/slicer-engine.unstripped"
[[ -f "$UNSTRIPPED" ]] || UNSTRIPPED="$RUN/work/slicer-engine.unstripped"
if [[ -f "$UNSTRIPPED" ]]; then
  "$POC/scan_macos_artifact.sh" "$UNSTRIPPED" >"$RUN/SCAN_unstripped.json" || true
fi

python3 - "$RUN" "$SCAN_RC" <<'PY'
import json, pathlib, sys
run = pathlib.Path(sys.argv[1])
rc = int(sys.argv[2])
scan = json.loads((run/"SCAN.json").read_text())
lines = [
  f"# M1 close run `{run.name}`",
  "",
  f"- scanner exit: **{rc}** ({scan.get('verdict')})",
  f"- stripped nm global brand: **{scan.get('nm_global_brand')}**",
  f"- stripped nm local brand: **{scan.get('nm_local_brand')}**",
  f"- codesign Identifier: `{scan.get('codesign_identifier')}`",
  "",
  "## .ips",
]
for e in scan.get("ips", []):
    lines.append(f"### {pathlib.Path(e['file']).name}")
    lines.append(f"- procName=`{e.get('procName')}` codeSigningID=`{e.get('codeSigningID')}`")
    lines.append(f"- Slic3r::={e.get('Slic3r_namespace')} slic3r_main={e['tokens'].get('slic3r_main')} prusaslicer={e['tokens'].get('prusaslicer')}")
    lines.append(f"- threads={e.get('threads')}")
    lines.append("")
if scan.get("notes"):
    lines.append("## Notes / FAIL reasons")
    for n in scan["notes"]:
        lines.append(f"- {n}")
(run/"SUMMARY.md").write_text("\n".join(lines)+"\n")
print("\n".join(lines))
sys.exit(rc)
PY
