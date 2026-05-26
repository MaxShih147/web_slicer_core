## Why

實機驗證發現 10×10×10mm cube 在 layer_height=0.05mm 切片時，PRZ 輸出存在 4 個彼此關聯的正確性問題：

| # | 症狀 | 根因（已 grill-me 鎖定） |
|---|---|---|
| 1 | PRZ `volume` 欄位以 mL 寫入（前端 / 韌體期望 mm³） | [agent/prz_encoder.py:490](agent/prz_encoder.py#L490) 直接複用 caller 傳入的 `resin_volume_ml` 寫入 PRZ |
| 2 | 切片少 5 層（實得 195 frame，物理高度 9.75mm） | PrusaSlicer fork SLA 預設 `initial_layer_height = 0.30mm`（[PrintConfig.cpp:4502](third_party/prusaslicer_fork/src/libslic3r/PrintConfig.cpp#L4502)），首 frame 厚度 = 0.30mm。PRZ writer 壓平等厚後實際物理高度短缺 |
| 3 | `print_time` 沿用 fork 的 PrusaSlicer 公式，不適用 Phrozen 機種運動模型 | [prz_encoder.py:486-487](agent/prz_encoder.py#L486-L487) 把 fork 的 `estimated_print_time` 直接寫入；fork 公式為 Prusa SL1 motion model，與 Phrozen 兩段 lift/retract + 多段 rest 結構不對應 |
| 4 | `Retract Distance` 與 `Bottom Retract Distance` 永遠是公式算出，無法外部 override | [prz_encoder.py:456-457](agent/prz_encoder.py#L456-L457) 永遠執行 `max(0, lift + lift2 - drop2)`；config dict 中沒有 `Retract Distance` 對應 key 的讀取入口 |

這 4 項全部都是 **Python 端 `agent/` 的工作**，fork（`third_party/prusaslicer_fork`）完全不需動。

## What Changes

### `prz-parser` 既有 capability 規格修改

- PRZ `volume` 欄位語意從「mL（毫升）」變更為「mm³（立方公釐）」。`weight`、`price` 兩個複用欄位的數值同步 ×1000（仍鏡像 volume，無下游當「公克」或「金額」計算的依賴）。
- PRZ `print_time` 欄位的計算來源從「fork 的 `estimated_print_time`」變更為「encoder 內部用 PRZ-aware 物理公式從每層 motion / exposure / rest 參數推導」。
- PRZ `Retract Distance` / `Bottom Retract Distance` / `Retract Second Distance` / `Bottom Retract Second Distance` 4 欄位的計算規則從「永遠用 `max(0, lift + lift2 - drop2)`」變更為「4-case override 邏輯」（詳見 `prz-motion-time` 新 capability）。

### `sla-slice-config` 新 capability

- 引入「SLA 切片 config 必須對齊均一層厚」的契約：`SLAConfig` 新增 `initial_layer_height` 欄位，並在 Pydantic `model_validator` 中保證未顯式設定時 fallback 到 `layer_height`。
- 透過 [agent/sla_operations.py:87](agent/sla_operations.py#L87) 的 `generate_config_ini()` 自動把 `initial_layer_height = layer_height` 寫入送給 PrusaSlicer fork 的 INI 檔，覆寫 fork 內部的 0.30mm 預設。
- 修正 10mm cube + 0.05mm layer_height = 200 frame 的契約（目前實得 195）。

### `prz-motion-time` 新 capability

- 定義 PRZ 每層 motion cycle 的物理推導公式：`T_layer = exposure + light_off + before_lift + (lift + lift2 段時間) + after_lift + (retract + retract2 段時間) + after_retract`。
- 定義 4-case Retract Distance override 邏輯（含新版 Case 4：dist 與 drop2 都未傳入時，強制 `retract = 0.0` 與 `drop2 = lift + lift2`）。
- 「未傳入」語意明確化為「falsy（None / 0 / 0.0 / ""）」。
- 開放後續加入加速度（acceleration）模型的擴展介面，Phase 1 以等速模型上線。

## Capabilities

### New Capabilities

- `sla-slice-config`：SLA 切片 config 模型契約，包含 `SLAConfig` 欄位定義與「均一層厚」不變量。
- `prz-motion-time`：PRZ 每層運動時間推導模型、Retract 4-case override 邏輯、`print_time` 物理公式。

### Modified Capabilities

- `prz-parser`：volume 單位（mL → mm³）、print_time 計算來源（fork 估值 → encoder 物理公式）、retract 4 欄位計算規則（固定公式 → 4-case override）。

## Impact

| 模組 | 修改類型 | 摘要 |
|---|---|---|
| `agent/models.py` | 新增欄位 + validator | `SLAConfig` 新增 `initial_layer_height: Optional[float] = None` 與對應 `model_validator(mode='after')` fallback；`PrzPrintTimingConfig` 不動 |
| `agent/sla_operations.py` | 不動程式碼 | `generate_config_ini()` 用 `model_dump()` 自動帶出新欄位 |
| `agent/prz_encoder.py` | 函式簽章 + 內部邏輯 | `encode_prz`、`encode_prz_streaming`、`_write_header` 參數 `resin_volume_ml` 改名 `resin_volume_mm3`；line 490, 494, 497 寫 mm³；line 486-487 改呼叫新的 `_compute_print_time()`；line 448-474 與 567-596 改用新的 `_resolve_retract_pair()` helper |
| `agent/jobs.py` / `main.py` / `api_v2.py` | caller 簽章對齊 | 4 個 call site 把 `resin_volume_ml=X` 改為 `resin_volume_mm3=X * 1000` |
| `agent/prz_decoder.py` | 不動 | 仍解析 volume / weight / price 為 float；單位語意改變但欄位定義不變，下游若依賴語意需自行 ÷ 1000 還原 mL |
| 前端 API 合約 | 新增 4 個選填 DS-Online key | `"Print.Retract Distance"`、`"Print.Bottom Retract Distance"`、`"Print.Lift Acceleration"`（保留）、`"Print.Retract Acceleration"`（保留）。未傳入時走預設值，向後相容 |

**爆炸半徑控制**：fork 不動、PRZ binary layout 不動、`PrzPrintTimingConfig` 不動、`prz_decoder.py` 不動。所有改動集中在 Python encoder 與 SLAConfig。
