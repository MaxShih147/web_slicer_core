## ADDED Requirements

### Requirement: SLA 切片 config 必須保證均一層厚

`SLAConfig` Pydantic model SHALL 提供 `initial_layer_height` 欄位。當該欄位未被顯式設定（值為 `None`）時，系統 SHALL 在 model validation 階段自動 fallback 為與 `layer_height` 相同的值。

#### Scenario: 使用者未顯式設定 initial_layer_height
- **WHEN** 使用者建構 `SLAConfig(layer_height=0.05)`，未提供 `initial_layer_height`
- **THEN** `SLAConfig.initial_layer_height` SHALL 等於 `0.05`
- **AND** `generate_config_ini()` 寫出的 INI 中 SHALL 含 `initial_layer_height = 0.05` 一行

#### Scenario: 使用者顯式設定 initial_layer_height
- **WHEN** 使用者建構 `SLAConfig(layer_height=0.05, initial_layer_height=0.30)`
- **THEN** `SLAConfig.initial_layer_height` SHALL 等於 `0.30`（使用者顯式 override 路徑保留）
- **AND** 切片後產生的 PRZ 首 frame 的 thickness SHALL 等於 0.30mm（非 0.05mm）

#### Scenario: 不同 layer_height 都正確 fallback
- **WHEN** 使用者建構 `SLAConfig(layer_height=0.10)` 或 `SLAConfig(layer_height=0.02)`，皆未提供 `initial_layer_height`
- **THEN** `SLAConfig.initial_layer_height` 分別 SHALL 等於 `0.10` 或 `0.02`

---

### Requirement: 切 10mm 立方體必須得到正確層數

當使用者建構 `SLAConfig(layer_height=L)` 並切片一個 10mm 高度的物體（無顯式設定 `initial_layer_height`、無 pad、無 supports）時，產出 PRZ 的 `total_layers` SHALL 等於 `round(10 / L)`，且最後一層的 `LayerPositionZ` SHALL 等於 `10.0`（容許浮點誤差 ≤ 1e-4）。

#### Scenario: 0.05mm 層高
- **WHEN** `layer_height = 0.05`，切 10×10×10mm cube
- **THEN** PRZ `total_layers == 200`
- **AND** PRZ 最後一層 `LayerPositionZ == 10.0`（容許 ±1e-4）
- **AND** 每一層的 `layer_height` 欄位 == 0.05（含第 1 層）

#### Scenario: 0.10mm 層高
- **WHEN** `layer_height = 0.10`，切 10×10×10mm cube
- **THEN** PRZ `total_layers == 100`
- **AND** PRZ 最後一層 `LayerPositionZ == 10.0`

#### Scenario: 0.02mm 層高
- **WHEN** `layer_height = 0.02`，切 10×10×10mm cube
- **THEN** PRZ `total_layers == 500`
- **AND** PRZ 最後一層 `LayerPositionZ == 10.0`

---

### Requirement: `generate_config_ini()` 不需特化處理 initial_layer_height

[`generate_config_ini()`](agent/sla_operations.py#L87) SHALL 持續使用 `SLAConfig.model_dump()` 一次寫出所有欄位，**不需**對 `initial_layer_height` 做特殊處理。該欄位的 fallback 邏輯 SHALL 完全封裝在 `SLAConfig` 的 `model_validator` 中。

#### Scenario: generate_config_ini 程式碼最小變動
- **WHEN** 本 change 完成
- **THEN** [`generate_config_ini()`](agent/sla_operations.py#L87) 的程式碼行 SHALL 與 change 前相同
- **AND** 輸出的 INI 內容 SHALL 自動新增 `initial_layer_height = X` 一行（X = layer_height 或 user 顯式值）

---

### Requirement: 既有 SLA 切片流程不受影響

新增 `initial_layer_height` 欄位 SHALL 與既有 `SLAConfig` 其他欄位（layer_height、exposure_time、support_*、hollowing_*、display_*）完全獨立；既有切片流程 SHALL 與 change 前行為一致（除「層數從 195 修正為 200」之外）。

#### Scenario: 既有切片 API 請求格式不變
- **WHEN** 前端使用 change 前的 API 請求格式（不含 `initial_layer_height`）發送切片請求
- **THEN** API SHALL 接受請求並照常處理，**不**回傳 422 或其他錯誤
- **AND** 切片結果 SHALL 為「均一層厚」（除層數從 195 → 200 之外，其餘行為與 change 前一致）

#### Scenario: 既有 SLAConfig 欄位行為不變
- **WHEN** 任一既有 `SLAConfig` 欄位（如 `exposure_time`、`bottom_layers`、`support_density`）被讀寫
- **THEN** 行為 SHALL 與 change 前完全一致
