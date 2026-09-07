# Optimization flag verification — Windows slicer-engine

**Verdict: CONFIRMED** — current Windows build uses **MSVC `/O2`** (same optimization class as GCC/Clang `-O2`).

## Why you may not see the string `-O2`

| Toolchain | Flag spelling |
|-----------|----------------|
| GCC / Clang (macOS/Linux) | `-O2` |
| MSVC (this Windows build) | `/O2` |

CMake maps `CMAKE_BUILD_TYPE=Release` / `--config Release` to these flags automatically.

## Hard evidence (this machine)

1. **CMakeCache.txt**
   - `CMAKE_CXX_FLAGS_RELEASE=/MD /O2 /Ob2 /DNDEBUG`
   - `CMAKE_C_FLAGS_RELEASE=/MD /O2 /Ob2 /DNDEBUG`
   - Contrast Debug: `... /Od ...` (optimization **disabled**)

2. **Generated MSBuild projects** (`Release|x64`)
   - `PrusaSlicer_app_console.vcxproj` → `slicer-engine.exe`
   - `libslic3r.vcxproj`
   - `<Optimization>MaxSpeed</Optimization>` = `/O2`
   - `<InlineFunctionExpansion>AnySuitable</InlineFunctionExpansion>` = `/Ob2`

3. **Build script**
   - `build_prusaslicer_fork_windows.bat` → `-DCMAKE_BUILD_TYPE=Release` and `--config Release`
   - Output under `...\prusaslicer_build\src\Release\`

4. **macOS script (documented, not re-run here)**
   - Default `RelWithDebInfo` → Clang typically `-O2` + debug info

## Files in this folder

- `01_CMakeCache_flags.txt`
- `02_vcxproj_PrusaSlicer_app_console_Release_x64.txt`
- `03_vcxproj_libslic3r_Release_x64.txt`
- `04_build_script_windows_Release.txt`
- `05_build_script_macos_RelWithDebInfo.txt`
- `VERDICT.json`
- `shots/` — screenshots of the above evidence

Captured: 2026-07-20T03:38:00.9034856Z
