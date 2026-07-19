# Gate 5／tasks 1.5／2.8／7.7 — Sign-off package（**APPROVED**）

| Field | Value |
|-------|--------|
| **Change** | `backend-slicer-engine-deidentification` |
| **Prepared** | 2026-07-19 |
| **Countersigned** | 2026-07-19 |
| **Decision** | **approved** |
| **Countersigner** | **Vance**（Backend Security／Release Engineering／QA／Legal／OSS — combined owner for this change） |
| **Engineering status** | Dual-platform §7 engineering **closed**（Win 7.2／7.5／7.6；mac 7.1／7.4／7.6） |

## Signatures

| Role | Name | Decision | Date | Notes |
|------|------|----------|------|-------|
| Backend Security | Vance | **Approve** | 2026-07-19 | A＋B＋slim C′ required L2；C-full／D／E＝L3 only |
| Release Engineering | Vance | **Approve** | 2026-07-19 | Evidence／scanner／blacklist／post-sign gates OK |
| QA | Vance | **Approve** | 2026-07-19 | 2.7 budget；Win＋mac 7.6／crash probes OK |
| Legal／OSS | Vance | **Approve** | 2026-07-19 | Already recorded in 1.6 — [`legal-1.6-vance-approved-20260719.md`](./legal-1.6-vance-approved-20260719.md) |

### 1.5／2.8 — L2 means confirmation

**Approved：** A＋B＋slim C′（rename＋identity＋strip／thread／Win export）is the required L2 means; C-full／OLLVM／packer／Crash-Reporter intercept remain L3／optional and **do not** replace A＋B＋C′.

**Inputs reviewed：** [`feasibility-A-E-2.1-20260719.md`](./feasibility-A-E-2.1-20260719.md)；`design.md` D3／D8／D13；PoC REPORT／REPORT-WIN；`windows-policy.md`；PROGRESS.

### 7.7／Gate 5 — Release readiness

**Approved：** Evidence metadata／hash／scanner／blacklist／dual-platform declares＋CI gates＋functional minimal matrix are sufficient for Gate 5 under this change’s acceptance line.

**Windows pack：** `windows/section7-win-declare-7.2-20260719.md`；`windows/functional-7.6-…`；`windows/ci-gate-7.5-…`；`windows/launcher-1.0.0-postsign-…`；`windows/qa-three-crash-…`  

**macOS pack：** `macos/section7-mac-declare-7.1-20260719.md`；`macos-launcher-evening-reinject-…`；`macos/functional-7.6-…`；`macos/ci-gate-7.4-…`；`macos/qa-three-crash-…`

## Task close

- `tasks.md` **1.5**／**2.8**／**7.7** → checked  
- **Follow-up（2026-07-19 夜）：** **8.5 promote 已關** — [`../../specs/slicer-engine-deidentification/spec.md`](../../specs/slicer-engine-deidentification/spec.md)。可選 **8.6** archive／`.openspec.yaml` `completed` 仍未做。
