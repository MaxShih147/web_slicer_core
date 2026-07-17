# 文件索引

> **Change ID：** `backend-slicer-engine-deidentification`  
> **根目錄：** `web_slicer_core/openspec/changes/backend-slicer-engine-deidentification/`  
> **Feature 標題：** 後端切片引擎去識別：Prusa CLI 改名重包與 OS Crash Report 指紋屏蔽（**L2／Win+macOS**）  
> **類型：** Feature（非 Bug／非優化）  
> **接受線：** L1+L2 必須（L2＝精簡版 C′＋D13 流水線）；平台 macOS+Windows 必須；C-full／OLLVM＝L3 不做  
> **Status：** `in_progress`（2026-07-17）· **M1／2.4 PASS** · 進度總表 [`PROGRESS.md`](./PROGRESS.md)

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
| [`poc/NOTION-TEST-TASK.md`](./poc/NOTION-TEST-TASK.md) | Notion「Test 測試」可貼上全文（依 M1 結果） |
| [`poc/run_m1_close.sh`](./poc/run_m1_close.sh)／[`poc/scan_macos_artifact.sh`](./poc/scan_macos_artifact.sh) | M1 close 腳本＋scanner 原型 |

## 2. 證據與產品脈絡

| 路徑 | 說明 |
|------|------|
| [`../../../../macOS_system_report.md`](../../../../macOS_system_report.md) | 實測 macOS System Report（Prusa 指紋） |
| `evidence/windows/baseline/` | Windows baseline（必備；尚未收集前實作 blocked） |
| Notion：基礎資安防護 | 產品 story（後端範圍；改名必要 + 加密／屏蔽評估優先） |

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
| macOS flags 定案（tasks 2.2） | **已完成** — visibility＋否決 strip -x；hash 鏈歸 5.1 |
| Notion Test 稿 | [`poc/NOTION-TEST-TASK.md`](./poc/NOTION-TEST-TASK.md) |
| 可行性評估報告定案 | 待 `tasks.md` 2.1／2.5／2.8；macOS C′ 已由 PoC 證明 |
| 引擎命名＋交接 schema | naming-manifest＋artifact-manifest.schema；**已簽核（2026-07-17）**；§3／§4／§5 可開工 |
| Windows baseline | 待收集；阻塞 Windows L2 |
| macOS／Windows final-artifact evidence | 待 `tasks.md` §7 |
| AGPL／source-offer release evidence | 待 `tasks.md` §6 |
