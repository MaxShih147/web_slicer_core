# prz-motion-time Specification

## Purpose
TBD - created by syncing change fix-prz-output-correctness. Update Purpose after archive.

## Requirements

### Requirement: PRZ Retract 4-case Override 邏輯

`prz_encoder.py` SHALL 在寫入 `Retract Distance` 與 `Retract Second Distance`（含 `Bottom` 變體）時，依下表 4 種情境分別處理：

| Case | dist 傳入？ | drop2 傳入？ | 最終 dist | 最終 drop2 |
|---|---|---|---|---|
| 1 | ✗（falsy） | ✓（truthy） | `max(0.0, lift + lift2 - drop2)` | drop2 |
| 2 | ✓（truthy） | ✗（falsy） | dist | `max(0.0, lift + lift2 - dist)` |
| 3 | ✓（truthy） | ✓（truthy） | dist | `max(0.0, lift + lift2 - dist)`（覆寫使用者傳入的 drop2） |
| 4 | ✗（falsy） | ✗（falsy） | `0.0` | `lift + lift2` |

「傳入」語意定義為：值為 truthy（非 None、非 0、非 0.0、非空字串）。

bottom 與 normal SHALL 各自獨立套用此邏輯（共 4 種變體：bottom_retract / bottom_drop2、normal_retract / normal_drop2）。

#### Scenario: Case 1 — 僅 drop2 傳入（沿用既有行為）
- **WHEN** config 含 `"Print.Retract Second Distance": 3.0`，未含 `"Print.Retract Distance"`
- **AND** `Lifting Distance + Lifting Second Distance = 8.0`
- **THEN** PRZ header 與 per-layer 的 normal retract = 5.0、drop2 = 3.0

#### Scenario: Case 2 — 僅 dist 傳入
- **WHEN** config 含 `"Print.Retract Distance": 2.0`，未含 `"Print.Retract Second Distance"`
- **AND** `Lifting Distance + Lifting Second Distance = 8.0`
- **THEN** PRZ header 與 per-layer 的 normal retract = 2.0、drop2 = 6.0

#### Scenario: Case 3 — dist 與 drop2 都傳入（強制重算 drop2）
- **WHEN** config 含 `"Print.Retract Distance": 2.0` 與 `"Print.Retract Second Distance": 99.0`（被覆寫）
- **AND** `Lifting Distance + Lifting Second Distance = 8.0`
- **THEN** PRZ header 與 per-layer 的 normal retract = 2.0、drop2 = 6.0（drop2 = 99.0 被覆寫為公式值）

#### Scenario: Case 4 — 兩者都未傳入（新版行為）
- **WHEN** config 中 `"Print.Retract Distance"` 與 `"Print.Retract Second Distance"` 都不存在或為 falsy
- **AND** `Lifting Distance + Lifting Second Distance = 8.0`
- **THEN** PRZ header 與 per-layer 的 normal retract = `0.0`，drop2 = `8.0`

#### Scenario: bottom 與 normal 獨立
- **WHEN** config 含 `"Print.Bottom Retract Distance": 1.0`（Case 2 for bottom）、`"Print.Retract Second Distance": 4.0`（Case 1 for normal）
- **THEN** bottom retract = 1.0、bottom drop2 = `max(0, lift_b + lift2_b - 1.0)`
- **AND** normal retract = `max(0, lift_n + lift2_n - 4.0)`、normal drop2 = 4.0
- **AND** 兩組互不干擾

#### Scenario: Case 1/2/3 underflow clamp
- **WHEN** Case 2 中 `dist = 99.0`，但 `lift + lift2 = 8.0`
- **THEN** drop2 = `max(0.0, 8.0 - 99.0) = 0.0`（clamp 而非負值）

#### Scenario: Case 4 邊界 — lift 與 lift2 都為 0
- **WHEN** Case 4 觸發，且 `lift = 0, lift2 = 0`
- **THEN** retract = 0.0、drop2 = 0.0（不出錯）

---

### Requirement: PRZ Print Time 從 PRZ 參數物理推導

`prz_encoder.py` SHALL 在寫入 PRZ header 的 `print_time` 欄位前，內部呼叫 `_compute_print_time(config, total_layers, timing)` 計算列印時間。**SHALL NOT** 直接使用 caller 傳入的 `estimated_print_time` 或 fork 估值。

每層時間公式：

```
T_layer = exposure(layer_idx)
        + light_off_time
        + before_lift_time
        + motion_time(LiftDist,        LiftSpeed)
        + motion_time(LiftSecondDist,  LiftSecondSpeed)
        + after_lift_time
        + motion_time(RetractDist,     RetractSpeed)        # 套 4-case override
        + motion_time(RetractSecondDist, RetractSecondSpeed) # 套 4-case override
        + after_retract_time
```

其中 `motion_time(d, v) = d / v if d > 0 and v > 0 else 0.0`。

`exposure(layer_idx)` 依 [_write_layer_definition() @ line 543-555](agent/prz_encoder.py#L543-L555) 的 ramp 邏輯計算（bottom / transition 線性內插 / normal 三段）。

時間相關參數（`light_off_time`、`before_lift_time`、`after_lift_time`、`after_retract_time`）依 `_resolve_timing_values(timing, is_bottom)` 取得。

Retract 兩值（`RetractDist`、`RetractSecondDist`）SHALL 透過上述 4-case override 邏輯取得。

總列印時間 = Σ T_layer for layer_idx in 0..total_layers−1。

#### Scenario: 基本 cube 計算
- **WHEN** 切 10×10×10mm cube，`layer_height = 0.05`，`bottom_layer_count = 5`，`transition_layer_count = 5`，使用預設 exposure / lift / retract / timing 值
- **THEN** PRZ `print_time` SHALL 等於 `_compute_print_time(...)` 回傳值
- **AND** 該值 SHALL NOT 等於 fork 的 `estimated_print_time`（兩者公式不同）

#### Scenario: lift2 = 0 不應 NaN
- **WHEN** config 含 `"Print.Lifting Second Distance": 0.0`（單段 lift）
- **THEN** `motion_time(0, lift2_speed) = 0.0`
- **AND** `T_layer` 內 lift2 對應段為 0，不出現 NaN 或 Inf

#### Scenario: speed = 0 不應除以零
- **WHEN** config 含 `"Print.Lifting Speed": 0.0`
- **THEN** `motion_time(lift, 0) = 0.0`（保護性，避免 ZeroDivisionError）

#### Scenario: bottom 與 normal layer 分別計算
- **WHEN** 一個切片有 5 層 bottom + 5 層 transition + 190 層 normal
- **THEN** 計算時前 5 層使用 `"Print.Bottom Exposure Time"` 與 bottom motion 參數
- **AND** 第 6–10 層 exposure 使用線性內插（[_write_layer_definition() @ line 553](agent/prz_encoder.py#L553) 公式），motion 使用 normal 參數
- **AND** 第 11–200 層使用 `"Print.Exposure Time"` 與 normal motion 參數

#### Scenario: 計算結果與手算對拍（速度 mm/min，需 ÷ 60）
- **WHEN** 給定一組已知 config：1 normal layer，exposure=2.5s，所有 rest 與 light_off=0，`Lifting Distance = 5 mm`，`Lifting Speed = 60 mm/min`，`Retract Distance = 5 mm`，`Normal Retract Speed = 120 mm/min`，其餘距離 / 速度為 0
- **THEN** `_compute_print_time(config, 1, timing)` 回傳值 SHALL 等於 `2.5 + 5/(60/60) + 5/(120/60) = 2.5 + 5/1 + 5/2 = 10.0` 秒
- **AND** 結果 SHALL 不依賴 fork 估值

---

### Requirement: print_time 計算 SHALL 重用 retract 4-case override

`_compute_print_time()` 內部 SHALL 透過 `_resolve_retract_pair()` 取得 retract 與 drop2 值。**SHALL NOT** 用未經 override 的 raw config 值。

#### Scenario: print_time 反映 Case 4 行為（速度 mm/min，需 ÷ 60）
- **WHEN** config 未傳 retract dist 與 drop2（Case 4）
- **AND** `Lifting Distance = 8.0`、`Lifting Second Distance = 0.0`、`Normal Retract Speed = 100 mm/min`（= 1.667 mm/s）
- **THEN** `_compute_print_time()` 中 retract 段時間 = `8.0 / (100/60) = 4.8` 秒（drop2 = 8.0 對應 second-stage 全段）
- **AND** PRZ header 寫入的 retract = 0.0、drop2 = 8.0
- **AND** 兩處（time 計算與 binary 寫入）使用相同的 4-case 結果

---

### Requirement: 速度單位強制 mm/min → mm/s 轉換

`_compute_print_time()` 內所有從 config dict 讀取的速度參數（`Bottom Lifting Speed`、`Lifting Speed`、`Bottom Lifting Second Speed`、`Lifting Second Speed`、`Bottom Retract Speed`、`Normal Retract Speed`、`Bottom Retract Second Speed`、`Normal Retract Second Speed`）原始語意均為 **mm/min**（與 UI / PRZ binary 寫入端對齊）。代入物理公式 `t = d / v` 前 SHALL 強制 **÷ 60 轉換為 mm/s**。

此轉換 SHALL **僅**作用於 `_compute_print_time()` 內部；PRZ binary 寫入路徑（`_write_header()` 與 `_write_layer_definition()` 中對應 speed 欄位的寫入點）SHALL 仍寫入 raw mm/min 值，**不改變既有韌體期望**。

#### Scenario: 60 mm/min = 1 mm/s
- **WHEN** `Lifting Speed = 60` mm/min，`Lifting Distance = 1` mm，其餘速度 / 距離 / 時間段為 0
- **THEN** `_compute_print_time()` 中對應 lift 段時間 = `1 / (60/60) = 1.0` 秒
- **AND** 若實作漏掉 ÷ 60，會錯算為 `1 / 60 = 0.0167` 秒（60× 低估），測試 SHALL fail

#### Scenario: 120 mm/min = 2 mm/s
- **WHEN** `Lifting Speed = 120` mm/min，`Lifting Distance = 1` mm，其餘速度 / 距離 / 時間段為 0
- **THEN** `_compute_print_time()` 中對應 lift 段時間 = `1 / (120/60) = 0.5` 秒
- **AND** 若實作漏掉 ÷ 60，會錯算為 `1 / 120 = 0.0083` 秒（60× 低估），測試 SHALL fail

#### Scenario: 0 mm/min 邊界 — 不除以 0
- **WHEN** `Lifting Speed = 0`
- **THEN** 對應 lift 段時間 = `0.0`（保護性，不出現 ZeroDivisionError）

#### Scenario: PRZ binary 速度欄位語意保持 mm/min
- **WHEN** `Lifting Speed = 60`，encoder 寫出 PRZ
- **THEN** PRZ header 對應 speed 欄位（4 byte float BE）SHALL 寫入 `60.0`（raw mm/min）
- **AND** PRZ per-layer 區塊對應 speed 欄位 SHALL 寫入 `60.0`
- **AND** 僅 `_compute_print_time()` 內部使用 `60 / 60 = 1.0` mm/s 進行物理推導

---

### Requirement: print_time 整數截斷

PRZ header 的 `print_time` 欄位為 4 byte unsigned int（big-endian）；`_compute_print_time()` 回傳的浮點數秒值 SHALL 在寫入前以 `int()` 截斷。

#### Scenario: 浮點數截斷為整數秒
- **WHEN** `_compute_print_time()` 回傳 `123.7`
- **THEN** PRZ header 寫入 `123`（int 截斷，向下取整）
