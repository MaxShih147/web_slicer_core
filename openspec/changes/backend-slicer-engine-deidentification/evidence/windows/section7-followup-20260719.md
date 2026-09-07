# Windows §7 follow-up note（engineering）

**Date：** 2026-07-19（updated after QA three-crash）  
**Scope：** Windows tasks 7.3／7.5／7.6  

## Status

| Item | Status |
|------|--------|
| **7.3** QA three-crash | **PASS** — [`qa-three-crash-20260719/SUMMARY.md`](./qa-three-crash-20260719/SUMMARY.md) |
| **7.5** post-Authenticode CI | **PASS** — [`ci-gate-7.5-20260719T144512Z/`](./ci-gate-7.5-20260719T144512Z/)＋GH workflows |
| **7.6** minimal matrix | **Win PASS** — [`functional-7.6-20260719T143000Z/`](./functional-7.6-20260719T143000Z/)；**mac PASS** — [`../macos/functional-7.6-20260719/`](../macos/functional-7.6-20260719/)；§6 延伸 SHOULD 後補 |
| **7.2** Win L1+L2 declare | **PASS** — [`section7-win-declare-7.2-20260719.md`](./section7-win-declare-7.2-20260719.md) |

## Already done（manual 7.5）

| Item | Evidence |
|------|----------|
| Post-Authenticode Setup | [`launcher-1.0.0-postsign-20260719/SUMMARY.md`](./launcher-1.0.0-postsign-20260719/SUMMARY.md) |
| Static consumer gate | `scan_slicer_engine_windows.ps1` PASS（含 legal pack） |
| CI automation | `Bundle-Launcher/scripts/ci_gate_windows_deid_7.5.ps1`＋build／release workflows |

## 7.5 CI automation

**Closed 2026-07-19.** Gate script fail-closed on scan＋`--help` PrusaSlicer=0；release workflow optionally checks Setup Authenticode Valid.

## 7.6 SLA

- **Win minimal MUST：** PASS（help／fail／`--export-sla` cold＋warm vs 2.7；agent smoke SKIP）— [`functional-7.6-20260719T143000Z/SUMMARY.md`](./functional-7.6-20260719T143000Z/SUMMARY.md)  
- **mac minimal MUST：** PASS — [`../macos/functional-7.6-20260719/SUMMARY.md`](../macos/functional-7.6-20260719/SUMMARY.md)  
- Extended §6 matrix：SHOULD／後補

## Decided elsewhere（not §7 blockers）

- **Legal 1.6** Vance approved — email／written offer  
- **5.5 Win** OneDrive manual store（uploaded `20260719T095415Z`）  
