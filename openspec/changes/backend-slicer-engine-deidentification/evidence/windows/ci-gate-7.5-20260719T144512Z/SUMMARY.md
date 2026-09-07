# Windows 7.5 — final-artifact CI gate（landed）

**Date：** 2026-07-19  
**Task：** **7.5** [REQ-DEID-013]  
**Verdict：** **PASS**（local gate run＋workflow wiring）

## What landed

| Deliverable | Path |
|-------------|------|
| Fail-closed gate script | `Bundle-Launcher/scripts/ci_gate_windows_deid_7.5.ps1` |
| PR／branch CI | `.github/workflows/build-windows-bundle-launcher.yml` → step **De-ID CI gate 7.5** |
| Release CI | `.github/workflows/release-bundle-launcher-windows.yml` → gate＋optional Setup Authenticode |
| Local evidence（this run） | this folder＋`gate-summary.json` |

## Gate checks（fail closed）

1. `scan_slicer_engine_windows.ps1` on consumer ArtifactRoot  
2. `slicer-engine --help` exit 0 and **PrusaSlicer=0**  
3. Optional `-SetupExe` → Authenticode **Valid**

## This machine run

| Mode | Artifact | Setup | Verdict |
|------|----------|-------|---------|
| Scan＋help | `web_slicer_core/slicer-engine` (`20260719T105832Z`) | — | **PASS** |
| Scan＋help＋Authenticode | same staging | `Bundle Launcher Setup 1.0.0.exe`（SHA256 `6592EE9E…`） | **PASS** |

Manual post-sign lifecycle remains documented in [`launcher-1.0.0-postsign-20260719/SUMMARY.md`](./launcher-1.0.0-postsign-20260719/SUMMARY.md). CI now enforces the static＋help＋（release）Authenticode slice of that checklist on every Windows Launcher build／release.

## Note

Full silent install／uninstall matrix stays a release smoke（already PASS manually）； CI gate focuses on reproducible fail-closed scan＋help＋signature without requiring elevated installers on every PR runner.
