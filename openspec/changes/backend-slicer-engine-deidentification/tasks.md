> **進度快照（2026-07-19）：** **Windows Launcher §4**（含已簽 Setup post-sign／4.6）與 **macOS Launcher §4 arm64**（D13 verify→組包→Developer ID→notarize→staple→final scan）皆已落地。下一步：**5.5**／§6–7 其餘／CLI help 殘留清理。詳見 [`PROGRESS.md`](./PROGRESS.md)。
## 1. 治理與必要輸入

- [x] 1.1 [REQ-DEID-002] 接受線定案：本版 L2（含 L1）
- [x] 1.2 [REQ-DEID-003] 平台定案：macOS + Windows 皆必過
- [x] 1.3a [REQ-DEID-015] 四項 canonical 已確認：`slicer-engine`／`slicer_core.dll`／`slicer_run_cli`／正式包目錄 `slicer-engine/`（2026-07-17；見 naming-manifest §0）
- [x] 1.3 [REQ-DEID-015] 產品完整簽核 [`naming-manifest.md`](./naming-manifest.md)（衍生 thread／env／VERSIONINFO 與簽核欄勾選；Status=approved）
- [x] 1.4 [REQ-DEID-015／LAUNCHER-001] 簽核 [`artifact-manifest.schema.md`](./artifact-manifest.schema.md)（pre／post_strip hash、flavor、files；Status=approved）
- [ ] 1.5 [REQ-DEID-007] Security／Release 審閱 A+B+C′ 必要、C-full／D／E 僅加成（L3）
- [ ] 1.6 [REQ-DEID-011] Legal／OSS owner 簽核修改後 fork 的 AGPL release policy
- [x] 1.7 [REQ-DEID-003/006] 保存 Windows 現況 baseline（2026-07-17；依 `acceptance-procedure.md` §5.1）：process／module、VERSIONINFO、`dumpbin /exports`（含 `slic3r_main`）、PDB path、shim loader error、minidump 模組＋PDB-free stack。證據 [`evidence/windows/baseline/win-baseline-20260717T055632Z/`](./evidence/windows/baseline/win-baseline-20260717T055632Z/)、[`evidence/windows/baseline/BASELINE.md`](./evidence/windows/baseline/BASELINE.md)。
- [x] 1.8 [REQ-DEID-006] C 策略定案：精簡版 C′；全面 namespace／OLLVM＝L3 不做（2026-07-17）
- [x] 1.9 [REQ-DEID-006／D13] strip／sign ownership 定案：fork strip＋manifest；Launcher 只驗證＋簽署

**Dependency：** 1.3／1.4／1.7／**2.3／2.5／2.6(PoC)** 已完成（2026-07-17）；§3／§4／§5 可依簽核名稱與雙平台 PoC 開工。
## 2. 可行性評估與雙平台 PoC

- [ ] 2.1 [REQ-DEID-006/007] 產出 A–E 可行性報告；**C′ 必須可達雙平台 L2**；明確記錄 C-full／OLLVM 為 L3 不做。（**進度：** 雙平台 C′ 可行性已由 **2.4／2.5 PoC** 證明；**書面 A–E 報告**仍缺）
- [x] 2.2 [REQ-DEID-006/012/D13] 定案 macOS（2026-07-17 PoC）：`-fvisibility=hidden -fvisibility-inlines-hidden`（libslic3r＋CLI）；**否決 `strip -x`**；採 plain `strip`；dSYM 先封存再 strip；驗收禁止同 UUID dSYM／未 strip 污染。見 [`poc/REPORT.md`](./poc/REPORT.md)。**pre／post_strip manifest hash 鏈**已由 **5.1** `scripts/package_slicer_engine_macos.sh` 產品化。
- [x] 2.3 [REQ-DEID-006/012] 定案 Windows（2026-07-17）：DLL＋shim ABI（`slicer-engine.exe`→`slicer_core.dll`→唯一 `slicer_run_cli`）；export 收斂為 1（否決只改名留下 470 mangled）；headless `/Zi`＋`/DEBUG`＋`/PDB:`＋**`/PDBALTPATH:`**；產→封存→consumer 無 pdb／無品牌 debug path；VERSIONINFO exe+DLL；原子遷移順序。見 [`windows-policy.md`](./windows-policy.md)。
- [x] 2.4 [REQ-DEID-006] macOS PoC **關閉**（2026-07-17）：改名＋`codeSigningID`＝L1 OK；visibility＋plain `strip`；thread→`slicer-worker`；三種 crash（含 exception／abort）皆有 `.ips`；乾淨符號環境下 `Slic3r::`=0；scanner PASS。證據 [`poc/evidence/m1-close-20260717T032408Z/`](./poc/evidence/m1-close-20260717T032408Z/)、[`poc/REPORT.md`](./poc/REPORT.md)。殘餘 nm≈172 移交 5.1。
- [x] 2.4b [REQ-DEID-006] 「已知乾淨參考報告」**已批准**（2026-07-17）：[`clean-reference-report.md`](./clean-reference-report.md)；錨點 `poc/evidence/m1-close-20260717T032408Z/`
- [x] 2.5 [REQ-DEID-006] Windows PoC **關閉／PASS**（2026-07-17）：`slicer-engine.exe`／`slicer_core.dll`／`slicer_run_cli`；VERSIONINFO 中性；`/PDBALTPATH:` RSDS 短中性名；三種 crash（overflow／segfault／exception）＋dump；minidump 模組無 `PrusaSlicer`。證據 [`poc/evidence/w25-close-20260717T083241Z/`](./poc/evidence/w25-close-20260717T083241Z/)、[`poc/REPORT-WIN.md`](./poc/REPORT-WIN.md)。**殘餘 named exports≈470 已由 5.3 產品化關閉**；LocalDumps 未穩定（本 PoC 以 `cdb`＋exit 證明）。
- [x] 2.6 [REQ-DEID-009] PoC：compile-time `BUNDLE_QA_CRASH_HARNESS`＋`bundle_qa_crash_probe`（已移出 `SLAPrint.cpp`）；QA flavor ON 可觸發三種 mode。**正式 consumer OFF 靜態稽核：** Win package 閘門＋macOS **5.6／5.7** 皆已關閉（2026-07-17）。
- [ ] 2.7 [REQ-DEID-014] 定案 golden output tolerance 與 performance budget
- [ ] 2.8 評估結論經 Backend Security／Release Engineering 審閱並回寫 `design.md`

**Dependency：** §5 雙平台可依 2.2／2.3／2.5 開工。§7 MUST blocked on 其餘 §2（2.1／2.7／2.8）與正式落地。

## 3. web_slicer_core／fork：L1 與功能相容

- [x] 3.1 [REQ-DEID-004/015] CMake 雙平台 target／output／runtime directory 使用簽核名稱（2026-07-17：macOS `OUTPUT_NAME=slicer-engine`、移除品牌 POST_BUILD symlink；Win 已驗證 `slicer-engine`／`slicer_core`＋staging）
- [x] 3.2 [REQ-DEID-005] macOS codeSigningID／Info.plist（刪除或中性化）／Version／thread name 去品牌（2026-07-17：`Info.plist.in` 中性；`--help`→`slicer-engine`／`Slicer Engine …`；package `codesign --identifier slicer-engine`；thread `slicer-worker`／`slicer-bg-slc`）
- [x] 3.3 [REQ-DEID-005/006] Windows VERSIONINFO（exe＋DLL 分 rc）、shim／export／agent 路徑（**Win 已驗證** dumpbin=1、`--help`）
- [x] 3.4 [REQ-DEID-004] 更新 `agent/config.py` 與 `SLICER_ENGINE_BIN`；舊 `PRUSA_SLICER_BIN` 僅 local fallback（跨平台；Win／macOS 路徑已煙測）
- [x] 3.5 [REQ-DEID-004] 掃描 user-visible errors、resources、paths、symlink 與 loader diagnostics（**macOS 2026-07-17** agent／CLI 錯誤中性；**Win 2026-07-19 post-sign：** `--help` 開頭中性，但 tooltip 仍含 `PrusaSlicer` 相容性字串 — 見 [`evidence/windows/launcher-1.0.0-postsign-20260719/SUMMARY.md`](./evidence/windows/launcher-1.0.0-postsign-20260719/SUMMARY.md)；`PrintConfig.cpp` 待清；resources 品牌檔名屬後續）
- [x] 3.6 [REQ-DEID-014] 雙平台執行完整 CLI operation／failure regression（**macOS 抽樣關閉 2026-07-17：** help／fail／`--export-sla`→`.sl1` PASS；Windows 與完整矩陣仍見 **7.6**）

## 4. Bundle-Launcher 跨平台包版

- [x] 4.1 [REQ-DEID-004] 更新 macOS 組包路徑 → `slicer-engine/`（**2026-07-19：** `build-mac-bundle.sh` 接 `third_party/slicer-engine`＋D13 verify；arm64 正式組包 PASS；證據 [`evidence/macos-launcher-section4-20260719.md`](./evidence/macos-launcher-section4-20260719.md)）
- [x] 4.2 [REQ-DEID-004/006] 更新 Windows x64 DLL＋shim＋resource 組包路徑（**2026-07-19：** `build-windows-bundle.ps1` D13 copy＋gate；`bundle-win`／`win-unpacked` 已交接掃描 PASS；證據 [`evidence/windows-launcher-section4-20260719.md`](./evidence/windows-launcher-section4-20260719.md)）
- [x] 4.3 [REQ-DEID-005] 更新簽章／公證／Authenticode 對新產物之識別（**macOS 2026-07-19：** engine `codesign --identifier slicer-engine`＋Developer ID＋notarize／staple PASS；**Win：** Authenticode 維持手動，組包腳本明確 skip）
- [x] 4.4 [REQ-DEID-013] 接入 final-artifact scanner，任何未豁免命中 fail closed（**macOS：** `scan_final_macos_artifact.sh` PASS；**Win 靜態 gate：** `scan_slicer_engine_windows.ps1`）
- [x] 4.5 [REQ-DEID-013/D13] 驗證 fork 已 strip（manifest hash＋掃描）；Launcher 不二次 strip／rename（**macOS：** `verify_slicer_engine_artifact.sh` pre-sign／post-sign；**Win 2026-07-19 PASS**）
- [x] 4.6 [REQ-DEID-014] packaged agent 雙平台可呼叫新 CLI 並通過 install／upgrade／rollback（**Win 2026-07-19：** 已簽 Setup install／uninstall／reinstall＋post-sign scan PASS；證據 [`evidence/windows/launcher-1.0.0-postsign-20260719/SUMMARY.md`](./evidence/windows/launcher-1.0.0-postsign-20260719/SUMMARY.md)；完整 SLA 回歸／rollback 舊版矩陣仍見 7.6；**macOS 4.6 抽樣／完整 lifecycle 仍待**）

## 5. L2／精簡版 C′ 與 crash harness（必要）

- [x] 5.1 [REQ-DEID-006/D13] macOS fork：依 2.2 定案 flags 產品化＋產 dSYM＋strip；產出 manifest pre／post_strip hash；收斂殘餘 nm brand（PoC≈172）（**關閉 2026-07-17：** `package_slicer_engine_macos.sh`；補 visibility；CLI `-Wl,-exported_symbol,_main`；consumer **nm brand global=0／local=0**）
- [ ] 5.1b [REQ-DEID-006] RTTI／例外：拋例外 crash site＋必要時 top-level catch（PoC exception→`.ips` 已證明可行；正式化）
- [x] 5.2 [REQ-DEID-006] 全部 thread call site 中性化（2026-07-17：`slicer-worker`／`slicer-tbb-N`；GUI `slicer-bg-slc`；證據 [`evidence/macos-productize-5.2-3.5-3.6.md`](./evidence/macos-productize-5.2-3.5-3.6.md)）
- [x] 5.3 [REQ-DEID-006] Windows：export 收斂為 1＋PDB 封存／排除（**2026-07-17 Win 驗證 PASS**：`dumpbin`=`slicer_run_cli` only；`package_slicer_engine_windows.ps1`）
- [x] 5.4 [REQ-DEID-006] consumer：local＋global 符號掃描通過；無 dSYM／PDB／品牌 debug path（**macOS：** `scan_slicer_engine_macos.sh` PASS；**Win 2026-07-19：** `scan_slicer_engine_windows.ps1` PASS — export／VERSIONINFO／harness／layout）
- [ ] 5.5 [REQ-DEID-012] symbol archive、build ID、ACL、retention、hash、runbook（**macOS 半邊草稿：** [`evidence/macos-symbol-archive-runbook-5.5.md`](./evidence/macos-symbol-archive-runbook-5.5.md)；缺正式 store／Win PDB／演練）
- [x] 5.6 [REQ-DEID-009/D7] compile-time QA harness；release-equivalent qa manifest／`qa_delta`；移除 runtime env harness（**macOS：** `SLICER_ENGINE_FLAVOR=qa`＋`qa_delta`；**Win：** consumer 預設 OFF＋package 靜態稽核 PASS）
- [x] 5.7 [REQ-DEID-009] Consumer binary inspection 無 harness（**macOS** scan＋`strings`；**Win** package 閘門）
- [x] 5.8 [REQ-DEID-007] （明確不做）C-full／OLLVM＝L3 殘餘風險
- [ ] 5.9 [REQ-DEID-007] （選配）D packer
- [ ] 5.10 [REQ-DEID-007] （預設否）E Crash Reporter intercept
- [ ] 5.11 [REQ-DEID-008] subprocess boundary test

## 6. AGPL／供應鏈／發布資訊

- [ ] 6.1 [REQ-DEID-011] 修正 `agpl-boundary.md` 與實際 modified fork 狀態一致
- [ ] 6.2 [REQ-DEID-011] 正式包提供 AGPL license、copyright、顯著修改聲明
- [ ] 6.3 [REQ-DEID-011] 提供 exact fork commit 的 Corresponding Source URL／written offer
- [ ] 6.4 [REQ-DEID-011] 建立 binary hash → build manifest／SBOM（SPDX 2.3 JSON，見 `design.md` D10a） → source commit 對應證據
- [ ] 6.5 [REQ-DEID-012] Engine `--version` 或 manifest 提供 neutral build ID
- [ ] 6.6 [REQ-DEID-012] 完成 production symbolication 演練
- [ ] 6.7 [REQ-DEID-012] 完成 symbol loss／artifact rollback 演練

## 7. 雙平台驗收與自動化

- [ ] 7.1 [REQ-DEID-002/003/006/010] macOS 各發布 architecture L1+L2 通過
- [ ] 7.2 [REQ-DEID-002/003/006/010] Windows x64 L1+L2 通過
- [ ] 7.3 [REQ-DEID-006/009] **三種** QA crash site 均通過；consumer 靜態＋inspection 通過
- [ ] 7.4 [REQ-DEID-013] macOS post-sign／notarize／staple CI gate 通過（**arm64 手動閉環 2026-07-19 PASS** — 見 [`evidence/macos-launcher-section4-20260719.md`](./evidence/macos-launcher-section4-20260719.md)；正式 CI 自動化仍待）
- [ ] 7.5 [REQ-DEID-013] Windows post-Authenticode CI gate 通過（**2026-07-19 手動：** Setup Valid＋安裝後 scan PASS — [`evidence/windows/launcher-1.0.0-postsign-20260719/SUMMARY.md`](./evidence/windows/launcher-1.0.0-postsign-20260719/SUMMARY.md)；正式 CI 自動化仍待）
- [ ] 7.6 [REQ-DEID-014] 雙平台 functional／performance regression 通過
- [ ] 7.7 [REQ-DEID-010] Evidence metadata、hash、scanner／blacklist version、四方簽核齊備

## 8. OpenSpec lifecycle

- [ ] 8.1 [REQ-DEID-001] 確認範圍未夾帶前端／UI／安裝流程
- [ ] 8.2 更新 `traceability.md`，所有 Requirement 均有 Design／Task／Evidence
- [x] 8.3 執行 `openspec validate backend-slicer-engine-deidentification --strict`（2026-07-17 通過；**2026-07-19 文件對齊後重跑 PASS**）
- [x] 8.4 將 `.openspec.yaml` status 更新為 **`in_progress`**（2026-07-17；M1／2.4 關閉後）。`completed` 待雙平台 L1+L2＋gates
- [ ] 8.5 完成時將能力 spec promote 至 `openspec/specs/slicer-engine-deidentification/spec.md`
- [ ] 8.6 將 change archive 至 `openspec/changes/archive/YYYY-MM-DD-backend-slicer-engine-deidentification/`
