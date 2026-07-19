# Windows §7.2 — Formal L1+L2 acceptance declaration

| Field | Value |
|-------|--------|
| **Task** | **7.2** [REQ-DEID-002／003／006／010] |
| **Platform** | Windows x64 |
| **Decision** | **DECLARE PASS**（engineering evidence package） |
| **Date** | 2026-07-19 |
| **Budget／gates** | 2.7 approved；blacklist 1.2；D13 post-strip＋Launcher verify |

> This closes the **Windows** half of dual-platform §7 acceptance for L1+L2 product surfaces covered by existing hard evidence. Full change `completed` still requires macOS 7.1／7.6 and release sign-offs (1.5／7.7).

## 1. Evidence chain（authoritative）

| Layer | Evidence | Verdict |
|-------|----------|---------|
| PoC L1+L2 | [`../../poc/evidence/w25-close-20260717T083241Z/`](../../poc/evidence/w25-close-20260717T083241Z/)、[`../../poc/REPORT-WIN.md`](../../poc/REPORT-WIN.md) | PASS |
| Productize export／scan | `scan_slicer_engine_windows.ps1`；tasks 5.3／5.4 | PASS |
| Launcher §4 unsigned | [`../windows-launcher-section4-20260719.md`](../windows-launcher-section4-20260719.md) | PASS |
| Post-sign Setup＋lifecycle | [`launcher-1.0.0-postsign-20260719/SUMMARY.md`](./launcher-1.0.0-postsign-20260719/SUMMARY.md) | PASS（Setup Authenticode Valid） |
| CLI help de-brand | [`cli-help-printconfig-20260719.md`](./cli-help-printconfig-20260719.md) | PASS（`--help` PrusaSlicer=0 on help-cleared package） |
| QA three-crash（7.3） | [`qa-three-crash-20260719/SUMMARY.md`](./qa-three-crash-20260719/SUMMARY.md) | PASS |
| Functional／perf minimal（7.6） | [`functional-7.6-20260719T143000Z/SUMMARY.md`](./functional-7.6-20260719T143000Z/SUMMARY.md) | PASS |
| AGPL legal pack | Setup／staging `legal/`；1.6 Vance approved | PASS |
| Symbol archive 5.5 | OneDrive adopted | PASS |

## 2. Artifact identity（7.6 under-test／current consumer staging）

| Field | Value |
|-------|--------|
| `engine_build_id` | `20260719T105832Z` |
| flavor | `consumer` |
| exe sha256 | `254248FC041C30FE0DB3529DA5EEEABC0BDE0156E712AB46B79D05E6F0DD76E5` |
| Formal scan | PASS |

### Install-tree note

`C:\Program Files\Bundle Launcher\...` may still be morning postsign (`F9498CCB…` exe；`--help` PrusaSlicer>0). **Declared consumer for help／7.6** = help-cleared staging above. Re-sign＋reinstall Setup when shipping that tree to end users.

## 3. Residual（explicitly not FAIL for 7.2）

- `bin/resources/**` ≈148 brand asset filenames（scanner note；not fail-closed）
- `--help-fff` still contains `Slic3r`／bare `Prusa` in FFF tooltips（SLA `--help` clean）
- Inner `Bundle Launcher.exe` NotSigned（Setup only）
- Extended acceptance-procedure §6 matrix＝SHOULD／後補

## 4. Declaration

**Windows x64 L1+L2 for this change is accepted** based on the evidence table in §1, subject to:

1. Shipping the help-cleared consumer (or re-injecting it into signed Setup) for end-user installs.  
2. macOS §7 still open for dual-platform change completion.  
3. Security／Release／QA sign-off（tasks 1.5／7.7） and CI gate 7.5 automation.

**Engineering owner：** backend／release engineering（this evidence pack）.  
**Human countersign：** see [`../signoff-gate5-pending-20260719.md`](../signoff-gate5-pending-20260719.md).
