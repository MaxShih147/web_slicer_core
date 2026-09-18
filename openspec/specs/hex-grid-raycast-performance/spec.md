# hex-grid-raycast-performance Specification

## Purpose

定義 `generate_hex_grid()`（`agent/sla_operations.py`，Ortho pipeline Step 4）對 hollow mesh 的固定垂直 ray raycast，其候選三角形搜尋（broad-phase）改為向量化 XY bounding-box 重疊測試（取代 trimesh 預設的通用 3D r-tree）時必須維持的正確性契約：候選集合對原 r-tree 結果 SHALL 為保守超集合（允許 false positive、禁止 false negative）、narrow-phase 與最終 hit 結果 SHALL 與 trimesh 既有實作等價、非固定垂直 ray 的 fallback 行為，以及最終 Hex Grid 幾何輸出的 byte-for-byte 等價判準。

## Requirements
### Requirement: 固定垂直 ray 的 broad-phase 優化不得改變外部可觀察行為

`generate_hex_grid()`（`agent/sla_operations.py`）對 hollow mesh 的 raycast，其候選三角形搜尋（broad-phase）SHALL 屬純效能／實作層級變更：以同一份 hollow mesh、同一組 ray origins/directions，改動前後 `generate_hex_grid()` 的最終輸出 SHALL 逐位元組相同——與本 repo 其他 mesh／Boolean 相關效能能力（例如 `auto-process-performance`）不同，本能力的候選三角形搜尋改動不涉及 Boolean 中間表示法或 triangle re-ordering，因此驗收線 SHALL 以「輸出 mesh 的 vertices／faces 陣列 byte-for-byte 相同」表達，而非幾何語意等價。

#### Scenario: 最終 Hex Grid mesh byte-for-byte 相同
- **WHEN** 以同一份已完成 hollow 與座標對齊的 mesh，分別使用改動前的 `mesh.ray.intersects_location()` 與改動後的候選三角形搜尋執行 `generate_hex_grid()`
- **THEN** 兩者回傳的 mesh 的 `.vertices` 陣列 SHALL 逐位元組相同
- **AND** 兩者回傳的 mesh 的 `.faces` 陣列 SHALL 逐位元組相同

#### Scenario: 每條 ray 的 hit/miss 與最高 Z 相同
- **WHEN** 對同一組固定 `(0, 0, 1)` 方向的 ray 分別以改動前後的路徑求交
- **THEN** 每條 ray 的 hit/miss 狀態（是否存在至少一個交點）SHALL 相同
- **AND** 有交點的 ray，其所有交點中最高 Z 值 SHALL 相同（誤差在浮點運算的捨入範圍內，且不得造成 `h_val < 1` 篩選結果改變）

### Requirement: 候選三角形搜尋 SHALL NOT 產生 false negative

新的候選三角形搜尋（向量化 XY bounding-box 重疊測試）SHALL 是 trimesh 預設 r-tree broad-phase 候選集合的超集合：任何會被 trimesh 原生 `RayMeshIntersector` 選為候選的 `(triangle, ray)` pair，SHALL 也被新搜尋選為候選。新搜尋 MAY 選出額外的候選（false positive），但這些額外候選 SHALL 在 narrow-phase 被正確排除，不得影響最終 hit 結果。

此不變式建立在「所有 ray 方向恰為 `(0, 0, 1)`」的前提上：此時 trimesh r-tree query box 的 Z 軸範圍恆涵蓋整個 mesh 的全域 Z 邊界，故 Z 軸從未實際發揮篩選作用，候選篩選條件在數學上等價於 XY 平面上的 bounding-box 重疊測試。

#### Scenario: XY bounding-box 重疊測試涵蓋所有真實命中
- **WHEN** 某三角形與某條垂直 ray 存在真實的幾何交點
- **THEN** 該三角形的 XY 投影 bounding box（padded by `buffer_dist=1e-5`）SHALL 包含該 ray 的 `(x, y)` 原點座標
- **AND** 該 `(triangle, ray)` pair SHALL 出現在候選集合中

#### Scenario: 分塊處理不遺漏任何三角形
- **WHEN** 三角形總數不是 `chunk_size` 的整數倍（partial final chunk），或候選三角形跨越多個 chunk 邊界
- **THEN** 每個三角形 SHALL 恰好被檢查一次（依其全域索引所在的 chunk），不因分塊而被遺漏或重複計入

### Requirement: Narrow-phase SHALL 與 trimesh 既有實作等價

候選三角形的精確求交（narrow-phase）SHALL 直接呼叫 trimesh 既有的 plane intersection（`trimesh.intersections.planes_lines`）與 barycentric 座標判定（`trimesh.triangles.points_to_barycentric`）函式，使用與 trimesh `ray_triangle.ray_triangle_id()` 相同的 epsilon（`trimesh.constants.tol.zero`）、forward-distance 篩選閾值（`-1e-6`）、`multiple_hits=True` 語意，以及 `trimesh.grouping.unique_rows` 的重複 hit 去重規則。MUST NOT 自行改寫為不同精度或不同判定公式的等價實作。

#### Scenario: 共享邊界的重複 hit 去重行為相同
- **WHEN** 一條 ray 精確命中兩個三角形的共享邊界（例如四邊形被拆成兩個三角形的對角線）
- **THEN** 去重後的 hit 數量與位置 SHALL 與 trimesh 原生 `intersects_location()` 的結果相同

#### Scenario: 退化與非流形三角形的處理相同
- **WHEN** mesh 包含法向量與 ray 方向平行的退化三角形（例如垂直於水平面的三角形），或包含重複三角形
- **THEN** 這些三角形對最終 hit 結果的影響 SHALL 與 trimesh 原生實作完全相同

### Requirement: 非固定垂直 ray 的 fallback

候選三角形搜尋函式 SHALL 只在全部 ray 方向恰為 `(0, 0, 1)` 時使用向量化 XY bounding-box 搜尋；若任一 ray 的方向不是 `(0, 0, 1)`，SHALL 直接呼叫 `mesh.ray.intersects_location()` 並原樣回傳其結果，MUST NOT 嘗試對非垂直 ray 套用同一套 XY 重疊邏輯。

#### Scenario: 非垂直 ray 回傳與 trimesh 原生實作逐位元組相同的結果
- **WHEN** 呼叫此函式時，ray directions 陣列包含至少一個不等於 `(0, 0, 1)` 的方向
- **THEN** 回傳的 `locations`／`index_ray`／`index_tri` 陣列 SHALL 與直接呼叫 `mesh.ray.intersects_location()` 逐位元組相同

