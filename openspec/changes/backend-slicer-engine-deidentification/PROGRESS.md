# Progress Snapshot — backend-slicer-engine-deidentification

**更新日期：** 2026-07-19（夜：Win 7.2／7.5／7.6 工程閉環；簽核包待人簽）  
**Change status：** `in_progress`（見 `.openspec.yaml`）  

## 證據錨點

| 證據 | 路徑 |
|------|------|
| macOS PoC | [`poc/evidence/m1-close-20260717T032408Z/`](./poc/evidence/m1-close-20260717T032408Z/) |
| Windows PoC | [`poc/evidence/w25-close-20260717T083241Z/`](./poc/evidence/w25-close-20260717T083241Z/) |
| macOS Launcher §4／晚上回灌 | [`evidence/macos-launcher-section4-20260719.md`](./evidence/macos-launcher-section4-20260719.md)、[`evidence/macos-launcher-evening-reinject-20260719.md`](./evidence/macos-launcher-evening-reinject-20260719.md) |
| Win §4／post-sign／CLI／7.3／2.7／7.6／7.2／7.5 | [`evidence/windows-launcher-section4-20260719.md`](./evidence/windows-launcher-section4-20260719.md)、[`evidence/windows/launcher-1.0.0-postsign-20260719/`](./evidence/windows/launcher-1.0.0-postsign-20260719/)、[`evidence/windows/cli-help-printconfig-20260719.md`](./evidence/windows/cli-help-printconfig-20260719.md)、[`evidence/windows/qa-three-crash-20260719/`](./evidence/windows/qa-three-crash-20260719/)、[`evidence/functional-budget-2.7-approved-20260719.md`](./evidence/functional-budget-2.7-approved-20260719.md)、[`evidence/windows/functional-7.6-20260719T143000Z/`](./evidence/windows/functional-7.6-20260719T143000Z/)、[`evidence/windows/section7-win-declare-7.2-20260719.md`](./evidence/windows/section7-win-declare-7.2-20260719.md)、[`evidence/windows/ci-gate-7.5-20260719T144512Z/`](./evidence/windows/ci-gate-7.5-20260719T144512Z/) |
| Legal 1.6／簽核包 | [`evidence/legal-1.6-vance-approved-20260719.md`](./evidence/legal-1.6-vance-approved-20260719.md)、[`evidence/signoff-gate5-pending-20260719.md`](./evidence/signoff-gate5-pending-20260719.md) |

---

## 1. 總覽（可驗證現況）

| 區塊 | 狀態 |
|------|------|
| 治理／命名／schema | **完成**（**1.5** 簽核包已備、待人簽；**1.6** approved） |
| §2 PoC／2.7 | **雙平台 PoC PASS**；**2.7 approved**；2.8 待人簽 |
| §3／§4／§5／§6 | 主線關閉（見既有 evidence） |
| §7 Windows | **7.2／7.3／7.5／7.6 PASS** |
| §7 macOS | **7.1／7.4／7.6 仍開** |
| 簽核 7.7 | Legal 已關；Security／Release／QA 待 |

**完成度（粗）：≈ 94–96%**（Win 工程結案項已關；主殘留 **mac 7.6**＋**人簽**）。  

**明確缺口：**
1. **mac §7.6**（＋7.1／7.4）  
2. **1.5／2.8／7.7** 人簽  
3. 可選：Win Setup 回灌 help-cleared；resources；mac 4.6；符號化演練  

---

## 2. Windows（本輪已關）

| 項 | 狀態 |
|----|------|
| 7.6 minimal matrix | **PASS** |
| 7.2 formal declare | **PASS** — `section7-win-declare-7.2-20260719.md` |
| 7.5 CI gate | **PASS** — script＋GH workflows＋本機 staging／Setup Authenticode |
| bundle-win sync | help-cleared staging 已同步；Setup 重新 EV 簽＋重裝見 reinject runbook |

---

## 3. 下一步

1. **mac §7.6**（＋7.1 宣告／7.4 CI）  
2. **人簽** [`evidence/signoff-gate5-pending-20260719.md`](./evidence/signoff-gate5-pending-20260719.md)  
3. 可選：[`evidence/windows/setup-reinject-help-cleared-runbook-20260719.md`](./evidence/windows/setup-reinject-help-cleared-runbook-20260719.md)  
4. mac＋簽核齊後再 8.5／8.6／`completed`  

---

## 4. 雙 repo 同步規則

- **權威：** 本 `PROGRESS.md`＋可重跑磁碟證據。  
- **Launcher 衛星**只引用本檔。  
- mac 現行 consumer＝DMG `…2111`；Win 宣告 consumer＝staging `20260719T105832Z`（install tree 可能仍 stale）。  
