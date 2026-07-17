#!/usr/bin/env bash
# Stage consumer slicer-engine layout for macOS (tasks 5.1 / 5.4 / D13).
# dSYM archive → plain strip → codesign identifier → artifact-manifest.json
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BUILD_SRC="${1:-$ROOT_DIR/third_party/prusaslicer_build/src}"
OUT_ROOT="${2:-$ROOT_DIR/slicer-engine}"
FLAVOR="${3:-consumer}"
BIN_NAME="slicer-engine"

SRC_BIN=""
for candidate in "$BUILD_SRC/$BIN_NAME" "$BUILD_SRC/prusa-slicer"; do
  if [[ -f "$candidate" ]]; then
    SRC_BIN="$candidate"
    break
  fi
done
if [[ -z "$SRC_BIN" ]]; then
  echo "[ERROR] Missing slicer-engine binary under $BUILD_SRC"
  echo "Build first: ./scripts/build_prusaslicer_fork_macos.sh"
  exit 1
fi

BIN_DIR="$OUT_ROOT/bin"
SYM_DIR="$OUT_ROOT/symbols"
rm -rf "$OUT_ROOT"
mkdir -p "$BIN_DIR" "$SYM_DIR"

DST_BIN="$BIN_DIR/$BIN_NAME"
cp -f "$SRC_BIN" "$DST_BIN"
chmod +x "$DST_BIN"

# Ensure resources next to binary
RES_SRC="$ROOT_DIR/third_party/prusaslicer_fork/resources"
if [[ -d "$RES_SRC" ]]; then
  rm -rf "$BIN_DIR/resources"
  cp -R "$RES_SRC" "$BIN_DIR/resources"
fi

sha256_file() {
  shasum -a 256 "$1" | awk '{print $1}'
}

PRE_HASH="$(sha256_file "$DST_BIN")"

# Archive dSYM then strip (plain strip; do NOT use strip -x as L2 sufficiency)
if command -v dsymutil >/dev/null 2>&1; then
  dsymutil "$DST_BIN" -o "$SYM_DIR/${BIN_NAME}.dSYM"
fi
strip "$DST_BIN"

# Neutral codeSigningID when signing identity available (optional locally)
if command -v codesign >/dev/null 2>&1; then
  if codesign -s - --force --identifier "$BIN_NAME" "$DST_BIN" 2>/dev/null; then
    echo "[OK] ad-hoc codesign identifier=$BIN_NAME"
  else
    echo "[WARN] codesign skipped/failed (CI release must sign with real identity)"
  fi
fi

POST_HASH="$(sha256_file "$DST_BIN")"
BUILD_ID="$(date -u +%Y%m%dT%H%M%SZ)"

# Consumer harness static audit
if [[ "$FLAVOR" == "consumer" ]]; then
  if strings "$DST_BIN" | grep -E 'BUNDLE_QA_CRASH_HARNESS|bundle_qa_crash_probe|BUNDLE_QA_CRASH_MODE' >/dev/null 2>&1; then
    echo "[ERROR] Consumer harness audit FAILED"
    exit 1
  fi
  echo "[OK] Consumer harness audit PASS"
fi

# Thread name brand check (best-effort)
if strings "$DST_BIN" | grep -E 'slic3r_main|slic3r_tbb|slic3r_BgSlcPcs' >/dev/null 2>&1; then
  echo "[WARN] Possible residual brand thread tokens in strings (review tasks 5.2)"
fi

cat > "$OUT_ROOT/artifact-manifest.json" <<EOF
{
  "schema_version": "1.0",
  "build_id": "$BUILD_ID",
  "flavor": "$FLAVOR",
  "platform": "macos",
  "files": [
    {
      "path": "bin/$BIN_NAME",
      "pre_strip_sha256": "$PRE_HASH",
      "post_strip_sha256": "$POST_HASH"
    }
  ],
  "symbols_archived": ["symbols/${BIN_NAME}.dSYM"],
  "notes": "macOS: dSYM archived then plain strip; Launcher must verify post_strip hash only."
}
EOF

echo "[OK] Wrote $OUT_ROOT/artifact-manifest.json"
echo "[OK] Consumer staging: $DST_BIN"
echo "export SLICER_ENGINE_BIN=$DST_BIN"
