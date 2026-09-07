## Why

在牙科模型一鍵處理流程中，蜂巢填充（hex grid）的 cell 之間應有互通的排液孔，使打印後樹脂能在相鄰 cell 間流動。實測發現：靠近平台中心的 cell 有正常打通的壁面孔，但距離中心超過一定範圍的 cell 雖然結構存在，卻缺少壁面孔。

根本原因是 [generate_hex_grid()](agent/sla_operations.py#L2212) 與 [generate_drain_holes()](agent/sla_operations.py#L2114) 各自獨立計算 grid 幾何，兩者在**中心座標**和 **grid 尺寸**上使用不同的值：

- `generate_hex_grid()` 依 `hollow_mesh.bounds` 將 grid 中心定在模型 hollow 的 bounding box 中心，並自動擴展 `n_cols`／`n_rows` 以完整覆蓋 hollow；
- `generate_drain_holes()` 固定以 `(0, 0)` 為中心，只遍歷 `grid_count × grid_count` 的固定範圍。

兩套獨立計算產生的 grid 中心與尺寸不一致，使 drain hole 圓柱無法與實際 hex cell 壁面位置對齊，外圍 cell 因此沒有對應的排液孔。

## What Changes

- **新增 `HexGridLayout` class**（[agent/sla_operations.py](agent/sla_operations.py)）：統一保存 grid 幾何參數（`center_x`、`center_y`、`n_cols`、`n_rows`、`col_step`、`row_step`、`wall_thickness`），作為兩個函式的共用資料結構。
- **新增 `compute_hex_grid_layout()`**（[agent/sla_operations.py](agent/sla_operations.py)）：將原本散落在 `generate_hex_grid()` 內的 grid 中心與尺寸計算邏輯抽出為共用 helper。依 `hollow_mesh.bounds` 計算中心與自動擴展尺寸（與原 `generate_hex_grid()` 邏輯相同），無 `hollow_mesh` 時退回 `(0, 0)` 中心與 `grid_count × grid_count`（維持舊有 standalone API 行為）。
- **修改 `generate_hex_grid()`**（[agent/sla_operations.py](agent/sla_operations.py)）：新增 optional `layout` 參數。有傳入時直接使用 layout，跳過內部 bounds 計算；無傳入時透過 `compute_hex_grid_layout()` 自行計算（向下相容）。
- **修改 `generate_drain_holes()`**（[agent/sla_operations.py](agent/sla_operations.py)）：新增 optional `layout` 參數。有傳入時使用 layout 的中心、`n_cols`、`n_rows`，正確遍歷完整 grid；無傳入時以不含 `hollow_mesh` 的 `compute_hex_grid_layout()` 計算（向下相容）。
- **修改 `run_ortho_pipeline()`**（[agent/ortho_pipeline.py](agent/ortho_pipeline.py)）：Step 3 完成 hollow 對齊之後，一次性計算 `grid_layout = compute_hex_grid_layout(..., hollow_mesh=hollow_mesh)`，並將 `layout=grid_layout` 傳給 Step 4 的 `generate_hex_grid()` 與 Step 5 的 `generate_drain_holes()`，確保兩者共用同一套 grid 參數。

## Capabilities

### New Capabilities
- `hex-grid-layout`：定義 `HexGridLayout` 與 `compute_hex_grid_layout()` 的語意與行為——grid 幾何 SHALL 依 hollow_mesh.bounds 計算並共用；`generate_hex_grid()` 與 `generate_drain_holes()` 在收到相同 layout 時 SHALL 在完全一致的 grid 座標系操作；standalone API 呼叫（無 layout）的 fallback 行為 SHALL 與修改前一致。

### Modified Capabilities
<!-- 無：排液孔與 hex grid 的 Boolean 流程、對外 API endpoint 行為皆不變。 -->

## Impact

- **程式碼**：
  - [agent/sla_operations.py](agent/sla_operations.py) — 新增 `HexGridLayout` class、`compute_hex_grid_layout()`；修改 `generate_drain_holes()` 與 `generate_hex_grid()` 各加 optional `layout` 參數。
  - [agent/ortho_pipeline.py](agent/ortho_pipeline.py) — import `compute_hex_grid_layout`，pipeline Step 3 結束後計算 `grid_layout` 並傳入 Step 4、Step 5。
- **API**：`/slices/{job_id}/generate-drain-holes` 與 `/slices/{job_id}/generate-hex-grid` 對外簽名不變（`layout` 為選填，舊呼叫端無需更新）。
- **行為**：一鍵處理（ortho pipeline）的 drain hole 圓柱現在覆蓋與 hex grid 完全一致的座標範圍，所有 hex cell 壁面皆有對應的排液孔。Standalone API endpoint 行為不變。
