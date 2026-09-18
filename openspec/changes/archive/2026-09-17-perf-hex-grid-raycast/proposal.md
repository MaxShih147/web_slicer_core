## Why

Auto Process Ortho pipeline Step 4（`generate_hex_grid()`，[agent/sla_operations.py:2314](../../../agent/sla_operations.py#L2314)）先前的效能調查（見 `openspec/changes/archive/2026-09-15-optimize-auto-process-performance/design.md` Non-Goals：「不處理 Hex Grid raycast backend——瓶頸已 100% 定位在 raycast，但替代 backend 尚未 prototype」）已確認 raycast 佔 Step 4 執行時間約 99.7%，但當時沒有可驗收的具體修法方向，明確排除在該提案之外。

後續 source-level 調查（本次變更的前置作業）重新以 `.venv` 實際使用的 `trimesh==4.11.1`（`has_embree=False`，未安裝 `embreex`／`pyembree`）重現 baseline，定位出真正瓶頸：`generate_hex_grid()` 對 hollow mesh 的單次批次 `intersects_location()` 呼叫，底層會對**全部**三角形建一個通用 3D r-tree（`mesh.triangles_tree`）——因為呼叫端在 Step 3 已對 hollow mesh 做過 `apply_translation()`，trimesh 的 hash-based cache 必然失效，這棵樹每次 pipeline 執行都要重建一次，且全流程只被查詢這一次（全 repo 確認 `hollow_mesh` 沒有第二處呼叫 `.ray.*`）。以 `001_p.stl`／`005_p.stl`／`DentalModel_1M.stl`／`DentalModel_NeedRotate.stl` 四個代表模型量測，tree build 佔這段 raycast 90～97%，而所有 ray 方向皆固定為 `+Z`——這是一個可以被向量化 XY bounding-box 重疊測試取代的通用結構，不需要真正的 3D 空間索引。

## What Changes

- **新增 `_hex_grid_vertical_ray_intersects_location()`**（[agent/sla_operations.py](../../../agent/sla_operations.py)）取代 `generate_hex_grid()` 內唯一一處 `hollow_mesh.ray.intersects_location()` 呼叫：
  - Broad-phase 改為對三角形分塊（`chunk_size=16384`）計算 XY bounding box，以與 trimesh `ray_bounds()` 相同的 `buffer_dist=1e-5` 判斷是否與各 ray 的 `(x, y)` 重疊，取代對全部三角形建 3D r-tree。因為所有 ray 方向固定為 `(0, 0, 1)`，trimesh 自身的 r-tree query box 在此條件下的 Z 軸範圍恆涵蓋整個 mesh（推導與根因見 `design.md`），故本項改動的候選集合是原 r-tree 結果的超集合——SHALL NOT 產生 false negative。
  - Narrow-phase（plane intersection、barycentric 判定、epsilon、forward-distance 篩選、`multiple_hits=True` 語意、重複 hit 去重）逐行沿用 trimesh 4.11.1 `ray_triangle.ray_triangle_id()` / `RayMeshIntersector.intersects_id()` 的既有實作，不自創精度或判定公式。
  - 若某次呼叫的 ray 方向不是全部恰為 `(0, 0, 1)`，直接 fallback 呼叫 `mesh.ray.intersects_location()`——此 helper 只是固定垂直 ray 場景的專用路徑，不是通用求交替代品。
- **不變更**：layout 計算（`compute_hex_grid_layout()`）、ray origins/directions 的產生方式、cell height／`h_val < 1` 篩選邏輯、cell mesh assembly（vertices/faces 組裝）、drain holes、後續 Boolean 流程。未新增任何第三方依賴，未採用 Embree／完整 grid bucket 等其他方案。

## Capabilities

### New Capabilities
- `hex-grid-raycast-performance`：定義 `generate_hex_grid()` 這項 raycast broad-phase 優化必須維持的正確性契約——固定垂直 ray 的候選三角形搜尋不得產生 false negative、narrow-phase 必須與 trimesh 既有實作等價、非垂直 ray 的 fallback 行為、以及最終 Hex Grid 幾何輸出的等價判準。

### Modified Capabilities
（無。本提案不修改任何既有 capability 的 spec 層級行為——`hex-grid-layout` 既有 requirement 涵蓋的 layout 計算、ray 產生方式完全未變動；本提案範圍限定在 raycast 候選三角形搜尋這個純實作層級細節。）

## Impact

- `agent/sla_operations.py`：新增 `_hex_grid_vertical_ray_intersects_location()`；`generate_hex_grid()` 內部呼叫點改為使用新 helper（[:2314](../../../agent/sla_operations.py#L2314) 起）。
- 測試：新增 `agent/tests/test_hex_grid_vertical_ray_intersect.py`（11 tests，合成幾何 + 端到端 byte-for-byte 比對）。
- 不觸及：`agent/ortho_pipeline.py` Step 4 呼叫端、`agent/api_v2.py` 的 `generate-hex-grid` 獨立端點呼叫端（兩者皆未修改參數或呼叫方式）、drain holes、Boolean 流程。
- 測試模型（唯讀，不納入 Git）：`C:\Users\user\Pictures\tempTest\001_p.stl`、`005_p.stl`、`DentalModel_1M.stl`、`DentalModel_NeedRotate.stl`。
