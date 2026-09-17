## 1. Phase 0：正式基準建立

- [x] 1.1 確認 working tree 與前次狀態一致，保留 `perf-surg-guide-grow-patches`／`perf-surg-guide-drill-patch-pca` 的既有修改與所有既有未提交項目
- [x] 1.2 自動搜尋 `C:\Users\user\Pictures\tempTest\SurgicalGuide*.stl`，確認 4 個模型
- [x] 1.3 以現行（Step 5 stats + PCA 皆已優化）程式碼為 baseline，建立 scratch benchmark/正確性 harness
- [x] 1.4 動態行為量測（`_norm`/`_dot` 呼叫次數、同一 patch 內重複比較規模、queue/frontier 大小分布——精確計數，非計時）；7 次交錯執行 benchmark（`time.perf_counter()` median，min/max/IQR 一併記錄）+ cProfile 歸因
- [x] 1.5 觀察到機器負載噪聲時，以多次獨立執行取最小值或改採交錯執行降低偏差
- [x] 1.6 建立正確性快照：逐 face 記錄修改前的 face membership、`patch_id` 陣列（含 `-2` 退化標記）、drill candidate membership、分支、最佳 patch、`res.dir`、`rotation_rad`

## 2. 實作：BFS region growing 向量化（A2）

- [x] 2.1 迴圈外預先以 `np.linalg.norm(mesh.face_n, axis=1)` 向量化算出全部 face 的法向量長度，取代迴圈內逐次呼叫 `_norm()`（design.md D3）
- [x] 2.2 inline dot product 維持與現行 `_dot()` 相同的 float32-until-the-end 精度（design.md D2）——seed 分量以 `numpy.float32` 純量取出（不透過 Python `float()`），逐項確認中間值 dtype
- [x] 2.3 確認未變更：fixed seed normal 比對語意、BFS assignment 語意、face/seed 遍歷順序、adjacency 建立方式、`cos_grow` 門檻數值、Step 5 per-patch statistics（本階段不重複觸碰）
- [x] 2.4 評估並否決 3 個候選方案（per-patch reject cache、float32 frontier batch、classifier-style float64），量測依據記錄於 design.md

## 3. A/B 正確性驗證

- [x] 3.1 以相同 4 模型重新建立正確性快照，逐 face 比對 patch membership 與 `patch_id` 陣列（含 `-2` 退化標記）——0 mismatches
- [x] 3.2 比較整體流程：drill candidate patch IDs、分支、decision faces/candidate faces、最佳 patch、`res.dir`、`rotation_rad`——全部相同
- [x] 3.3 確認 `SurgicalGuide_4.stl` 已識別出的 5 組 float32/float64 精度分歧候選，A2 的 inline dot 與現行 `_dot()` bit-exact、accept/reject 判定相同
- [x] 3.4 記錄浮點差異來源：本階段的 inline dot 與 `mesh.face_n_norms` 皆為 bit-exact（0 差異），因為 A2 的算術路徑刻意設計為與原實作等價，而非近似

## 4. Benchmark 與正式測試

- [x] 4.1 以相同 4 模型、相同環境 benchmark：`_grow_patches()`（BFS 子區段 + 整體）、`_find_guide_direction()`、`compute_auto_orientation_surg_guide_detail()`
- [x] 4.2 計算相對「Step5+PCA 皆已優化」（Round 2 結束版本）baseline 的增量改善（6.2%～9.2% 核心 Auto Orient，28%～35% BFS/`_grow_patches()`）
- [x] 4.3 累積改善數字（相對最原始版本，39.8%～42.3%）取自不同 session 的量測，已在 design.md 明確標註不可與本階段增量改善百分比相加
- [x] 4.4 新增正式 regression test `agent/tests/test_auto_orient_surg_guide_bfs_region_growing.py`（11 tests，合成幾何，涵蓋 dtype/精度等價性、fixed-seed 語意、shared-neighbor candidate、degenerate normal、2° threshold 兩側、小/大 patch、face-level 與 rotation 穩定性）
- [x] 4.5 執行 `pytest agent/tests/ -q --continue-on-collection-errors`：686 passed（675 既有基準 + 11 新增）、1 failed、3 errors——既有 failure/errors 數字未增加
- [x] 4.6 執行三個 OpenSpec change 的 `--strict` validation：`perf-surg-guide-bfs-region-growing`、`perf-surg-guide-grow-patches`（重新確認未受影響）、`perf-surg-guide-drill-patch-pca`（重新確認未受影響）

## 5. 收尾

- [x] 5.1 design.md 已補齊實際量測數字、A/B 正確性比對結果，取代原本的初步範圍界定量測段落
- [x] 5.2 記錄新的耗時分布與下一階段候選（`_Patch` 物件建構開銷、BFS 迴圈自身的 Python 遍歷/索引成本、`detect_concave_faces()`）於 design.md Open Questions

**本 change 範圍之外的後續工作**（`_Patch` 物件建構方式調整、BFS 迴圈結構本身的進一步優化、`detect_concave_faces()` 優化）不屬於本提案的實作任務，記錄於 `design.md` 的 Open Questions（第 144～148 行）；其中 `detect_concave_faces()` 已由後續的 `perf-surg-guide-concave-chunking` 落地，`_Patch` 物件建構方式與 BFS 迴圈結構本身的進一步優化仍待未來 profiling 決定是否處理。
