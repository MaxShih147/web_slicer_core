#!/usr/bin/env bash
# Initialize the third_party/prusaslicer_fork submodule
# (git@github.com:MaxShih147/PrusaSlicer.git), pinned to the commit
# recorded by this repo's checked-out branch.
#
# NOTE: intentionally NOT --recursive. The fork itself has no .gitmodules
# of its own, and passing --recursive here has been observed to throw a
# spurious "Failed to recurse into submodule" error after the fork is
# already checked out correctly — see docs/slicer-engine-deidentification
# or ask in #web-slicer-core if this resurfaces upstream.
#
# Idempotent: safe to re-run; git submodule update is a no-op if already
# at the pinned commit. Every command is echoed (set -x) and mirrored to
# a timestamped log under scripts/logs/.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SUBMODULE_PATH="third_party/prusaslicer_fork"

LOG_DIR="$ROOT_DIR/scripts/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/init_fork_submodule_macos_$(date +%Y%m%d_%H%M%S).log"
exec > >(tee -a "$LOG_FILE") 2>&1
echo "[init_fork_submodule] Log: $LOG_FILE"

cd "$ROOT_DIR"

set -x
git submodule update --init -- "$SUBMODULE_PATH"
git submodule status -- "$SUBMODULE_PATH"
set +x

echo "[init_fork_submodule] Done. Fork checked out at: $ROOT_DIR/$SUBMODULE_PATH"
