## 1. 新增 `PrzPrintTimingConfig` Pydantic Model（`agent/models.py`）

- [x] 1.1 在 `agent/models.py` 中引入必要 import：`Optional`、`field_validator`、`model_validator`（若尚未引入）
- [x] 1.2 定義 `PrzPrintTimingConfig` class，包含 8 個欄位：`exposure_delay_mode`（預設 `1`）、`light_off_delay`（預設 `1.0`）、`rest_before_lift`（預設 `0.0`）、`rest_after_lift`（預設 `0.0`）、`rest_after_retract`（預設 `1.0`）、`bottom_rest_before_lift`（`Optional[float] = None`）、`bottom_rest_after_lift`（`Optional[float] = None`）、`bottom_rest_after_retract`（`Optional[float] = None`）
- [x] 1.3 實作 `validate_delay_mode` field_validator：驗證 `exposure_delay_mode` 必須為 `0` 或 `1`，否則拋出 `ValueError`
- [x] 1.4 實作 `validate_light_off_delay` field_validator：驗證 `light_off_delay` 在 `0.0–120.0` 範圍內
- [x] 1.5 實作 `validate_rest` field_validator（覆蓋 `rest_before_lift`、`rest_after_lift`、`rest_after_retract`）：驗證每個值在 `0.0–60.0` 範圍內
- [x] 1.6 實作 `validate_bottom_rest` field_validator（`mode='before'`，覆蓋三個 `bottom_rest_*` 欄位）：若值非 `None` 則驗證在 `0.0–60.0` 範圍內
- [x] 1.7 實作 `apply_bottom_fallbacks` model_validator（`mode='after'`）：將三個 `bottom_rest_*` 為 `None` 的欄位自動填入對應一般層值

---

## 2. 新增 DS-Online Key 映射與 Extractor 函數（`agent/api_v2.py`）

- [x] 2.1 在 `agent/api_v2.py` 頂部引入 `PrzPrintTimingConfig`（從 `agent/models` import）
- [x] 2.2 定義模組層級常數 `_DS_TO_PRZ_TIMING: Dict[str, str]`，包含 8 組 DS-Online Title Case key → snake_case 欄位名稱的對應（`"Exposure Delay Mode"` → `"exposure_delay_mode"` 等，詳見 design.md D4 表格）
- [x] 2.3 實作 `_extract_prz_timing_config(config: Dict[str, Any]) -> PrzPrintTimingConfig` 函數：使用 `config.get("Print", config)` 取得 `print_config`，遍歷 `_DS_TO_PRZ_TIMING`，僅將前端有傳入的 key 加入 `timing_dict`，最後以 `PrzPrintTimingConfig(**timing_dict)` 回傳（未傳入的欄位使用 Pydantic 預設值）

---

## 3. 重構 `prz_encoder.py`：新增內部工具函數

- [x] 3.1 在 `agent/prz_encoder.py` 頂部引入 `PrzPrintTimingConfig`（從 `agent/models` import）
- [x] 3.2 實作 `_resolve_timing_values(timing: PrzPrintTimingConfig, is_bottom: bool) -> tuple[float, float, float, float]` 函數，回傳 `(light_off_time, before_lift_time, after_lift_time, after_retract_time)`：
  - `delay_mode == 0`（lightOff）：回傳 `(timing.light_off_delay, 0.0, 0.0, 0.0)`
  - `delay_mode == 1`（waitTime）且 `is_bottom=True`：回傳 `(0.0, timing.bottom_rest_before_lift, timing.bottom_rest_after_lift, timing.bottom_rest_after_retract)`
  - `delay_mode == 1`（waitTime）且 `is_bottom=False`：回傳 `(0.0, timing.rest_before_lift, timing.rest_after_lift, timing.rest_after_retract)`

---

## 4. 重構 `_write_header()`（`agent/prz_encoder.py`）

- [x] 4.1 修改 `_write_header()` 函數簽名，加入 `timing: PrzPrintTimingConfig` 參數
- [x] 4.2 移除 `delay_mode` hardcode（`buf.write(struct.pack("B", 1))`），改為 `buf.write(struct.pack("B", timing.exposure_delay_mode))`
- [x] 4.3 呼叫 `_resolve_timing_values(timing, is_bottom=True)` 取得 `bottom` tuple，呼叫 `_resolve_timing_values(timing, is_bottom=False)` 取得 `normal` tuple
- [x] 4.4 將 header 中的 `light_off_time`（1 個）寫入 `bottom[0]`（lightOff 與 waitTime 下結果等效，取 bottom 結果即可）
- [x] 4.5 將 `bottom_before_lift_time`、`bottom_after_lift_time`、`bottom_after_retract_time` 分別寫入 `bottom[1]`、`bottom[2]`、`bottom[3]`，取代原本的 hardcode `0.0` 與共用 `rest_time`
- [x] 4.6 將 `before_lift_time`、`after_lift_time`、`after_retract_time` 分別寫入 `normal[1]`、`normal[2]`、`normal[3]`，取代原本的 hardcode `0.0` 與共用 `rest_time`
- [x] 4.7 移除 `_get_float(config, "Print.Light-off Delay", ...)` 與 `_get_float(config, "Print.Rest Time After Retract", ...)` 在 header 段的呼叫（計時參數已全數由 `timing` 物件提供）

---

## 5. 重構 `_write_layer_definition()`（`agent/prz_encoder.py`）

- [x] 5.1 修改 `_write_layer_definition()` 函數簽名，加入 `timing: PrzPrintTimingConfig` 與 `is_bottom: bool` 參數（若原本已有 `is_bottom` 相關邏輯則沿用，否則從呼叫端傳入）
- [x] 5.2 在函數內呼叫 `vals = _resolve_timing_values(timing, is_bottom=is_bottom)` 取得當前層的計時四元組
- [x] 5.3 將 per-layer 的 `light_off_time`、`before_lift_time`、`after_lift_time`、`after_retract_time` 分別寫入 `vals[0]`–`vals[3]`，取代原本對 `_get_float(config, "Print.Light-off Delay", ...)` 和 hardcode `0.0` 的使用

---

## 6. API 路由層串接（`agent/api_v2.py`）

- [x] 6.1 找到呼叫 PRZ encoder（`_write_header()` 或 `encode_prz()`）的路由函數，確認其接收到的 `config` dict 格式
- [x] 6.2 在路由函數中，於呼叫 encoder 前插入：`timing = _extract_prz_timing_config(config)`
- [x] 6.3 將 `timing` 作為參數傳入 `_write_header()` 與 `_write_layer_definition()`（或傳入 encoder 的頂層入口函數，由其內部向下傳遞）
- [x] 6.4 確認現有 Pydantic validation 錯誤（`422 Unprocessable Entity`）能正常從 `PrzPrintTimingConfig` 的 validator 拋出並被 FastAPI 捕捉回傳

---

## 7. 測試

- [x] 7.1 單元測試：`PrzPrintTimingConfig` 所有欄位的合法值建立成功（含僅傳部分欄位、完全使用預設值）
- [x] 7.2 單元測試：`exposure_delay_mode=2` 應拋出 validation error
- [x] 7.3 單元測試：`light_off_delay=150.0` 應拋出 validation error（超過 120s 上限）
- [x] 7.4 單元測試：任一 rest 參數值 `80.0` 應拋出 validation error（超過 60s 上限）
- [x] 7.5 單元測試：底層 fallback 邏輯 ── 僅傳 `rest_after_retract=2.0`，驗證 `bottom_rest_after_retract` 自動等於 `2.0`
- [x] 7.6 單元測試：`_resolve_timing_values()` 在 `delay_mode=0` 時，所有 rest 值強制為 `0.0`；`light_off_time` 為傳入值
- [x] 7.7 單元測試：`_resolve_timing_values()` 在 `delay_mode=1` 時，`light_off_time` 強制為 `0.0`；bottom 與 normal 各取各自欄位
- [x] 7.8 整合測試：發送含完整計時參數的切片請求，驗證 `.prz` binary 中的對應 offset 值正確寫入
- [x] 7.9 整合測試：發送不含任何計時參數的切片請求，驗證 `.prz` 以預設計時值（`delay_mode=1`、`light_off=0.0`、`after_retract=1.0`）產生，且切片流程無錯誤
