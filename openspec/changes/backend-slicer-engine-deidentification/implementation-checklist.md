# 跨 Repository Implementation Checklist

**進度（2026-07-19 夜）：** mac 晚上 consumer 已回灌簽過包（`…2111`；`legal/`＋help=0）。≈**92–94%**。詳見 [`PROGRESS.md`](./PROGRESS.md)。

## Gate 0 — 規格與治理

- [x] `openspec validate backend-slicer-engine-deidentification --strict` 通過（主 change；2026-07-17）
- [x] naming-manifest、artifact-manifest.schema 簽核（黑名單 v1.2 沿用；Security 審閱見 1.5）
- [x] Windows baseline 收集完成（[`evidence/windows/baseline/BASELINE.md`](./evidence/windows/baseline/BASELINE.md)；2026-07-17）
- [x] Windows ABI／PDB／export 政策定案（[`windows-policy.md`](./windows-policy.md)；tasks 2.3；2026-07-17）
- [x] 已知乾淨參考報告批准（[`clean-reference-report.md`](./clean-reference-report.md)；錨點 `m1-close-20260717T032408Z`；2026-07-17）
- [x] A+B+C′ **雙平台 PoC** go／no-go（macOS 2.4＋Windows 2.5；C-full／OLLVM＝L3 不做；Win export=1 → 5.3）
- [x] AGPL／開源法務簽核完成（**1.6 Vance approved 2026-07-19** — email／書面 offer）

## Gate 1 — web_slicer_core／fork

- [x] macOS 真實 OUTPUT_NAME／codeSigningID／Info.plist 去品牌（2026-07-17）
- [x] Agent 中立 env／路徑（`SLICER_ENGINE_BIN`／`SLICER_ENGINE_CLI`；2026-07-17）
- [x] Windows DLL／shim／export／VERSIONINFO 原子遷移（**5.3／3.3 PASS**；`slicer_run_cli` only）
- [x] macOS：dSYM 先封存；**fork 完成 consumer strip**；寫入 pre／post_strip hash manifest；**nm brand 0**（tasks **5.1**）
- [x] Windows headless PDB policy 落地（產→封存→consumer 排除；`package_slicer_engine_windows.ps1`；**5.3／5.4**）
- [x] release-equivalent QA flavor（compile-time harness）；移除 runtime env harness（**macOS 5.6／5.7**；**Win consumer OFF package 閘門 PASS**）
- [x] consumer Release 不含 harness（**macOS 5.7**；**Win scan／package PASS 2026-07-19**）
- [ ] SBOM／exact source commit 產生（6.4）
- [x] 全 CLI operation regression 通過（**macOS 抽樣 2026-07-17**；Windows／完整矩陣 → 7.6）

## Gate 2 — Bundle-Launcher

- [x] 驗證 artifact manifest；僅複製 post-strip 產物（**雙平台 2026-07-19：** Win `build-windows-bundle.ps1`；macOS `verify_slicer_engine_artifact.sh`＋`build-mac-bundle.sh`）
- [x] 雙平台 layout 去品牌；agent 中立 env／路徑
- [x] **驗證** strip／hash 後才允許簽署（不二次 strip／rename；**Win：** Authenticode **手動**；**macOS：** Developer ID）
- [x] macOS codesign（`--identifier slicer-engine`）→ notarize → staple → Gatekeeper（**arm64 手動 PASS**；CI 待）
- [x] Windows Authenticode → install/uninstall（**2026-07-19 手動 Setup Valid＋lifecycle smoke**；內嵌 app exe 未簽）
- [x] AGPL license／NOTICE／source offer 隨正式包可取得（**Win＋mac 簽過包 PASS**；mac＝`…2111`；1.6 approved）

## Gate 3 — 自動掃描

- [x] macOS：**PoC scanner 原型**對 path／identity／`.ips` 符號可讀性通過（`poc/scan_macos_artifact.sh`；非正式 CI gate）
- [x] macOS：正式 path、identity、**local＋global** 符號掃描通過（`scan_slicer_engine_macos.sh`＋`scan_final_macos_artifact.sh` **手動 PASS**；CI 待）
- [x] Windows：path（PE／layout）、VERSIONINFO、exports、debug directory 通過（**`scan_slicer_engine_windows.ps1` 2026-07-19**；`bin/resources/**` 品牌資產僅 note）
- [x] consumer 不含 dSYM／PDB／QA harness（**macOS 5.4／5.7**；**Win package／Launcher gate 2026-07-19**）
- [x] scanner、blacklist **1.2**、pre／post_strip／**post-sign** hashes 入 evidence（雙平台）
- [x] 任一命中 fail-fast，無 `continue-on-error`（雙平台 Launcher／package 已 fail closed；CI 配線待）

## Gate 4 — 動態驗收

- [x] macOS **arm64 PoC**：三種 crash site＋品牌歸因複核通過（正式各 arch／qa flavor 仍待 7.1）
- [x] Windows **x64 PoC**：三種 crash＋minidump 模組中性（2.5；`w25-close-20260717T083241Z`）
- [ ] macOS 各發布 architecture：release-equivalent qa 三種 crash site＋品牌歸因複核通過
- [x] Windows x64：正式 release-equivalent qa 三 crash（**7.3 PASS 2026-07-19** — `evidence/windows/qa-three-crash-20260719/`）
- [ ] consumer 靜態 L1／L2＋binary inspection 通過（正式簽署包 — 手動已有；CI 宣告待）
- [ ] 乾淨環境（無私有 dSYM／PDB／_NT_SYMBOL_PATH）有紀錄（PoC 已記錄教訓；正式 runbook 待補）
- [ ] Agent 在 engine crash 後存活、job failure semantics 正確
- [ ] 受控 dump／report 依資料分類政策保存

## Gate 5 — Release readiness

- [ ] Release Engineering、Backend Security、QA、Legal／OSS 四方簽核（Legal 1.6 已關；其餘待）
- [ ] 舊版相容／升級／rollback 路徑驗證（Win Setup smoke 有；完整矩陣 → 7.6／mac 4.6）
- [ ] 支援 runbook 可依 build ID 找到 symbols（Win OneDrive＋mac drill 有；演練 6.6–6.7 待）
- [x] source offer／exact fork commit 渠道可用（**1.6 email／書面 offer approved**）
- [ ] OpenSpec status 更新為 completed 並準備 archive／spec promotion（目前 **`in_progress`**）
