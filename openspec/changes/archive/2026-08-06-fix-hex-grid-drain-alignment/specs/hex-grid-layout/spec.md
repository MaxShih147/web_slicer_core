## ADDED Requirements

### Requirement: HexGridLayout 持有 grid 幾何的單一定義

`HexGridLayout`（[agent/sla_operations.py](agent/sla_operations.py)）SHALL 持有以下欄位：`center_x`、`center_y`（grid XY 中心，mm）、`n_cols`、`n_rows`（grid 列數與行數）、`col_step`、`row_step`（cell 間距，mm）、`wall_thickness`（cell 壁面厚度，mm）。任何使用 `HexGridLayout` 的函式 SHALL 不得在函式內部另行重算上述欄位的等效值，而 SHALL 直接使用 layout 所提供的值。

#### Scenario: layout 欄位覆蓋函式內部計算
- **GIVEN** 一個 `HexGridLayout` 由 `compute_hex_grid_layout(radius=R, wall_thickness=T, grid_count=N, hollow_mesh=M)` 計算產生
- **WHEN** 該 layout 被傳入 `generate_hex_grid()` 或 `generate_drain_holes()`
- **THEN** 函式 SHALL 使用 `layout.center_x`、`layout.center_y`、`layout.n_cols`、`layout.n_rows`、`layout.col_step`、`layout.row_step` 建構 grid，而 SHALL NOT 以函式本身接收的 `radius`、`wall_thickness`、`grid_count` 重新推算上述值

---

### Requirement: compute_hex_grid_layout() 依 hollow_mesh.bounds 計算中心與尺寸

`compute_hex_grid_layout(radius, wall_thickness, grid_count, hollow_mesh=None)` SHALL 計算 hex grid 的中心座標與列數：
- 當 `hollow_mesh` 不為 `None` 時，`center_x` 與 `center_y` SHALL 等於 `hollow_mesh.bounds` 的 XY bounding box 中心；`n_cols` 與 `n_rows` SHALL 等於 `max(grid_count, ceil(hollow_span / col_step) + 3)`（加 3 列邊界裕量）。
- 當 `hollow_mesh` 為 `None` 時，`center_x = center_y = 0.0`，`n_cols = n_rows = grid_count`（向下相容）。

#### Scenario: hollow_mesh 存在 — 中心對齊 hollow
- **GIVEN** 一個 `hollow_mesh`，其 XY bounding box 為 `[bmin_x, bmax_x] × [bmin_y, bmax_y]`
- **WHEN** `compute_hex_grid_layout(radius, wall_thickness, grid_count, hollow_mesh=hollow_mesh)` 執行
- **THEN** `layout.center_x` SHALL 等於 `(bmin_x + bmax_x) / 2`
- **AND** `layout.center_y` SHALL 等於 `(bmin_y + bmax_y) / 2`

#### Scenario: hollow_mesh 存在且面積大 — n_cols 自動擴展
- **GIVEN** `hollow_mesh` 的 XY span 使 `ceil(span_x / col_step) + 3 > grid_count`
- **WHEN** `compute_hex_grid_layout(radius, wall_thickness, grid_count, hollow_mesh=hollow_mesh)` 執行
- **THEN** `layout.n_cols` SHALL 大於 `grid_count`
- **AND** `layout.n_rows` SHALL 大於 `grid_count`（若 Y span 亦超出）

#### Scenario: hollow_mesh 為 None — 退回原點中心與固定尺寸
- **GIVEN** `hollow_mesh=None`
- **WHEN** `compute_hex_grid_layout(radius, wall_thickness, grid_count)` 執行
- **THEN** `layout.center_x` SHALL 等於 `0.0`
- **AND** `layout.center_y` SHALL 等於 `0.0`
- **AND** `layout.n_cols` SHALL 等於 `grid_count`
- **AND** `layout.n_rows` SHALL 等於 `grid_count`

---

### Requirement: generate_hex_grid() 與 generate_drain_holes() 收到相同 layout 時使用一致的 grid 座標系

當 `generate_hex_grid()` 與 `generate_drain_holes()` 收到相同的 `HexGridLayout` 物件時，兩者 cell `(row, col)` 的 XY 中心座標 SHALL 完全一致。`generate_drain_holes()` 中的 `cell_center(row, col)` 計算結果 SHALL 等於 `generate_hex_grid()` 中對應 cell 的 `(cx, cy)`。

#### Scenario: 同一 layout 下兩函式 cell 座標一致
- **GIVEN** `layout = compute_hex_grid_layout(radius=R, wall_thickness=T, grid_count=N, hollow_mesh=M)`
- **AND** `hex_mesh = generate_hex_grid(..., layout=layout)`
- **AND** `drain_mesh = generate_drain_holes(..., layout=layout)`
- **WHEN** 比較兩函式對任意有效 `(row, col)` 的 cell 中心座標
- **THEN** `generate_drain_holes` 中 `cell_center(row, col)` 的 `(x, y)` SHALL 等於 `generate_hex_grid` 中對應 cell 的 `(cx, cy)`（誤差 < 1e-9 mm）

#### Scenario: drain_holes XY 邊界與 hex_grid 中心對齊
- **GIVEN** `hollow_mesh` 中心在非原點的任意位置 `(cx0, cy0)`
- **AND** 兩函式使用相同 layout
- **WHEN** 比較 `hex_mesh` 與 `drain_mesh` 的 XY 邊界中心
- **THEN** 兩者 XY 邊界中心差值 SHALL 小於 `col_step`（一個 cell 間距）

#### Scenario: drain_holes 遍歷與 hex_grid 相同的列數與行數
- **GIVEN** layout 的 `n_cols > grid_count`（hollow 面積觸發自動擴展）
- **AND** 兩函式使用相同 layout
- **WHEN** `generate_drain_holes()` 遍歷 cell pairs
- **THEN** 其 row 迴圈範圍 SHALL 為 `range(layout.n_rows)`
- **AND** col 迴圈範圍 SHALL 為 `range(layout.n_cols)`
- **AND** 鄰居邊界檢查 SHALL 使用 `layout.n_rows` 與 `layout.n_cols`，而非 `grid_count`

---

### Requirement: ortho pipeline 只計算一次 grid layout

`run_ortho_pipeline()` SHALL 在 Step 3（hollow 對齊）完成後、Step 4（hex grid 生成）開始前，以 `compute_hex_grid_layout(radius, wall_thickness, grid_count, hollow_mesh=hollow_mesh)` 計算一次 `grid_layout`。Step 4 的 `generate_hex_grid()` 與 Step 5 的 `generate_drain_holes()` SHALL 共用此同一個 `grid_layout` 物件（透過 `layout=grid_layout` 參數傳入）。

#### Scenario: pipeline 不重複計算 grid 幾何
- **GIVEN** `run_ortho_pipeline()` 執行到 Step 3 結束（hollow 已對齊至 input_mesh 中心）
- **WHEN** 進入 Step 4 與 Step 5
- **THEN** `generate_hex_grid()` 與 `generate_drain_holes()` SHALL 接收到同一個 `layout` 物件
- **AND** 兩者 SHALL NOT 各自獨立從 `hollow_mesh.bounds` 或參數重新推算 grid 中心與尺寸

---

### Requirement: 無 layout 時保持向下相容

當 `generate_hex_grid()` 或 `generate_drain_holes()` 在 `layout=None`（預設值）情況下被呼叫時，其行為 SHALL 與修改前完全一致。`generate_hex_grid()` SHALL 透過 `compute_hex_grid_layout(..., hollow_mesh=hollow_mesh)` 自行計算 layout；`generate_drain_holes()` SHALL 透過 `compute_hex_grid_layout(..., hollow_mesh=None)` 計算 layout（中心在原點，尺寸為 `grid_count × grid_count`）。

#### Scenario: 既有 API endpoint 呼叫不傳 layout — 行為不變
- **GIVEN** `api_v2.py` 的 `/generate-drain-holes` endpoint 以舊式呼叫（不含 `layout` 參數）呼叫 `generate_drain_holes(hex_cell_radius, wall_thickness, grid_count, drain_radius, bottom_z)`
- **WHEN** 函式執行
- **THEN** 函式 SHALL 以 `compute_hex_grid_layout(radius=hex_cell_radius, wall_thickness=wall_thickness, grid_count=grid_count)` 計算 layout
- **AND** 回傳的 drain hole 圓柱數量與位置 SHALL 與修改前相同
