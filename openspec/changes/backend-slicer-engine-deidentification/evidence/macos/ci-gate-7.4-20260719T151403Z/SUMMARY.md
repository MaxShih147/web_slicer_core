# macOS 7.4 — final-artifact CI gate（landed）

**Date：** 2026-07-19  
**Task：** **7.4** [REQ-DEID-013]  
**Verdict：** **PASS**（local gate run on notarized DMG `…2111`＋script／workflow wiring）

## What landed

| Deliverable | Path |
|-------------|------|
| Fail-closed gate script | `Bundle-Launcher/scripts/ci_gate_macos_deid_7.4.sh` |
| Post-sign scan hygiene | `verify_slicer_engine_artifact.sh`／`scan_final_macos_artifact.sh` write reports **outside** sealed `.app` |
| PR／local CI workflow | `Bundle-Launcher/.github/workflows/ci-macos-deid-7.4.yml` |
| Local evidence（this run） | this folder＋`gate-summary.json` |

## Gate checks（fail closed）

1. `scan_final_macos_artifact.sh` on signed `.app`（D13 post-sign＋brand paths＋nm）  
2. `slicer-engine --help` exit 0 and **PrusaSlicer=0**  
3. `codesign --verify --deep --strict` on `.app`  
4. Optional `STAPLE_CHECK=1` → `xcrun stapler validate`

## This machine run

| Mode | Artifact | Staple | Verdict |
|------|----------|--------|---------|
| Scan＋help＋codesign＋stapler | DMG `Bundle Launcher_mac_arm64_1.0.0-202607192111.dmg` mounted app | yes | **PASS** |

Engine post_sign sha256：`336f930329d11dd02330ec4173802f20f9cd2eddacce171254eb41225cbda5d1`

## Reproduce

```bash
hdiutil attach ~/Desktop/Bundle\ Launcher_mac_arm64_1.0.0-202607192111.dmg -readonly -nobrowse -mountpoint /tmp/bundle-dmg-2111
APP_PATH="/tmp/bundle-dmg-2111/Bundle Launcher.app" STAPLE_CHECK=1 \
  REPORT_DIR=…/evidence/macos/ci-gate-7.4-<stamp> \
  Bundle-Launcher/scripts/ci_gate_macos_deid_7.4.sh
```

## Note

Do **not** let post-sign scans overwrite `slicer-engine/scan-report.json` inside a signed app — that breaks the seal（fixed 2026-07-19）.
