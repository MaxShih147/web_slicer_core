## Why

Web API（`GET /jobs/{id}` 等）回傳的 `estimatedPrintTime` 來自 [jobs.py](agent/jobs.py#L156) 解析 fork 寫入 `.sl1` 的舊式 SL1 估值（`printTime`），而下載的 PRZ 檔內的列印時間卻是 [prz_encoder.py](agent/prz_encoder.py#L631) 透過 `_compute_print_time()` 以新物理公式（exposure + light-off + lift/retract motion，速度 mm/min ÷ 60）推導出來的值。兩條路徑各算各的、互不同步，導致使用者在網頁上看到的時間與實機列印（PRZ）所依據的時間不一致。本變更建立**單一真值來源**，讓 Web API 顯示的時間即為 PRZ 物理公式的結果。

## What Changes

- **以物理公式複寫 status.json 的列印時間（核心方案）**：在 [jobs.py](agent/jobs.py) 切片解析完成後，呼叫與 PRZ 相同的 `_compute_print_time()` 計算物理列印時間，並複寫 `status.json["estimated_print_time"]`，取代原本來自 fork SL1 的估值。Web API 既有回傳欄位（`estimatedPrintTime`）不變，僅其數值來源改變。
- **持久化前端完整 config**：將前端送來的完整 config 字典存為獨立檔案 `jobs/{id}/prz_config.json`，使切片解析階段能取得計算物理時間所需的 timing / lift / retract 參數（與 PRZ 匯出路徑使用同一份來源）。
- **重構：抽離萃取邏輯以解循環依賴**：將 `_extract_prz_timing_config()` 從 [api_v2.py](agent/api_v2.py#L1402) 移至 [models.py](agent/models.py)，讓 [jobs.py](agent/jobs.py) 可直接匯入而不會與 `api_v2.py` 形成循環依賴。`api_v2.py` 與 [main.py](agent/main.py#L797) 改為從 `models.py` 匯入，行為不變。
- **Fallback 行為**：當 `prz_config.json` 缺失、無法解析、或計算結果不可用時，保留原本 fork SL1 估值作為退路，確保不會回傳空值或使流程失敗。

## Capabilities

### New Capabilities
- `print-time-sync`：定義 Web API 回傳的 `estimated_print_time` SHALL 反映 PRZ 物理公式（`_compute_print_time`）的計算結果，作為單一真值來源；涵蓋 config 持久化來源、切片完成後複寫 status.json 的時機，以及 config 缺失 / 計算失敗時退回 fork 估值的 fallback 邏輯。

### Modified Capabilities
<!-- 無：_compute_print_time 與 PRZ 寫入端（prz-motion-time）、PrzPrintTimingConfig 萃取語意（prz-timing-config）的需求皆不變，僅程式碼位置與呼叫端調整，屬實作細節。 -->

## Impact

- **程式碼**：
  - [agent/jobs.py](agent/jobs.py) — 切片解析後新增複寫 `estimated_print_time` 的流程；持久化 `prz_config.json`。
  - [agent/models.py](agent/models.py) — 接收自 `api_v2.py` 移入的 `_extract_prz_timing_config()`（純函式）。
  - [agent/api_v2.py](agent/api_v2.py#L1402) 與 [agent/main.py](agent/main.py#L797) — 改為從 `models.py` 匯入 `_extract_prz_timing_config`。
  - [agent/prz_encoder.py](agent/prz_encoder.py#L381) — `_compute_print_time()` 被 `jobs.py` 重用（既有公式不動）。
- **API**：對外回傳結構不變（`estimatedPrintTime` 欄位保留），僅數值來源由 fork 估值改為物理公式值；對前端而言為非破壞性變更。
- **檔案 / 持久化**：每個 job 目錄新增 `jobs/{id}/prz_config.json`。
- **測試**：新增 `agent/tests/test_jobs_sync.py`，不使用 mock，針對純 helper function 驗證時間同步與 fallback 邏輯；既有 `_extract_prz_timing_config` 相關測試之匯入路徑需配合更新。
