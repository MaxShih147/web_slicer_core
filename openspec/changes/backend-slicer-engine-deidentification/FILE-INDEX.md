# 文件索引

> **Change ID：** `backend-slicer-engine-deidentification`  
> **根目錄：** `web_slicer_core/openspec/changes/backend-slicer-engine-deidentification/`  
> **Feature 標題：** 後端切片引擎去識別：Prusa CLI 改名重包與 OS Crash Report 指紋屏蔽（**L2／Win+macOS**）  
> **類型：** Feature（非 Bug／非優化）  
> **接受線：** L1+L2 必須（L2＝精簡版 C′＋D13 流水線）；平台 macOS+Windows 必須；C-full／OLLVM＝L3 不做  
> **Status：** `in_progress`（2026-07-19 夜）· 完成度 ≈ **92–94%** · mac 晚上 consumer 已回灌（`…2111`）· 進度 [`PROGRESS.md`](./PROGRESS.md)

## 1. 本 change 產物

| 檔案 | 說明 |
|------|------|
| [`.openspec.yaml`](./.openspec.yaml) | change 中繼資料（status=`in_progress`） |
| [`clean-reference-report.md`](./clean-reference-report.md) | **已批准**（2026-07-17）macOS 乾淨參考報告／tasks 2.4b |
| [`glossary.md`](./glossary.md) | 跨角色術語表（單一定義入口，不建立新規範） |
| [`proposal.md`](./proposal.md) | 緣由、範圍、影響面 |
| [`design.md`](./design.md) | 決策 D1–D13、L1／L2、**精簡版 C′**、D13 流水線與發布治理 |
| [`tasks.md`](./tasks.md) | 實作與評估檢查清單 |
| [`effort-estimate.md`](./effort-estimate.md) | 人日草案 |
| [`specs/slicer-engine-deidentification/spec.md`](./specs/slicer-engine-deidentification/spec.md) | 需求與 Scenario |
| [`blacklist.md`](./blacklist.md) | Canonical token、scope、例外、pass／fail |
| [`acceptance-procedure.md`](./acceptance-procedure.md) | macOS／Windows 可重現驗收 |
| [`traceability.md`](./traceability.md) | Requirement → Design → Task → Evidence |
| [`implementation-checklist.md`](./implementation-checklist.md) | 跨 repo release gates |
| [`naming-manifest.md`](./naming-manifest.md) | 跨平台命名表／佈局（**approved** 2026-07-17） |
| [`artifact-manifest.schema.md`](./artifact-manifest.schema.md) | fork→Launcher 交接 schema／hash 鏈／flavor（**approved** 2026-07-17） |
| [`crash-harness-forensics.md`](./crash-harness-forensics.md) | crash harness 取證設計修正待辦（compile-time／移出 SLAPrint／三類 crash／參數化） |
| [`poc/REPORT.md`](./poc/REPORT.md) | macOS PoC **關閉**（2026-07-17）：L1+L2+三 crash+scanner PASS；權威證據 `poc/evidence/m1-close-20260717T032408Z/` |
| [`poc/REPORT-WIN.md`](./poc/REPORT-WIN.md) | Windows PoC **關閉／PASS**（2026-07-17 tasks 2.5）：rename／VERSIONINFO／PDBALTPATH／三 crash；權威 `poc/evidence/w25-close-20260717T083241Z/` |
| [`poc/NOTION-TEST-TASK.md`](./poc/NOTION-TEST-TASK.md) | Notion「Test 測試」可貼上全文（依 M1 結果） |
| [`poc/NOTION-WIN-BASELINE-TASK.md`](./poc/NOTION-WIN-BASELINE-TASK.md) | Notion Win baseline（tasks 1.7）可貼上全文 |
| [`poc/NOTION-WIN-POC-TASK.md`](./poc/NOTION-WIN-POC-TASK.md) | Notion Win PoC（tasks 2.5）可貼上全文 |
| [`poc/NOTION-WIN-POLICY-POC-TASK.md`](./poc/NOTION-WIN-POLICY-POC-TASK.md) | Notion **2.3＋2.5 合併** Test（政策定案＋PoC 完整結果） |
| [`windows-policy.md`](./windows-policy.md) | Windows ABI／export／PDB／debug directory **政策定案**（tasks 2.3；2026-07-17） |
| [`evidence/windows/baseline/BASELINE.md`](./evidence/windows/baseline/BASELINE.md) | Windows 現況 baseline 報告（1.7 關閉） |
| [`poc/run_m1_close.sh`](./poc/run_m1_close.sh)／[`poc/scan_macos_artifact.sh`](./poc/scan_macos_artifact.sh) | M1 close 腳本＋scanner 原型 |
| [`poc/run_w25_close.ps1`](./poc/run_w25_close.ps1) | Windows 2.5 close 腳本 |
| [`evidence/macos-productize-5.2-3.5-3.6.md`](./evidence/macos-productize-5.2-3.5-3.6.md) | macOS 5.2／3.5／3.6 抽樣關閉記錄 |
| [`evidence/macos-productize-5.4-5.6-5.7.md`](./evidence/macos-productize-5.4-5.6-5.7.md) | macOS 5.4／5.6／5.7 正式 scan／qa_delta／consumer harness OFF |
| `scripts/package_slicer_engine_macos.sh` | **D13 產品化**（dSYM→strip→manifest；tasks 5.1） |
| `scripts/scan_slicer_engine_macos.sh` | **正式掃描閘**（tasks 5.4／5.6／5.7；packager fail-closed） |
| `scripts/package_slicer_engine_windows.ps1` | **Win D13 package**（PDB 封存、manifest、export／harness 閘） |
| `scripts/scan_slicer_engine_windows.ps1` | **Win 正式掃描閘**（tasks 4.4／4.5／5.4；fail closed；Authenticode 不要求） |
| [`evidence/windows-launcher-section4-20260719.md`](./evidence/windows-launcher-section4-20260719.md) | Win Launcher §4 unsigned gate PASS |
| [`evidence/windows/launcher-1.0.0-postsign-20260719/SUMMARY.md`](./evidence/windows/launcher-1.0.0-postsign-20260719/SUMMARY.md) | **已簽 Setup** post-sign／lifecycle／scan PASS |
| `third_party/slicer-engine/`（local gitignored） | consumer 佈局＋manifest＋`scan-report.json` |
| `third_party/slicer-engine-qa/`（local gitignored） | QA flavor＋`qa_delta` |
| `slicer-engine/`（Win local staging） | Windows consumer layout＋`engine-artifact-manifest.json` |

## 2. 證據與產品脈絡

| 路徑 | 說明 |
|------|------|
| [`../../../../macOS_system_report.md`](../../../../macOS_system_report.md) | 實測 macOS System Report（Prusa 指紋） |
| [`evidence/windows/baseline/`](./evidence/windows/baseline/) | Windows baseline（**1.7 已關閉**；權威 `win-baseline-20260717T055632Z/`） |
| [`poc/evidence/w25-close-20260717T083241Z/`](./poc/evidence/w25-close-20260717T083241Z/) | Windows PoC evidence（**2.5 PASS**） |
| Notion：基礎資安防護 | 產品 story（後端範圍；改名必要 + 加密／屏蔽評估優先） |
| Notion Test 稿（Win 2.3＋2.5） | [`poc/NOTION-WIN-POLICY-POC-TASK.md`](./poc/NOTION-WIN-POLICY-POC-TASK.md) |

## 3. 相關程式／包版（實作時必碰）

| 路徑 | 說明 |
|------|------|
| `web_slicer_core/third_party/prusaslicer_fork/` | 引擎原始碼與建置 |
| `web_slicer_core/scripts/build_prusaslicer_fork_macos.sh` | macOS 建置 |
| `web_slicer_core/scripts/build_prusaslicer_fork_windows.bat` | Windows 建置 |
| `web_slicer_core/agent/config.py` | CLI 路徑 |
| `web_slicer_core/agent/sla_operations.py`／`jobs.py` | subprocess 呼叫 |
| `web_slicer_core/docs/single-node-cloud/agpl-boundary.md` | AGPL 邊界（不得破壞） |
| `Bundle-Launcher/build-scripts/build-mac-bundle.sh` | 打入 `bundle` 資源 |
| `Bundle-Launcher/build-scripts/build-windows-bundle.ps1` | Windows 組包 |
| `Bundle-Launcher/scripts/sign_and_verify.sh` 等 | 簽章／公證 |
| [`../../../../Bundle-Launcher/openspec/changes/backend-slicer-engine-deidentification/`](../../../../Bundle-Launcher/openspec/changes/backend-slicer-engine-deidentification/) | Launcher 本地 change／acceptance |

## 4. 閱讀順序建議

| 角色 | 順序 |
|------|------|
| PM／Max | `glossary.md` → `naming-manifest.md`＋`artifact-manifest.schema.md`（簽核）→ `proposal.md` → `design.md`（威脅模型、D3、D13） |
| 後端／包版 | `design.md` D13 → `artifact-manifest.schema.md` → `spec.md` → `tasks.md` |
| 資安／Release | `blacklist.md` → `acceptance-procedure.md` → `implementation-checklist.md` |
| Legal／OSS | `glossary.md` → `spec.md` REQ-DEID-011 → `agpl-boundary.md` → `tasks.md` §6 |

## 5. 待補交付（實作期）

| 產物 | 狀態 |
|------|------|
| macOS PoC（tasks 2.4） | **已關閉 PASS** — [`poc/REPORT.md`](./poc/REPORT.md)／`m1-close-20260717T032408Z` |
| 乾淨參考報告（tasks 2.4b） | **已批准** — [`clean-reference-report.md`](./clean-reference-report.md) |
| macOS flags 定案（tasks 2.2） | **已完成** — visibility＋否決 strip -x |
| macOS L1 產品化（3.1／3.2／3.4） | **已落地**（2026-07-17 晚）— CMake／plist／help／`SLICER_ENGINE_BIN` |
| macOS D13 package（5.1） | **關閉** — 流水線＋nm brand **0**（2026-07-17 夜） |
| Notion Test 稿 | [`poc/NOTION-TEST-TASK.md`](./poc/NOTION-TEST-TASK.md) |
| 可行性評估報告定案 | 待 `tasks.md` 2.1／2.8；雙平台 C′ 已由 2.4／2.5 PoC 證明 |
| 引擎命名＋交接 schema | naming-manifest＋artifact-manifest.schema；**已簽核（2026-07-17）** |
| Windows baseline | **已關閉**（1.7） |
| Windows PoC | **已關閉 PASS**（2.5） |
| Windows 5.3／formal scan | **已關閉 PASS**（export=1＋`scan_slicer_engine_windows.ps1`） |
| Launcher §4 | **雙平台手動閉環 2026-07-19**（Win Setup／4.6；macOS arm64 verify→notarize→final scan） |
| macOS／Windows final-artifact evidence | **雙平台手動 post-sign evidence 已存**；CI 自動化待 §7 |
| CLI help／resource 殘留 | **雙平台簽過包 CLI help 已清**；resources ≈148 |
| AGPL／source-offer | **1.6 approved**；Win＋mac 簽過包皆有 `legal/`（mac＝`…2111`） |
| 5.5 symbol store | **Win＝OneDrive**；mac 本機 drill PASS；演練 6.6–6.7 後補 |
| Win 7.3 QA 三 crash | **PASS** — `evidence/windows/qa-three-crash-20260719/` |
| mac 晚上回灌 | **PASS** — [`evidence/macos-launcher-evening-reinject-20260719.md`](./evidence/macos-launcher-evening-reinject-20260719.md) |
