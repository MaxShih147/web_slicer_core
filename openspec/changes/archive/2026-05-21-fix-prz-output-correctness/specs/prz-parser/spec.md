## MODIFIED Requirements

### Requirement: PRZ 體積 / 重量 / 價格欄位單位

PRZ header 的 `volume`、`weight`、`price` 三個欄位 SHALL 以**立方公釐（mm³）**為單位寫入與解析。

三個欄位 SHALL 保持相同數值（鏡像 Mechado C++ 原作行為：encoder 將 volume 同時寫入 weight 與 price 欄位）。

`prz_decoder.py` 的 `PrzHeader.volume`、`PrzHeader.weight`、`PrzHeader.price` 欄位語意 SHALL 為 mm³。下游若需 mL，可自行 ÷ 1000 換算。

#### Scenario: 切片產出的 PRZ volume 為 mm³
- **WHEN** 編碼一個 1000 mm³ 樹脂消耗的物體（如 10×10×10mm 實心 cube）
- **THEN** PRZ header 的 `volume` 欄位 SHALL ≈ 1000.0（容許 ±10 為樹脂支撐 / 切片精度誤差）

#### Scenario: weight 與 price 同步為 mm³
- **WHEN** 解碼任一 PRZ 檔案
- **THEN** `PrzHeader.weight == PrzHeader.volume`
- **AND** `PrzHeader.price == PrzHeader.volume`
- **AND** 三者單位均為 mm³

#### Scenario: 對比 change 前版本數值放大 1000×
- **WHEN** 同一份切片資料分別用 change 前 / change 後版本編碼
- **THEN** change 後的 `volume` / `weight` / `price` 三欄數值 SHALL 為 change 前的 ~1000 倍

---

### Requirement: PRZ print_time 欄位由 encoder 內部物理推導

PRZ header 的 `print_time` 欄位（4 byte unsigned int 秒）SHALL 由 [`prz_encoder.py`](agent/prz_encoder.py) 內部呼叫 `_compute_print_time(config, total_layers, timing)` 計算。**SHALL NOT** 直接使用 fork（PrusaSlicer）的 `estimated_print_time` 估值。

計算公式定義詳見 `prz-motion-time` capability。

#### Scenario: print_time 不再來自 fork 估值
- **WHEN** 編碼任一 PRZ 檔案
- **THEN** PRZ `print_time` SHALL 等於 `_compute_print_time(config, total_layers, timing)` 的回傳值（int 截斷）
- **AND** SHALL NOT 等於 caller 傳入的 `estimated_print_time` 參數值

#### Scenario: 不同 motion 參數產生不同 print_time
- **WHEN** 同一物體分別用兩組不同 lift_speed 編碼（例如 50 vs 100）
- **THEN** 兩份 PRZ 的 `print_time` 欄位數值 SHALL 不同（反映 motion 公式的速度依賴）

---

### Requirement: PRZ Retract Distance 4 欄位採 4-case override

PRZ header 與 per-layer 的 `Retract Distance`、`Bottom Retract Distance`、`Retract Second Distance`、`Bottom Retract Second Distance` 4 欄位 SHALL 依「4-case override 邏輯」計算，詳見 `prz-motion-time` capability 的 Requirement。

舊行為（永遠執行 `max(0, lift + lift2 - drop2)`）SHALL 被取代。

#### Scenario: 既有未傳 retract 參數的 config 行為改變（breaking change）
- **WHEN** 既有 config 未傳 `"Print.Retract Distance"` 與 `"Print.Retract Second Distance"`（change 前走「永遠公式」路徑）
- **THEN** change 後 PRZ 寫入 `retract = 0.0`、`drop2 = lift + lift2`（Case 4 新版行為）
- **AND** 此行為改變 SHALL 在 release notes 中明確標示

---

## ADDED Requirements

### Requirement: encoder 接受 `Print.Retract Distance` 與 `Print.Bottom Retract Distance` config key

[`prz_encoder.py`](agent/prz_encoder.py) SHALL 從 config dict 讀取以下兩個新 key（既有 `_get_float()` 機制即可）：
- `"Print.Retract Distance"`
- `"Print.Bottom Retract Distance"`

未傳入時（falsy）走 4-case override 的 Case 1 或 Case 4 路徑。

#### Scenario: 前端傳入 Retract Distance
- **WHEN** API 請求的 `config` 含 `"Print": {"Retract Distance": 2.0}`
- **THEN** PRZ header 的 normal retract = 2.0
- **AND** PRZ header 的 normal drop2 = `max(0, lift + lift2 - 2.0)`（Case 2 路徑）

#### Scenario: 前端傳入 Bottom Retract Distance
- **WHEN** API 請求的 `config` 含 `"Print": {"Bottom Retract Distance": 1.5}`
- **THEN** PRZ header 的 bottom retract = 1.5
- **AND** PRZ header 的 bottom drop2 = `max(0, bottom_lift + bottom_lift2 - 1.5)`

#### Scenario: 既有 API 請求向後相容
- **WHEN** API 請求不含這兩個新 key（change 前的請求格式）
- **THEN** SHALL NOT 回傳 422 錯誤
- **AND** 走 4-case override 的 Case 1（若 drop2 仍有傳）或 Case 4（drop2 也未傳）路徑
