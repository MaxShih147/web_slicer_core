# macOS Before / After Comparison — De-identification

**Generated：** 2026-07-21  
**Change：** `backend-slicer-engine-deidentification`  
**Deliverable：** real macOS UI screenshots + comparison composites + tables  
**Mirror of：** [`../../windows/before-after-compare-20260720/`](../../windows/before-after-compare-20260720/)

## Provenance (strict)

| Side | Crash / `.ips` | Install folder filenames | Identity |
|------|----------------|--------------------------|----------|
| **BEFORE** | Authentic OS ReportCrash `.ips` from `~/Library/Logs/DiagnosticReports/Retired/PrusaSlicer-*.ips`（2026-07-14／07-17）；stack copy also in PoC `ips-clean/baseline-overflow.ips` | Live Finder of installed Bundle Launcher **pre-deid** tree：`/Applications/Bundle Launcher.app/…/third_party/prusaslicer_build/src/`（`PrusaSlicer` + `prusa-slicer` symlink） | `codesign -dv` → `Identifier=com.prusa3d.slic3r/`；`Info.plist` → `CFBundleIdentifier=com.prusa3d.slic3r/` |
| **AFTER** | Authentic stripped PoC `.ips` `m1-close-…/ips/segfault.ips`（Console Translated Report；`imageOffset` only＋`slicer-worker`）＋ 5.1b clean exception `.ips` | Live Finder of signed-equivalent consumer：`Bundle-Launcher/dist/mac-arm64/…/bundle/slicer-engine/` | `codesign -dv` → `Identifier=slicer-engine`；`Info.plist=not bound` |

> **Real OS UI rule：** Finder／Console／Terminal／Get Info are live captures on this Mac.  
> Shots `16`／`17` place authentic OS-generated `.ips` files into small Finder folders so the **filename surface**（`PrusaSlicer-*.ips` vs `slicer-engine-*.ips`）is readable — same intent as Windows cropping `AppCrash_*` folders. Shot `15` is the live `DiagnosticReports/Retired` folder.

## Side-by-side comparison images

| # | File | What it shows |
|---|------|----------------|
| 1 | [`shots/COMPARE_01_install_folder_before_vs_after.png`](./shots/COMPARE_01_install_folder_before_vs_after.png) | Finder install folder filenames |
| 2 | [`shots/COMPARE_02_crash_ips_stack_before_vs_after.png`](./shots/COMPARE_02_crash_ips_stack_before_vs_after.png) | Console Translated Report — Before `Slic3r::…` vs After `imageOffset`／`slicer-worker` |
| 3 | [`shots/COMPARE_03_codesign_identity_before_vs_after.png`](./shots/COMPARE_03_codesign_identity_before_vs_after.png) | `codesign -dv` Identifier（Win VERSIONINFO 對等） |
| 4 | [`shots/COMPARE_04_DiagnosticReports_before_vs_after.png`](./shots/COMPARE_04_DiagnosticReports_before_vs_after.png) | DiagnosticReports `.ips` filenames（Win WER AppCrash 對等） |
| 5 | [`shots/COMPARE_05_GetInfo_before_vs_after.png`](./shots/COMPARE_05_GetInfo_before_vs_after.png) | Finder Get Info |

### Individual real screenshots

| Shot | Description |
|------|-------------|
| `01_BEFORE_finder_install_folder.png` | Finder BEFORE — `PrusaSlicer`／`prusa-slicer`／`libslic3r` |
| `02_AFTER_finder_install_folder.png` | Finder AFTER — `slicer-engine/bin/slicer-engine` only |
| `03_AFTER_finder_slicer-engine_root.png` | Finder AFTER — `slicer-engine/` root（manifest／legal／bin） |
| `08_BEFORE_GetInfo.png`／`09_AFTER_GetInfo.png` | Finder Get Info |
| `08b_BEFORE_codesign_Terminal.png`／`09b_AFTER_codesign_Terminal.png` | Terminal `codesign -dv` |
| `10_BEFORE_Info_plist_Terminal.png` | Terminal `plutil -p` — branded `CFBundleIdentifier` |
| `15_OS_DiagnosticReports_Retired.png` | Live `~/Library/Logs/DiagnosticReports/Retired` |
| `16_OS_DiagnosticReports_slicer-engine.png` | AFTER `.ips` filenames |
| `17_OS_DiagnosticReports_PrusaSlicer.png` | BEFORE `.ips` filenames |
| `18_OS_ips_slicer-engine_Console.png` | Console AFTER segfault Translated Report |
| `18b_OS_ips_slicer-engine_exception_clean_Console.png` | Console AFTER 5.1b clean exception |
| `22_OS_ips_PrusaSlicer_Console.png` | Console BEFORE overflow — `Slic3r::` stack |

## Table A — Crash & OS diagnostics surface

| Surface | BEFORE | AFTER |
|---------|--------|-------|
| Process / image | `PrusaSlicer` | `slicer-engine` |
| `codeSigningID` | `PrusaSlicer` | `slicer-engine` |
| Bundle ID／Identifier | `com.prusa3d.slic3r/` | （none／`Info.plist=not bound`）＋ codesign `slicer-engine` |
| Version string | `PrusaSlicer PrusaSlicer-2.9.4+UNKNOWN` | neutral／empty（no branded Version） |
| Thread name | `slic3r_main` | `slicer-worker` |
| Readable stack symbols | `Slic3r::bundle_force_stack_overflow`／`Slic3r::SLAPrint::process`／`Slic3r::CLI::…` | **imageOffset only**（no `Slic3r::`） |
| DiagnosticReports filename | `PrusaSlicer-YYYY-….ips` | `slicer-engine-YYYY-….ips` |
| Install path brand | `…/prusaslicer_build/src/PrusaSlicer` | `…/slicer-engine/bin/slicer-engine` |

## Table B — Install folder files & paths

| Item | BEFORE（舊安裝樹） | AFTER（正式 consumer） |
|------|-------------------|------------------------|
| Engine root | `…/third_party/prusaslicer_build/src/` | `…/bundle/slicer-engine/` |
| CLI exe（真實 Mach-O） | `PrusaSlicer`（`prusa-slicer` → symlink） | **`slicer-engine` only** |
| Viewer／GUI leftovers | `prusa-gcodeviewer`／`PrusaGCodeViewer` aliases | **not shipped** |
| Build tree dirs | `libslic3r`／`slic3r-arrange*` present in install tree | **not in consumer package** |
| Manifest／legal | （pre-deid） | `engine-artifact-manifest.json`／`legal/`／`scan-report.json`／`engine_build_id.txt` |

## Compiler optimization（macOS）

**Verdict：CONFIRMED** — this machine’s CMake cache：

```
CMAKE_BUILD_TYPE=RelWithDebInfo
CMAKE_CXX_FLAGS_RELWITHDEBINFO=-O2 -g -DNDEBUG
```

See [`optimization-evidence/SUMMARY.md`](./optimization-evidence/SUMMARY.md).

## Capture tooling

- [`capture_os_surfaces.sh`](./capture_os_surfaces.sh) — Finder／Console／Terminal／Get Info region captures via `screencapture -R`
- Hard-refresh browser cache when viewing `index.html` if images appear stale
