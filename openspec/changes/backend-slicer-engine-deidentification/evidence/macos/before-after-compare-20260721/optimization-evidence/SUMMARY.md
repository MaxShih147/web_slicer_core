# macOS compiler optimization evidence

**Verdict：CONFIRMED** — this machine’s engine CMake cache uses **`RelWithDebInfo`** with:

```
CMAKE_CXX_FLAGS_RELWITHDEBINFO=-O2 -g -DNDEBUG
```

That is the Clang equivalent class to Windows MSVC `/O2` (see Windows `before-after-compare-20260720/optimization-evidence`).

| Source | Finding |
|--------|---------|
| `prusaslicer_build/CMakeCache.txt` | `CMAKE_BUILD_TYPE=RelWithDebInfo`；`…_RELWITHDEBINFO=-O2 -g -DNDEBUG` |
| `CMAKE_CXX_FLAGS_RELEASE` | `-O3 -DNDEBUG`（本機現行預設為 RelWithDebInfo，非 Release） |
| `build_prusaslicer_fork_macos.sh` | 預設 RelWithDebInfo |

Artifacts：`01_CMakeCache_and_script_flags.txt`、`05_build_script_macos_RelWithDebInfo.txt`、`VERDICT.json`、`shots/01_CMakeCache_flags.png`
