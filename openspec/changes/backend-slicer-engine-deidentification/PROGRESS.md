# Progress Snapshot — backend-slicer-engine-deidentification

**更新日期：** 2026-07-20（已簽 Setup 7.5；Win 5.11／6.4–6.7；未做 8.6 archive）  
**Change status：** `in_progress`（見 `.openspec.yaml`）  

## 證據錨點

| 證據 | 路徑 |
|------|------|
| macOS PoC | [`poc/evidence/m1-close-20260717T032408Z/`](./poc/evidence/m1-close-20260717T032408Z/) |
| Windows PoC | [`poc/evidence/w25-close-20260717T083241Z/`](./poc/evidence/w25-close-20260717T083241Z/) |
| macOS Launcher §4／晚上回灌 | [`evidence/macos-launcher-section4-20260719.md`](./evidence/macos-launcher-section4-20260719.md)、[`evidence/macos-launcher-evening-reinject-20260719.md`](./evidence/macos-launcher-evening-reinject-20260719.md) |
| macOS staging CLI／AGPL／5.5 | [`evidence/macos-cli-agpl-5.5-20260719.md`](./evidence/macos-cli-agpl-5.5-20260719.md) |
| macOS 7.1／7.4／7.6／qa crash | [`evidence/macos/section7-mac-declare-7.1-20260719.md`](./evidence/macos/section7-mac-declare-7.1-20260719.md)、[`evidence/macos/ci-gate-7.4-20260719T151403Z/`](./evidence/macos/ci-gate-7.4-20260719T151403Z/)、[`evidence/macos/functional-7.6-20260719/SUMMARY.md`](./evidence/macos/functional-7.6-20260719/SUMMARY.md)、[`evidence/macos/qa-three-crash-20260719/`](./evidence/macos/qa-three-crash-20260719/) |
| Win §4／post-sign／CLI／7.3 | [`evidence/windows-launcher-section4-20260719.md`](./evidence/windows-launcher-section4-20260719.md)、[`evidence/windows/launcher-1.0.0-postsign-20260719/`](./evidence/windows/launcher-1.0.0-postsign-20260719/)、[`evidence/windows/cli-help-printconfig-20260719.md`](./evidence/windows/cli-help-printconfig-20260719.md)、[`evidence/windows/qa-three-crash-20260719/`](./evidence/windows/qa-three-crash-20260719/) |
| 2.7／Win 7.6／7.2／7.5 | [`evidence/functional-budget-2.7-approved-20260719.md`](./evidence/functional-budget-2.7-approved-20260719.md)、[`evidence/windows/functional-7.6-20260719T143000Z/`](./evidence/windows/functional-7.6-20260719T143000Z/)、[`evidence/windows/section7-win-declare-7.2-20260719.md`](./evidence/windows/section7-win-declare-7.2-20260719.md)、[`evidence/windows/ci-gate-7.5-20260719T144512Z/`](./evidence/windows/ci-gate-7.5-20260719T144512Z/) |
| Win Setup 回灌／resources／QA 4.2 | [`evidence/windows/setup-reinject-20260720/SUMMARY.md`](./evidence/windows/setup-reinject-20260720/SUMMARY.md)；[`CI-GATE-7.5-SIGNED.md`](./evidence/windows/setup-reinject-20260720/CI-GATE-7.5-SIGNED.md)；Launcher QA 4.2 |
| Win 5.11／6.4–6.7 | [`evidence/windows/subprocess-5.11-20260719T164527Z/`](./evidence/windows/subprocess-5.11-20260719T164527Z/)、[`source-chain-6.4-6.5-20260720/`](./evidence/windows/source-chain-6.4-6.5-20260720/)、[`symbolication-6.6-6.7-20260719T165250Z/`](./evidence/windows/symbolication-6.6-6.7-20260719T165250Z/) |
| 2.1 A–E／Legal／簽核包 | [`evidence/feasibility-A-E-2.1-20260719.md`](./evidence/feasibility-A-E-2.1-20260719.md)、[`evidence/legal-1.6-vance-approved-20260719.md`](./evidence/legal-1.6-vance-approved-20260719.md)、[`evidence/signoff-gate5-pending-20260719.md`](./evidence/signoff-gate5-pending-20260719.md) |

---

## 1. 總覽（可驗證現況）

| 區塊 | 狀態 |
|------|------|
| 治理／命名／schema | **完成**（**1.5／1.6** Vance Approve；**2.1** A–E） |
| §2 PoC／2.7 | **雙平台 PoC PASS**；**2.7 approved**；**2.8** Vance Approve |
| §3 L1／CLI help | **Win＋mac 簽過包已清**（mac `…2111`；Win PF／staging help=0；**resources brand=0**） |
| §4／§5／§6 | 主線關閉（雙平台 §4；C′／5.5；AGPL legal/＋1.6） |
| §7 Windows | **7.2／7.3／7.5／7.6 PASS** |
| §7 macOS | **7.1／7.4／7.6 PASS**（arm64） |
| 簽核 7.7 | **四方 Vance Approve** |

**完成度（粗）：≈ 100%**（blocking＋8.5 promote；**未**做 8.6 archive／`completed`）。  

**已定案：** Legal 1.6＝email／書面 offer；5.5 Win＝OneDrive；**2.7** golden／perf — [`evidence/functional-budget-2.7-approved-20260719.md`](./evidence/functional-budget-2.7-approved-20260719.md)。  

**明確缺口（非 blocking）：**
1. 可選：8.6 archive → `status: completed`（**8.5 已做**）  
2. 可選：mac 4.6；mac QA 4.2；mac 側 5.11／6.4–6.7 對稱證據  
3. 後補：5.1b（RTTI／例外正式化）；5.9／5.10（明確選配／預設否）  

**本輪已關（2026-07-20 Win）：** Setup 安裝樹回灌；resources=0；QA 4.2；**EV 簽 Setup＋7.5 `-SetupExe` PASS**；**5.11／6.4／6.5／6.6／6.7**。

---

## 2. 雙平台已驗證（union）

### Windows

| 項 | 狀態 |
|----|------|
| §4 unsigned＋已簽 Setup lifecycle | **PASS** |
| CLI help／AGPL／5.5／7.3 | **PASS** |
| 7.6 minimal matrix | **PASS** — `functional-7.6-20260719T143000Z` |
| 7.2 formal declare | **PASS** — `section7-win-declare-7.2-20260719.md` |
| 7.5 CI gate | **PASS** — script＋GH workflows＋本機 staging／Setup Authenticode |
| bundle-win sync | help-cleared＋resources=0；`20260719T162525Z`；PF 已回灌；**Setup EV Valid**＋7.5 `-SetupExe` PASS（SHA256 `15C3E441…`） |

### macOS

| 產物 | build_id | 證明 | CLI help | `legal/` | 7.6 |
|------|----------|------|----------|---------|-----|
| **已簽** `.app`＋DMG `…2111` | `…2026-07-19T095348Z` | `post_strip`＝`3c6c0976…`；簽後＝`336f9303…`；Identifier=`slicer-engine` | **PASS** | **有** | **PASS** — `macos/functional-7.6-20260719` |
| staging（同源） | 同上 | formal scan PASS | **PASS** | **有** | — |
| 下午 DMG `…1450`（舊） | `…2026-07-17T123302Z` | 歷史；已被 `…2111` 取代 | 未證明 | 無 | — |

---

## 3. 已知殘留（非 blocking）

1. 內嵌 Win app exe 未 Authenticode；mac 4.6；mac QA 4.2；mac 5.11／6.4–6.7 對稱  
2. 5.1b RTTI／例外正式化  

---

## 4. 下一步

1. **8.5 promote 已關**  
2. 可選：**8.6 archive** → `completed`（依指示可暫緩）  
3. 可選：mac 4.6／mac QA 4.2／mac 合規對稱  

---

## 5. 關鍵路徑

| 產物 | 路徑 |
|------|------|
| mac D13／AGPL | `scripts/package_slicer_engine_macos.sh`、`stage_slicer_engine_agpl_macos.sh` |
| mac 5.5／7.1／7.4／7.6 | `verify_symbol_archive_macos.sh`；`evidence/macos/section7-mac-declare-7.1-20260719.md`；`ci_gate_macos_deid_7.4.sh`；`evidence/macos/functional-7.6-20260719/` |
| Win 7.5／7.6 | `ci_gate_windows_deid_7.5.ps1`；`evidence/windows/functional-7.6-20260719T143000Z/` |
| Launcher D13／final scan | `Bundle-Launcher/scripts/verify_slicer_engine_artifact.sh`、`scan_final_macos_artifact.sh`、`ci_gate_macos_deid_7.4.sh` |
| 權威進度 | 本檔；Launcher 衛星須與本檔一致 |

---

## 6. 雙 repo 同步規則

- **權威：** 本 `PROGRESS.md`＋可重跑磁碟證據（hash／`--help`／目錄是否存在）。  
- **Launcher 衛星**只引用本檔。  
- Legal 1.6 以 [`evidence/legal-1.6-vance-approved-20260719.md`](./evidence/legal-1.6-vance-approved-20260719.md) 為政策證據。  
- mac 現行 consumer＝DMG `…2111`；Win 現行 consumer／PF＝`20260719T162525Z`（help=0；resources=0；**Setup EV Valid**）。  
- **勿**再寫「mac／Win 7.6 對方未跑」— 雙平台最小矩陣 evidence 皆已存在。  
- **2026-07-20：** 衛星對齊；Win 回灌＋resources＋QA 4.2；**7.5 signed Setup**；**5.11／6.4–6.7 Win PASS**。
