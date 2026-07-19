#!/usr/bin/env bash
# Local symbol-archive drill (tasks 5.5 macOS half).
# Verifies consumer has no dSYM, symbols dir has matching UUID, and atos can resolve.
#
# Usage:
#   ./scripts/verify_symbol_archive_macos.sh
#   ./scripts/verify_symbol_archive_macos.sh <artifact-root> <symbols-root>
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
ART_ROOT="${1:-$ROOT_DIR/third_party/slicer-engine}"
SYM_ROOT="${2:-$ROOT_DIR/third_party/slicer-engine-symbols}"
ART_ROOT="$(cd "$ART_ROOT" && pwd)"
SYM_ROOT="$(cd "$SYM_ROOT" && pwd)"

BIN="$ART_ROOT/bin/slicer-engine"
MANIFEST="$ART_ROOT/engine-artifact-manifest.json"
DSYM="$SYM_ROOT/slicer-engine.dSYM"

fail() { echo "FAIL: $*" >&2; exit 1; }

[[ -x "$BIN" ]] || fail "missing $BIN"
[[ -f "$MANIFEST" ]] || fail "missing $MANIFEST"
[[ -d "$DSYM" ]] || fail "missing $DSYM (re-run package_slicer_engine_macos.sh)"

# Consumer must not contain symbols
if find "$ART_ROOT" \( -name '*.dSYM' -o -name '*.unstripped' -o -name '*.pdb' \) 2>/dev/null | grep -q .; then
  fail "debug artifacts leaked into consumer tree"
fi

UUID_BIN="$(dwarfdump --uuid "$BIN" 2>/dev/null | awk '/UUID:/ {print $2; exit}')"
UUID_DSYM="$(dwarfdump --uuid "$DSYM" 2>/dev/null | awk '/UUID:/ {print $2; exit}')"
[[ -n "$UUID_BIN" ]] || fail "could not read binary UUID"
[[ "$UUID_BIN" == "$UUID_DSYM" ]] || fail "UUID mismatch bin=$UUID_BIN dsym=$UUID_DSYM"

MAN_UUID="$(python3 -c "import json;m=json.load(open('$MANIFEST'));print((m.get('symbol_archive') or {}).get('uuid_or_guid') or '')")"
if [[ -n "$MAN_UUID" && "$MAN_UUID" != "$UUID_BIN" ]]; then
  fail "manifest uuid_or_guid=$MAN_UUID != binary $UUID_BIN"
fi

# Smoke: atos should not error on a load address (best-effort)
LOAD="$(nm -gU "$BIN" 2>/dev/null | awk '/ _main$/{print $1; exit}')"
if [[ -n "$LOAD" ]]; then
  atos -o "$DSYM/Contents/Resources/DWARF/slicer-engine" -l "0x$LOAD" "0x$LOAD" >/tmp/atos-slicer-engine.txt 2>&1 || true
  echo "[5.5] atos smoke written /tmp/atos-slicer-engine.txt"
fi

echo "PASS: symbol archive drill"
echo "  build_id=$(python3 -c "import json;print(json.load(open('$MANIFEST')).get('engine_build_id'))")"
echo "  uuid=$UUID_BIN"
echo "  dsym=$DSYM"
echo "NOTE: formal ACL／remote store／Win PDB／rollback drill still open for full 5.5."
