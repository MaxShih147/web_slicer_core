#!/usr/bin/env bash
# Install CMake 3.27.9 as a standalone app bundle inside the repo root.
#
# build_prusaslicer_fork_macos.sh expects the binary at exactly:
#   <repo_root>/cmake-3.27.9.app/Contents/bin/cmake
# (PrusaSlicer's CMake scripts have known issues with 3.28+, so this is
# pinned deliberately and kept separate from any system-wide `cmake`.)
#
# Idempotent: if the pinned version is already installed, this is a no-op.
# Every command run is echoed (set -x) and mirrored to a timestamped log
# under scripts/logs/ so the whole install can be audited or replayed.
set -euo pipefail

CMAKE_VERSION="3.27.9"
DMG_URL="https://github.com/Kitware/CMake/releases/download/v${CMAKE_VERSION}/cmake-${CMAKE_VERSION}-macos-universal.dmg"

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
TARGET_APP="$ROOT_DIR/cmake-${CMAKE_VERSION}.app"
CMAKE_BIN="$TARGET_APP/Contents/bin/cmake"

LOG_DIR="$ROOT_DIR/scripts/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/setup_cmake_macos_$(date +%Y%m%d_%H%M%S).log"
exec > >(tee -a "$LOG_FILE") 2>&1
echo "[setup_cmake] Log: $LOG_FILE"

# ---- Already installed? ----------------------------------------------
if [ -x "$CMAKE_BIN" ]; then
  INSTALLED_VERSION="$("$CMAKE_BIN" --version | head -1 | awk '{print $3}')"
  if [ "$INSTALLED_VERSION" = "$CMAKE_VERSION" ]; then
    echo "[setup_cmake] CMake $CMAKE_VERSION already installed at $CMAKE_BIN — skipping."
    exit 0
  else
    echo "[setup_cmake] Found $TARGET_APP but version is $INSTALLED_VERSION, expected $CMAKE_VERSION. Reinstalling."
    rm -rf "$TARGET_APP"
  fi
fi

# ---- Download ----------------------------------------------------------
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT
DMG_PATH="$TMP_DIR/cmake-${CMAKE_VERSION}-macos-universal.dmg"

echo "[setup_cmake] Downloading $DMG_URL"
set -x
curl -fL --retry 3 -o "$DMG_PATH" "$DMG_URL"
set +x

# ---- Mount, copy CMake.app, unmount ------------------------------------
set -x
MOUNT_POINT="$(hdiutil attach "$DMG_PATH" -nobrowse -readonly | tail -1 | awk -F '\t' '{print $NF}')"
set +x
echo "[setup_cmake] Mounted at: $MOUNT_POINT"

if [ ! -d "$MOUNT_POINT/CMake.app" ]; then
  echo "[setup_cmake] ERROR: CMake.app not found in mounted dmg ($MOUNT_POINT)"
  hdiutil detach "$MOUNT_POINT" >/dev/null 2>&1 || true
  exit 1
fi

set -x
cp -R "$MOUNT_POINT/CMake.app" "$TARGET_APP"
hdiutil detach "$MOUNT_POINT"
# Remove Gatekeeper quarantine flag so macOS won't block execution.
xattr -cr "$TARGET_APP"
set +x

# ---- Verify --------------------------------------------------------------
set -x
"$CMAKE_BIN" --version
set +x

echo "[setup_cmake] Done. CMAKE_BIN=$CMAKE_BIN"
