# Windows CLI help de-ID — PrintConfig cleanup

**Date：** 2026-07-19  
**Tasks：** main 3.5 residual；priority #1  

## Change

- `third_party/prusaslicer_fork/src/libslic3r/PrintConfig.cpp`：user-visible tooltip／help 字串 `PrusaSlicer` → `Slicer Engine`（保留 AGPL 檔頭與歷史註解）
- Incremental rebuild：`build_prusaslicer_fork_windows.bat low`（`PrintConfig.cpp` 重編＋relink `slicer_core.dll`）
- `package_slicer_engine_windows.ps1` + `scan_slicer_engine_windows.ps1`：**PASS**

## Verification

| Check | Result |
|-------|--------|
| `--help` `PrusaSlicer` hits | **0** |
| `--help-fff` hits | **0** |
| `--help-sla` hits | **0** |
| config-compatibility text | `This version of Slicer Engine may not…` |
| scan verdict | **PASS** |
| dll `post_strip_sha256` | `8b85e334ea085b02915e5fda1ea3bbb2c26b449da5caf2ea79be08c4bdf4645b` |
| exe `post_strip_sha256` | `f9498ccb208c67ae878dcca58d5826754dbb9b7c0cdd29bc009760db6ad62f2f`（shim 未變） |
| `engine_build_id` | `20260719T095415Z` |

Artifact help capture：[`cli-help-after-printconfig-20260719.txt`](./cli-help-after-printconfig-20260719.txt)

## Residual（unchanged this round）

- `bin/resources/**` ≈148 brand asset paths（scanner note）
- GUI／non-CLI message strings outside PrintConfig（headless consumer 不暴露）
