## 1. 新增共用 grid 幾何結構

- [x] 1.1 在 [agent/sla_operations.py](agent/sla_operations.py)（`generate_drain_holes()` 定義前）新增 `HexGridLayout` class，持有欄位：`center_x`、`center_y`、`n_cols`、`n_rows`、`col_step`、`row_step`、`wall_thickness`
- [x] 1.2 新增 `compute_hex_grid_layout(radius, wall_thickness, grid_count, hollow_mesh=None) -> HexGridLayout`：將原 `generate_hex_grid()` 內的 grid 中心與尺寸計算邏輯移至此 helper；有 `hollow_mesh` 時依 bounds 計算中心與擴展尺寸，無 `hollow_mesh` 時退回 `(0, 0)` 與固定 `grid_count`

## 2. 修改 generate_drain_holes()

- [x] 2.1 在 [agent/sla_operations.py](agent/sla_operations.py) 的 `generate_drain_holes()` 簽名加入 `layout: "HexGridLayout" = None`
- [x] 2.2 函式開頭加入 `if layout is None: layout = compute_hex_grid_layout(radius=hex_cell_radius, wall_thickness=wall_thickness, grid_count=grid_count)`
- [x] 2.3 以 `layout.col_step`、`layout.row_step`、`layout.center_x`、`layout.center_y`、`(layout.n_cols - 1) / 2`、`(layout.n_rows - 1) / 2` 取代原本的局部計算值
- [x] 2.4 將 `cell_center()` 內的座標公式加入 `+ center_x` / `+ center_y` 平移項
- [x] 2.5 將雙層 for 迴圈改為 `range(layout.n_rows)` × `range(layout.n_cols)`
- [x] 2.6 將鄰居邊界檢查 `nr >= grid_count or nc >= grid_count` 改為 `nr >= layout.n_rows or nc >= layout.n_cols`
- [x] 2.7 將 `cyl_length = wall_thickness * 3` 改為 `cyl_length = layout.wall_thickness * 3`
- [x] 2.8 更新 docstring 說明 `layout` 參數語意與 fallback 行為

## 3. 修改 generate_hex_grid()

- [x] 3.1 在 [agent/sla_operations.py](agent/sla_operations.py) 的 `generate_hex_grid()` 簽名加入 `layout: "HexGridLayout" = None`
- [x] 3.2 以 `if layout is None: layout = compute_hex_grid_layout(...)` 取代函式內的 spacing／grid placement 計算區塊（含原有的 `# Grid placement: anchor the lattice...` 大段）
- [x] 3.3 以 `layout.col_step`、`layout.row_step`、`layout.center_x`、`layout.center_y`、`layout.n_cols`、`layout.n_rows` 取代對應的局部變數（`has_hollow`、raycast 部分保持不變）

## 4. 修改 ortho_pipeline.py

- [x] 4.1 在 [agent/ortho_pipeline.py](agent/ortho_pipeline.py) import 區段加入 `compute_hex_grid_layout`
- [x] 4.2 在 `run_ortho_pipeline()` 的 Step 3 結束後（`bottom_z = float(...)` 之後）、Step 4 之前，加入 `grid_layout = compute_hex_grid_layout(radius=hex_cell_radius, wall_thickness=hex_wall_thickness, grid_count=hex_grid_count, hollow_mesh=hollow_mesh)`
- [x] 4.3 在 Step 4 的 `generate_hex_grid()` 呼叫加入 `layout=grid_layout`
- [x] 4.4 在 Step 5 的 `generate_drain_holes()` 呼叫加入 `layout=grid_layout`

## 5. 驗證

- [x] 5.1 確認 import 正常：`python -c "from agent.sla_operations import HexGridLayout, compute_hex_grid_layout, generate_drain_holes, generate_hex_grid; print('OK')"` → `OK`
- [x] 5.2 確認無 hollow 時 layout 中心為原點：`layout = compute_hex_grid_layout(5.0, 1.0, 10); assert layout.center_x == 0.0` → 通過
- [x] 5.3 確認 legacy 呼叫（無 layout 參數）face count 與修改前相同（33408 faces）→ 通過
- [x] 5.4 確認 offset hollow mesh（中心 (50, 30)）時兩函式 XY 邊界中心一致（差值 0.0000 mm）→ 通過
- [x] 5.5 確認大 hollow（XY 120mm × 100mm）觸發 n_cols=16, n_rows=16 自動擴展，且 drain_holes 同步擴展、XY 中心差值 0.0000 mm → 通過
- [x] 5.6 確認 ortho_pipeline import 正常且 pipeline 程式碼含 `compute_hex_grid_layout` 與 `layout=grid_layout` → 通過
- [x] 5.7 實機一鍵處理驗證：所有 hex cell 壁面均有對應排液孔，外圍 cell 不再缺孔 → 通過（使用者實測確認）
