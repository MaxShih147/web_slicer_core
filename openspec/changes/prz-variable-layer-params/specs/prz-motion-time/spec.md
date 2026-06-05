## MODIFIED Requirements

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

**逐層參數來源依任務型態決定：**

- **等高任務（單一全域層厚）**：`exposure(layer_idx)` 依 `_write_layer_definition()` 的 ramp 邏輯計算（bottom / transition 線性內插 / normal 三段）；時間與 motion 參數依 `_resolve_timing_values(timing, is_bottom)` 取得（行為與本變更前一致）。
- **變動層厚任務（區間數 > 1）**：每層的曝光、光熄、抬升、回抽與時間參數 SHALL 依「以該層 `z_end` 為錨點、µm 量化、`[low, high)` 半開」選定的高度區間參數組合取得（與 `prz-variable-layer-encode` 同一判定規則）。bottom 層判定（`layer_idx < Bottom Layer Count`）SHALL 維持，且其優先權高於區間參數（bottom 段仍套 bottom 參數）。

時間相關參數（`light_off_time`、`before_lift_time`、`after_lift_time`、`after_retract_time`）在等高任務依 `_resolve_timing_values(timing, is_bottom)` 取得；在變動層厚任務依所屬區間取得。

Retract 兩值（`RetractDist`、`RetractSecondDist`）SHALL 透過 4-case override 邏輯取得。

總列印時間 = Σ T_layer for layer_idx in 0..total_layers−1。對變動層厚任務，`total_layers` SHALL 等於權威表層數（與 `.sl1` PNG 張數一致），時間累加 SHALL 逐層套用各自區間參數，而非以單一全域參數乘層數。

#### Scenario: 基本 cube 計算
- **WHEN** 切 10×10×10mm cube，`layer_height = 0.05`，`bottom_layer_count = 5`，`transition_layer_count = 5`，使用預設 exposure / lift / retract / timing 值（等高任務）
- **THEN** PRZ `print_time` SHALL 等於 `_compute_print_time(...)` 回傳值
- **AND** 該值 SHALL NOT 等於 fork 的 `estimated_print_time`（兩者公式不同）

#### Scenario: lift2 = 0 不應 NaN
- **WHEN** config 含 `"Print.Lifting Second Distance": 0.0`（單段 lift）
- **THEN** `motion_time(0, lift2_speed) = 0.0`
- **AND** `T_layer` 內 lift2 對應段為 0，不出現 NaN 或 Inf

#### Scenario: speed = 0 不應除以零
- **WHEN** config 含 `"Print.Lifting Speed": 0.0`
- **THEN** `motion_time(lift, 0) = 0.0`（保護性，避免 ZeroDivisionError）

#### Scenario: bottom 與 normal layer 分別計算（等高任務）
- **WHEN** 一個切片有 5 層 bottom + 5 層 transition + 190 層 normal
- **THEN** 計算時前 5 層使用 `"Print.Bottom Exposure Time"` 與 bottom motion 參數
- **AND** 第 6–10 層 exposure 使用線性內插公式，motion 使用 normal 參數
- **AND** 第 11–200 層使用 `"Print.Exposure Time"` 與 normal motion 參數

#### Scenario: 變動層厚任務逐層套用區間參數
- **WHEN** 變動層厚任務，區間 `A = [0, 10mm) @ 曝光 2.5s`、`B = [10mm, 20mm) @ 曝光 3.0s`，且某層 `z_end_um == 10000`
- **THEN** `_compute_print_time()` 對該層 SHALL 使用區間 `B` 的曝光與 motion 參數（`z_end` 錨點、`[low, high)` 半開）
- **AND** 總時間 SHALL 為各層依其所屬區間參數計算的 `T_layer` 之和
- **AND** SHALL NOT 以單一全域參數乘以總層數估算

#### Scenario: 變動層厚任務 bottom 層優先於區間
- **WHEN** 變動層厚任務，`Bottom Layer Count = 5`，前 5 層 `z_end` 落在區間 `A` 內
- **THEN** 前 5 層 SHALL 套用 bottom 參數（bottom 判定優先）
- **AND** 第 6 層起 SHALL 依其 `z_end` 所屬區間取參數

#### Scenario: 計算結果與手算對拍（速度 mm/min，需 ÷ 60）
- **WHEN** 給定一組已知 config：1 normal layer，exposure=2.5s，所有 rest 與 light_off=0，`Lifting Distance = 5 mm`，`Lifting Speed = 60 mm/min`，`Retract Distance = 5 mm`，`Normal Retract Speed = 120 mm/min`，其餘距離 / 速度為 0
- **THEN** `_compute_print_time(config, 1, timing)` 回傳值 SHALL 等於 `2.5 + 5/(60/60) + 5/(120/60) = 2.5 + 5/1 + 5/2 = 10.0` 秒
- **AND** 結果 SHALL 不依賴 fork 估值