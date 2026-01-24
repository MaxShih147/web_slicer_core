#!/usr/bin/env bash
set -e

FORK_URL="git@github.com:MaxShih147/PrusaSlicer.git"
FORK_BRANCH="master"
ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SRC_DIR="$ROOT_DIR/third_party/prusaslicer_fork"
BUILD_DIR="$ROOT_DIR/third_party/prusaslicer_build"

echo "[PrusaSlicer] Using fork: $FORK_URL ($FORK_BRANCH)"

# Clone or update fork
if [ ! -d "$SRC_DIR/.git" ]; then
  echo "[PrusaSlicer] Cloning fork..."
  git clone "$FORK_URL" "$SRC_DIR"
fi

cd "$SRC_DIR"
git fetch origin
git checkout "$FORK_BRANCH"
git pull origin "$FORK_BRANCH"

# Prepare build dir
mkdir -p "$BUILD_DIR"
cd "$BUILD_DIR"

echo "[PrusaSlicer] Configuring build..."
cmake "$SRC_DIR" \
  -DCMAKE_BUILD_TYPE=Release \
  -DSLIC3R_GUI=OFF \
  -DSLIC3R_BUILD_TESTS=OFF

echo "[PrusaSlicer] Building..."
cmake --build . --parallel

echo
echo "[PrusaSlicer] Build complete."
echo "[PrusaSlicer] Binary location: $BUILD_DIR/src/prusa-slicer"
echo
echo "[PrusaSlicer] To use with the agent:"
echo "  export PRUSA_SLICER_BIN=$BUILD_DIR/src/prusa-slicer"
echo "  ./scripts/run_agent.sh"
