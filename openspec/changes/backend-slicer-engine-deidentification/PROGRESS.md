# Progress Snapshot — backend-slicer-engine-deidentification

**更新日期：** 2026-07-19（夜：mac 晚上 consumer 已回灌簽過包）  
**Change status：** `in_progress`（見 `.openspec.yaml`）  

## 證據錨點

| 證據 | 路徑 |
|------|------|
| macOS PoC | [`poc/evidence/m1-close-20260717T032408Z/`](./poc/evidence/m1-close-20260717T032408Z/) |
| Windows PoC | [`poc/evidence/w25-close-20260717T083241Z/`](./poc/evidence/w25-close-20260717T083241Z/) |
| macOS Launcher §4（首次 arm64） | [`evidence/macos-launcher-section4-20260719.md`](./evidence/macos-launcher-section4-20260719.md) |
| macOS 晚上回灌（CLI＋legal） | [`evidence/macos-launcher-evening-reinject-20260719.md`](./evidence/macos-launcher-evening-reinject-20260719.md) |
| macOS staging CLI／AGPL／5.5 | [`evidence/macos-cli-agpl-5.5-20260719.md`](./evidence/macos-cli-agpl-5.5-20260719.md) |
| Win Launcher／post-sign | [`evidence/windows-launcher-section4-20260719.md`](./evidence/windows-launcher-section4-20260719.md)、[`evidence/windows/launcher-1.0.0-postsign-20260719/`](./evidence/windows/launcher-1.0.0-postsign-20260719/) |
| Win CLI help | [`evidence/windows/cli-help-printconfig-20260719.md`](./evidence/windows/cli-help-printconfig-20260719.md) |
| Win 5.5／7.3／Legal 1.6／2.7 | [`evidence/windows-symbol-archive-runbook-5.5.md`](./evidence/windows-symbol-archive-runbook-5.5.md)、[`evidence/windows/qa-three-crash-20260719/`](./evidence/windows/qa-three-crash-20260719/)、[`evidence/legal-1.6-vance-approved-20260719.md`](./evidence/legal-1.6-vance-approved-20260719.md)、[`evidence/functional-budget-2.7-approved-20260719.md`](./evidence/functional-budget-2.7-approved-20260719.md) |

---

## 1. 總覽（可驗證現況）

| 區塊 | 狀態 |
|------|------|
| 治理／命名／schema | **完成**（缺 1.5 Security；**1.6**＝evidence 記載 Vance approved） |
| §2 PoC | **雙平台關閉／PASS** |
| §3 L1／CLI help | **Win＋mac 簽過包已清**（mac `--help`／`--help-fff` PrusaSlicer=0 on `…2111` app） |
| §5 C′／5.5 | 主線關閉；**Win OneDrive adopted**；**mac 本機 drill PASS**；演練 6.6–6.7 後補 |
| §4 Launcher | **雙平台手動閉環 PASS**；mac 現行產物＝晚上回灌 DMG `…2111`；mac 4.6 lifecycle 待 |
| §6 AGPL | **1.6 approved**；**Win＋mac 簽過包皆有 `legal/`** |
| §7 | **Win 7.3 PASS**；7.4／7.5 手動有、CI 待；**7.6 SLA 未跑** |

**完成度（粗）：≈ 92–94%**（mac 回灌缺口已關；主殘留 §7.6／CI／resources／4.6／1.5）。  

**已定案：** Legal 1.6 channel＝email／書面 offer；5.5 Win＝OneDrive 手動；**2.7** golden／perf — [`evidence/functional-budget-2.7-approved-20260719.md`](./evidence/functional-budget-2.7-approved-20260719.md)。  

**明確缺口（勿寫成已完成）：**
1. §7.6（依 2.7 最小矩陣）；7.4／7.5 CI  
2. resources 品牌檔名；mac 4.6；1.5；符號化演練  

---

## 2. 已驗證結果

### Windows（以 Win evidence 為準）

| 項 | 狀態 |
|----|------|
| §4 unsigned＋已簽 Setup lifecycle | **PASS** |
| CLI help 清零 | **PASS** |
| AGPL `legal/`＋1.6 | **PASS** |
| 5.5 OneDrive／7.3 QA 三 crash | **PASS** |

### macOS — 現行簽過產物（2026-07-19 夜）

| 產物 | build_id | 證明 | CLI help | `legal/` |
|------|----------|------|----------|----------|
| **已簽** `.app`＋DMG `…2111` | `…2026-07-19T095348Z` | `post_strip`＝`3c6c0976…`；簽後＝`336f9303…`＝scan JSON **PASS**；Identifier=`slicer-engine` | **PASS**（exit 0；PrusaSlicer=0） | **有** |
| staging（同源） | 同上 | formal scan PASS | **PASS** | **有** |
| 下午 DMG `…1450`（舊） | `…2026-07-17T123302Z` | 歷史證據；**已被 `…2111` 取代為現行 consumer** | 未證明 | 無 |

```bash
cd Bundle-Launcher
SKIP_PRINTER_BUILD=1 SKIP_X64=1 ./build-scripts/build-mac-bundle.sh
export CERT_ID="Developer ID Application: Po Yuan Wang (TM35RSG7WJ)"
export TEAM_ID="TM35RSG7WJ"
export NOTARY_PROFILE="phrozen-notary"
export APP_PATH="dist/mac-arm64/Bundle Launcher.app"
export ARCH_SUFFIX="arm64"
./release_sign_notarize.sh
```

---

## 3. 已知殘留

1. resources 品牌檔名 ≈148  
2. 內嵌 Win app exe 未 Authenticode  
3. macOS 4.6 install lifecycle  
4. §7.6 SLA；7.4／7.5 CI；5.1b；6.6–6.7 演練；1.5 Security  

---

## 4. 下一步

1. **§7.6**（mac／Win 依 2.7 最小矩陣；可與 7.1 證據整理並行）  
2. 7.4／7.5 CI；1.5／2.8／7.7 簽核  
3. 可選：resources、mac 4.6、符號化演練  

---

## 5. 關鍵路徑

| 產物 | 路徑 |
|------|------|
| mac D13 package（含 AGPL staging） | `scripts/package_slicer_engine_macos.sh`、`stage_slicer_engine_agpl_macos.sh` |
| mac 5.5 drill | `scripts/verify_symbol_archive_macos.sh` |
| Launcher D13／final scan | `Bundle-Launcher/scripts/verify_slicer_engine_artifact.sh`、`scan_final_macos_artifact.sh` |
| 權威進度 | 本檔；Launcher 衛星須與本檔一致 |

---

## 6. 雙 repo 同步規則

- **權威：** 本 `PROGRESS.md`＋可重跑磁碟證據（hash／`--help`／目錄是否存在）。  
- **Launcher 衛星**只引用本檔。  
- Legal 1.6 以 [`evidence/legal-1.6-vance-approved-20260719.md`](./evidence/legal-1.6-vance-approved-20260719.md) 為政策證據（非 Apple／hash 級證明）。  
- mac 現行 consumer 以 [`evidence/macos-launcher-evening-reinject-20260719.md`](./evidence/macos-launcher-evening-reinject-20260719.md)（DMG `…2111`）為準，勿再引用 `…1450` 作 CLI／AGPL 現況。
