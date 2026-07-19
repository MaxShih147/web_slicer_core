# 跨 Repository Implementation Checklist

**進度（2026-07-17 夜）：** Gate 0 大部完成；雙平台 PoC 已關閉；**macOS Gate 1：3.1／3.2／3.4＋5.1 關閉**（nm brand 0）。詳見 [`PROGRESS.md`](./PROGRESS.md)。

## Gate 0 — 規格與治理

- [x] `openspec validate backend-slicer-engine-deidentification --strict` 通過（主 change；2026-07-17）
- [x] naming-manifest、artifact-manifest.schema 簽核（黑名單 v1.2 沿用；Security 審閱見 1.5）
- [x] Windows baseline 收集完成（[`evidence/windows/baseline/BASELINE.md`](./evidence/windows/baseline/BASELINE.md)；2026-07-17）
- [x] Windows ABI／PDB／export 政策定案（[`windows-policy.md`](./windows-policy.md)；tasks 2.3；2026-07-17）
- [x] 已知乾淨參考報告批准（[`clean-reference-report.md`](./clean-reference-report.md)；錨點 `m1-close-20260717T032408Z`；2026-07-17）
- [x] A+B+C′ **雙平台 PoC** go／no-go（macOS 2.4＋Windows 2.5；C-full／OLLVM＝L3 不做；Win export=1 → 5.3）
- [ ] AGPL／開源法務簽核完成

## Gate 1 — web_slicer_core／fork

- [x] macOS 真實 OUTPUT_NAME／codeSigningID／Info.plist 去品牌（2026-07-17 晚：正式落地；thread 全 call site 稽核仍見 **5.2**）
- [x] Agent 中立 env／路徑（`SLICER_ENGINE_BIN`／`SLICER_ENGINE_CLI`；2026-07-17）
- [ ] Windows DLL／shim／export／VERSIONINFO 原子遷移（**PoC 已驗證** rename／VERSIONINFO／PDBALTPATH；export=1 → **5.3**；Launcher 路徑未完）
- [x] macOS：dSYM 先封存；**fork 完成 consumer strip**；寫入 pre／post_strip hash manifest；**nm brand 0**（2026-07-17 夜：tasks **5.1** 關閉）
- [ ] Windows headless PDB policy 落地（產→封存→consumer 排除；**PDBALTPATH PoC 2.5 已證**）
- [x] release-equivalent QA flavor（compile-time harness）；移除 runtime env harness（**macOS 2026-07-17：** 5.6／5.7；`qa_delta`＋consumer scan PASS；Windows 仍待）
- [x] consumer Release 不含 harness（**macOS 2026-07-17：** 5.7；Windows 仍待）
- [ ] SBOM／exact source commit 產生
- [x] 全 CLI operation regression 通過（**macOS 抽樣 2026-07-17**；Windows／完整矩陣 → 7.6）

## Gate 2 — Bundle-Launcher

- [ ] 驗證 artifact manifest；僅複製 post-strip 產物
- [ ] macOS／Windows layout 去品牌；agent 中立 env／路徑
- [ ] **驗證** strip／hash 後才 signing（不二次 strip／rename）
- [ ] macOS codesign（中性 identifier）→ notarize → staple → Gatekeeper
- [ ] Windows Authenticode → install/uninstall
- [ ] AGPL license／NOTICE／source offer 隨正式包可取得

## Gate 3 — 自動掃描

- [x] macOS：**PoC scanner 原型**對 path／identity／`.ips` 符號可讀性通過（`poc/scan_macos_artifact.sh`；非正式 CI gate）
- [ ] macOS：正式 CI path、identity、**local＋global** 符號掃描通過
- [ ] Windows：path、VERSIONINFO、exports、debug directory 通過
- [x] consumer 不含 dSYM／PDB／QA harness（**macOS 2026-07-17：** 5.4／5.7 scan；Windows PDB 仍見 5.3）
- [ ] scanner、blacklist **1.2**、pre／post_strip／post-sign hashes 入 evidence
- [ ] 任一命中 fail-fast，無 `continue-on-error`

## Gate 4 — 動態驗收

- [x] macOS **arm64 PoC**：三種 crash site＋品牌歸因複核通過（正式各 arch／qa flavor 仍待 7.1／7.3）
- [x] Windows **x64 PoC**：三種 crash＋minidump 模組中性（2.5；`w25-close-20260717T083241Z`；正式 qa flavor／§7 仍待）
- [ ] macOS 各發布 architecture：release-equivalent qa 三種 crash site＋品牌歸因複核通過
- [ ] Windows x64：正式 release-equivalent qa／§7 同上
- [ ] consumer 靜態 L1／L2＋binary inspection 通過
- [ ] 乾淨環境（無私有 dSYM／PDB／_NT_SYMBOL_PATH）有紀錄（PoC 已記錄教訓；正式 runbook 待補）
- [ ] Agent 在 engine crash 後存活、job failure semantics 正確
- [ ] 受控 dump／report 依資料分類政策保存

## Gate 5 — Release 與 rollback

- [ ] Release Engineering、Backend Security、QA、Legal／OSS 四方簽核
- [ ] 舊版相容／升級／rollback 路徑驗證
- [ ] 支援 runbook 可依 build ID 找到 symbols
- [ ] source offer URL 與 exact fork commit 可用
- [ ] OpenSpec status 更新為 completed 並準備 archive／spec promotion（目前 **`in_progress`**）
