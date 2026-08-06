## Context

牙科模型一鍵處理（`run_ortho_pipeline`）在 Step 4 生成蜂巢填充、Step 5 生成填充 cell 間壁面排液孔，兩步驟緊接完成後在 Step 7 透過 Boolean union 將兩者合併：

```
Step 4: generate_hex_grid(hollow_mesh=hollow_mesh, ...)   → hex_mesh
Step 5: generate_drain_holes(...)                          → drain_mesh
Step 7: boolean_meshes(hex_mesh, drain_mesh, UNION)        → step7_mesh
Step 8: boolean_meshes(flipped_hollow, step7_mesh, INTER)  → step8_mesh（裁至 hollow 內部）
Step 10: boolean_meshes(input_mesh, step9_mesh, DIFF)      → 最終結果
```

**根本原因（2026-08-06 確認）**：兩個函式各自計算 grid 幾何，存在兩項不一致：

1. **Grid 中心不同**
   - `generate_hex_grid()`：`center_x/y = hollow_mesh.bounds 中心`（模型在哪，grid 就在哪）
   - `generate_drain_holes()`：`center_x/y = (0, 0)`（永遠在平台原點）
   - 若模型不在原點，兩套 grid 的 (row, col) 代表的 XY 座標完全不同，drain 圓柱不會落在 hex cell 壁面上。

2. **Grid 尺寸不同**
   - `generate_hex_grid()`：`n_cols = max(grid_count, ceil(span_x / col_step) + 3)`（依 hollow bounds 自動擴展）
   - `generate_drain_holes()`：永遠使用 `grid_count × grid_count`（固定不擴展）
   - 即使中心相同，自動擴展後 `half_cols = (n_cols−1)/2` 與 `(grid_count−1)/2` 不同，導致同一 (row, col) index 對應不同的 XY 座標，外圍 cell 沒有 drain 圓柱。

**實測現象說明**：模型若近似平台原點且 hollow 面積剛好在 grid_count 範圍內，兩函式 grid 部分重疊，中心附近的 cell 仍能得到孔；遠離中心或面積超出 grid_count 的 cell 便完全缺孔，符合使用者觀察「靠近中心有孔、外圍無孔」。

**約束**：
- `api_v2.py` 的 `/generate-hex-grid` 與 `/generate-drain-holes` endpoint 是 DS-Online 舊版分步流程的遠端呼叫點，其函式簽名不可破壞向下相容性。
- `generate_hex_grid()` 仍需 `hollow_mesh` 用於 Step 4 的高度 raycast，不能從簽名移除。
- 兩函式的 grid 中心與尺寸計算邏輯應有**單一來源**，避免日後再次不同步。

## Goals / Non-Goals

**Goals:**
- 確保 `generate_hex_grid()` 與 `generate_drain_holes()` 在 ortho pipeline 中使用完全一致的 grid 座標系（相同中心、相同 n_cols/n_rows、相同 half_cols/half_rows）。
- 消除 grid 幾何計算的程式碼重複，建立單一計算來源 `compute_hex_grid_layout()`。
- 保持 standalone API endpoint 的向下相容（無 `layout` 時行為不變）。

**Non-Goals:**
- 不改動 Boolean union/difference 流程（Step 7–10）。
- 不改動 hex cell 幾何建構邏輯或 drain 圓柱的方向、尺寸計算。
- 不修改 `generate_side_wall_drains()` 的多物件問題（另一獨立議題）。
- 不更動對外 REST API 簽名或回傳結構。

## Decisions

### D1：以 `HexGridLayout` dataclass 作為共用載體

選擇以單純的 class（非 `@dataclass` 裝飾器）持有 grid 幾何欄位：`center_x`、`center_y`、`n_cols`、`n_rows`、`col_step`、`row_step`、`wall_thickness`。此結構不涉及序列化或繼承，plain class 最輕量。`wall_thickness` 納入是因為 `generate_drain_holes()` 需要它計算圓柱長度（`cyl_length = wall_thickness * 3`），與其讓函式保留舊參數又從 layout 取 step，不如統一持有。

**替代方案（已否決）**：
- *NamedTuple*：欄位不可變，與「optional layout 有時由函式內部填入」的使用模式略顯奇怪，且未提供額外收益。
- *直接讓 `generate_hex_grid()` 回傳 `(mesh, layout)` tuple*：破壞現有呼叫端（api_v2 endpoint、舊版 tests），重構成本過高。

### D2：`layout` 為 optional 參數，保持向下相容

兩個函式各加 `layout: "HexGridLayout" = None`。有傳入時使用 layout，跳過內部計算；無傳入時呼叫 `compute_hex_grid_layout()` 以等效邏輯自行計算。

這樣 `api_v2.py` 的 `/generate-drain-holes` endpoint（無 `hollow_mesh`）與 `/generate-hex-grid` endpoint 皆不需修改，舊有行為不變。

**替代方案（已否決）**：
- *將 `layout` 改為必填*：所有既有呼叫端（包含 api_v2.py）需同步修改，風險高且沒有實質收益。
- *讓 `generate_hex_grid()` 內部直接呼叫 `generate_drain_holes()` 並回傳兩者*：職責混淆，且 pipeline 的 Step 4/5 是獨立步驟，強耦合不合適。

### D3：只在 `compute_hex_grid_layout()` 保留完整中心／尺寸計算邏輯

`generate_hex_grid()` 的 `layout is None` fallback 現在改為呼叫 `compute_hex_grid_layout()`，不再在函式體內重複 bounds 計算程式碼。如此未來任何 grid 計算邏輯的調整只需改動一處。

## Risks / Trade-offs

- **[Standalone endpoint 仍有中心不一致的潛在問題]** `/generate-drain-holes` endpoint 單獨呼叫時（沒有 `hollow_mesh`）grid 中心仍在 `(0, 0)`，與同 job 的 `/generate-hex-grid` 結果中心可能不同。這是舊版分步 API 的既有限制，不在本次修正範圍，且分步 API 已被 ortho pipeline 取代為主要流程。
- **[n_cols/n_rows 擴展後 drain hole 圓柱數大幅增加]** grid 面積等比增大時，壁面數量（drain 圓柱數）也線性增長。對 Boolean 效能有輕微影響，但 Step 8 的 intersection 會裁掉 hollow 外的圓柱，實際參與最終 difference 的圓柱數由 hollow 大小決定，不會無上限增長。
- **[`wall_thickness` 放入 layout 而非維持在函式參數]** layout 持有的 `wall_thickness` 由 `compute_hex_grid_layout()` 傳入時設定，與 `generate_drain_holes()` 簽名中既有的 `wall_thickness` 參數同義。有 layout 時忽略簽名中的 `wall_thickness`，無 layout 時使用簽名中的值。此行為在函式 docstring 中已說明。

## Migration Plan

1. 在 [agent/sla_operations.py](agent/sla_operations.py) 的 `generate_drain_holes()` 定義前新增 `HexGridLayout` class 與 `compute_hex_grid_layout()` 函式。**【已完成】**
2. 修改 `generate_drain_holes()` 加入 `layout` 參數、更新 docstring、將 grid 計算替換為 layout 驅動。**【已完成】**
3. 修改 `generate_hex_grid()` 加入 `layout` 參數、將內部 bounds 計算區塊替換為 `compute_hex_grid_layout()` 呼叫。**【已完成】**
4. 在 [agent/ortho_pipeline.py](agent/ortho_pipeline.py) import `compute_hex_grid_layout`，於 Step 3 結束後計算 `grid_layout`，並傳入 Step 4、Step 5。**【已完成】**
5. 驗證：imports 正常、legacy 呼叫正常、offset 模型的 grid 中心一致、大 hollow 觸發 n_cols 擴展後 drain holes 同步擴展。**【已完成；見 tasks.md 驗證步驟】**

**回滾**：移除 `grid_layout` 計算行與 `layout=grid_layout` 傳遞，並還原兩個函式的 `layout` 參數即可；兩函式本身的 fallback 路徑（`layout is None`）確保無需同時改動 api_v2.py。

## Open Questions

<!-- 無。 -->
