# macOS §7.1 — Formal L1+L2 acceptance declaration

| Field | Value |
|-------|--------|
| **Task** | **7.1** [REQ-DEID-002／003／006／010] |
| **Platform** | macOS **arm64**（current published architecture；Intel `x86_64` not in current ship matrix） |
| **Decision** | **DECLARE PASS**（engineering evidence package） |
| **Date** | 2026-07-19 |
| **Budget／gates** | 2.7 approved；blacklist 1.2；D13 post-strip＋Launcher verify／sign／notarize／staple |

> This closes the **macOS arm64** half of dual-platform §7 acceptance for L1+L2 product surfaces covered by existing hard evidence. **Gate 5／1.5／2.8／7.7 Vance Approve 2026-07-19.** **Windows 7.2** already DECLARE PASS.

## 1. Evidence chain（authoritative）

| Layer | Evidence | Verdict |
|-------|----------|---------|
| PoC L1+L2＋three crash | [`../../poc/evidence/m1-close-20260717T032408Z/`](../../poc/evidence/m1-close-20260717T032408Z/)、[`../../poc/REPORT.md`](../../poc/REPORT.md) | PASS |
| Productize／nm／threads／CLI sample | tasks 3.x／5.1–5.7；PROGRESS | PASS |
| Launcher §4＋evening reinject | [`../macos-launcher-section4-20260719.md`](../macos-launcher-section4-20260719.md)、[`../macos-launcher-evening-reinject-20260719.md`](../macos-launcher-evening-reinject-20260719.md) | PASS（DMG `…2111`；`legal/`＋help=0） |
| QA three-crash（release-equivalent qa tree） | [`qa-three-crash-20260719/SUMMARY.md`](./qa-three-crash-20260719/SUMMARY.md) | PASS |
| Functional／perf minimal（7.6） | [`functional-7.6-20260719/SUMMARY.md`](./functional-7.6-20260719/SUMMARY.md) | PASS |
| Post-sign CI gate（7.4） | [`ci-gate-7.4-20260719T151403Z/`](./ci-gate-7.4-20260719T151403Z/) | PASS |
| AGPL legal pack | signed app `legal/`；1.6 Vance approved | PASS |
| Symbol archive 5.5 | local mac drill PASS | PASS |

## 2. Artifact identity（declared consumer）

| Field | Value |
|-------|--------|
| `engine_build_id` | `slicer-engine-consumer-2026-07-19T095348Z` |
| flavor | `consumer` |
| Ship DMG | `Bundle Launcher_mac_arm64_1.0.0-202607192111.dmg` |
| Engine post_sign sha256 | `336f930329d11dd02330ec4173802f20f9cd2eddacce171254eb41225cbda5d1` |
| Engine post_strip sha256 | `3c6c0976ff2c6bfe4adf5c13a61e41378f0aab787f09ee47b3e4abba3866b95b` |

### QA companion

| Field | Value |
|-------|--------|
| `engine_build_id` | `slicer-engine-qa-2026-07-17T121917Z` |
| Tree | `web_slicer_core/third_party/slicer-engine-qa/` |
| Note | Dynamic three-site exit probes 2026-07-19；full `.ips` forensics remain covered by PoC `m1-close` |

## 3. Residual（explicitly not FAIL for 7.1）

- `bin/Resources/**` brand asset filenames may remain（scanner note；not fail-closed）
- Intel `x86_64` mac package **out of current publish matrix**（re-open 7.1 if shipping Intel）
- Extended acceptance-procedure §6 matrix＝SHOULD／後補 per 2.7
- macOS 4.6 full lifecycle sample optional

### Sync note（2026-07-20）

§3「4.6 optional」為宣告當日狀態。現行：**mac 4.6 DMG lifecycle sample PASS**；**mac QA 4.2／5.11／6.4–6.7 PASS** — 見 [`PROGRESS.md`](../../PROGRESS.md)。

## 4. Declaration

**macOS arm64 L1+L2 for this change is accepted** based on the evidence table in §1, subject to:

1. Security／Release／QA／（Legal already done） countersign — tasks **1.5**／**2.8**／**7.7**.  
2. Windows half already declared（7.2）＋7.5／7.6 PASS.

**Engineering owner：** backend／release engineering（this evidence pack）.  
**Human countersign：** see [`../signoff-gate5-pending-20260719.md`](../signoff-gate5-pending-20260719.md).
