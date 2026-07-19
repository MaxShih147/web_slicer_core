# Windows §7 follow-up note（engineering）

**Date：** 2026-07-19（updated after QA three-crash）  
**Scope：** Windows tasks 7.3／7.5／7.6  

## Status

| Item | Status |
|------|--------|
| **7.3** QA three-crash | **PASS** — [`qa-three-crash-20260719/SUMMARY.md`](./qa-three-crash-20260719/SUMMARY.md) |
| **7.5** post-Authenticode | **手動 PASS**（Setup Valid＋lifecycle）；**CI 自動化未做**（後補） |
| **7.6** full SLA／perf | **未跑**（完整矩陣；不擋本輪 7.3） |

## Already done（manual 7.5）

| Item | Evidence |
|------|----------|
| Post-Authenticode Setup | [`launcher-1.0.0-postsign-20260719/SUMMARY.md`](./launcher-1.0.0-postsign-20260719/SUMMARY.md) |
| Static consumer gate | `scan_slicer_engine_windows.ps1` PASS（含 legal pack） |

## 7.5 CI automation（仍開）

Promote the manual checklist into CI when ready:

1. Build／package consumer  
2. Optional：sign Setup（or consume pre-signed artifact）  
3. `Setup /S` → scan install root  
4. Uninstall／reinstall → rescan  
5. Fail closed on scan FAIL or Authenticode invalid  

## 7.6 SLA

Run agent／CLI SLA matrix against packaged `slicer-engine` when scheduled（out of this Windows priority pass）.

## Decided elsewhere（not §7 blockers）

- **Legal 1.6** Vance approved — email／written offer  
- **5.5 Win** OneDrive manual store（uploaded `20260719T095415Z`）  
