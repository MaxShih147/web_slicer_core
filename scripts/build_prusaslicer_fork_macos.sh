#!/usr/bin/env bash
set -e

FORK_URL="git@github.com:MaxShih147/PrusaSlicer.git"
ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SRC_DIR="$ROOT_DIR/third_party/prusaslicer_fork"
DEPS_BUILD_DIR="$SRC_DIR/deps/build"
BUILD_DIR="$ROOT_DIR/third_party/prusaslicer_build"

# Use CMake 3.27 (3.28+ has issues with PrusaSlicer)
CMAKE_BIN="$ROOT_DIR/cmake-3.27.9.app/Contents/bin/cmake"
if [ ! -f "$CMAKE_BIN" ]; then
  echo "[ERROR] CMake 3.27.9 not found at $CMAKE_BIN"
  echo "Please download from: https://github.com/Kitware/CMake/releases/download/v3.27.9/cmake-3.27.9-macos-universal.dmg"
  exit 1
fi

# Prefer RelWithDebInfo so dsymutil can archive DWARF before strip (D13 / 5.1).
# Override with SLICER_ENGINE_BUILD_TYPE=Release if needed.
BUILD_TYPE="${SLICER_ENGINE_BUILD_TYPE:-RelWithDebInfo}"

# Flavor: consumer (default, harness OFF) | qa (BUNDLE_QA_CRASH_HARNESS=ON)
# Accept positional arg for compatibility: ./build_prusaslicer_fork_macos.sh qa
FLAVOR="${SLICER_ENGINE_FLAVOR:-${1:-consumer}}"
if [[ "$FLAVOR" == "qa" ]]; then
  HARNESS_FLAG=ON
elif [[ "$FLAVOR" == "consumer" ]]; then
  HARNESS_FLAG=OFF
else
  echo "[ERROR] SLICER_ENGINE_FLAVOR must be consumer or qa (got: $FLAVOR)" >&2
  exit 1
fi
export SLICER_ENGINE_FLAVOR="$FLAVOR"

echo "[PrusaSlicer] Using fork: $FORK_URL"
echo "[PrusaSlicer] Using CMake: $CMAKE_BIN"
echo "[PrusaSlicer] Flavor: $FLAVOR (harness=$HARNESS_FLAG)"

# Pin to the active Xcode SDK (CMake cache can retain stale paths after Xcode updates)
OSX_SYSROOT="$(xcrun --show-sdk-path)"
if [ ! -d "$OSX_SYSROOT" ]; then
  echo "[ERROR] macOS SDK not found at $OSX_SYSROOT"
  echo "Install Xcode command-line tools or run: sudo xcodebuild -license accept"
  exit 1
fi
echo "[PrusaSlicer] Using macOS SDK: $OSX_SYSROOT"

# Clone fork only if missing; otherwise build from the current branch as-is
# NOTE: use -e (not -d) so this also recognizes a submodule checkout, where
# .git is a gitlink *file* (not a directory) pointing at ../../.git/modules/...
if [ ! -e "$SRC_DIR/.git" ]; then
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
    -DCMAKE_OSX_SYSROOT="$OSX_SYSROOT" \
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

# Reconfigure when the cached SDK path no longer exists (common after Xcode updates)
if [ -f CMakeCache.txt ]; then
  CACHED_SYSROOT="$(grep '^CMAKE_OSX_SYSROOT:PATH=' CMakeCache.txt | cut -d= -f2-)"
  if [ -n "$CACHED_SYSROOT" ] && [ "$CACHED_SYSROOT" != "$OSX_SYSROOT" ]; then
    echo "[PrusaSlicer] SDK changed ($CACHED_SYSROOT -> $OSX_SYSROOT); reconfiguring..."
    rm -f CMakeCache.txt
    rm -rf CMakeFiles
  fi
fi

echo "[PrusaSlicer] Configuring build (CMAKE_BUILD_TYPE=$BUILD_TYPE, flavor=$FLAVOR, harness=$HARNESS_FLAG)..."
"$CMAKE_BIN" "$SRC_DIR" \
  -DCMAKE_BUILD_TYPE="$BUILD_TYPE" \
  -DCMAKE_OSX_SYSROOT="$OSX_SYSROOT" \
  -DSLIC3R_GUI=OFF \
  -DSLIC3R_BUILD_TESTS=OFF \
  -DBUNDLE_QA_CRASH_HARNESS="$HARNESS_FLAG" \
  -DCMAKE_PREFIX_PATH="$DEPS_DESTDIR" \
  -DCMAKE_EXE_LINKER_FLAGS="-framework Foundation"

echo "[PrusaSlicer] Building..."
"$CMAKE_BIN" --build . --parallel $(sysctl -n hw.ncpu)

SLICER_BIN="$BUILD_DIR/src/slicer-engine"
if [ ! -x "$SLICER_BIN" ]; then
  echo "[ERROR] Expected binary missing: $SLICER_BIN"
  exit 1
fi

# Drop stale branded names from older builds (CMake POST_BUILD also removes these).
rm -f "$BUILD_DIR/src/PrusaSlicer" \
      "$BUILD_DIR/src/prusa-slicer" \
      "$BUILD_DIR/src/prusa-gcodeviewer" \
      "$BUILD_DIR/src/PrusaGCodeViewer"

# D13 package is opt-in: normal compile stops after the build tree binary.
# Enable with PACKAGE_SLICER_ENGINE=1 when you need the consumer/qa artifact.
PACKAGED=0
if [ "${PACKAGE_SLICER_ENGINE:-0}" = "1" ]; then
  echo ""
  echo "[slicer-engine] Step 3: Package $FLAVOR artifact (D13)..."
  # Pair qa → last known consumer build id when present
  CONSUMER_EQ=""
  if [[ "$FLAVOR" == "qa" && -f "$ROOT_DIR/third_party/slicer-engine/engine_build_id.txt" ]]; then
    CONSUMER_EQ="$(cat "$ROOT_DIR/third_party/slicer-engine/engine_build_id.txt")"
  fi
  SLICER_ENGINE_BUILD_BIN="$SLICER_BIN" \
  SLICER_ENGINE_FLAVOR="$FLAVOR" \
  SLICER_ENGINE_CONSUMER_EQUIVALENT_BUILD_ID="$CONSUMER_EQ" \
    "$ROOT_DIR/scripts/package_slicer_engine_macos.sh"
  PACKAGED=1
fi

echo ""
echo "[PrusaSlicer] =========================================="
echo "[PrusaSlicer] Build complete!"
echo "[PrusaSlicer] =========================================="
echo ""
echo "[slicer-engine] Dev binary: $SLICER_BIN (flavor=$FLAVOR harness=$HARNESS_FLAG)"
if [ "$PACKAGED" = "1" ]; then
  if [[ "$FLAVOR" == "qa" ]]; then
    echo "[slicer-engine] Packaged QA: $ROOT_DIR/third_party/slicer-engine-qa/bin/slicer-engine"
  else
    echo "[slicer-engine] Packaged:   $ROOT_DIR/third_party/slicer-engine/bin/slicer-engine"
  fi
else
  echo "[slicer-engine] Packaging skipped (set PACKAGE_SLICER_ENGINE=1 to package)"
fi
echo ""
echo "[slicer-engine] To use with the agent:"
echo "  export SLICER_ENGINE_BIN=$SLICER_BIN"
echo "  ./scripts/run_agent.sh"
echo "[slicer-engine] QA build: SLICER_ENGINE_FLAVOR=qa ./scripts/build_prusaslicer_fork_macos.sh"
echo "[slicer-engine] Package:  PACKAGE_SLICER_ENGINE=1 ./scripts/build_prusaslicer_fork_macos.sh"
