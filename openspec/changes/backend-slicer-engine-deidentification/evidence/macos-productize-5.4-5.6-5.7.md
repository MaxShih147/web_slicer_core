# macOS productize — tasks 5.4／5.6／5.7

**Date：** 2026-07-17  
**Host：** local macOS arm64  
**Verdict：** **PASS**（consumer＋qa formal scan gate）

## Scope closed

| Task | Result |
|------|--------|
| **5.4** Formal consumer scan gate | `scripts/scan_slicer_engine_macos.sh` fail-closed from packager；nm brand global/local=0；no dSYM/PDB；codesign id=`slicer-engine`；manifest hash match |
| **5.6** QA flavor＋`qa_delta`；no runtime-only harness | `SLICER_ENGINE_FLAVOR=qa` → `third_party/slicer-engine-qa/`；manifest `qa_delta`；env `BUNDLE_QA_CRASH_MODE` alone does **not** crash consumer |
| **5.7** Consumer binary inspection zero harness | `harness_markers: []`；`strings` clean for harness tokens |

## Scripts

| Script | Role |
|--------|------|
| `scripts/scan_slicer_engine_macos.sh` | Formal gate（flavor-aware） |
| `scripts/package_slicer_engine_macos.sh` | D13 package＋invoke scan |
| `scripts/build_prusaslicer_fork_macos.sh` | `SLICER_ENGINE_FLAVOR=consumer\|qa` → `BUNDLE_QA_CRASH_HARNESS` OFF/ON |

## Artifacts（local gitignored）

| Flavor | Root | `engine_build_id`（sample） | Scan |
|--------|------|------------------------------|------|
| consumer | `third_party/slicer-engine/` | `slicer-engine-consumer-2026-07-17T123302Z` | `scan-report.json` **PASS** |
| qa | `third_party/slicer-engine-qa/` | `slicer-engine-qa-2026-07-17T121917Z` | **PASS**；markers present |

Consumer `checks`（authoritative local report）：

- `nm_brand_global`: 0 / `nm_brand_local`: 0  
- `debug_leaks`: [] / `brand_paths`: []  
- `harness_markers`: []  
- `codesign_identifier`: `slicer-engine`  
- `post_strip_sha256` manifest＝actual

QA `qa_delta`：

- `harness_compile_flag`: `BUNDLE_QA_CRASH_HARNESS`  
- `only_differences`: compile-time crash harness sites  
- `consumer_equivalent_build_id`: paired consumer id from same session  

## Runtime probe（5.6／5.7）

```text
BUNDLE_QA_CRASH_MODE=overflow <consumer>/bin/slicer-engine --help
→ exit 0；prints Slicer Engine help（no crash）
```

Harness `getenv("BUNDLE_QA_CRASH_MODE")` remains only under `#ifdef BUNDLE_QA_CRASH_HARNESS` in `bundle_qa_crash_probe.cpp` — not compiled into consumer.

## Operational note

Toggling `BUNDLE_QA_CRASH_HARNESS` via global `add_definitions` forces a broad `libslic3r` rebuild. After a QA build, restore consumer with `SLICER_ENGINE_FLAVOR=consumer`（or cmake `-DBUNDLE_QA_CRASH_HARNESS=OFF`）and rebuild before re-packaging from the build tree — packager scan would otherwise fail-closed on harness markers in a mislabeled consumer.

## Out of scope（still open）

- ~~Windows **5.3**／Windows formal scan gate~~ → **closed 2026-07-17～19**（export=1＋`scan_slicer_engine_windows.ps1`＋Launcher unsigned gate）  
- **5.5** symbol archive runbook  
- **5.1b** RTTI formalization  
- **macOS** Launcher **§4** handoff／CI gate（**Win unsigned＋post-sign Setup closed 2026-07-19**）  
- Dual-platform §7 acceptance（含 qa 動態）；CLI help `PrusaSlicer` 殘留清理  
