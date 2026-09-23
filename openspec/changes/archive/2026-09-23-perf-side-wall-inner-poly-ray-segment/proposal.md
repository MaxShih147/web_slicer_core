## Why

`perf-side-wall-point-in-polygon`（已 archive）處理了 Step 6（`agent/ortho_pipeline.py::generate_side_wall_drains()`）內 `point_in_polygon_2d()` 的向量化，明確把 inner-poly ray/segment 迴圈列為獨立、不重疊的 Non-Goal，留待本輪處理。`evaluate_sample_idx()` 內每次呼叫都用 Python scalar 迴圈對 `inner_poly` 全部邊逐一呼叫 `ray_seg_intersect_2d()`，取最近正向 hit，成本隨 inner 輪廓點數與 evaluate 呼叫次數（每個成功 bin 最多 11 次、12 bins 上限 132 次）線性增長。

以下 Step 6 正式改善數字，皆以**真正的 HEAD `7d3e439`** `generate_side_wall_drains()`（git worktree 完整簽出，逐 candidate 對 `inner_poly` 執行 Python `for` 迴圈、逐邊呼叫既有 `ray_seg_intersect_2d()`、該函式內部每次重新計算 `ex`/`ey`/`denom`/`t`/`u`）作為 reference，與目前 working tree 的向量化 implementation 交錯執行（interleaved）量測，取代審查中發現不適用的「precomputed-edge scalar control」（該 control 已預先套用本輪才新增的 `inner_poly` 邊陣列一次性預計算，因而漏算了舊 production 逐 candidate 重新計算 `ex`/`ey` 與逐邊函式呼叫的開銷，低估了真實改善幅度；詳見 `design.md`「量測方法澄清」）。四個真實模型上，正式 Step 6 timing 改善 30.2%～87.4%（`DentalModel_NeedRotate.stl` 30.2%、`DentalModel_1M.stl` 72.8%、`005_p.stl` 85.1%、`001_p.stl` 87.4%；詳見 `design.md`「實作與驗證記錄」）。以 NumPy 對 inner_poly 全部邊做 elementwise ray-segment 求交取代該 scalar 迴圈後，四個真實模型上直接呼叫 production `generate_side_wall_drains()`（僅 monkeypatch 新增的私有向量化 helper 這一個模組層級名稱切換 reference/implementation，此正確性驗證改用 precomputed-edge scalar control 作為 oracle 是合適的——因為它與向量化版本共用同一組 `ax`/`ex` 數學式，適合隔離向量化本身的數值等價性，不受「是否重複計算邊陣列」這個效能面向的差異干擾）驗證：ray 呼叫次數、逐次查詢結果、skip reasons、hole 數量與順序、pre-Boolean `.vertices`／`.faces` 皆 `np.array_equal`。

## What Changes

- **新增私有 vectorized helper `_ray_polygon_nearest_hit_t()`**（`agent/ortho_pipeline.py`）：對單一 ray（origin/direction）與一組預先計算好的 polygon 邊陣列（`ax`／`ay`／`ex`／`ey`）一次性計算 `denom`／`t`／`u`，取代 `evaluate_sample_idx()` 內對 `inner_poly` 逐邊呼叫 `ray_seg_intersect_2d()` 的 Python `for` 迴圈。
- **`generate_side_wall_drains()` 新增一次性 inner_poly edge 陣列預計算**：選定 `inner_poly` 後，立即建立 `inner_ax`／`inner_ay`／`inner_ex`／`inner_ey`（`b` 為下一個 polygon 點，最後一點連回第一點），在該次呼叫的所有 `evaluate_sample_idx()` 呼叫間重用，不逐 candidate 重建。
- **`ray_seg_intersect_2d()` 完全不變**：函式簽章、實作、既有呼叫方式（若有其他呼叫端）不受影響，本次只新增一個服務於 `evaluate_sample_idx()` 這個呼叫點的獨立 helper。
- **不改變**：`point_in_polygon_2d()`（上一輪已完成）、`slice_mesh_at_z()`、candidate/slide search、angle bins、wall score、spacing gate、hole 幾何建立、Step 7～10 Boolean。
- **不新增**：第三方依賴、針對特定模型點數的硬編碼 fast path、candidate×edge 全矩陣。

## Capabilities

### New Capabilities
- `side-wall-inner-poly-ray-segment-performance`：定義 `_ray_polygon_nearest_hit_t()` 向量化實作必須維持的正確性契約——與逐邊呼叫既有 `ray_seg_intersect_2d()` 的 scalar 組合完全一致（一般 hit、多重 hit 選最近、無 hit、parallel/collinear/zero-length edge、segment endpoint、`u` 邊界、`t` 邊界含 `t>0.01` 嚴格閾值、`abs(denom)>=1e-12` 邊界、同 `t` tie-break）、不得對無效 edge 無條件除法造成新增 NumPy runtime warning、`generate_side_wall_drains()` 下游 pre-Boolean 輸出的 `np.array_equal` 等價判準。

### Modified Capabilities
（無。本提案不修改 `side-wall-point-in-polygon-performance` 或 `side-wall-drain-slice-performance` 的 spec 層級行為——三者是 Step 6 內三個獨立、不重疊的成本點。）

## Impact

- `agent/ortho_pipeline.py`：新增 `_ray_polygon_nearest_hit_t()`；`generate_side_wall_drains()` 新增一次性 inner_poly edge 陣列預計算；`evaluate_sample_idx()` 內原本的 scalar ray 迴圈改為呼叫新 helper。`ray_seg_intersect_2d()`、`point_in_polygon_2d()` 不變。
- 測試：新增 `agent/tests/test_side_wall_inner_poly_ray_vectorized.py`，涵蓋一般單一/多重 hit、無 hit、空/單點 polygon、parallel/collinear/zero-length edge、segment endpoint（`u=0`／`u=1`）、`u` 超出範圍、`t` 邊界（`t=0`／`t=0.01`／略大於 `0.01`）、`abs(denom)` 相對 `1e-12` 的邊界、同 `t` tie-break（保留較低 edge index）、最後一點連回第一點、固定 seed random 壓力對照、warnings-as-error、float64 不被內部 downcast。
- 效能（正式 timing 與詳細 instrumentation 分開量測，reference 與 implementation 交錯執行降低系統時間漂移，1 次 warm-up + 3 次計時取 median）：4 個真實代表模型的 Step 6 wall time 改善，reference 為 git worktree 簽出的真正 HEAD `7d3e439` `generate_side_wall_drains()`；另對 `001_p.stl`／`DentalModel_1M.stl` 量測完整 Auto Process（`run_ortho_pipeline()`）端到端改善，reference 同樣為 worktree 簽出的真正 HEAD `7d3e439`（含其原始 Step 1～10 全部行為），implementation 為目前 working tree，數字記錄於 `design.md`。
- 正確性：4 個真實模型的 reference（precomputed-edge scalar control，作為向量化數值等價性的 oracle）與 implementation（向量化）使用完全相同的 in-memory `outer_shell`／`inner_shell` 輸入（同一次 PrusaSlicer CLI hollow 輸出＋Step 2/3 extend/align，不經 STL round-trip），比較 ray 呼叫次數、逐次查詢結果、skip reasons、hole 數量與順序，並以 `np.array_equal(vertices)`／`np.array_equal(faces)` 作為 pre-Boolean Side-wall drains 的正式驗收線；完整 Auto Process 端到端比較 faces／vertices count、volume、bounds、`is_watertight` 等語意結果（reference 為真正 HEAD `7d3e439`），不宣稱 Boolean 後 STL byte equality。
- 不觸及：`point_in_polygon_2d()`、`ray_seg_intersect_2d()`、`slice_mesh_at_z()`、candidate/slide search、wall score、spacing gate、hole 幾何、Step 7～10 Boolean、`agent/sla_operations.py`。
- 測試模型（唯讀，不納入 Git）：`C:\Users\user\Pictures\tempTest\001_p.stl`、`005_p.stl`、`DentalModel_1M.stl`、`DentalModel_NeedRotate.stl`。
