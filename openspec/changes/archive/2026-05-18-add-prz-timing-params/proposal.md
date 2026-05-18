## Why

前端需要將列印計時參數（曝光延遲模式、抬升前後等待時間、回縮後等待時間、關燈延遲）寫入 `.prz` 檔案，但後端 `prz_encoder.py` 目前將 `delay_mode` 硬編碼為 `1`、多個 rest 時間硬編碼為 `0.0`，且 `Pydantic SLAConfig` 完全缺少這些欄位，導致前端無法透過 API 控制任何計時行為。

## What Changes

- 新增 `PrzPrintTimingConfig` Pydantic model，涵蓋 8 個計時參數，含型別驗證與邊界值校驗（`lightOffDelay` 0–120s，其餘 rest 參數 0–60s），以及底層參數未傳入時自動 fallback 至一般層值的邏輯。
- 新增 `_extract_prz_timing_config()` 函數（`api_v2.py`），從 DS-Online 格式的 `"Print"` section 提取計時參數，對應關係獨立維護，不修改現有 `_convert_v2_config_to_sla()` 與 `SLAConfig`。
- 重構 `prz_encoder.py` 的 `_write_header()` 與 `_write_layer_definition()`：解除所有計時參數的 hardcode，改從 `PrzPrintTimingConfig` 讀取，並實作 `delay_mode` 互斥邏輯（`0=lightOff` 時強制將所有 rest 時間寫 `0.0`；`1=waitTime` 時強制將 `lightOffDelay` 寫 `0.0`）。
- 底層（bottom layers）與一般層的 `restAfterRetract` 解耦，各自獨立；底層參數未傳入時由後端自動複製一般層值。
- **`SLAConfig` 不做任何改動**，既有切片流程零風險。

## Capabilities

### New Capabilities

- `prz-timing-config`：PRZ 列印計時參數的完整規格，涵蓋 API 接收格式（DS-Online key 映射）、Pydantic model 欄位定義、`delay_mode` 邏輯分支、底層 fallback 規則，以及邊界值驗證策略。

### Modified Capabilities

（無。PRZ encoder 的重構屬於實作細節，不涉及現有 `prz-parser` 的規格層行為變更。）

## Impact

- **`agent/models.py`**：新增 `PrzPrintTimingConfig` model
- **`agent/api_v2.py`**：新增 `_extract_prz_timing_config()` 函數；在呼叫 encoder 的路徑中傳入 `PrzPrintTimingConfig` 實例
- **`agent/prz_encoder.py`**：`_write_header()` 與 `_write_layer_definition()` 簽名加入 `timing: PrzPrintTimingConfig` 參數，移除所有計時參數的 hardcode，新增 `_resolve_timing_values()` 內部函數處理 delay_mode 邏輯
- **前端 API 合約**：前端在 `"Print"` section 加入新的 DS-Online key（`"Exposure Delay Mode"`、`"Light-off Delay"`、`"Rest Before Lift"` 等）；不傳入時後端使用預設值，**向後相容**
- **未來擴展**：架構保留反向解析（PRZ → API 回傳計時參數）的擴展空間，待前端 PRZ 讀取功能完成後再實作
