## Why

Surgical Guide Auto Orient 完成 Phase 1（`_grow_patches()` per-patch statistics 優化，見 `perf-surg-guide-grow-patches`）後，以 Phase 1 完成後的程式碼重新 profiling（真實模型 `SurgicalGuide_1.stl`）確認 `_is_drill_patch_by_edges()`（[agent/auto_orient_surg_guide.py:498](../../../agent/auto_orient_surg_guide.py#L498)）已成為目前最大的單一候選之一，cumulative time 約 1.3 秒。進一步拆解該函式的 7 個子階段（vertex set、orthonormal basis、PCA projection、covariance/eigen decomposition、diameter/aspect gate、scanline、turn-angle）確認：**PCA projection + covariance/eigen decomposition（含 vertex set 建立與 orthonormal basis）合計占該函式總時間的 73～82%**，其中單獨 covariance/eigen 一項就占 36～47%——遠高於 scanline（僅在少數通過 shape gate 的 patch 上執行）與 turn-angle（僅在通過 scanline 的 patch 上執行）。

`agent/model_classifier.py::_drill_is_drill_patch()`（[model_classifier.py:1780](../../../agent/model_classifier.py#L1780)）是同一段 C++（`isDrillPatchByEdges`）的另一份 1:1 port，其 PCA 投影／covariance 區段已完成完全相同性質的向量化優化（`2da36f1 perf(classifier): optimize drill hole detection`）並穩定運行於生產環境：逐 vertex 的 `project_to_plane()` 迴圈改為 `(K,3) @ (3,)` 批次矩陣運算，`np.cov()` 改為直接的 2×2 covariance dot-product 公式。這是本提案優化方向已被驗證安全的直接先例。

## What Changes

- **`_is_drill_patch_by_edges()` 的 PCA projection 改為批次矩陣運算**：`vids2d` 對應的頂點座標一次性透過 `(K,3) @ (3,)` 矩陣乘法投影到 patch 平面座標系，取代逐 vertex 呼叫 `project_to_plane()` 的 Python 迴圈。數值語意（雙精度運算、`ex`/`ey` 正交基底、`center` 平移）與原本逐 vertex 呼叫完全一致。
- **covariance 改為直接的 2×2 dot-product 公式**，取代 `np.cov(centered.T)`：`cxx/cxy/cyy` 以 `np.dot` 計算並除以 `N-1`（與 `np.cov` 預設 `ddof=1` 一致），避免 `np.cov` 的 broadcasting／中間物件開銷。
- **不變更**：函式的輸入／回傳契約、`_build_orthonormal_basis()` 規則與呼叫方式、`RING_OUTER_DIAM_MIN/MAX`／`RING_MAX_ASPECT` 等 threshold、`eigh` 的 eigenvalue/eigenvector 排序語意、long/short axis 判定（取 `extents.max()/min()`，不依賴 eigenvalue 排序）、early rejection 順序、`_patch_has_hole_by_scanlines()` 與 turn-angle chain walk 的呼叫方式與資料（`project_to_plane()` 函式本身保留，供 conn-edge bbox 與 turn-angle walk 沿用既有的逐 vertex 呼叫）、debug/candidate/decision face 資料、最終 orientation 流程。
- **本輪不處理**（留待下一輪視新 profiling 決定）：scanline rasterizer（`_patch_has_hole_by_scanlines()`）、BFS region growing、`detect_concave_faces()`、concave vote、fallback、vertex weld、adjacency、turn-angle chain walk 本身。

## Capabilities

### New Capabilities
- `surgical-guide-drill-patch-pca-performance`：定義 `_is_drill_patch_by_edges()` 的 PCA projection／covariance 向量化這項純效能改動必須維持的正確性契約（逐 patch 的 PCA 中間值、diameter/aspect gate 判定、drill candidate 集合、最終 orientation 等價）。

### Modified Capabilities
（無。本提案獨立於 `perf-surg-guide-grow-patches`，不修改該 change 涵蓋的 `_grow_patches()` per-patch statistics 契約，也不修改任何其他既有 capability 的 spec 層級行為。）

## Impact

- `agent/auto_orient_surg_guide.py`：`_is_drill_patch_by_edges()`（[:498-593](../../../agent/auto_orient_surg_guide.py#L498-L593) 範圍內的 PCA projection／covariance 區段）。
- 測試：新增 `agent/tests/test_auto_orient_surg_guide_drill_patch_pca.py`（regression，覆蓋本輪行為與 diameter/aspect gate 的正確性邊界）。
- 不觸及：scanline rasterizer、BFS、`detect_concave_faces()`、concave vote、fallback、vertex weld、adjacency、turn-angle chain walk——留待下一輪視 profiling 結果決定範圍，不在本提案預先承諾。
- 前置依賴：以 `perf-surg-guide-grow-patches`（Phase 1，尚未 commit）完成後的程式碼為 baseline；本提案不與最原始版本（Phase 1 之前）混合比較。
- 測試模型（唯讀，不納入 Git）：`C:\Users\user\Pictures\tempTest\SurgicalGuide_1.stl` ~ `SurgicalGuide_4.stl`（4 個模型，`SurgicalGuide_4.stl` 為刻意加入的第 4 個模型，非異常）。
