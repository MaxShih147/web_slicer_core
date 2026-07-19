# Progress Snapshot — backend-slicer-engine-deidentification

**更新日期：** 2026-07-19（1.6 Vance approved；**5.5 Win＝OneDrive 手動**已上傳 `20260719T095415Z`；接著 §7）  
**Change status：** `in_progress`（見 `.openspec.yaml`）  
**權威 macOS PoC：** [`poc/evidence/m1-close-20260717T032408Z/`](./poc/evidence/m1-close-20260717T032408Z/)  
**權威 Windows PoC：** [`poc/evidence/w25-close-20260717T083241Z/`](./poc/evidence/w25-close-20260717T083241Z/)  
**macOS 產品化證據：** [`evidence/macos-productize-5.2-3.5-3.6.md`](./evidence/macos-productize-5.2-3.5-3.6.md)、[`evidence/macos-productize-5.4-5.6-5.7.md`](./evidence/macos-productize-5.4-5.6-5.7.md)  
**macOS Launcher §4：** [`evidence/macos-launcher-section4-20260719.md`](./evidence/macos-launcher-section4-20260719.md)  
**Win Launcher unsigned：** [`evidence/windows-launcher-section4-20260719.md`](./evidence/windows-launcher-section4-20260719.md)  
**Win post-sign Setup：** [`evidence/windows/launcher-1.0.0-postsign-20260719/SUMMARY.md`](./evidence/windows/launcher-1.0.0-postsign-20260719/SUMMARY.md)  
**Win CLI help cleanup：** [`evidence/windows/cli-help-printconfig-20260719.md`](./evidence/windows/cli-help-printconfig-20260719.md)  
**Win 5.5 runbook：** [`evidence/windows-symbol-archive-runbook-5.5.md`](./evidence/windows-symbol-archive-runbook-5.5.md)  
**Legal 1.6：** [`evidence/legal-1.6-vance-approved-20260719.md`](./evidence/legal-1.6-vance-approved-20260719.md)

---

## 1. 總覽

| 區塊 | 狀態 |
|------|------|
| 治理／命名／schema（§1 大部） | **完成**（缺 1.5 Security；**1.6 Legal＝Vance approved**） |
| 雙平台 PoC（§2） | **關閉／PASS** |
| §3 L1 | **關閉**（Win CLI help 已清）；resources ≈148 仍殘 |
| §5 C′ | **大部關閉**；5.1b 待；**5.5 Win＝OneDrive 手動（已上傳一版）**；macOS store／演練後補 |
| §4 Launcher | **雙平台工程閉環**；macOS 4.6 完整 lifecycle 待 |
| §6–7 | **§6＋1.6 關閉**；**Win 7.3 QA 三 crash PASS**；Win 7.5 **手動** PASS（CI 後補）；**7.6 SLA 未跑** |

**完成度（粗）：≈ 90%**。  
**已定案（勿再列「仍待」）：** Legal 1.6；5.5 Win store＝**OneDrive 手動**（禁 git；無強制 public GitHub URL）。  
剩餘主線＝§7 動態／SLA／CI、resources、macOS 4.6、1.5 Security。

---

## 2. 已驗證結果（雙平台）

### Windows

| 項 | 狀態 |
|----|------|
| **5.3** export=1 | **PASS** |
| Win package／formal scan | **PASS**（含 **legal/** fail-closed） |
| CLI `--help`／`--help-fff`／`--help-sla` | **PASS** — 零 `PrusaSlicer`（build `20260719T095415Z`） |
| Launcher §4 unsigned gate | **PASS** |
| **Post-sign Setup 1.0.0** | **PASS** — Authenticode **Valid**（PHROZEN TECH EV）；install／uninstall／reinstall；scan **PASS** |
| Setup SHA256 | `6592EE9E01D311ABE6BEF22FF384DBD3526DCBAC3FB414B797D23EEE37D446C5` |
| AGPL legal pack | `slicer-engine/legal/`；**1.6 Vance approved**（email／書面 offer） |
| **5.5 OneDrive** | 已上傳 `…\slicer-engine-symbols\windows\20260719T095415Z\` |
| **7.3 QA 三 crash** | **PASS** — [`evidence/windows/qa-three-crash-20260719/SUMMARY.md`](./evidence/windows/qa-three-crash-20260719/SUMMARY.md) |
| 內嵌 `Bundle Launcher.exe` | **NotSigned**（僅簽 Setup） |

```bat
scripts\build_prusaslicer_fork_windows.bat low
powershell -File scripts\package_slicer_engine_windows.ps1
powershell -File ..\Bundle-Launcher\scripts\verify_slicer_engine_windows.ps1
```

### macOS

| 項 | 狀態 |
|----|------|
| Formal scan gate | `scan_slicer_engine_macos.sh`；packager fail-closed |
| Consumer | nm 0；無 dSYM；`harness_markers=[]`；PASS |
| QA flavor | `slicer-engine-qa/`＋`qa_delta`；PASS |
| **Launcher §4 arm64** | **PASS** — D13 verify→bundle→Developer ID→notarize→staple→final scan |
| DMG | `~/Desktop/Bundle Launcher_mac_arm64_1.0.0-202607191450.dmg` |

---

## 3. 已知殘留

1. ~~CLI `--help` `PrusaSlicer` tooltip~~ → **已清（Win 2026-07-19）**  
2. `bin/resources/**` 品牌檔名（profiles／icons；scanner note）  
3. 內嵌 Win app exe 未 Authenticode（僅 Setup 簽章）  
4. macOS 4.6 install／upgrade／rollback 完整 lifecycle 未抽樣  
5. ~~5.5 正式 store~~ → **Win 定案 OneDrive 手動**（已上傳 `20260719T095415Z`）；macOS／演練後補；5.1b RTTI  
6. ~~Legal 1.6~~ → **Vance approved**（email／書面 offer）  
7. ~~§7.3 動態三 crash~~ → **Win PASS**；完整 SLA／CI 自動化仍開  

---

## 4. 下一步（Windows 機優先）

1. **§7.6** SLA 回歸（完整矩陣）— 排程另跑  
2. **§7.5** 升 CI（手動已 PASS）  
3. 可選：resources 品牌檔名；Launcher 4.2 QA 組包；1.5 Security；5.5 符號化演練  

**已定案（勿再當「仍待」）：**  
- Legal 1.6 — Vance approved；email／書面 offer；無強制 GitHub URL  
- 5.5 Win store — OneDrive 手動（已上傳 `20260719T095415Z`）  
- §7.3 Win QA 三 crash — PASS

---

## 5. 關鍵路徑

| 產物 | 路徑 |
|------|------|
| Win package／scan | `scripts/package_slicer_engine_windows.ps1`、`scan_slicer_engine_windows.ps1` |
| Win legal templates | `legal/slicer-engine/` |
| Win Launcher | `Bundle-Launcher/build-scripts/build-windows-bundle.ps1`、`scripts/verify_slicer_engine_windows.ps1` |
| Post-sign evidence (Win) | [`evidence/windows/launcher-1.0.0-postsign-20260719/`](./evidence/windows/launcher-1.0.0-postsign-20260719/) |
| D13 package (macOS) | `scripts/package_slicer_engine_macos.sh` |
| Formal scan (macOS) | `scripts/scan_slicer_engine_macos.sh` |
| Launcher D13 verify (macOS) | `Bundle-Launcher/scripts/verify_slicer_engine_artifact.sh` |
| Final app scan (macOS) | `Bundle-Launcher/scripts/scan_final_macos_artifact.sh` |
| macOS §4 證據 | [`evidence/macos-launcher-section4-20260719.md`](./evidence/macos-launcher-section4-20260719.md) |

---

## 6. 文件同步（2026-07-19）

已對齊：本檔、`tasks.md`（3.5／5.5／6.1–6.3）、`agpl-boundary.md`、Launcher satellite `tasks.md` 4.3、Win evidence（CLI help／5.5 runbook／§7 follow-up）。
