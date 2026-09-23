## ADDED Requirements

### Requirement: `_ray_polygon_nearest_hit_t()` 向量化實作 SHALL 與逐邊呼叫 `ray_seg_intersect_2d()` 的 scalar 組合結果完全一致

`_ray_polygon_nearest_hit_t()`（`agent/ortho_pipeline.py`）SHALL 對單一 ray（origin `ox`/`oy`、direction `dx`/`dy`）與一組預先計算好的 polygon 邊陣列（`ax`/`ay` 邊起點、`ex`/`ey` 邊向量）一次性以 NumPy 計算 `denom`/`t`/`u`，取代逐邊呼叫既有 `ray_seg_intersect_2d()` 並套用 `t > 0.01 and t < best_t` 篩選出最近正向 hit 的 Python `for` 迴圈。`ray_seg_intersect_2d()` 本身 SHALL 保持不變。對任意合法輸入，向量化版本回傳的 `best_t`（或 `None`）SHALL 與「逐邊呼叫 `ray_seg_intersect_2d()`、僅保留 `t > 0.01`、以嚴格 `t < best_t` 取最小值」這個 scalar 組合的結果完全一致，不得使用 tolerance 或近似判準。

#### Scenario: 一般單一 hit 與 scalar 組合一致
- **WHEN** 對任意 polygon 與任意 ray 呼叫 `_ray_polygon_nearest_hit_t()`，且僅一條邊產生合格 hit
- **THEN** 回傳的 `best_t` SHALL 與 scalar 組合對同一輸入的結果完全相同

#### Scenario: 多重 hit 時選擇最近者
- **WHEN** ray 與 polygon 的多條邊都產生合格 hit
- **THEN** 回傳的 `best_t` SHALL 是這些合格 hit 中數值最小者，與 scalar 組合的結果完全相同

#### Scenario: 無合格 hit 時回傳 `None`
- **WHEN** ray 與 polygon 的任何邊都沒有產生合格 hit（例如 ray 指向背離 polygon 的方向）
- **THEN** `_ray_polygon_nearest_hit_t()` SHALL 回傳 `None`，與 scalar 組合的結果一致

### Requirement: 邊界與退化輸入 SHALL 保持既有 scalar 語意

`_ray_polygon_nearest_hit_t()` 對下列邊界情況的行為 SHALL 與 scalar 組合（逐邊呼叫 `ray_seg_intersect_2d()`）完全一致：`abs(denom) < 1e-12`（含 parallel edge、collinear edge、zero-length edge）視為無交點；`u` 的合格範圍為含端點的 `0 <= u <= 1`（`u=0`、`u=1` 皆合格）；`t` 必須嚴格大於 `0.01`（`t=0`、`t=0.01` 皆被拒絕，僅 `t` 嚴格大於 `0.01` 才合格）；多條邊在數值上產生完全相同的最小 `t` 時，回傳值 SHALL 與 scalar 組合的結果相同（scalar 組合僅保留 `best_t` 數值本身，未對外暴露 tie-break 選中的 edge index，故此處以數值相等為判準）。空 polygon 或邊陣列長度不足時，SHALL 回傳 `None`，不得對空陣列呼叫 `np.argmin()` 或其他會在空輸入上拋出例外的操作。

#### Scenario: `abs(denom)` 低於、等於、高於 `1e-12` 的既有行為
- **WHEN** 以固定的 ray 與經過設計、`abs(denom)` 分別略小於、恰等於、略大於 `1e-12` 的單一邊呼叫 `_ray_polygon_nearest_hit_t()`
- **THEN** `abs(denom) < 1e-12` 時 SHALL 視為無交點
- **AND** `abs(denom) >= 1e-12` 時 SHALL 依 `t`/`u` 條件正常判定，與 scalar 組合結果一致

#### Scenario: segment endpoint（`u=0`／`u=1`）視為合格
- **WHEN** ray 恰好命中 segment 的其中一個端點（`u=0` 或 `u=1`）
- **THEN** 該 hit SHALL 被視為合格，與 scalar 組合結果一致

#### Scenario: `t` 邊界嚴格性
- **WHEN** 某條邊的交點 `t` 恰為 `0`、恰為 `0.01`，或恰略大於 `0.01`
- **THEN** `t=0` 與 `t=0.01` SHALL 被拒絕
- **AND** 略大於 `0.01` 的 `t` SHALL 被接受（若為最小合格值）

#### Scenario: 空或退化 polygon 不觸發例外
- **WHEN** 傳入長度為 0 或邊陣列全部無效（例如全部 `abs(denom) < 1e-12`）的 polygon
- **THEN** `_ray_polygon_nearest_hit_t()` SHALL 回傳 `None`，不得拋出例外

### Requirement: 向量化實作 SHALL NOT 對無效 edge 產生除以零或新增 NumPy runtime warning

`_ray_polygon_nearest_hit_t()` 在計算 `t`/`u` 時，SHALL 只對 `abs(denom) >= 1e-12` 的邊使用真實除數；對不滿足此條件的邊，SHALL 以結構性方式（例如遮罩替換除數）避免計算出真正的 `0/0` 或無效除法，而非僅用 `np.errstate` 事後壓制警告輸出。正常輸入下呼叫 `_ray_polygon_nearest_hit_t()` SHALL NOT 產生任何新增的 NumPy `RuntimeWarning`（`divide by zero encountered` 或 `invalid value encountered`）。

#### Scenario: parallel/collinear/zero-length edge 不觸發除以零
- **WHEN** polygon 包含至少一條 parallel、collinear 或 zero-length 的邊，且以任意 ray 呼叫 `_ray_polygon_nearest_hit_t()`
- **THEN** 呼叫過程 SHALL NOT 產生 NumPy 的 `RuntimeWarning`

#### Scenario: 正常與隨機壓力輸入下無新增 warning
- **WHEN** 在 `warnings.simplefilter("error")` 的環境下，對正常與固定 seed 產生的大量隨機 polygon／ray 輸入重複呼叫 `_ray_polygon_nearest_hit_t()`
- **THEN** SHALL NOT 有任何呼叫拋出 warning-as-error 例外

### Requirement: 向量化實作 SHALL NOT 改變 dtype 或引入跨呼叫狀態

`_ray_polygon_nearest_hit_t()` SHALL NOT 對輸入的邊陣列做 dtype 強制轉換（尤其 SHALL NOT 降為 `float32`）。實作 SHALL NOT 使用任何全域變數、模組層級快取，或跨呼叫保存的狀態；每次呼叫 SHALL 是獨立、無副作用的純函式呼叫。`generate_side_wall_drains()` 對 `inner_poly` 邊陣列（`ax`/`ay`/`ex`/`ey`）的預計算 SHALL 只在單次呼叫內建立一次並重複使用，SHALL NOT 跨越 `generate_side_wall_drains()` 的多次呼叫持有。

#### Scenario: float64 精度不得因內部 downcast 而遺失
- **WHEN** 以 `float64` 邊陣列呼叫 `_ray_polygon_nearest_hit_t()`，且輸入包含在 `float64` 中可區分、但降為 `float32` 後會塌陷的座標差異
- **THEN** 回傳結果 SHALL 與 scalar 組合使用原始 `float64` 輸入的結果完全一致
- **AND** 實作 SHALL NOT 因內部降為 `float32` 而改變判定結果

### Requirement: `generate_side_wall_drains()` 下游輸出 SHALL 維持 array-exact 等價

以完全相同的 in-memory `outer_shell`／`inner_shell`／參數，分別使用修改前（inner-poly ray scalar 迴圈）與修改後（`_ray_polygon_nearest_hit_t()` 向量化）執行 `generate_side_wall_drains()`，兩者的候選評估過程（每次 ray 查詢的結果、每個 candidate 的 accepted／rejected 結果、skip reasons、hole 數量與順序）SHALL 完全一致；非 `None` 的回傳 mesh，其 `.vertices`／`.faces` SHALL `np.array_equal`。

#### Scenario: 真實模型端到端 array-exact
- **WHEN** 對同一個真實模型（真實 PrusaSlicer CLI hollow 輸出，經 Step 2 extend_bottom_vertices／Step 3 align hollow to input，未經 STL round-trip），分別以修改前後的 ray 查詢實作執行 `generate_side_wall_drains()`
- **THEN** 兩次執行的 ray 查詢次數 SHALL 相同
- **AND** 每次查詢的結果 SHALL 逐次相同
- **AND** skip reasons（`no_bin`／`no_inner_hit`／`too_close`）與 hole 數量 SHALL 相同
- **AND** 回傳 mesh 的 `.vertices`／`.faces` SHALL `np.array_equal`
