## Why

今天錯誤代號的產生方向是**反的**：引擎印出一句英文，Python 拿關鍵字去猜對應的代號。這讓真值落在 Python 手上，而引擎——唯一真正做判斷的那一方——對自己回報的是什麼錯完全無感。

後果有三：

1. **引擎改一個字，分類就靜默壞掉。** 訊息字串是 `_u8L` 可翻譯字串，去識別化或上游 refactor 改寫任何一句，Python 的比對就不再命中，退化成 fallback。目前靠契約測試擋，但那是事後補救。
2. **動態資訊拿不到。** 引擎知道「側壁角度至少要 51.4 度」，但它只印一句沒有數字的話。前端只能顯示「底墊參數不正確」。
3. **15 處 `return 1` 寫在 `bool` 函式裡。** 失敗被讀成成功，離開代碼變 0。這件事必須修，但修之前規則表要先從離開代碼上解開（已由 `merge-engine-result-classifiers` 完成）。

## What Changes

- **引擎新增 error code string table。** 在 C++ 側建立 `code → message` 的單一對照表，涵蓋 `owner=engine` 的 15 個代號（原 13 ＋ `merge-engine-result-classifiers` 新增的 2 個；原寫 16／14，已依程式碼訂正）。message 只服務 log 與 CLI 使用者，**不傳給 Python 或前端**。
- **引擎輸出結構化錯誤行。** 失敗時印一行機器可讀的 JSON 到 **stdout**（不是 stderr，stderr 混了太多雜訊）：

  ```
  PHZ_ERROR {"code":"PAD_CONFIG_INVALID","fields":["pad_wall_slope","pad_wall_thickness","pad_brim_size"],"values":{"min_pad_wall_slope":51.4,"pad_wall_slope":50}}
  ```

  （實作時訂正：`values` 的 key 與 `/support-params/validate` 回傳的同名，前端不必分兩套讀法。）

  `fields` 使用後端 `SLAConfig` 的 snake_case 欄位名（前端 `data-field` 已一致，無需轉換）。
- **Python 新增 `EngineCode` 比對器**，插在 `ENGINE_RULES` 每列 `matchers` 的**最前面**。字串比對降為第二層。規則列的 `code` / `flows` / `stream` 欄位不動。
- **15 處 `return 1` 改為 `return false`**（`CLI/ProcessActions.cpp` L400 · 417 · 426 · 432 · 436 · 442 · 451 · 457 · 477 · 484 · 500 · 512 · 516 · 679 · 737）。
- **D6：支撐 mesh 寫檔失敗改為有代號的失敗。** `Failed to export support mesh to ...` 目前只印 stderr、沒有代號，而且後面沒有 return，支撐流程會 exit 0。改為在**支撐專用模式**輸出結構化錯誤行、登錄新代號 `SUPPORT_MESH_EXPORT_FAILED`，並 `return false`。切片模式照同檔預覽 ZIP 的先例維持原狀：`.sl1` 已寫好，支撐 STL 只給 UI 用，不讓它拖垮切片。
  - （實作時訂正：原寫三個訊息。另外兩個 `Support mesh is empty`、`Pad skipped: ...` 查證後是**警告**，引擎會繼續跑完，之後印出 `(pad only)` 或 `No support/pad mesh generated`，現行 spec 規定這時為 `COMPLETED` + `SUPPORT_NOT_NEEDED`。印成錯誤行會讓分類器把這些正常完成判成失敗，因此不做。若要讓使用者看到這類警告，需另設計「完成的 job 也能帶警告」的管道，另開單。）
- **拆除 legacy exit-code 分支。** 刪掉 `merge-engine-result-classifiers` 留下的 `_LEGACY_EXIT0_ONLY_CODES`，並把 `test_exit_code_independence.py` 的兩個 `xfail` 改為正常斷言。
- **匯出機器可讀的引擎代號清單**，供 Python 登錄檔的契約測試逐項對帳。
- **字串層退場**：本單**保留**字串比對作為第二層。下一版 bundle 出過之後才刪（條件見 `merge-engine-result-classifiers` design D2）。

**本單刻意不做**：不搬 `owner=python` 的 14 個代號進 C++（那些需要 job、檔案系統、HTTP 的上下文）；不改前端（前端只吃 `code`，不受影響）。

## Capabilities

### New Capabilities

- `engine-error-code-table`：引擎側的 code ↔ message 對照表、結構化錯誤行的輸出格式、Python 側的代號比對層，以及兩邊清單的對帳契約。

### Modified Capabilities

- `engine-result-classification`：`matchers` 新增 `EngineCode` 型別並置於最前；分類完全不再依賴離開代碼（legacy 分支移除）。
- `support-generation-error-codes`：支撐 mesh 寫檔失敗從 fail-closed fallback 改為專屬代號 `SUPPORT_MESH_EXPORT_FAILED`（D6）。

## Impact

| 對象 | 影響 |
|---|---|
| `third_party/prusaslicer_fork` | **需重建引擎**。新增 string table、結構化輸出、15 處回傳型別修正、D6 支撐 mesh 寫檔失敗 |
| `agent/engine_rules.py` | 新增 `EngineCode` 比對器 |
| `agent/slicing_classifier.py` | 移除 `_LEGACY_EXIT0_ONLY_CODES` |
| `agent/error_codes.py` | 新增 D6 一個代號（原寫三個，見 D6 訂正）；新增引擎清單對帳 |
| `agent/tests/test_exit_code_independence.py` | 兩個 `xfail` 改為正常斷言 |
| `Bundle-Launcher/bundle-win/slicer-engine/` | **換 binary**，並更新 `artifact-manifest.json`、`engine_build_id.txt`、`sbom.spdx.json`、`source-chain.json`、`scan-report.json` |
| DS-Online | 需補 D6 新代號 `SUPPORT_MESH_EXPORT_FAILED` 的四語系文案；其餘不受影響 |

**前置條件**：`merge-engine-result-classifiers` 必須先完成並關單。未解開 exit-code 相依就動 C++，`INVALID_MODEL` 與 `MODEL_OUT_OF_BOUNDS` 會退化成 `JOB_FAILED`。

**不與面板開放同批**：本單驗收需跑完整切片回歸與引擎重建，節奏與面板開放不同。
