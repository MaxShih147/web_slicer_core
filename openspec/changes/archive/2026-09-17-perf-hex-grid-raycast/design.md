## Context

`generate_hex_grid()`（[agent/sla_operations.py:2314](../../../agent/sla_operations.py#L2314)）是 Ortho pipeline Step 4 的核心：對 hollow mesh 送出一批固定 `+Z` 方向的 ray（每個 hex cell 中心一條），用 `intersects_location()` 找出每條 ray 的最高 Z 交點，決定該 cell 的 prism 高度；無交點的 cell 落回全域 fallback 高度。呼叫端只有兩處（`agent/ortho_pipeline.py` Step 4、`agent/api_v2.py` 的 `generate-hex-grid` 端點），兩者在呼叫前都會對 hollow mesh 做一次 `apply_translation()`（把 PrusaSlicer hollow 輸出對齊回 input model 座標），這會讓 trimesh 的 hash-based cache 失效。

`openspec/changes/archive/2026-09-15-optimize-auto-process-performance` 的調查已把瓶頸 100% 定位在 raycast（99.7% of Step 4 時間），但當時沒有具體、可驗收的修法方向，列為 Non-Goal。本提案的前置調查（source tracing + baseline 重現）進一步定位：raycast 本身的時間幾乎全部花在 trimesh 預設 `RayMeshIntersector`（`agent.ray.ray_triangle`）的 broad-phase——`mesh.triangles_tree` 這個對全部三角形建立的通用 3D r-tree（`rtree.index.Index` stream bulk-load）。因為：
1. 這棵樹每次 pipeline 執行都是冷的（Step 3 的 translation 使快取失效）；
2. 全 repo 確認 `hollow_mesh` 在整條 pipeline 中只有這一處呼叫 `.ray.*`——沒有第二次查詢可以攤提建樹成本；
3. 所有 ray 方向固定為 `(0, 0, 1)`。

這三點合起來代表：不需要一個通用的 3D 空間加速結構，只需要一個針對「固定垂直 ray、少量已知查詢點」設計的專用 broad-phase。

## Goals / Non-Goals

**Goals:**
- 用向量化 NumPy 計算取代「對全部三角形建 3D r-tree」這個 broad-phase，保留 trimesh 既有的 narrow-phase（plane intersection、barycentric、epsilon、multi-hit、去重）不變。
- 保證新 broad-phase 是舊 r-tree 候選集合的**超集合**（不得有 false negative），並用真實模型與合成邊界案例驗證最終幾何輸出等價。
- 完整 `generate_hex_grid()` 至少在 `001_p.stl`／`005_p.stl` 上改善 ≥40% 或 ≥0.5 秒（wall time），且其他代表模型無明顯退化。

**Non-Goals（本輪不處理）：**
- 不引入 Embree／`embreex`／`pyembree` 或任何新的第三方依賴。
- 不做完整的 2D/3D grid bucket 空間索引（本輪選擇最小改動：純向量化 XY 重疊測試，不建任何額外資料結構）。
- 不改變 layout 計算、ray origins/directions 產生方式、cell height／`h_val < 1` 篩選、cell mesh assembly、drain holes、Boolean 流程。
- 不處理 Side-wall drains 幾何搜尋、Surgical Guide 相關優化（其他 capability 範圍）。

## Decisions

### D1：Broad-phase 改為向量化 XY bounding-box 重疊測試，取代通用 3D r-tree

**根因**：trimesh `ray_triangle.ray_triangle_id()` 的 broad-phase（[ray_triangle.py:303](../../../.venv/Lib/site-packages/trimesh/ray/ray_triangle.py#L303) `ray_triangle_candidates()`）對每條 ray 各自計算一個「ray 通過整個 tree 體積」的 3D query box，再逐條呼叫 `tree.intersection(bounds)`（Python for-loop）。這個 query box 的計算方式（[ray_bounds():340](../../../.venv/Lib/site-packages/trimesh/ray/ray_triangle.py#L340)）用 ray 的主軸（此處恆為 Z）搭配**樹的全域邊界**（而非 ray 自身的物理長度）算出 Z 範圍：`t = (tree 全域 Z 邊界 - ray origin Z) / ray direction Z`。因為所有 ray 的 origin Z 恆為 `-100`、direction 恆為 `(0,0,1)`，算出來的 Z 範圍就是 `[tree 全域 min Z - eps, tree 全域 max Z + eps]`——**恆為整個 mesh 的 Z 範圍**，不可能排除任何三角形。真正發揮篩選作用的只有 X／Y 兩軸：`ray_bounding = [cx-eps, cy-eps, ..., cx+eps, cy+eps, ...]`，與 r-tree 裡每個三角形的 3D bounding box 做 AABB 重疊測試時，Z 軸永遠重疊，等價於只測試 X／Y 是否重疊。

**結論**：對於方向恰為 `(0, 0, 1)` 的 ray，「三角形是否可能被此 ray 命中」的 broad-phase 篩選條件，在數學上等價於「三角形的 XY 投影 bounding box 是否包含 `(cx, cy)`（padded by `buffer_dist=1e-5`）」。因此可以完全跳過建樹，直接向量化計算：

```
tri_xy_min = triangles[:, :, :2].min(axis=1)   # (n_faces, 2)
tri_xy_max = triangles[:, :, :2].max(axis=1)
in_x = (ray_x >= tri_xy_min[:,0] - eps) & (ray_x <= tri_xy_max[:,0] + eps)
in_y = (ray_y >= tri_xy_min[:,1] - eps) & (ray_y <= tri_xy_max[:,1] + eps)
candidate = in_x & in_y
```

三角形依 `chunk_size=16384` 分塊處理（避免一次配置完整 `n_faces × n_rays` 矩陣），每塊做上述比較後用 `np.nonzero` 取出候選 `(triangle_id, ray_id)` pair。

**為何不會有 false negative**：新 broad-phase 只用 XY 重疊測試，是原本「XY 重疊 AND Z 恆真」條件的邏輯超集合（拿掉一個恆真的 AND 項不會讓集合變小）。任何原本會被 r-tree 選中的候選三角形，一定也會被新 broad-phase 選中；新 broad-phase 唯一可能比原本多選的候選，會在 narrow-phase（未改動的精確 plane intersection + barycentric 判定）被正確排除，不影響最終結果。

**考慮過的替代方案**：
- 完整 2D/3D grid bucket（依 hex layout 的 col_step/row_step 分桶三角形）——需要額外的分桶資料結構與邊界情況處理（三角形跨多個 bucket），本輪的量測顯示純向量化 XY 測試已達到門檻改善幅度，判斷不需要更複雜的方案；列為未來若有更高 ray 數場景再評估的方向。
- Embree（`embreex`）——理論上 BVH 建構與查詢都更快，但需要新增原生依賴，且此服務跑在使用者不可控的個人電腦上，部署／打包風險高，本輪明確排除（見 Non-Goals）。

### D2：Narrow-phase 逐行沿用 trimesh 既有實作

`_hex_grid_vertical_ray_intersects_location()` 的 narrow-phase（plane intersection `intersections.planes_lines()`、barycentric `triangles.points_to_barycentric()`、`tol.zero` epsilon、forward-distance 篩選 `distance > -1e-6`、`multiple_hits=True` 語意、`grouping.unique_rows` 去重）直接呼叫 trimesh 4.11.1 對應函式，程式碼結構逐行對應 `ray_triangle.ray_triangle_id()` 與 `RayMeshIntersector.intersects_id(return_locations=True)`，不自行改寫精度或判定公式。這保證 hit 結果與 trimesh 參考實作**逐位元組相同**，不是「數值相近」。

### D3：非垂直 ray 的 fallback

`_hex_grid_vertical_ray_intersects_location()` 檢查 `ray_directions` 是否全部恰為 `(0, 0, 1)`（`np.allclose`），若否直接呼叫 `mesh.ray.intersects_location()` 回傳。目前兩個生產呼叫點（`ortho_pipeline.py` Step 4、`api_v2.py` 的 `generate-hex-grid` 端點）都固定用 `np.tile([0.0, 0.0, 1.0], ...)` 產生 ray 方向，這個 fallback 路徑目前不會被觸發，但保留作為安全網——避免此 helper 未來被誤用在非固定垂直 ray 的情境時，靜默產生錯誤結果。

## 實作與驗證記錄

**Baseline 重現與代表模型**（`generate_hollow()` 真實 PrusaSlicer CLI 呼叫，預設 `hollowing_quality=0.5`；hollow 後 face count 見下表）：

| 模型 | input faces | hollow faces | rays (n_cols × n_rows) |
|---|---|---|---|
| `001_p.stl` | 32,138 | 427,868 | 110（11×10） |
| `005_p.stl` | 166,672 | 353,164 | 110（11×10） |
| `DentalModel_1M.stl` | 1,024,996 | 626,192 | 132（12×11） |
| `DentalModel_NeedRotate.stl` | 37,470 | 570,108 | 120（10×12） |

**`DentalModel_1M.stl` 面數說明**：原始輸入約 1,025,000 faces（檔名對應），但用預設 `hollowing_quality=0.5` hollow 之後只剩 **626,192 faces**——與 `001_p.stl`／`005_p.stl` 的 hollow mesh 同一量級，**不是百萬面等級**。本輪的量測結果 SHALL NOT 被解讀為「已驗證百萬面 hollow mesh 下的 raycast scaling」；若要驗證真正百萬面級 hollow mesh，需要更高 `hollowing_quality` 或另找/另建面數更高的 hollow 輸出，留待下一輪視需求決定。

**Benchmark（old/new interleaved，各模型 5 runs 取 median；獨立 subprocess 執行，確保每次都是冷 mesh，`time.perf_counter()`）**：

| 模型 | 舊版 tree build + query（median） | 新版 xy_bbox + broadphase + narrowphase + hit_grouping（median） | 完整 `generate_hex_grid()`：舊 → 新 | 改善 |
|---|---|---|---|---|
| `001_p.stl` | 1319.6ms（1276.5 + 43.1） | 378.4ms（60.3 + 278.7 + 39.3 + 0.1） | 1310.7ms → 388.6ms | **−70.4% / −922ms** |
| `005_p.stl` | 1049.1ms（1046.5 + 2.7） | 278.5ms（50.6 + 227.6 + 0.2 + 0.1） | 1060.7ms → 287.4ms | **−72.9% / −773ms** |
| `DentalModel_1M.stl` | 1963.3ms（1959.2 + 4.0） | 575.9ms（90.1 + 485.4 + 0.3 + 0.1） | 1937.2ms → 592.9ms | **−69.4% / −1344ms** |
| `DentalModel_NeedRotate.stl` | 1741.6ms（1738.4 + 3.2） | 486.3ms（82.8 + 403.2 + 0.3 + 0.1） | 1740.1ms → 499.7ms | **−71.3% / −1240ms** |

`cells_built`／`mesh_faces` 四模型新舊完全相同；新版 broad-phase 耗時經 `chunk_size` 2048～427,868（單塊）掃描確認與分塊大小無關（同一區間內波動），純粹是 O(faces × rays) 向量化比較本身的成本——分塊只影響記憶體峰值，不影響速度，符合設計預期。

**正確性驗證**：
- 合成幾何單元測試（`agent/tests/test_hex_grid_vertical_ray_intersect.py`，11 tests）：single/multi-hit、無 hit（ray 落在 footprint 外）、共享邊界 hit 去重、垂直退化三角形（plane 平行 ray 方向）、重複三角形、跨多個 ray 的大三角形、chunk 邊界＋非整除的 partial final chunk（`chunk_size` 1/3/8/16/100000 全部驗證一致）、非 `(0,0,1)` ray 的 fallback 逐位元組相同、空三角形 mesh。
- 4 個真實代表模型（含 `DentalModel_NeedRotate.stl`）：以「新版 raycast」與「暫時 monkeypatch 回 trimesh 原生 `intersects_location()`」分別跑完整 `generate_hex_grid()`，**最終 mesh 的 vertices／faces 逐位元組相同**（`np.array_equal` 全部 `True`）。

**記憶體**：以 Windows `GetProcessMemoryInfo`（純 `ctypes`，未新增依賴）量測各獨立 subprocess 的 Peak Working Set，四模型新舊 median 幾乎相同（例如 `001_p.stl` 341.7MB vs 341.3MB）。未觀察到記憶體退化；但此製程層級峰值主要由 mesh 載入與 trimesh/numpy import 等基底成本主導，量測解析度不足以單獨看出 chunking 節省的量——chunking 的記憶體效益要在 ray 數遠高於本次代表模型（110～132）的場景下才會在製程峰值上顯現。

**回歸測試**：`pytest agent/tests/ -q --continue-on-collection-errors`：710 passed、1 failed、3 errors——與既有基準（699 passed、1 failed、3 errors，見 `2026-09-15-optimize-auto-process-performance` 收尾時的數字）相比，新增的 710−699=11 即本項新增測試；既有的 1 failed（`test_prz_print_time.py`）與 3 collection errors（缺少 `httpx`）數字不變，確認非本項引入。

## Risks / Trade-offs

- **[XY bounding-box 重疊測試在 ray 數大幅增加時理論上會變慢]**（非目前 blocker）O(faces × rays) 的向量化比較成本隨 ray 數線性增長；若 ray 數遠高於本次代表模型（110～132），新 broad-phase 有可能反而比 r-tree 慢。→ 目前一鍵 Auto Process 流程中，`hex_cell_radius`／`hex_grid_count` 皆使用固定的後端預設值，前端未將 cell size 暴露為可調參數（全 repo 確認 `web/` 前端沒有任何呼叫傳遞 `hex_cell_radius`／`hex_grid_count`），而牙模的實際尺寸範圍本身有限（口腔／牙弓模型的 XY 跨度不會無限增長）——兩者合起來使 ray 數在可預期的未來維持在與本次 4 個代表模型（110～132）相近的量級。本輪 4 個代表模型皆有 69～73% 的改善，且改善幅度不隨模型面數增加而縮小（`DentalModel_1M.stl` 面數最高、改善幅度仍達 69.4%），**判定 ray 數量問題不阻擋本次採用**。若未來開放更小的 cell size（因而推高 ray 數）成為可調參數，SHALL 在開放前重新 profiling 確認 O(faces × rays) 曲線是否仍然有利，必要時才升級為分桶結構（design 中列為考慮過但本輪不採用的替代方案）。
- **[非垂直 ray fallback 路徑目前無實測覆蓋於真實 pipeline]** fallback 邏輯只由合成單元測試覆蓋（`test_non_vertical_ray_falls_back_to_reference_exactly`），因為兩個生產呼叫點目前都只送出固定 `(0,0,1)` ray。→ 此為刻意設計的安全網，即使未來被觸發也只是退化為呼叫 trimesh 原生實作，不會產生錯誤結果；不視為阻擋本次採用的風險。
- **[`DentalModel_1M.stl` 未能代表真正百萬面級 hollow mesh]**（非目前 blocker，降為未來 stress test 範圍）本輪的效能與正確性結論不涵蓋面數遠高於 ~63 萬的 hollow mesh；已驗證的 4 個代表模型涵蓋當前實際會遇到的面數範圍，且改善幅度在面數最高的 `DentalModel_1M.stl`（626,192 faces）上依然成立（69.4%），沒有隨面數上升而衰退的跡象。→ 真正百萬面級 hollow mesh 的 scaling 驗證，留待未來若取得更高面數的真實樣本時作為獨立 stress test 補充，不阻擋本次採用。

## Migration Plan

單一階段，可獨立驗證與獨立 commit：

| 階段 | 內容 | 回滾方式 |
|---|---|---|
| 0 | Baseline 重現與 A/B benchmark harness 建立（scratchpad，不落地） | — |
| 1 | `_hex_grid_vertical_ray_intersects_location()` 新增與 `generate_hex_grid()` 呼叫點替換（`agent/sla_operations.py`） | 單一 commit revert |

## Open Questions

以下兩項是刻意保留給未來的後續工作，非本次採用的前提條件——本輪判定皆不阻擋 prototype 採用：

- **若未來開放更小的 cell size（`hex_cell_radius`）為可調參數，是否需要預先建立分桶結構？** 目前一鍵 Auto Process 流程的 `hex_cell_radius`／`hex_grid_count` 皆為固定後端預設值，前端未暴露為可調參數，故 ray 數目前受限於這個固定設定與牙模本身有限的尺寸範圍。若未來產品需求開放更小 cell size（因而推高 ray 數），SHALL 在開放前重新 benchmark 確認 O(faces × rays) 的向量化比較是否仍然優於 r-tree，必要時再評估 design 中提到但本輪不採用的分桶方案。
- **是否需要找到/建立真正百萬面級的 hollow mesh 樣本作為 stress test？** 目前 4 個代表模型的 hollow mesh 都落在 35～63 萬面區間；`DentalModel_1M.stl` 雖然原始輸入達百萬面，hollow 後降到 62.6 萬面，未能驗證更高面數下的 scaling 行為。此為未來 stress test 的候選項目，若屆時取得更高面數的真實樣本再行補充驗證。
