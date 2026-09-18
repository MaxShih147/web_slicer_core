## Why

Surgical Guide Auto Orient 已完成兩輪效能優化（`perf-surg-guide-grow-patches`：`_grow_patches()` per-patch statistics；`perf-surg-guide-drill-patch-pca`：`_is_drill_patch_by_edges()` PCA projection/covariance；兩者皆尚未 commit）。以目前（兩輪疊加後）的程式碼重新 profiling 確認：`_grow_patches()`（[agent/auto_orient_surg_guide.py:289](../../../agent/auto_orient_surg_guide.py#L289)）中，per-patch statistics（Step 5）已優化到僅占極小比例，**BFS region growing（Step 4）現在是 `_grow_patches()` 內部剩下的主要成本**——以現行程式碼重複量測（見 `design.md` Context 段的 4 次獨立執行數據），排除量測噪聲後，BFS 占 `_grow_patches()` 總時間約 76～92%。

`perf-surg-guide-grow-patches` 的 design.md 曾在 Non-Goals 中提及「BFS region growing 本身的向量化」、`perf-surg-guide-drill-patch-pca` 的 Open Questions 也提過「`_grow_patches()` 的 BFS 部分」——但**兩者都只是排除範圍或待辦提示，並未對 BFS 做過任何正式的階段拆解、根因分析、正確性邊界界定或量化 profiling**，不構成本輪的規劃或驗收依據。本提案是針對 BFS 的第一份正式規劃文件。

`agent/model_classifier.py::_drill_region_growing()`（[model_classifier.py:1583](../../../agent/model_classifier.py#L1583)）是同一段 C++ 的另一份 1:1 port，已完成部分性質相近的優化：BFS 迴圈外預先以 `np.linalg.norm(face_n, axis=1)` 向量化算出所有 face 的法向量長度，取代逐次呼叫 `_norm()`；並將 seed 法向量分量抽成純量 `sx/sy/sz`，把 `_dot()` 的呼叫改為 inline 乘加。但**兩份程式碼在這個 inline dot product 上潛在的浮點精度路徑不同**（見 `design.md` D2 的分析）——這是本提案不能直接照搬 classifier 寫法、必須額外處理的正確性風險，也是本提案與前兩輪「直接移植 classifier 已驗證實作」性質不同之處。

## What Changes

- **BFS region growing（`_grow_patches()` Step 4）動態行為調查與 Phase 0 基準已完成**：以現行（兩輪優化後）程式碼建立正式基準，量化 BFS 佔比、`_norm`/`_dot` 呼叫次數、同一 patch 內重複比較規模、frontier/queue 大小分布。
- **已在 scratch 中比較 5 種候選方案，正式採用其中 1 種（A2）**：
  - **A2（已採用，production 已落地）**：(1) 迴圈外預先以向量化 `np.linalg.norm(mesh.face_n, axis=1)` 算出全部 face 的法向量長度，取代 BFS 內對每個候選 face 逐次呼叫 `_norm()` 做退化法向量檢查；(2) 將 patch 的 seed 法向量分量抽成 `numpy.float32` 純量後，以 inline 乘加取代 `_dot(n, n_seed)` 呼叫——**分量抽取與乘加運算維持與現行 `_dot()` 相同的 float32 精度路徑**，不透過 Python `float()` 抽取分量（那會把運算精度從 float32 全程運算改變為 upcast 到 float64）。
  - **per-patch reject cache（已評估，不採用）**：實測同一 patch 內重複比較僅占 unique 配對的 ~1%，加入 cache 反而更慢。
  - **float32 frontier batch（已評估，不採用）**：BFS queue 大小中位數為 1，批次向量化開銷使其比 Reference 慢 3～5 倍。
  - **classifier-style 全 float64（已評估，不採用）**：在 `SurgicalGuide_4.stl` 上找到 5 個真實的 accept/reject 翻轉案例，證實存在真實正確性風險，即使這次未影響最終分組結果。
- **不變更（已驗證，非規劃）**：fixed seed normal 的比對語意、BFS 的 assignment 語意、face/seed 遍歷順序、adjacency 建立方式（`_weld_and_build()`）、vertex weld `eps=1e-4`、非流型 edge 處理、`cos_grow`（2° 門檻）本身的數值、`_Patch` 物件的建構與欄位語意、Step 5 per-patch statistics（已由 `perf-surg-guide-grow-patches` 處理，本階段不重複觸碰）。

**本階段完成 = BFS region growing 這一個效能候選完成規劃、實作、驗證與收斂；不代表 Surgical Guide Auto Orient 整體效能優化已經結束。** `_Patch` 物件建構開銷、BFS 迴圈自身的 Python 遍歷/索引成本、`detect_concave_faces()` 等仍是尚未處理的候選，留給後續視新的 profiling 決定（見 `design.md` Open Questions）。

## Capabilities

### New Capabilities
- `surgical-guide-bfs-region-growing-performance`：定義 `_grow_patches()` BFS region growing（Step 4）向量化這項純效能改動必須維持的正確性契約（patch 分組結果、`cos_grow` 門檻比較的精度等價性、最終 drill candidate 與 orientation 結果等價）。

### Modified Capabilities
（無。本提案獨立於 `perf-surg-guide-grow-patches`（Step 5 per-patch statistics）與 `perf-surg-guide-drill-patch-pca`（`_is_drill_patch_by_edges()` PCA），三者互不重疊、可各自獨立 commit；不修改任何既有 capability 的 spec 層級行為。）

## Impact

- `agent/auto_orient_surg_guide.py`：`_grow_patches()` 的 BFS 區段（Step 4）——已修改。相對 Round 2（PCA）結束版本的獨立 patch：**+16 / −4 行**（淨增 12 行；經 `git diff --no-index --numstat` 對照重建的 pre-A2 檔案內容精確量測，不是估計值）。Step 5 per-patch statistics、`_is_drill_patch_by_edges()` 的 PCA 區段、其餘所有函式完全未變動。
- 測試：新增 `agent/tests/test_auto_orient_surg_guide_bfs_region_growing.py`（regression，覆蓋 dtype/精度等價性、fixed-seed 語意、shared-neighbor candidate、face-level assignment 穩定性、最終 orientation 穩定性）。前兩輪既有測試保留、未被覆蓋或合併。
- 不觸及：Step 5 per-patch statistics（`perf-surg-guide-grow-patches` 已處理）、`_is_drill_patch_by_edges()`（`perf-surg-guide-drill-patch-pca` 已處理）、scanline、`detect_concave_faces()`、concave vote、fallback、vertex weld、adjacency 建立本身。
- 測試模型（唯讀，不納入 Git）：`C:\Users\user\Pictures\tempTest\SurgicalGuide_1.stl` ~ `SurgicalGuide_4.stl`。

## Non-Goals（本階段完成範圍，已確認）

見 `design.md` 的完整 Non-Goals 清單（含已評估但不採用的 3 個候選方案及其量測依據）。摘要：per-patch reject cache、float32 frontier batch、classifier-style 全 float64、`_Patch` 建構方式變更、BFS 迴圈結構重寫、`_weld_and_build()`／`detect_concave_faces()` 等其他函式——皆不在本階段範圍。
