# Gate 5／tasks 1.5／2.8／7.7 — Sign-off package（pending human countersign）

| Field | Value |
|-------|--------|
| **Change** | `backend-slicer-engine-deidentification` |
| **Prepared** | 2026-07-19 |
| **Purpose** | Request Security／Release／QA countersign so tasks **1.5**／**2.8**／**7.7** can close |

## Already signed

| Owner | Task | Evidence | Status |
|-------|------|----------|--------|
| Legal／OSS（Vance） | 1.6／REQ-DEID-011 | [`legal-1.6-vance-approved-20260719.md`](./legal-1.6-vance-approved-20260719.md) | **approved** |

## Pending signatures（please mark Approve／Reject＋date＋name）

### 1.5／2.8 — Backend Security／Release Engineering

**Ask：** Confirm A+B+C′（rename＋identity＋strip／thread／Win export）is the required L2 means; C-full／OLLVM／packer／Crash-Reporter intercept remain L3／optional and **do not** replace A+B+C′.

| Role | Name | Decision (Approve／Reject) | Date | Notes |
|------|------|---------------------------|------|-------|
| Backend Security | | | | |
| Release Engineering | | | | |

**Inputs to review：** `design.md` D3／D8／D13；PoC REPORT／REPORT-WIN；`windows-policy.md`；PROGRESS ≈93–95%.

### 7.7／Gate 5 — Evidence＋four-party release readiness

| Role | Scope | Decision | Date |
|------|-------|----------|------|
| Release Engineering | Evidence hash／scanner／blacklist 1.2／post-sign paths | | |
| Backend Security | L1+L2 threat-model acceptance（Win declared；mac 7.6 open） | | |
| QA | Win 7.3／7.6／2.7 budget acceptable；mac 7.6 TBD | | |
| Legal／OSS | Already approved（1.6） | **approved** | 2026-07-19 |

**Windows evidence pack：**

- [`windows/section7-win-declare-7.2-20260719.md`](./windows/section7-win-declare-7.2-20260719.md)  
- [`windows/functional-7.6-20260719T143000Z/`](./windows/functional-7.6-20260719T143000Z/)  
- [`windows/ci-gate-7.5-20260719T144512Z/`](./windows/ci-gate-7.5-20260719T144512Z/)  
- [`windows/launcher-1.0.0-postsign-20260719/`](./windows/launcher-1.0.0-postsign-20260719/)  
- [`windows/qa-three-crash-20260719/`](./windows/qa-three-crash-20260719/)  

**Explicit open before dual-platform `completed`：** macOS 7.1／7.6；optional Setup reinject of help-cleared Win engine into install tree.

## How to close tasks after signatures

1. Attach signed copy／email／Notion link under `evidence/`.  
2. Check `tasks.md` 1.5／2.8／7.7.  
3. Do **not** mark change `completed` until mac §7＋these signatures are done.
