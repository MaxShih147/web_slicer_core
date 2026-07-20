# Windows Before / After Comparison — De-identification

**Generated：** 2026-07-20  
**Change：** `backend-slicer-engine-deidentification`  
**Deliverable：** real window screenshots + comparison composites + tables  

## Provenance (strict)

| Side | Crash / dump | Install folder filenames |
|------|--------------|--------------------------|
| **BEFORE** | Authentic baseline capture `win-baseline-20260717T055632Z`（cdb PDB-free stack／WER brand lines／VERSIONINFO／PATH_INVENTORY／process modules） | Live Explorer from `C:\Program Files\Bundle Launcher\resources\bundle\third_party\prusaslicer_build\src\Release`（authentic Prusa PE icons；2026-07-20 refresh） |
| **AFTER** | Authentic PoC dump `w25-close-20260717T083241Z\dumps\segfault.dmp`（live WinDbg + archived stack log）＋ `rtti-5.1b` `Report.wer` | Real consumer tree：`Bundle-Launcher\dist\win-unpacked\resources\bundle\slicer-engine\` |

> AFTER install-path screenshots use the signed-equivalent **win-unpacked** consumer layout（`slicer-engine\bin`）.

## Side-by-side comparison images

| # | File | What it shows |
|---|------|----------------|
| 1 | [`shots/COMPARE_01_install_folder_before_vs_after.png`](./shots/COMPARE_01_install_folder_before_vs_after.png) | Explorer install folder filenames |
| 2 | [`shots/COMPARE_02_crash_minidump_stack_before_vs_after.png`](./shots/COMPARE_02_crash_minidump_stack_before_vs_after.png) | PDB-free crash minidump stack |
| 3 | [`shots/COMPARE_03_VERSIONINFO_before_vs_after.png`](./shots/COMPARE_03_VERSIONINFO_before_vs_after.png) | PE VERSIONINFO — **real** Explorer Properties · 詳細資料（非 dump） |
| 4 | [`shots/COMPARE_04_WER_surface_before_vs_after.png`](./shots/COMPARE_04_WER_surface_before_vs_after.png) | WER brand lines vs Report.wer |

### Individual real screenshots

| Shot | Description |
|------|-------------|
| `01_BEFORE_explorer_install_folder.png` | Explorer BEFORE filename layout |
| `02_AFTER_explorer_install_folder.png` | Explorer AFTER `slicer-engine\bin` |
| `03_AFTER_explorer_slicer-engine_root.png` | Explorer AFTER `slicer-engine\` root |
| `04_BEFORE_crash_minidump_stack.png` | Baseline cdb stack（`prusa_slicer_console`／`PrusaSlicer`） |
| `05_BEFORE_wer_brand_lines.png` | Baseline WER／dump brand lines |
| `06_AFTER_crash_minidump_stack.png` | PoC segfault stack（`slicer_core!slicer_run_cli`） |
| `07_AFTER_WER_Report.png` | Live archived `Report.wer`（App=`slicer-engine.exe`） |
| `08_BEFORE_VERSIONINFO.png` | Real Properties · 詳細資料 — `prusa-slicer-console.exe`（Prusa Research / PrusaSlicer） |
| `09_AFTER_VERSIONINFO.png` | Real Properties · 詳細資料 — `slicer-engine.exe`（Phrozen / Slicer Engine 1.0.5；對齊現行 `version.inc`） |
| `10_BEFORE_path_inventory.png` | Baseline PATH_INVENTORY |
| `11_BEFORE_process_modules.png` | Baseline live process／module paths |
| `12_AFTER_live_WinDbg_segfault_dump.png` | **Live** WinDbg opening `segfault.dmp` |
| `13_AFTER_exe_Properties.png` | Properties of real `slicer-engine.exe` |

---

## Table A — Crash / OS diagnostics surface

| Surface | BEFORE（修改前） | AFTER（修改後） |
|---------|------------------|-----------------|
| Process / image name | `prusa-slicer-console`／`prusa-slicer-console.exe` | `slicer-engine`／`slicer-engine.exe` |
| Core module | `PrusaSlicer`／`PrusaSlicer.dll` | `slicer_core`／`slicer_core.dll` |
| Minidump `lm` modules | `prusa_slicer_console`，`PrusaSlicer` | `slicer_engine`，`slicer_core` |
| Stack frames（PDB-free） | `prusa_slicer_console!wmain+…` | `slicer_core!slicer_run_cli+…`，`slicer_engine+0x…` |
| Public export | `slic3r_main`（+ ~470 mangled；baseline） | `slicer_run_cli`（唯一公開 entry；5.3） |
| WER App / Friendly | brand module／path lines in baseline dump surface | `NsAppName=slicer-engine.exe`；Friendly／Product=`Slicer Engine` |
| Exception（PoC segfault） | （baseline dump＝loader breakpoint；非 QA crash） | Access violation `c0000005` on QA segfault dump |
| Company / Product（VERSIONINFO） | `Prusa Research`／`PrusaSlicer`／`PrusaSlicer-2.9.4+UNKNOWN` | `Phrozen Technology`／`Slicer Engine`／`SlicerEngine-2.9.4+UNKNOWN` |
| PDB path in PE | `...\prusaslicer_build\...\prusa-slicer-console.pdb` | short neutral `slicer-engine.pdb`／`slicer_core.pdb`（`/PDBALTPATH:`） |

---

## Table B — Install folder files & paths

| Item | BEFORE（修改前） | AFTER（修改後） |
|------|------------------|-----------------|
| Bundle engine root | `...\bundle\third_party\prusaslicer_build\src\Release\` | `...\bundle\slicer-engine\` |
| Runtime bin dir | same Release folder | `...\slicer-engine\bin\` |
| Shim / CLI exe | `prusa-slicer.exe`，`prusa-slicer-console.exe` | **`slicer-engine.exe` only** |
| Core DLL | `PrusaSlicer.dll` | **`slicer_core.dll`** |
| Viewer leftover | `prusa-gcodeviewer.exe` present | **not** in consumer engine bin |
| Build leftovers | `PrusaSlicer.exp`，`PrusaSlicer.lib` | **not** in consumer package |
| Deps kept | `libgmp-10.dll`，`libmpfr-4.dll`，`OCCTWrapper.dll`（STEP） | `libgmp-10.dll`，`libmpfr-4.dll`，**`OCCTWrapper.dll`**（2026-07-20：正式包 MUST 附帶） |
| Manifest／legal | （pre-deid layout） | `engine-artifact-manifest.json`，`scan-report.json`，`legal\`，`sbom.spdx.json` |
| Program Files（policy） | n/a（old unpack path） | `C:\Program Files\Bundle Launcher\resources\bundle\slicer-engine\`（reinject evidence；folder empty on this PC now） |

### Filename rename map（canonical）

| BEFORE | AFTER |
|--------|-------|
| `prusa-slicer-console.exe`／`prusa-slicer.exe` | `slicer-engine.exe` |
| `PrusaSlicer.dll` | `slicer_core.dll` |
| `slic3r_main`（export） | `slicer_run_cli` |
| `...\prusaslicer_build\...` | `...\slicer-engine\` |
| `prusa-gcodeviewer.exe` | removed from engine consumer path |

---

## Fixes applied 2026-07-20（report refresh）

1. **PE icon：** `slicer-engine.exe` now embeds `WebSlicer_PrinterControl/assets/icon.ico`（same bytes as Bundle-Launcher `icon.ico`；`ExtractAssociatedIcon` hash match）. Applied to consumer trees＋`package_slicer_engine_windows.ps1` now runs `rcedit --set-icon` before post hash.
2. **VERSIONINFO After path：** evidence re-dumped from `Bundle-Launcher\dist\win-unpacked\resources\bundle\slicer-engine\bin\` — **no** `prusaslicer_build` in the File= lines.

---

## Compiler optimization verification（2026-07-20）

**Verdict：CONFIRMED** — Windows consumer build uses **MSVC `/O2`**（equivalent class to GCC/Clang `-O2`）.

| Source | Finding |
|--------|---------|
| `prusaslicer_build/CMakeCache.txt` | `CMAKE_CXX_FLAGS_RELEASE=/MD /O2 /Ob2 /DNDEBUG` |
| `PrusaSlicer_app_console.vcxproj` Release\|x64 | `<Optimization>MaxSpeed</Optimization>` → `/O2` |
| `libslic3r.vcxproj` Release\|x64 | same |
| `build_prusaslicer_fork_windows.bat` | `--config Release` |

Evidence pack + screenshots：[`optimization-evidence/`](./optimization-evidence/)（also section **06** in `index.html`）.

## BEFORE Explorer refresh (2026-07-20 afternoon)

`01_BEFORE_explorer_install_folder.png` / `COMPARE_01` left panel now captured from the **real installed tree**:

`C:\Program Files\Bundle Launcher\resources\bundle\third_party\prusaslicer_build\src\Release`

This shows authentic `prusa-slicer*.exe` / `PrusaSlicer.dll` PE icons (not the name-only museum placeholders).

## bin/resources necessity (2026-07-20)

**Decision：** Keep `slicer-engine/bin/resources/` **directory** on Windows. Content under it is largely optional for dental SLA headless.

### Runtime necessity (dental SLA / `SLIC3R_GUI=OFF`)

Product path: `slicer-engine.exe … --load <job.ini>`.

| Folder | ~Size | Verdict |
|--------|-------|---------|
| `resources/` (empty OK) | — | **MUST exist** (Setup.cpp `exe_dir/resources`) |
| `profiles/` | ~46 MB | Not needed by agent (no system presets); smoke before delete |
| `fonts/` `localization/` `shapes/` | ~20+12+12 MB | Not needed (GUI / model library) |
| `icons/` `shaders/` `web/` `udev/` `data/` | small | Not needed |

**Practice：** High-confidence removable: icons/shaders/fonts/localization/shapes/udev/web/most data. `profiles/` is half the volume — remove only after `--export-sla` / `--export-support-stl` / hollow smoke. Staging today only strips **branded path names**, not content.

### Brand text leakage in `bin/resources`

| Kind | Result |
|------|--------|
| Path / filename | **0** (`resource_brand_path_count: 0`) |
| Binary blobs | **0** |
| Text content | **76 files** still hit prusa/slic3r/PrusaSlicer/… |

Leak clusters: PrusaSlicer (40), slic3r/`min_slic3r_version` (42), files.prusa3d.com (35), non-prusa-* (34), Prusament (11), `_prusaSlicer` (2). Mostly under `profiles/` (70) + 6 others (hints.ini, geometries.json, localization, web connect HTML, udev).

**Gate gap：** Scanner fail-closed on **path** brands only — content can still leak while scan PASSes. Fastest content cleanup = drop `profiles/` (+ listed web/data/localization files), which also matches headless non-use.

### Impact on slice / supports / hollow / holes

| Feature | Agent call | Needs resources content? |
|---------|------------|--------------------------|
| Slice | `--export-sla --load config.ini` | **No** |
| Supports | `--export-support-stl --load` | **No** |
| Hollow | `--export-hollow-stl --load` | **No** |
| Cut | `--cut --export-stl` | **No** |
| Drain / hex holes | agent `trimesh` | **No** |
| Boolean | agent trimesh/manifold | **No** |

Evidence HTML: [`shim-three-way-proof.html#s9`](./shim-three-way-proof.html#s9)；policy: [`windows-policy.md`](../../windows-policy.md) §1.1.
