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
| 2 | [`shots/COMPARE_02_crash_minidump_stack_before_vs_after.png`](./shots/COMPARE_02_crash_minidump_stack_before_vs_after.png) | PDB-free crash minidump — **differentiating frames**: Before `lm`+`k` brand tokens vs After AV + `slicer_run_cli`（boilerplate omitted；2026-07-21 rebuild） |
| 3 | [`shots/COMPARE_03_VERSIONINFO_before_vs_after.png`](./shots/COMPARE_03_VERSIONINFO_before_vs_after.png) | PE VERSIONINFO — **real** Explorer Properties · 詳細資料（非 dump） |
| 4 | [`shots/COMPARE_04_WER_surface_before_vs_after.png`](./shots/COMPARE_04_WER_surface_before_vs_after.png) | **Real OS UI** — Explorer `AppCrash_*` folders + full `Report.wer` in Notepad（`NsAppName=`） |
| 4b | [`shots/COMPARE_04b_WER_Report_wer_notepad_before_vs_after.png`](./shots/COMPARE_04b_WER_Report_wer_notepad_before_vs_after.png) | Notepad-only identity compare（full live `Report.wer`） |

### Individual real screenshots

| Shot | Description |
|------|-------------|
| `01_BEFORE_explorer_install_folder.png` | Explorer BEFORE filename layout |
| `02_AFTER_explorer_install_folder.png` | Explorer AFTER `slicer-engine\bin` |
| `03_AFTER_explorer_slicer-engine_root.png` | Explorer AFTER `slicer-engine\` root |
| `04_BEFORE_crash_minidump_stack.png` | Baseline cdb `lm`+`k` brand frames（`prusa_slicer_console`／`PrusaSlicer`／`wmain`） |
| `05_BEFORE_wer_brand_lines.png` | （legacy）Baseline WER／dump brand lines — **superseded by OS shots 17／22 for WER surface** |
| `06_AFTER_crash_minidump_stack.png` | PoC segfault AV + `slicer_core!slicer_run_cli` frames |
| `07_AFTER_WER_Report.png` | （legacy）archived `Report.wer` view — **superseded by shot 18** |
| `16_OS_WER_ReportArchive_slicer-engine.png` | **Live** Explorer AFTER · `AppCrash_slicer-engine…` |
| `17_OS_WER_ReportArchive_prusa-slicer-console.png` | **Live** Explorer BEFORE · `AppCrash_prusa-slicer-con…`（fresh crash 2026-07-20） |
| `18_OS_WER_Report_wer_slicer-engine_notepad.png` | **Live** Notepad AFTER · full `Report.wer` · `NsAppName=slicer-engine.exe` |
| `22_OS_WER_Report_wer_prusa-slicer-console_notepad.png` | **Live** Notepad BEFORE · full `Report.wer` · `NsAppName=prusa-slicer-console.exe` |
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
| WER AppCrash folder（Explorer） | `AppCrash_prusa-slicer-con…`（live ReportArchive） | `AppCrash_slicer-engine…`（live ReportArchive） |
| WER `NsAppName`／`Sig[0]`（Report.wer） | `prusa-slicer-console.exe` | `slicer-engine.exe` |
| WER AppName／Friendly | `PrusaSlicer` | `Slicer Engine` |
| Exception（PoC segfault） | （baseline dump＝loader breakpoint；非 QA crash） | Access violation `c0000005` on QA segfault dump |
| Company / Product（VERSIONINFO） | `Prusa Research`／`PrusaSlicer`／`PrusaSlicer-2.9.4+UNKNOWN` | `Phrozen Technology`／`Slicer Engine`／`SlicerEngine-2.9.4+UNKNOWN` |
| PDB path in PE | `...\prusaslicer_build\...\prusa-slicer-console.pdb` | short neutral `slicer-engine.pdb`／`slicer_core.pdb`（`/PDBALTPATH:`） |

---

## Table B — Install folder files & paths

Before 欄＝舊 unpack／Program Files 清點（`BEFORE_path_inventory.txt`），**不是**現行官方 bat 產物清單。
GUI／viewer 在 Before 出現＝舊全量樹殘留；agent 只呼叫 console。
現行管線＝預設**不編** GUI／viewer + 打包 SKIP 防舊檔（見 [`shim-three-way-proof.html` §08](./shim-three-way-proof.html#s8)）。
After「not shipped」＝正式包不出貨，**不是**「三個都編好再刪」。

| Item | BEFORE（舊清點） | AFTER（正式包） |
|------|------------------|-----------------|
| Bundle engine root | `...\bundle\third_party\prusaslicer_build\src\Release\` | `...\bundle\slicer-engine\` |
| Runtime bin dir | same Release folder | `...\slicer-engine\bin\` |
| Shim / CLI exe（agent 實際呼叫；唯一會編） | `prusa-slicer-console.exe` | **`slicer-engine.exe` only** |
| GUI（舊樹殘留；現行不編） | `prusa-slicer.exe`（非 agent 路徑） | **not shipped** |
| Core DLL | `PrusaSlicer.dll` | **`slicer_core.dll`** |
| Viewer（舊樹殘留；現行不編） | `prusa-gcodeviewer.exe` present | **not shipped** |
| Build leftovers | `PrusaSlicer.exp`，`PrusaSlicer.lib` | **not** in consumer package |
| Deps kept | `libgmp-10.dll`，`libmpfr-4.dll`，`OCCTWrapper.dll`（STEP） | `libgmp-10.dll`，`libmpfr-4.dll`，**`OCCTWrapper.dll`**（2026-07-20：正式包 MUST 附帶） |
| Manifest／legal | （pre-deid layout） | `engine-artifact-manifest.json`，`scan-report.json`，`legal\`，`sbom.spdx.json` |
| Program Files（policy） | n/a（old unpack path） | `C:\Program Files\Bundle Launcher\resources\bundle\slicer-engine\`（reinject evidence；folder empty on this PC now） |

### Filename rename map（canonical）

| BEFORE | AFTER |
|--------|-------|
| `prusa-slicer-console.exe`（agent CLI；唯一會編） | `slicer-engine.exe` |
| `prusa-slicer.exe`（舊樹殘留；現行不編／不出貨） | not shipped |
| `PrusaSlicer.dll` | `slicer_core.dll` |
| `slic3r_main`（export） | `slicer_run_cli` |
| `...\prusaslicer_build\...` | `...\slicer-engine\` |
| `prusa-gcodeviewer.exe`（舊樹殘留；現行不編／不出貨） | not shipped |

---

## Fixes applied 2026-07-20（report refresh）

1. **PE icon：** `slicer-engine.exe` now embeds `WebSlicer_PrinterControl/assets/icon.ico`（same bytes as Bundle-Launcher `icon.ico`；`ExtractAssociatedIcon` hash match）. Applied to consumer trees＋`package_slicer_engine_windows.ps1` now runs `rcedit --set-icon` before post hash.
2. **VERSIONINFO After path：** evidence re-dumped from `Bundle-Launcher\dist\win-unpacked\resources\bundle\slicer-engine\bin\` — **no** `prusaslicer_build` in the File= lines.
3. **WER surface → real OS UI（night）：** Forced a fresh `prusa-slicer-console.exe` AppCrash（no debugger）so Windows wrote a live `AppCrash_prusa-slicer-con…` ReportArchive； recaptured AFTER `AppCrash_slicer-engine…`； opened full `Report.wer` in Notepad（word-wrap off，find `NsAppName=`）. Rebuilt `COMPARE_04`／`COMPARE_04b`. Capture helper：[`capture_wer_os_surface.ps1`](./capture_wer_os_surface.ps1). Artifacts：`BEFORE_Report.wer`／`AFTER_Report.wer`.
4. **WER clean + annotate（night follow-up）：** Removed Notepad/Mica ghosting and overlapping composite labels. Explorer crops via `PrintWindow`（avoids Cursor overlay）. Identity fields = verbatim clean render from live `Report.wer` with red boxes on `prusa|slic3r|PrusaSlicer` and green boxes on `slicer-engine|Slicer Engine|slicer_core`. Scripts：[`clean_annotate_wer.ps1`](./clean_annotate_wer.ps1). Annotated assets：`*_annotated.png`，`COMPARE_04`／`COMPARE_04b`.
5. **COMPARE_02 stack rebuild（2026-07-21）：** Old composite cropped WinDbg boilerplate so Before／After looked almost identical. Rebuilt from authentic log excerpts：Before = `lm`+`k` brand frames；After = AV + `slicer_run_cli`. Script：[`rebuild_compare02_stack.ps1`](./rebuild_compare02_stack.ps1). Updated `04`／`06`／`COMPARE_02`.

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
