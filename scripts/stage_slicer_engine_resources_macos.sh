#!/usr/bin/env bash
# Stage de-branded resources next to slicer-engine for macOS Apple path layout.
# Binary at <artifact>/bin/slicer-engine resolves resources via parent/../Resources
# (CLI/Setup.cpp __APPLE__).
#
# Usage:
#   ./scripts/stage_slicer_engine_resources_macos.sh <artifact-root>
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
ART_ROOT="${1:?artifact root required}"
ART_ROOT="$(cd "$ART_ROOT" && pwd)"
RES_SRC="${SLICER_ENGINE_RESOURCES_SRC:-$ROOT_DIR/third_party/prusaslicer_fork/resources}"
DEST="$ART_ROOT/Resources"

if [[ ! -d "$RES_SRC" ]]; then
  echo "[ERROR] resources source missing: $RES_SRC" >&2
  exit 1
fi

rm -rf "$DEST"
mkdir -p "$DEST"

# Copy runtime resources but drop brand-named paths (L1 path gate).
# SLA agent uses --load with job INI; bundled PrusaResearch* profiles/icons are not required.
rsync -a \
  --exclude='*prusa*' --exclude='*Prusa*' \
  --exclude='*slic3r*' --exclude='*Slic3r*' \
  --exclude='*PRUSA*' \
  "$RES_SRC/" "$DEST/"

# Case-sensitive volumes: also expose lowercase alias used by some layouts
if [[ ! -e "$ART_ROOT/resources" ]]; then
  ln -s Resources "$ART_ROOT/resources"
fi

if find "$DEST" \( -iname '*prusa*' -o -iname '*slic3r*' \) 2>/dev/null | grep -q .; then
  echo "[ERROR] brand path remained under Resources after filter:" >&2
  find "$DEST" \( -iname '*prusa*' -o -iname '*slic3r*' \) -print >&2
  exit 1
fi

echo "[OK] Staged de-branded resources -> $DEST"
