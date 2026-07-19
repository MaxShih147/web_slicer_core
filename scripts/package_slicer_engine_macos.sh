#!/usr/bin/env bash
# D13 productization (tasks 5.1 / 5.4 / 5.6): dSYM archive → plain strip →
# codesign → engine-artifact-manifest.json → formal scan gate.
#
# Does NOT use strip -x (rejected in PoC 2.2). Does NOT ship dSYM with consumer.
#
# Env:
#   SLICER_ENGINE_BUILD_BIN   source Mach-O (default: prusaslicer_build/.../slicer-engine)
#   SLICER_ENGINE_FLAVOR      consumer|qa (default: consumer)
#   SLICER_ENGINE_ARTIFACT_DIR / SLICER_ENGINE_SYMBOLS_DIR
#   SLICER_ENGINE_CONSUMER_EQUIVALENT_BUILD_ID  (qa only; pairs qa→consumer)
#   SKIP_SLICER_ENGINE_SCAN=1  skip fail-closed gate (debug only)
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
FLAVOR="${SLICER_ENGINE_FLAVOR:-consumer}"
BUILD_SRC="${SLICER_ENGINE_BUILD_BIN:-$ROOT_DIR/third_party/prusaslicer_build/src/slicer-engine}"

if [[ -z "${SLICER_ENGINE_ARTIFACT_DIR:-}" ]]; then
  if [[ "$FLAVOR" == "qa" ]]; then
    OUT_ROOT="$ROOT_DIR/third_party/slicer-engine-qa"
  else
    OUT_ROOT="$ROOT_DIR/third_party/slicer-engine"
  fi
else
  OUT_ROOT="$SLICER_ENGINE_ARTIFACT_DIR"
fi

if [[ -z "${SLICER_ENGINE_SYMBOLS_DIR:-}" ]]; then
  if [[ "$FLAVOR" == "qa" ]]; then
    SYMBOLS_ROOT="$ROOT_DIR/third_party/slicer-engine-qa-symbols"
  else
    SYMBOLS_ROOT="$ROOT_DIR/third_party/slicer-engine-symbols"
  fi
else
  SYMBOLS_ROOT="$SLICER_ENGINE_SYMBOLS_DIR"
fi

CONSUMER_EQ_ID="${SLICER_ENGINE_CONSUMER_EQUIVALENT_BUILD_ID:-}"
STAMP="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

BIN_OUT="$OUT_ROOT/bin/slicer-engine"
MANIFEST="$OUT_ROOT/engine-artifact-manifest.json"
DSYM_NAME="slicer-engine.dSYM"

if [[ ! -x "$BUILD_SRC" ]]; then
  echo "[ERROR] Missing built binary: $BUILD_SRC" >&2
  echo "Run ./scripts/build_prusaslicer_fork_macos.sh first." >&2
  exit 1
fi

if [[ "$FLAVOR" != "consumer" && "$FLAVOR" != "qa" ]]; then
  echo "[ERROR] SLICER_ENGINE_FLAVOR must be consumer or qa (got: $FLAVOR)" >&2
  exit 1
fi

echo "[slicer-engine] Packaging macOS artifact (D13)..."
echo "[slicer-engine] Source:  $BUILD_SRC"
echo "[slicer-engine] Output:  $OUT_ROOT"
echo "[slicer-engine] Symbols: $SYMBOLS_ROOT"
echo "[slicer-engine] Flavor:  $FLAVOR"

rm -rf "$OUT_ROOT" "$SYMBOLS_ROOT"
mkdir -p "$OUT_ROOT/bin" "$SYMBOLS_ROOT"

cp -f "$BUILD_SRC" "$BIN_OUT"
cp -f "$BUILD_SRC" "$SYMBOLS_ROOT/slicer-engine.unstripped"

if command -v dsymutil >/dev/null; then
  dsymutil "$BIN_OUT" -o "$OUT_ROOT/bin/$DSYM_NAME"
  mv "$OUT_ROOT/bin/$DSYM_NAME" "$SYMBOLS_ROOT/$DSYM_NAME"
else
  echo "[ERROR] dsymutil not found" >&2
  exit 1
fi

PRE_HASH="$(shasum -a 256 "$BIN_OUT" | awk '{print $1}')"
UUID="$(dwarfdump --uuid "$BIN_OUT" | awk '{print $2}' | head -1)"
if [[ -z "$UUID" ]]; then
  echo "[ERROR] Could not read LC_UUID from $BIN_OUT" >&2
  exit 1
fi

strip "$BIN_OUT"

DSYM_HASH="$(find "$SYMBOLS_ROOT/$DSYM_NAME" -type f -print0 | sort -z | xargs -0 shasum -a 256 | shasum -a 256 | awk '{print $1}')"
UNSTRIPPED_HASH="$(shasum -a 256 "$SYMBOLS_ROOT/slicer-engine.unstripped" | awk '{print $1}')"

codesign --force --sign - --identifier slicer-engine "$BIN_OUT"
POST_HASH="$(shasum -a 256 "$BIN_OUT" | awk '{print $1}')"

ARCH="$(uname -m)"
case "$ARCH" in
  arm64) ARCH_LABEL="arm64" ;;
  x86_64) ARCH_LABEL="x86_64" ;;
  *) ARCH_LABEL="$ARCH" ;;
esac

ENGINE_COMMIT="unknown"
if [[ -d "$ROOT_DIR/third_party/prusaslicer_fork/.git" ]]; then
  ENGINE_COMMIT="$(git -C "$ROOT_DIR/third_party/prusaslicer_fork" rev-parse HEAD 2>/dev/null || echo unknown)"
fi

TOOLCHAIN="$(clang --version 2>/dev/null | head -1 | tr -d '\n' || echo unknown)"
SDK="$(xcrun --show-sdk-path 2>/dev/null || echo unknown)"
BUILD_ID="slicer-engine-${FLAVOR}-${STAMP//[:]/}"

count_brand() {
  local bin="$1" mode="$2"
  if [[ "$mode" == global ]]; then
    nm -gU "$bin" 2>/dev/null | grep -Eic 'slic3r|prusa' || true
  else
    nm -U "$bin" 2>/dev/null | grep -Eic 'slic3r|prusa' || true
  fi
}
GLOBAL_HITS="$(count_brand "$BIN_OUT" global)"
LOCAL_HITS="$(count_brand "$BIN_OUT" local)"
GLOBAL_HITS="${GLOBAL_HITS:-0}"
LOCAL_HITS="${LOCAL_HITS:-0}"

export _PKG_MANIFEST="$MANIFEST"
export _PKG_ENGINE_COMMIT="$ENGINE_COMMIT"
export _PKG_BUILD_ID="$BUILD_ID"
export _PKG_FLAVOR="$FLAVOR"
export _PKG_ARCH="$ARCH_LABEL"
export _PKG_TOOLCHAIN="$TOOLCHAIN; SDK=$SDK"
export _PKG_STAMP="$STAMP"
export _PKG_PRE="$PRE_HASH"
export _PKG_POST="$POST_HASH"
export _PKG_UUID="$UUID"
export _PKG_DSYM_URI="file://$SYMBOLS_ROOT/$DSYM_NAME"
export _PKG_DSYM_HASH="$DSYM_HASH"
export _PKG_UNSTRIPPED_HASH="$UNSTRIPPED_HASH"
export _PKG_GLOBAL="$GLOBAL_HITS"
export _PKG_LOCAL="$LOCAL_HITS"
export _PKG_CONSUMER_EQ="$CONSUMER_EQ_ID"

python3 <<'PY'
import json, os
from pathlib import Path

flavor = os.environ["_PKG_FLAVOR"]
qa_delta = None
if flavor == "qa":
    qa_delta = {
        "harness_compile_flag": "BUNDLE_QA_CRASH_HARNESS",
        "only_differences": ["compile-time crash harness sites"],
        "consumer_equivalent_build_id": os.environ.get("_PKG_CONSUMER_EQ") or None,
    }

doc = {
    "schema_version": "1.0",
    "engine_commit": os.environ["_PKG_ENGINE_COMMIT"],
    "engine_build_id": os.environ["_PKG_BUILD_ID"],
    "flavor": flavor,
    "platform": "macOS",
    "architecture": os.environ["_PKG_ARCH"],
    "toolchain": os.environ["_PKG_TOOLCHAIN"],
    "created_at_utc": os.environ["_PKG_STAMP"],
    "pre_strip_sha256": os.environ["_PKG_PRE"],
    "post_strip_sha256": os.environ["_PKG_POST"],
    "symbol_archive": {
        "kind": "dSYM",
        "uuid_or_guid": os.environ["_PKG_UUID"],
        "archive_uri": os.environ["_PKG_DSYM_URI"],
        "archive_sha256": os.environ["_PKG_DSYM_HASH"],
        "unstripped_sha256": os.environ["_PKG_UNSTRIPPED_HASH"],
    },
    "files": [
        {
            "path": "slicer-engine/bin/slicer-engine",
            "sha256": os.environ["_PKG_POST"],
            "role": "engine_cli",
        }
    ],
    "identity": {
        "macos_codesign_identifier": "slicer-engine",
        "product_version": "Slicer Engine",
    },
    "qa_delta": qa_delta,
    "sbom": {
        "format": "SPDX-2.3-JSON",
        "uri_or_inline_sha256": "pending",
    },
    "approvals": {
        "naming_manifest_version": "1.3",
    },
    "scan_hints": {
        "nm_brand_global": int(os.environ["_PKG_GLOBAL"]),
        "nm_brand_local": int(os.environ["_PKG_LOCAL"]),
    },
}
path = Path(os.environ["_PKG_MANIFEST"])
path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
print(f"[slicer-engine] Wrote {path}")
PY

# Persist build id for qa pairing
echo "$BUILD_ID" >"$OUT_ROOT/engine_build_id.txt"

# Stage de-branded Resources for Apple CLI path (bin/../Resources)
"$ROOT_DIR/scripts/stage_slicer_engine_resources_macos.sh" "$OUT_ROOT"

# AGPL materials (tasks 6.2／6.3) — path names stay neutral; content may name upstream
if [[ "${SKIP_SLICER_ENGINE_AGPL:-0}" != "1" ]]; then
  "$ROOT_DIR/scripts/stage_slicer_engine_agpl_macos.sh" "$OUT_ROOT"
fi

if [[ -e "$OUT_ROOT/bin/$DSYM_NAME" ]]; then
  echo "[ERROR] dSYM leaked into artifact tree" >&2
  exit 1
fi
if find "$OUT_ROOT" \( -iname '*prusa*' -o -iname '*slic3r*' \) | grep -q .; then
  echo "[ERROR] Brand token path under artifact:" >&2
  find "$OUT_ROOT" \( -iname '*prusa*' -o -iname '*slic3r*' \) -print >&2
  exit 1
fi

if [[ "${SKIP_SLICER_ENGINE_SCAN:-0}" != "1" ]]; then
  echo "[slicer-engine] Running formal scan gate (5.4/5.6/5.7)..."
  SLICER_ENGINE_EXPECT_FLAVOR="$FLAVOR" \
    SLICER_ENGINE_SCAN_REPORT_DIR="$OUT_ROOT" \
    "$ROOT_DIR/scripts/scan_slicer_engine_macos.sh" "$OUT_ROOT"
fi

echo "[slicer-engine] =========================================="
echo "[slicer-engine] Package complete"
echo "[slicer-engine]   binary:    $BIN_OUT"
echo "[slicer-engine]   manifest:  $MANIFEST"
echo "[slicer-engine]   flavor:    $FLAVOR"
echo "[slicer-engine]   build_id:  $BUILD_ID"
echo "[slicer-engine]   dSYM:      $SYMBOLS_ROOT/$DSYM_NAME"
echo "[slicer-engine]   legal:     $OUT_ROOT/legal/"
echo "[slicer-engine]   nm brand:  global=$GLOBAL_HITS local=$LOCAL_HITS"
echo "[slicer-engine] =========================================="
echo "[slicer-engine] Use:"
echo "  export SLICER_ENGINE_BIN=$BIN_OUT"
