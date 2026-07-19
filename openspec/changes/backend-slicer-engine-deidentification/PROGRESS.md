# Progress Snapshot — backend-slicer-engine-deidentification

**更新日期：** 2026-07-19（post-Authenticode Setup 驗收＋文件全面對齊）  
**Change status：** `in_progress`（見 `.openspec.yaml`）  
**權威 macOS PoC：** [`poc/evidence/m1-close-20260717T032408Z/`](./poc/evidence/m1-close-20260717T032408Z/)  
**權威 Windows PoC：** [`poc/evidence/w25-close-20260717T083241Z/`](./poc/evidence/w25-close-20260717T083241Z/)  
**macOS 產品化證據：** [`evidence/macos-productize-5.2-3.5-3.6.md`](./evidence/macos-productize-5.2-3.5-3.6.md)、[`evidence/macos-productize-5.4-5.6-5.7.md`](./evidence/macos-productize-5.4-5.6-5.7.md)  
**Win Launcher unsigned：** [`evidence/windows-launcher-section4-20260719.md`](./evidence/windows-launcher-section4-20260719.md)  
**Win post-sign Setup：** [`evidence/windows/launcher-1.0.0-postsign-20260719/SUMMARY.md`](./evidence/windows/launcher-1.0.0-postsign-20260719/SUMMARY.md)

---

## 1. 總覽

| 區塊 | 狀態 |
|------|------|
| 治理／命名／schema（§1 大部） | **完成**（缺 1.5／1.6） |
| 雙平台 PoC（§2） | **關閉／PASS** |
| §3 L1 | **macOS 3.1–3.6／Win 3.3 關閉**；**殘留：** CLI `--help` 仍含 `PrusaSlicer` tooltip（待清） |
| §5 C′ | **macOS 5.1／5.2／5.4／5.6／5.7＋Win 5.3／5.4 關閉**；5.1b／5.5 待 |
| §4 Launcher | **Win 4.2／4.4／4.5／4.6 關閉**（含已簽 Setup post-sign）；macOS／4.3 待 |
| §6–7 | **部分：** Win 7.5 **手動** post-sign PASS；qa 動態／7.6／macOS／CI 自動化未開始 |

**完成度（粗）：≈ 83%**（區間 **80–85%**）。  
Win 工程鏈（fork→package→Launcher→已簽 Setup→install／uninstall／reinstall→scan）已閉環；剩餘主線＝macOS Launcher、Legal／AGPL、§7 動態與完整回歸、CLI help／resource 殘留清理。

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
| Formal scan／consumer／qa | **PASS**（fork 產品化） |
| Launcher §4 | **未做**（需 Mac） |

---

## 3. 已知殘留（不擋本輪 Win post-sign PASS）

1. CLI `--help`／`PrintConfig.cpp` tooltip 仍含 `PrusaSlicer` 相容性字串（user-visible）  
2. `bin/resources/**` ≈148 品牌檔名（profiles／icons；scanner note only）  
3. 內嵌 app exe 未 Authenticode（僅 Setup 簽章）

---

## 4. 下一步

1. **macOS Launcher §4**（需 Mac）  
2. 清 CLI help `PrusaSlicer` 字串（`PrintConfig.cpp` 等）→ 重編重包重驗 `--help`  
3. **5.5** symbol archive；**1.5／1.6** Security／Legal；§6 AGPL  
4. §7：qa 三 crash、完整 SLA（7.6）、CI 自動化 7.5  

---

## 5. 關鍵路徑

| 產物 | 路徑 |
|------|------|
| Win package／scan | `scripts/package_slicer_engine_windows.ps1`、`scan_slicer_engine_windows.ps1` |
| Win Launcher | `Bundle-Launcher/build-scripts/build-windows-bundle.ps1`、`scripts/verify_slicer_engine_windows.ps1` |
| Post-sign evidence | [`evidence/windows/launcher-1.0.0-postsign-20260719/`](./evidence/windows/launcher-1.0.0-postsign-20260719/) |
| macOS package／scan | `scripts/package_slicer_engine_macos.sh`、`scan_slicer_engine_macos.sh` |

---

## 6. 文件同步（2026-07-19 晚）

已對齊：本檔、`tasks.md`、`.openspec.yaml`、`implementation-checklist.md`、`effort-estimate.md`、`FILE-INDEX.md`、`traceability.md`、`design.md`、`acceptance-procedure.md`、`windows-policy.md`、`poc/REPORT*.md`、baseline／macos footnotes、Launcher 衛星 change（proposal／design／tasks／FILE-INDEX／.openspec.yaml／evidence）。
