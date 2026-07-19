# Progress Snapshot — backend-slicer-engine-deidentification

**更新日期：** 2026-07-19（雙平台 Launcher §4：macOS arm64 閉環＋Win post-Authenticode Setup）  
**Change status：** `in_progress`（見 `.openspec.yaml`）  
**權威 macOS PoC：** [`poc/evidence/m1-close-20260717T032408Z/`](./poc/evidence/m1-close-20260717T032408Z/)  
**權威 Windows PoC：** [`poc/evidence/w25-close-20260717T083241Z/`](./poc/evidence/w25-close-20260717T083241Z/)  
**macOS 產品化證據：** [`evidence/macos-productize-5.2-3.5-3.6.md`](./evidence/macos-productize-5.2-3.5-3.6.md)、[`evidence/macos-productize-5.4-5.6-5.7.md`](./evidence/macos-productize-5.4-5.6-5.7.md)  
**macOS Launcher §4：** [`evidence/macos-launcher-section4-20260719.md`](./evidence/macos-launcher-section4-20260719.md)  
**Win Launcher unsigned：** [`evidence/windows-launcher-section4-20260719.md`](./evidence/windows-launcher-section4-20260719.md)  
**Win post-sign Setup：** [`evidence/windows/launcher-1.0.0-postsign-20260719/SUMMARY.md`](./evidence/windows/launcher-1.0.0-postsign-20260719/SUMMARY.md)

---

## 1. 總覽

| 區塊 | 狀態 |
|------|------|
| 治理／命名／schema（§1 大部） | **完成**（缺 1.5／1.6） |
| 雙平台 PoC（§2） | **關閉／PASS** |
| §3 L1 | **macOS 3.1–3.6／Win 3.3 關閉**；**殘留：** CLI `--help` 仍含 `PrusaSlicer` tooltip（待清） |
| §5 C′ | **macOS 5.1／5.2／5.4／5.6／5.7＋Win 5.3／5.4 關閉**；5.1b／5.5 待（mac runbook 草稿已有） |
| §4 Launcher | **macOS arm64 4.1／4.3–4.5 PASS**；**Win 4.2／4.4–4.6 PASS**（含已簽 Setup）；macOS 4.6 完整 lifecycle 待 |
| §6–7 | **部分：** Win 7.5／macOS 7.4 **手動** post-sign PASS；qa 動態／7.6／CI 自動化未開始 |

**完成度（粗）：≈ 85%**（區間 **83–88%**）。  
雙平台 Launcher 工程鏈（fork→package→verify→簽／公證或 Setup）已閉環；剩餘主線＝Legal／AGPL、§7 動態與完整回歸、CLI help／resource 殘留、macOS 4.6、正式 symbol store。

---

## 2. 已驗證結果（雙平台）

### Windows

| 項 | 狀態 |
|----|------|
| **5.3** export=1 | **PASS** |
| Win package／formal scan | **PASS** |
| Launcher §4 unsigned gate | **PASS** |
| **Post-sign Setup 1.0.0** | **PASS** — Authenticode **Valid**（PHROZEN TECH EV）；`/S` upgrade／uninstall／reinstall；安裝後 scan **PASS** |
| Setup SHA256 | `6592EE9E01D311ABE6BEF22FF384DBD3526DCBAC3FB414B797D23EEE37D446C5` |
| 內嵌 `Bundle Launcher.exe` | **NotSigned**（僅簽 Setup；符合現行手動流程） |

```bat
scripts\build_prusaslicer_fork_windows.bat low clean
powershell -File scripts\package_slicer_engine_windows.ps1
powershell -File ..\Bundle-Launcher\scripts\verify_slicer_engine_windows.ps1
# after manual Authenticode on Setup:
# Setup /S → scan installed slicer-engine → Uninstall /S → Setup /S → rescan
```

### macOS

| 項 | 狀態 |
|----|------|
| Formal scan gate | `scan_slicer_engine_macos.sh`；packager fail-closed |
| Consumer | nm 0；無 dSYM；`harness_markers=[]`；PASS |
| QA flavor | `slicer-engine-qa/`＋`qa_delta`；PASS |
| **Launcher §4 arm64** | **PASS** — D13 verify→bundle→Developer ID→notarize→staple→final scan |
| DMG | `~/Desktop/Bundle Launcher_mac_arm64_1.0.0-202607191450.dmg` |

```bash
cd Bundle-Launcher
SKIP_PRINTER_BUILD=1 SKIP_X64=1 ./build-scripts/build-mac-bundle.sh
# then release_sign_notarize.sh with CERT_ID / APPLE_ID / NOTARY_APP_PASSWORD
```

---

## 3. 已知殘留（不擋本輪雙平台 Launcher §4 PASS）

1. CLI `--help`／`PrintConfig.cpp` tooltip 仍含 `PrusaSlicer` 相容性字串（user-visible）  
2. `bin/resources/**` 品牌檔名（profiles／icons；scanner note／後續清理）  
3. 內嵌 Win app exe 未 Authenticode（僅 Setup 簽章）  
4. macOS 4.6 install／upgrade／rollback 完整 lifecycle 未抽樣  
5. 5.5 正式 symbol store／Win PDB；5.1b RTTI；§6 AGPL；§7 動態三 crash／完整 SLA  

---

## 4. 下一步

1. 清 CLI help `PrusaSlicer` 字串（`PrintConfig.cpp` 等）→ 重編重包重驗 `--help`  
2. **5.5** symbol archive；**1.5／1.6** Security／Legal；§6 AGPL  
3. macOS **4.6** lifecycle 抽樣（可選）  
4. §7：qa 三 crash、完整 SLA（7.6）、CI 自動化 7.4／7.5  

---

## 5. 關鍵路徑

| 產物 | 路徑 |
|------|------|
| Win package／scan | `scripts/package_slicer_engine_windows.ps1`、`scan_slicer_engine_windows.ps1` |
| Win Launcher | `Bundle-Launcher/build-scripts/build-windows-bundle.ps1`、`scripts/verify_slicer_engine_windows.ps1` |
| Post-sign evidence (Win) | [`evidence/windows/launcher-1.0.0-postsign-20260719/`](./evidence/windows/launcher-1.0.0-postsign-20260719/) |
| D13 package (macOS) | `scripts/package_slicer_engine_macos.sh` |
| Formal scan (macOS) | `scripts/scan_slicer_engine_macos.sh` |
| Launcher D13 verify (macOS) | `Bundle-Launcher/scripts/verify_slicer_engine_artifact.sh` |
| Final app scan (macOS) | `Bundle-Launcher/scripts/scan_final_macos_artifact.sh` |
| macOS §4 證據 | [`evidence/macos-launcher-section4-20260719.md`](./evidence/macos-launcher-section4-20260719.md) |

---

## 6. 文件同步（2026-07-19）

已對齊（含 stash 合併後）：本檔、`tasks.md`、`.openspec.yaml`、`traceability.md`；Launcher 衛星 change（tasks／.openspec.yaml）。其餘 checklist／effort／FILE-INDEX 等若仍寫「單平台 §4 未做」請以本檔為準。
