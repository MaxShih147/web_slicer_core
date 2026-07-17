#!/usr/bin/env bash
set -e

FORK_URL="git@github.com:MaxShih147/PrusaSlicer.git"
FORK_BRANCH="master"
ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SRC_DIR="$ROOT_DIR/third_party/prusaslicer_fork"
DEPS_BUILD_DIR="$SRC_DIR/deps/build"
BUILD_DIR="$ROOT_DIR/third_party/prusaslicer_build"
BUILD_FLAVOR="${1:-consumer}"  # consumer | qa

# Use CMake 3.27 (3.28+ has issues with PrusaSlicer)
CMAKE_BIN="$ROOT_DIR/cmake-3.27.9.app/Contents/bin/cmake"
if [ ! -f "$CMAKE_BIN" ]; then
  echo "[ERROR] CMake 3.27.9 not found at $CMAKE_BIN"
  echo "Please download from: https://github.com/Kitware/CMake/releases/download/v3.27.9/cmake-3.27.9-macos-universal.dmg"
  exit 1
fi

echo "[PrusaSlicer] Using fork: $FORK_URL ($FORK_BRANCH)"
echo "[PrusaSlicer] Using CMake: $CMAKE_BIN"
echo "[PrusaSlicer] Flavor: $BUILD_FLAVOR"

# Clone or update fork
if [ ! -d "$SRC_DIR/.git" ]; then
  echo "[PrusaSlicer] Cloning fork..."
  mkdir -p "$ROOT_DIR/third_party"
  git clone "$FORK_URL" "$SRC_DIR"
fi

cd "$SRC_DIR"
# Disabled auto-pull during product builds (match Windows script policy)
# git fetch origin && git checkout "$FORK_BRANCH" && git pull origin "$FORK_BRANCH"
CURRENT_BRANCH="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo unknown)"
echo "[PrusaSlicer] Building on current branch: $CURRENT_BRANCH (fetch/checkout/pull disabled)"

# ============================================
# Step 1: Build dependencies (if not already built)
# ============================================
DEPS_DESTDIR="$DEPS_BUILD_DIR/destdir/usr/local"
if [ ! -d "$DEPS_DESTDIR" ]; then
  echo ""
  echo "[PrusaSlicer] =========================================="
  echo "[PrusaSlicer] Step 1: Building dependencies..."
  echo "[PrusaSlicer] This may take a while (30-60 minutes)..."
  echo "[PrusaSlicer] =========================================="
  echo ""

  mkdir -p "$DEPS_BUILD_DIR"
  cd "$DEPS_BUILD_DIR"

  # Build deps without wxWidgets (headless/CLI mode)
  "$CMAKE_BIN" .. \
    -DCMAKE_BUILD_TYPE=Release \
    -DPrusaSlicer_deps_PACKAGE_EXCLUDES="wxWidgets"

  make -j$(sysctl -n hw.ncpu)
else
  echo "[PrusaSlicer] Dependencies already built at $DEPS_DESTDIR"
fi

# ============================================
# Step 2: Build slicer-engine CLI
# ============================================
echo ""
echo "[PrusaSlicer] =========================================="
echo "[PrusaSlicer] Step 2: Building slicer-engine CLI..."
echo "[PrusaSlicer] =========================================="
echo ""

mkdir -p "$BUILD_DIR"
cd "$BUILD_DIR"

if [[ "$BUILD_FLAVOR" == "qa" ]]; then
  QA_FLAG="-DBUNDLE_QA_CRASH_HARNESS=ON"
else
  QA_FLAG="-DBUNDLE_QA_CRASH_HARNESS=OFF"
fi

echo "[PrusaSlicer] Configuring build ($QA_FLAG)..."
"$CMAKE_BIN" "$SRC_DIR" \
  -DCMAKE_BUILD_TYPE=Release \
  -DSLIC3R_GUI=OFF \
  -DSLIC3R_BUILD_TESTS=OFF \
  $QA_FLAG \
  -DCMAKE_PREFIX_PATH="$DEPS_DESTDIR" \
  -DCMAKE_EXE_LINKER_FLAGS="-framework Foundation"

echo "[PrusaSlicer] Building..."
"$CMAKE_BIN" --build . --parallel $(sysctl -n hw.ncpu)

SLICER_BIN="$BUILD_DIR/src/slicer-engine"
if [ ! -f "$SLICER_BIN" ]; then
  echo "[ERROR] Expected binary missing: $SLICER_BIN"
  exit 1
fi

echo ""
echo "[PrusaSlicer] =========================================="
echo "[PrusaSlicer] Build complete!"
echo "[PrusaSlicer] =========================================="
echo ""
echo "[PrusaSlicer] Binary location: $SLICER_BIN"
echo "[PrusaSlicer] Flavor: $BUILD_FLAVOR"
echo ""
echo "[PrusaSlicer] Package consumer staging (dSYM + strip + manifest):"
echo "  ./scripts/package_slicer_engine_macos.sh"
echo ""
echo "[PrusaSlicer] To use with the agent:"
echo "  export SLICER_ENGINE_BIN=$SLICER_BIN"
echo "  ./scripts/run_agent.sh"
