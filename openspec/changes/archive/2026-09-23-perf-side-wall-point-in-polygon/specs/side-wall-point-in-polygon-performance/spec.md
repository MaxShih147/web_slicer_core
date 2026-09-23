## ADDED Requirements

### Requirement: `point_in_polygon_2d()` 向量化實作 SHALL 與修改前 scalar 版本逐點結果完全一致

`point_in_polygon_2d()`（`agent/ortho_pipeline.py`）SHALL 保留函式簽章 `point_in_polygon_2d(poly: np.ndarray, px: float, py: float) -> bool` 與既有呼叫方式不變，內部實作 SHALL 以 NumPy 對 polygon 全部邊做 elementwise crossing/parity 判定，取代原本對每條邊逐一執行的 Python `for` 迴圈。對任意合法輸入（一般 convex/concave polygon、edge/vertex 邊界、horizontal/vertical edge、repeated vertex、zero-length edge、空 polygon、少於三點的 degenerate polygon），向量化版本回傳的布林值 SHALL 與修改前 scalar 版本逐點結果完全一致，不得使用 tolerance 或近似判準。

#### Scenario: 一般 polygon 的 parity 判定與 scalar 版本一致
- **WHEN** 對任意 convex 或 concave polygon 與任意 query point 呼叫 `point_in_polygon_2d()`
- **THEN** 回傳值 SHALL 與凍結的修改前 scalar 版本對同一輸入的回傳值完全相同

#### Scenario: polygon orientation 反轉不影響一致性
- **WHEN** 同一個 polygon 以順時針與逆時針兩種點序分別呼叫 `point_in_polygon_2d()`
- **THEN** 兩種點序下的回傳值 SHALL 分別與 scalar 版本對相同點序的回傳值一致

#### Scenario: query point 落於 edge 或 vertex 上的既有行為不變
- **WHEN** query point 恰好落在 polygon 的某條邊上，或恰好等於某個頂點座標
- **THEN** `point_in_polygon_2d()` 的回傳值 SHALL 與修改前 scalar 版本對相同輸入的回傳值完全相同（不因向量化而改變 point-on-boundary 語意）

#### Scenario: horizontal／vertical edge 的既有行為不變
- **WHEN** polygon 包含 horizontal edge（兩端點 y 座標相同）或 vertical edge（兩端點 x 座標相同）
- **THEN** `point_in_polygon_2d()` 對該 polygon 任意 query point 的回傳值 SHALL 與修改前 scalar 版本一致

#### Scenario: repeated vertex 或 zero-length edge 不影響一致性且不當機
- **WHEN** polygon 的點序中含有相鄰重複的頂點（即 zero-length edge）
- **THEN** `point_in_polygon_2d()` SHALL 正常回傳布林值、不拋出例外
- **AND** 回傳值 SHALL 與修改前 scalar 版本對相同輸入的回傳值一致

#### Scenario: 空 polygon 或少於三點的 degenerate polygon 回傳既有行為
- **WHEN** `poly` 為長度 0、1 或 2 的陣列
- **THEN** `point_in_polygon_2d()` SHALL 回傳與修改前 scalar 版本對相同輸入完全相同的布林值（不拋出例外）

### Requirement: 向量化實作 SHALL NOT 對不滿足 crossing 條件的邊產生除以零或新增 NumPy runtime warning

向量化實作在計算 x-intercept 時，SHALL 只對滿足 crossing 條件（`(yi > py) != (yj > py)`）的邊使用真實除數；對不滿足該條件的邊（含 horizontal edge，其 `yi == yj` 恆不滿足 crossing 條件），SHALL 以結構性方式（例如遮罩替換除數）避免計算出真正的 `0/0` 或無效除法，而非僅用 `np.errstate` 事後壓制警告輸出。正常輸入下呼叫 `point_in_polygon_2d()` SHALL NOT 產生任何新增的 NumPy `RuntimeWarning`（`divide by zero encountered` 或 `invalid value encountered`）。

#### Scenario: horizontal edge 不觸發除以零
- **WHEN** polygon 包含至少一條 horizontal edge，且以任意 query point 呼叫 `point_in_polygon_2d()`
- **THEN** 呼叫過程 SHALL NOT 產生 NumPy 的 `RuntimeWarning`（`divide by zero encountered` 或 `invalid value encountered`）

#### Scenario: 正常與隨機壓力輸入下無新增 warning
- **WHEN** 在 `warnings.simplefilter("error")` 的環境下，對正常 polygon／query 輸入與固定 seed 產生的大量隨機 polygon／query 輸入重複呼叫 `point_in_polygon_2d()`
- **THEN** SHALL NOT 有任何呼叫拋出 warning-as-error 例外

### Requirement: 向量化實作 SHALL NOT 改變 dtype 或引入跨呼叫狀態

`point_in_polygon_2d()` SHALL NOT 對輸入的 `poly` 陣列做 dtype 強制轉換（尤其 SHALL NOT 降為 `float32`），輸入陣列的 dtype 在呼叫前後 SHALL 保持不變。實作 SHALL NOT 使用任何全域變數、模組層級快取，或跨呼叫保存的狀態；每次呼叫 SHALL 是獨立、無副作用的純函式呼叫。

#### Scenario: 輸入陣列 dtype 不被修改
- **WHEN** 以 `dtype=float64` 的 `poly` 陣列呼叫 `point_in_polygon_2d()`
- **THEN** 呼叫前後 `poly.dtype` SHALL 保持為 `float64`

#### Scenario: float64 精度不得因內部 downcast 而遺失
- **WHEN** 以 `float64` polygon 呼叫 `point_in_polygon_2d()`，且 polygon 包含在 `float64` 中可區分、但降為 `float32` 後會塌陷的座標差異
- **THEN** 回傳結果 SHALL 與修改前 scalar reference 使用原始 `float64` 輸入的結果完全一致
- **AND** 實作 SHALL NOT 因內部降為 `float32` 而改變判定結果

### Requirement: `generate_side_wall_drains()` 下游輸出 SHALL 維持 array-exact 等價

以完全相同的 in-memory `outer_shell`／`inner_shell`／參數，分別使用修改前（scalar）與修改後（向量化）的 `point_in_polygon_2d()` 執行 `generate_side_wall_drains()`，兩者的候選評估過程（每次呼叫的 query point 與布林結果、每個 candidate 的 normal flipped 結果、accepted／rejected 結果、skip reasons、hole 數量與順序）SHALL 完全一致；非 `None` 的回傳 mesh，其 `.vertices`／`.faces` SHALL `np.array_equal`。

#### Scenario: 真實模型端到端 array-exact
- **WHEN** 對同一個真實模型（真實 PrusaSlicer CLI hollow 輸出，經 Step 2 extend_bottom_vertices／Step 3 align hollow to input，未經 STL round-trip），分別以修改前後的 `point_in_polygon_2d()` 執行 `generate_side_wall_drains()`
- **THEN** 兩次執行的 PIP 呼叫次數 SHALL 相同
- **AND** 每次呼叫的 query point 與布林結果 SHALL 逐次相同
- **AND** skip reasons（`no_bin`／`no_inner_hit`／`too_close`）與 hole 數量 SHALL 相同
- **AND** 回傳 mesh 的 `.vertices`／`.faces` SHALL `np.array_equal`
