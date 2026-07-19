# 跨 Repository Implementation Checklist

**進度（2026-07-20）：** 雙平台 §7＋Gate 5＋**8.5 promote**＋**5.1b**；Win＋**mac** 回灌／QA 4.2／4.6／5.11／6.4–6.7；未做 8.6。詳見 [`PROGRESS.md`](./PROGRESS.md)。

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
- [x] SBOM／exact source commit 產生（**Win＋mac 6.4／6.5 PASS 2026-07-20** — Win [`source-chain-6.4-6.5-20260720/`](./evidence/windows/source-chain-6.4-6.5-20260720/)；mac [`source-chain-6.4-6.5-20260719T191352Z/`](./evidence/macos/source-chain-6.4-6.5-20260719T191352Z/)）
- [x] 全 CLI operation regression 通過（**macOS 抽樣 2026-07-17**；**雙平台 7.6 最小矩陣 PASS 2026-07-19**；§6 延伸 SHOULD）

## Gate 2 — Bundle-Launcher

- [x] 驗證 artifact manifest；僅複製 post-strip 產物（**雙平台 2026-07-19：** Win `build-windows-bundle.ps1`；macOS `verify_slicer_engine_artifact.sh`＋`build-mac-bundle.sh`）
- [x] 雙平台 layout 去品牌；agent 中立 env／路徑
- [x] **驗證** strip／hash 後才允許簽署（不二次 strip／rename；**Win：** Authenticode **手動**；**macOS：** Developer ID）
- [x] macOS codesign（`--identifier slicer-engine`）→ notarize → staple → Gatekeeper（**arm64 PASS**；**7.4 CI** `ci_gate_macos_deid_7.4.sh` **2026-07-19**）
- [x] Windows Authenticode → install/uninstall（**2026-07-19** Setup Valid＋lifecycle；**2026-07-20** reinject Setup **EV Valid**＋7.5 `-SetupExe` PASS — SHA256 `15C3E441…`；內嵌 app exe 未簽）
- [x] AGPL license／NOTICE／source offer 隨正式包可取得（**Win＋mac 簽過包 PASS**；mac＝`…2111`；1.6 approved）
- [x] Win QA flavor isolation（Launcher **4.2 PASS 2026-07-20**）；**mac QA 4.2 PASS 2026-07-20** — Launcher `verify_qa_flavor_isolation_macos.sh`

## Gate 3 — 自動掃描

- [x] macOS：**PoC scanner 原型**對 path／identity／`.ips` 符號可讀性通過（`poc/scan_macos_artifact.sh`；非正式 CI gate）
- [x] macOS：正式 path、identity、**local＋global** 符號掃描通過（`scan_slicer_engine_macos.sh`＋`scan_final_macos_artifact.sh`；**7.4 CI** PASS）
- [x] Windows：path（PE／layout）、VERSIONINFO、exports、debug directory 通過（**`scan_slicer_engine_windows.ps1`**；**resources brand=0** fail-closed — 2026-07-20）
- [x] consumer 不含 dSYM／PDB／QA harness（**macOS 5.4／5.7**；**Win package／Launcher gate 2026-07-19**）
- [x] scanner、blacklist **1.2**、pre／post_strip／**post-sign** hashes 入 evidence（雙平台）
- [x] 任一命中 fail-fast，無 `continue-on-error`（雙平台 Launcher／package fail closed；**Win 7.5**＋**mac 7.4** CI gates **2026-07-19／20**）

## Gate 4 — 動態驗收

- [x] macOS **arm64 PoC**：三種 crash site＋品牌歸因複核通過
- [x] Windows **x64 PoC**：三種 crash＋minidump 模組中性（2.5；`w25-close-20260717T083241Z`）
- [x] macOS 現行發布 architecture（arm64）：release-equivalent qa 三種 crash site 可觸發（**2026-07-19** — `evidence/macos/qa-three-crash-20260719/`；`.ips` 鑑識見 PoC）
- [x] Windows x64：正式 release-equivalent qa 三 crash（**7.3 PASS 2026-07-19** — `evidence/windows/qa-three-crash-20260719/`）
- [x] consumer 靜態 L1／L2＋binary inspection 通過（**Win：** 手動 post-sign＋**7.5 CI**；**mac：** 手動＋**7.4 CI** PASS）
- [ ] 乾淨環境（無私有 dSYM／PDB／_NT_SYMBOL_PATH）有紀錄（PoC 已記錄教訓；正式 runbook 待補）
- [ ] Agent 在 engine crash 後存活、job failure semantics 正確
- [ ] 受控 dump／report 依資料分類政策保存

## Gate 5 — Release readiness

- [x] Release Engineering、Backend Security、QA、Legal／OSS 四方簽核（**2026-07-19 Vance Approve** — [`evidence/signoff-gate5-pending-20260719.md`](./evidence/signoff-gate5-pending-20260719.md)）
- [x] 舊版相容／升級／rollback 路徑驗證（**Win Setup smoke＋7.2 declare**；**mac 4.6 DMG lifecycle sample PASS 2026-07-20**）
- [x] 支援 runbook 可依 build ID 找到 symbols（**Win 6.6／6.7 PASS**；**mac 6.6／6.7 PASS 2026-07-20** — [`evidence/macos/symbolication-6.6-6.7-20260719T191352Z/`](./evidence/macos/symbolication-6.6-6.7-20260719T191352Z/)）
- [x] source offer／exact fork commit 渠道可用（**1.6 email／書面 offer approved**）
- [x] Spec promote（8.5）→ [`../../specs/slicer-engine-deidentification/spec.md`](../../specs/slicer-engine-deidentification/spec.md)
- [ ] OpenSpec status=`completed`＋archive（8.6；**未執行**；目前仍 `in_progress`）
