# A–E feasibility summary（tasks 2.1／inputs for 1.5／2.8）

| Field | Value |
|-------|--------|
| **Change** | `backend-slicer-engine-deidentification` |
| **Date** | 2026-07-19 |
| **Purpose** | Written A–E feasibility for Security／Release review（closes doc gap called out in task 2.1） |

## Verdict

**Required L2 means = A＋B＋slim C′.** C-full／OLLVM／packer／Crash-Reporter intercept are **L3／optional** and **do not** replace A＋B＋C′.

| Track | Means | Dual-platform status |
|-------|--------|----------------------|
| **A** | Rename／path／identity（`slicer-engine`，neutral codesign ID） | **PASS** — mac PoC＋signed `…2111`；Win PoC＋Setup |
| **B** | Identity／VERSIONINFO／thread／proc naming | **PASS** — both platforms |
| **C′（slim）** | visibility＋strip；all threads；Win export=1；RTTI test；**not** full namespace rewrite | **PASS** — mac nm brand 0；Win export `slicer_run_cli` |
| **C-full** | Full `Slic3r::` namespace rewrite | **L3 — not required** |
| **D** | OLLVM／heavy obfuscation | **L3 — not required** |
| **E** | Packer／runtime Crash-Reporter intercept | **L3 — not required** |

## Proof anchors

- macOS PoC：`poc/REPORT.md`＋`poc/evidence/m1-close-20260717T032408Z/`  
- Windows PoC：`poc/REPORT-WIN.md`＋`poc/evidence/w25-close-20260717T083241Z/`  
- Design：`design.md` D3／D8／D13  
- Product declares：Win [`windows/section7-win-declare-7.2-20260719.md`](./windows/section7-win-declare-7.2-20260719.md)；mac [`macos/section7-mac-declare-7.1-20260719.md`](./macos/section7-mac-declare-7.1-20260719.md)

## Review result（1.5／2.8）

**Approved 2026-07-19 by Vance** — recorded in [`signoff-gate5-pending-20260719.md`](./signoff-gate5-pending-20260719.md).
