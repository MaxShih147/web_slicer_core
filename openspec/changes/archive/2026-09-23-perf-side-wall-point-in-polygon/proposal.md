## Why

前一輪調查（`slice_mesh_at_z()` broad-phase，已 archive 為 `perf-side-wall-drain-slice`）明確排除了 Step 6（`agent/ortho_pipeline.py::generate_side_wall_drains()`）內兩項尚未處理的成本，其中之一是 `point_in_polygon_2d()`：它用純 Python scalar 迴圈對 outer 輪廓（fine outer contour）做 ray-casting parity 判定，成本隨 outer 輪廓點數線性增長。呼叫重複型態量測（4 個真實模型）顯示同一 query point 完全重複的比例只有 0%～15.4%，代表快取幾乎沒有價值，真正的成本是「每次呼叫內部 O(outer 輪廓點數) 的 Python scalar 迴圈」本身。

以下數字皆為本 change 針對真實 production `generate_side_wall_drains()` 的正式量測（詳見 `design.md`「實作與驗證記錄」，reference／implementation 使用完全相同的 in-memory `outer_shell`／`inner_shell` 輸入，未經 STL round-trip）：在 outer 輪廓點數特別多的模型（`DentalModel_1M.stl`，4,644 點）上，診斷用 instrumented 執行顯示 `point_in_polygon_2d()` 單一 helper 佔候選評估階段約 67.8%，正式 Step 6 timing 從 1.4709s 降到 0.4872s（−66.9%）；在 outer 輪廓較稀疏的模型上，正式 Step 6 改善幅度為 5.8%～11.7%（`DentalModel_NeedRotate.stl` 5.8%、`001_p.stl` 9.5%、`005_p.stl` 11.7%）。以 NumPy 對 polygon 邊做 elementwise parity 判定取代該 scalar 迴圈後，四個真實模型上直接呼叫 production `generate_side_wall_drains()`（僅 monkeypatch `point_in_polygon_2d` 這一個模組層級名稱切換 reference/implementation）驗證：PIP 呼叫次數、逐次查詢點與翻轉結果、skip reasons、hole 數量與順序、pre-Boolean `.vertices`／`.faces` 皆 `np.array_equal`。

## What Changes

- **`point_in_polygon_2d()` 內部實作改為 NumPy 向量化**（`agent/ortho_pipeline.py`）：以 `np.roll` 取得每個頂點的「前一個頂點」座標，對全部邊一次性計算 parity-toggle 條件與 x-intercept，取代目前逐邊執行的 Python `for` 迴圈。
- **函式簽章、回傳型態、呼叫方式完全不變**：仍是 `point_in_polygon_2d(poly: np.ndarray, px: float, py: float) -> bool`，`evaluate_sample_idx()` 內唯一呼叫點（`sx + nx*0.1, sy + ny*0.1`）不需任何修改。
- **不改變**：比較運算子方向（`>`、`<`）、既有 point-on-boundary／horizontal edge 行為、`ray_seg_intersect_2d()`、inner-poly ray/segment 迴圈、`slice_mesh_at_z()`、candidate／slide search、wall score、spacing gate、hole 幾何建立、Step 7～10 Boolean。
- **不新增**：快取、全域狀態、第三方依賴、針對特定模型點數的硬編碼 fast path。

## Capabilities

### New Capabilities
- `side-wall-point-in-polygon-performance`：定義 `point_in_polygon_2d()` 向量化實作必須維持的正確性契約——與 scalar reference 的逐點判定結果完全一致（一般 polygon、edge/vertex 邊界情況、horizontal edge、degenerate/空 polygon）、不得對不滿足 parity 條件的邊無條件除法造成新增 NumPy runtime warning、`generate_side_wall_drains()` 下游 pre-Boolean 輸出的 `np.array_equal` 等價判準。

### Modified Capabilities
（無。本提案不修改 `side-wall-drain-slice-performance` 或其他既有 capability 的 spec 層級行為——上一輪處理的 `slice_mesh_at_z()` broad-phase 與本輪的 `point_in_polygon_2d()` 向量化是 Step 6 內兩個獨立、不重疊的成本點。）

## Impact

- `agent/ortho_pipeline.py`：只修改 `point_in_polygon_2d()` 函式本體的 parity 判定實作方式，簽章與呼叫端不變。
- 測試：新增 `agent/tests/test_point_in_polygon_2d_vectorized.py`，涵蓋 convex/concave polygon、orientation 反轉、內部/外部/edge/vertex query、horizontal/vertical edge、repeated vertex、zero-length edge、空 polygon、degenerate（<3 點）polygon、固定資料對照、固定 seed 的 random parity 對照，並確認正常輸入不新增 NumPy runtime warning。
- 效能（正式 timing 與詳細 instrumentation 分開量測，1 次 warm-up + 3 次計時取 median）：4 個真實代表模型（`001_p.stl`／`005_p.stl`／`DentalModel_1M.stl`／`DentalModel_NeedRotate.stl`）的 Step 6 wall time 改善，數字待本輪正式量測記錄於 design.md。
- 正確性：4 個真實模型的 reference（scalar）與 implementation（vectorized）使用完全相同的 in-memory `outer_shell`／`inner_shell` 輸入（同一次 PrusaSlicer CLI hollow 輸出＋Step 2/3 extend/align，不經 STL round-trip），比較 outer/inner polygon 點數、evaluate 次數、PIP 呼叫數、逐 candidate normal flipped 結果、accepted/rejected candidate、hole 數量與順序、skip reasons，並以 `np.array_equal(vertices)`／`np.array_equal(faces)` 作為 pre-Boolean Side-wall drains 的正式驗收線。
- 不觸及：`ray_seg_intersect_2d()`、inner-poly ray/segment 迴圈、`slice_mesh_at_z()`、candidate/slide search、wall score、spacing gate、hole 幾何、Step 7～10 Boolean、`agent/sla_operations.py`。
- 測試模型（唯讀，不納入 Git）：`C:\Users\user\Pictures\tempTest\001_p.stl`、`005_p.stl`、`DentalModel_1M.stl`、`DentalModel_NeedRotate.stl`。
