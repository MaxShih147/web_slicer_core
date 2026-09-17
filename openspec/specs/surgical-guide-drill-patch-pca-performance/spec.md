# surgical-guide-drill-patch-pca-performance Specification

## Purpose
TBD - created by archiving change perf-surg-guide-drill-patch-pca. Update Purpose after archive.
## Requirements
### Requirement: PCA projection／covariance 向量化不得改變外部可觀察行為

`_is_drill_patch_by_edges()`（`agent/auto_orient_surg_guide.py`）的 PCA projection（頂點投影到 patch 平面）與 covariance/eigen decomposition 向量化 SHALL 屬純效能／實作層級變更：以同一份輸入，改動前後該函式的回傳值（accept/reject）、`_find_guide_direction()` 與 `compute_auto_orientation_surg_guide_detail()` 的外部可觀察行為 SHALL 等價。

#### Scenario: 逐 patch 的 PCA 中間值與 gate 判定不受影響
- **WHEN** 以同一份輸入分別在修改前後對每個面數 `>=5` 的 patch 執行 PCA 投影與 covariance/eigen decomposition
- **THEN** 投影後的點雲 bounding range、covariance matrix、eigenvalues、`long_edge`／`short_edge`、aspect ratio SHALL 數值相等（或誤差在浮點路徑改變的合理範圍內）
- **AND** diameter/aspect gate 的通過/拒絕結果 SHALL 完全相同
- **AND** 是否進入 `_patch_has_hole_by_scanlines()`、scanline 判定結果、是否成為 drill candidate SHALL 完全相同

#### Scenario: 最終方向與 rotation 輸出不受影響
- **WHEN** 以同一份輸入分別在修改前後呼叫 `_find_guide_direction()` 與 `compute_auto_orientation_surg_guide_detail()`
- **THEN** drill candidate 集合、選中的分支（正常導孔判定 vs. fallback）、最佳 patch、`res.dir`、`rotation_rad` SHALL 完全相同

### Requirement: 向量化實作 SHALL 不改變 orthonormal basis 規則與呼叫方式

PCA projection 的向量化 SHALL 繼續使用 `_build_orthonormal_basis()` 產生的 `ex`／`ey`，計算方式（`center` 平移、雙精度運算）SHALL 與原本逐 vertex 的 `project_to_plane()` 語意一致。`project_to_plane()` 函式本身 SHALL 保留，供 conn-edge bbox 收集與 turn-angle chain walk 沿用既有的逐 vertex 呼叫方式，MUST NOT 因本項優化被移除或改變呼叫方式。

#### Scenario: conn-edge 與 turn-angle 呼叫方式不變
- **WHEN** `_is_drill_patch_by_edges()` 執行到 conn-edge bbox 收集或 turn-angle chain walk 階段
- **THEN** 這兩階段 SHALL 繼續呼叫既有的 `project_to_plane()` 函式，逐 vertex 計算投影座標，不受 PCA 區段向量化影響

### Requirement: covariance 計算 SHALL 與 np.cov 的預設語意數學等價

covariance 的直接 2×2 公式計算 SHALL 使用 `ddof=1`（除以 `N-1`），與 `np.cov()` 的預設行為一致；`np.linalg.eigh()` 的呼叫、其 eigenvalue 升冪排序語意、以及下游取 `long_edge`／`short_edge` 的方式（`extents.max()`／`extents.min()`，不依賴 eigenvalue 排序）SHALL 不變。

#### Scenario: 不再呼叫 np.cov
- **WHEN** `_is_drill_patch_by_edges()` 執行 PCA gate 區段
- **THEN** SHALL NOT 呼叫 `numpy.cov()`
- **AND** 計算出的 covariance matrix SHALL 與 `np.cov(centered.T)` 的結果數值相等（在浮點精度範圍內）

