#!/usr/bin/env bash
# Stage AGPL legal materials into a slicer-engine artifact (tasks 6.2／6.3).
# Filenames intentionally avoid *prusa* / *slic3r* so path scanners stay green;
# file *contents* may name the upstream project (blacklist §4 exemption).
#
# Usage:
#   ./scripts/stage_slicer_engine_agpl_macos.sh <artifact-root>
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
ART_ROOT="${1:?artifact root required}"
ART_ROOT="$(cd "$ART_ROOT" && pwd)"
SRC="$ROOT_DIR/legal/slicer-engine-agpl"
DEST="$ART_ROOT/legal"
FORK="$ROOT_DIR/third_party/prusaslicer_fork"
MANIFEST="$ART_ROOT/engine-artifact-manifest.json"

[[ -d "$SRC" ]] || { echo "[ERROR] missing $SRC" >&2; exit 1; }
[[ -f "$FORK/LICENSE" ]] || { echo "[ERROR] missing fork LICENSE" >&2; exit 1; }

mkdir -p "$DEST"
cp -f "$FORK/LICENSE" "$DEST/LICENSE"
cp -f "$SRC/NOTICE" "$DEST/NOTICE"
cp -f "$SRC/MODIFICATIONS.md" "$DEST/MODIFICATIONS.md"
cp -f "$SRC/SOURCE-OFFER.md" "$DEST/SOURCE-OFFER.md"

FORK_COMMIT="unknown"
if [[ -d "$FORK/.git" ]]; then
  FORK_COMMIT="$(git -C "$FORK" rev-parse HEAD 2>/dev/null || echo unknown)"
fi

BUILD_ID="unknown"
POST_HASH="unknown"
if [[ -f "$MANIFEST" ]]; then
  BUILD_ID="$(python3 -c "import json;print(json.load(open('$MANIFEST')).get('engine_build_id') or 'unknown')")"
  POST_HASH="$(python3 -c "import json;print(json.load(open('$MANIFEST')).get('post_strip_sha256') or 'unknown')")"
fi

STAMP_FILE="$DEST/BUILD-STAMP.txt"
cat >"$STAMP_FILE" <<EOF
# Stamped at package time — do not edit by hand for released artifacts
engine_build_id=$BUILD_ID
post_strip_sha256=$POST_HASH
fork_commit=$FORK_COMMIT
stamped_at_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)
EOF

# Append stamp block to SOURCE-OFFER for auditors
{
  echo ""
  echo "## Package stamp (auto)"
  echo ""
  echo '```'
  cat "$STAMP_FILE"
  echo '```'
} >>"$DEST/SOURCE-OFFER.md"

echo "[agpl] Staged legal materials → $DEST"
echo "[agpl] fork_commit=$FORK_COMMIT build_id=$BUILD_ID"
echo "[agpl] WARNING: SOURCE-OFFER still contains REPLACE_WITH_* placeholders until Legal sign-off (1.6)."
