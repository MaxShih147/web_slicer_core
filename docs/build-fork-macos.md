# Build PrusaSlicer Fork (macOS)

Step-by-step flow to build `third_party/prusaslicer_fork` into `slicer-engine`
on a clean macOS checkout of `web_slicer_core`, with every step's output
captured to a log file so success/failure can be confirmed after the fact.

Applies from `release/v1.0.5` onward — the fork pin and build script both
include fixes for macOS SDK detection and dependency-download timeouts
(see [Known issues fixed](#known-issues-already-fixed-in-this-branch) below).

## Prerequisites

- macOS (Apple Silicon or Intel)
- Xcode + command-line tools (`xcode-select --install`)
- Python 3.9+, Node.js 18+ (for the agent/frontend, not needed for this build)
- `git`, `curl`

## 1. Clone and checkout

```bash
git clone git@github.com:MaxShih147/web_slicer_core.git
cd web_slicer_core
git checkout release/v1.0.5
```

## 2. Init the fork submodule

```bash
./scripts/init_prusaslicer_fork_submodule_macos.sh
```

Idempotent — safe to re-run. Logs to `scripts/logs/init_fork_submodule_macos_<timestamp>.log`.

## 3. Install CMake 3.27.9

The build is pinned to CMake 3.27.9 (3.28+ has known issues with PrusaSlicer's
CMake scripts). This installs it as a standalone app bundle at the repo root
(`cmake-3.27.9.app`) — separate from any system-wide `cmake`.

```bash
./scripts/setup_cmake_macos.sh
```

Idempotent — skips the download if already installed at the right version.
Logs to `scripts/logs/setup_cmake_macos_<timestamp>.log`.

## 4. Build, with log output to a file

```bash
mkdir -p scripts/logs
LOG_FILE="scripts/logs/build_prusaslicer_fork_macos_$(date +%Y%m%d_%H%M%S).log"

./scripts/build_prusaslicer_fork_macos.sh 2>&1 | tee "$LOG_FILE"
echo "Exit code: ${PIPESTATUS[0]}" | tee -a "$LOG_FILE"
```

- `tee` shows live output in the terminal **and** writes it to `$LOG_FILE`.
- `${PIPESTATUS[0]}` (not `$?`) captures the build script's real exit code,
  since the command runs through a pipe into `tee`.
- First run builds dependencies too (**30–60+ minutes**); reruns skip
  dependencies that are already built and go straight to the slicer-engine
  compile (a few minutes).

### Running it in the background (recommended for the first build)

```bash
mkdir -p scripts/logs
LOG_FILE="scripts/logs/build_prusaslicer_fork_macos_$(date +%Y%m%d_%H%M%S).log"
nohup ./scripts/build_prusaslicer_fork_macos.sh > "$LOG_FILE" 2>&1 &
echo $! > /tmp/build_pid.txt
echo "PID: $(cat /tmp/build_pid.txt), log: $LOG_FILE"
```

Check progress any time:

```bash
tail -f "$LOG_FILE"
```

Check whether it's still running:

```bash
kill -0 "$(cat /tmp/build_pid.txt)" 2>/dev/null && echo "still running" || echo "finished"
```

## 5. Confirm success from the log

**Success** ends with this banner and a binary path:

```
[PrusaSlicer] ==========================================
[PrusaSlicer] Build complete!
[PrusaSlicer] ==========================================

[slicer-engine] Dev binary: .../third_party/prusaslicer_build/src/slicer-engine
```

Quick check:

```bash
grep -n "Build complete\|CMake Error\|Configuring incomplete\|\*\*\* \[" "$LOG_FILE"
```

- `Build complete` present, nothing else → success.
- `CMake Error`, `Configuring incomplete`, or a `make: *** [...] Error N` line
  → failed; read the surrounding context in `$LOG_FILE` for the real cause
  (grep for `error:` case-sensitively — case-insensitive `-i error` matches
  too much noise, e.g. filenames like `*Error.hxx` from OpenCASCADE).

## 6. Verify the binary

```bash
SLICER_BIN="third_party/prusaslicer_build/src/slicer-engine"

# No PrusaSlicer/slic3r branding should appear (de-identified build)
"$SLICER_BIN" --help | head -5

# Fork's custom CLI options should be present
"$SLICER_BIN" --help | grep -i "export-support\|export-hollow"
```

## 7. Use it with the agent

```bash
export SLICER_ENGINE_BIN="$(pwd)/third_party/prusaslicer_build/src/slicer-engine"
./scripts/run_agent.sh
```

---

## Known issues already fixed in this branch

These were real failures hit while building on Xcode 26.6 / macOS 26.5 SDK;
fixed permanently in the fork (`release/v1.0.5`, commit `5bc83b0`) and in
`web_slicer_core`'s build script (commit `6d94dcb`). Listed here so a
recurrence is recognizable instead of confusing.

### "Could not determine OS X SDK version"

Newer Xcode makes `xcrun --show-sdk-path` resolve to the unversioned
`MacOSX.sdk` symlink instead of a versioned `MacOSXNN.N.sdk` path.
`deps/CMakeLists.txt` used to regex-infer the deployment target from that
path and hard-fail when there was no version in it. Fixed: falls back to
`xcrun --show-sdk-version` directly.

### A dependency download hangs forever (e.g. stuck on GMP/MPFR/OpenSSL/Boost/...)

`file(DOWNLOAD)` has no timeout by default — if a connection stalls (remote
closes, local socket sits in `CLOSE_WAIT`), the download step waits forever
instead of retrying. Fixed: `TIMEOUT 600` / `INACTIVITY_TIMEOUT 60` added to
every dependency's `ExternalProject_Add`, so a stall now fails fast and
triggers the retry-with-backoff CMake already has built in.

If a specific host is simply flaky on your network even with retries, you can
pre-seed the download so CMake's hash check skips re-downloading it:

```bash
DEST="third_party/prusaslicer_fork/deps/build/downloads/<DEP>/<filename>"
mkdir -p "$(dirname "$DEST")"
curl -L --retry 15 --retry-delay 2 --retry-all-errors -C - -o "$DEST" "<url>"
```
(Get `<DEP>`, `<filename>`, `<url>` from the corresponding `deps/+<DEP>/<DEP>.cmake` file.)

### deps skipped even though they're incomplete

`build_prusaslicer_fork_macos.sh` only checks whether
`deps/build/destdir/usr/local` **exists**, not whether the deps build
actually finished. If a previous run was killed mid-build, that directory
already exists (partially populated), so Step 1 gets skipped and Step 2
fails later on a missing dependency (e.g. `Could not find CGAL`). Fix: resume
the deps build directly before rerunning the full script:

```bash
cd third_party/prusaslicer_fork/deps/build
make -j$(sysctl -n hw.ncpu)
```

This is safe to re-run — CMake's `ExternalProject_Add` tracks per-step stamps,
so it only finishes what's incomplete rather than rebuilding from scratch.
