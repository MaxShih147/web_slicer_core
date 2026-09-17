## 1. Phase 0：以 Phase 1 baseline 重新建立基準

- [x] 1.1 確認 working tree 與前次 Phase 1 回報一致，保留所有既有未提交項目
- [x] 1.2 自動搜尋 `C:\Users\user\Pictures\tempTest\SurgicalGuide*.stl`，確認 4 個模型（`SurgicalGuide_4.stl` 為刻意加入）
- [x] 1.3 建立/沿用 scratchpad benchmark harness，以 Phase 1 完成後的程式碼為 baseline
- [x] 1.4 將 `_is_drill_patch_by_edges()` 拆成子階段逐段計時：vertex set、orthonormal basis、PCA projection、covariance/eigen decomposition、diameter/aspect gate、scanline、turn-angle verification
- [x] 1.5 確認 1.3 秒主要來自 covariance/eigen decomposition（36～47%）與 PCA projection/vertex-set/orthonormal-basis（合計 73～82%），而非僅依賴 cumulative time 推測
- [x] 1.6 建立 scratchpad 正確性快照 harness，記錄修改前每個 `>=5`-face patch 的 PCA 中間值（pts2d range、covariance matrix、eigenvalues、long/short edge、aspect、gate 結果、scanline 結果、是否為 drill candidate）與整體流程結果

## 2. 實作：PCA projection／covariance 向量化

- [x] 2.1 逐行比較 `_is_drill_patch_by_edges()` 與 `model_classifier.py::_drill_is_drill_patch()`，只挑選與 PCA projection／covariance 數學語意等價的部分
- [x] 2.2 PCA projection 改為批次矩陣運算（`(K,3) @ (3,)`），取代逐 vertex 的 `project_to_plane()` 迴圈
- [x] 2.3 covariance 改為直接 2×2 dot-product 公式（`ddof=1`），取代 `np.cov()`
- [x] 2.4 確認未變更：輸入/回傳契約、orthonormal basis 規則、thresholds、eigenvector 排序語意、long/short axis 判定、early rejection 順序、scanline 與 turn-angle 呼叫方式、debug/candidate/decision face 資料、最終 orientation 流程
- [x] 2.5 確認 `project_to_plane()` 函式保留，供 conn-edge bbox 與 turn-angle chain walk 沿用

## 3. A/B 正確性驗證

- [x] 3.1 以相同 4 模型重新建立正確性快照，逐 patch 比較 face membership、pts2d range、covariance matrix、eigenvalues、long/short edge、aspect、diameter gate、scanline 是否執行、scanline 結果、是否為 drill candidate
- [x] 3.2 比較整體流程：drill candidate patch IDs、分支（正常導孔/fallback）、decision faces/candidate faces、最佳 patch、`res.dir`、`rotation_rad`
- [x] 3.3 確認全部 4 模型、所有比較項目 bit-exact 相同（無需 fallback 到「調整成等價」或「還原本輪修改」的分支）
- [x] 3.4 列出浮點差異來源分析（結果为 bit-exact，記錄為何未觀察到差異）

## 4. Benchmark 與測試

- [x] 4.1 以相同 4 模型、相同環境重新 benchmark：`_is_drill_patch_by_edges()`（改善 31～36%）、`_find_guide_direction()`（改善 7.3～9.4%）、`compute_auto_orientation_surg_guide_detail()`（改善 6.6～8.7%）
- [x] 4.2 計算相對 Phase 1 baseline 的增量改善（上述數字）
- [x] 4.3 計算相對最原始版本（Phase 1 之前）的累積改善（39.8～42.3%），並明確標註兩次量測分屬不同 script 執行，不可與增量改善百分比混用
- [x] 4.4 偵測到偶發背景負載尖峰後，改採多次獨立執行取最小值的方式抑制噪聲
- [x] 4.5 新增 regression test（`agent/tests/test_auto_orient_surg_guide_drill_patch_pca.py`，合成矩形 patch 幾何，5 tests）
- [x] 4.6 執行 `pytest agent/tests/ -q --continue-on-collection-errors`，確認除新增測試外無新增失敗（675 passed vs. 既有基準 670 passed，既有 1 failed/3 errors 數字不變）
- [x] 4.7 執行 `openspec validate perf-surg-guide-drill-patch-pca --strict`

## 5. 收尾

- [x] 5.1 design.md 補齊實際量測數字與 A/B 正確性比對結果
- [x] 5.2 記錄新的耗時分布與下一輪候選（`detect_concave_faces()`、BFS 部分）

**本 change 範圍之外的後續工作**（scanline rasterizer／BFS／concave detection／turn-angle chain walk 向量化）不屬於本提案的實作任務，記錄於 `design.md` 的 Non-Goals（第 14 行）與 Open Questions（第 109～111 行）；此後兩輪（`perf-surg-guide-bfs-region-growing`／`perf-surg-guide-concave-chunking`）已依序落地其中的 BFS、concave detection 部分，scanline rasterizer／turn-angle chain walk 目前仍待未來 profiling 決定是否處理。
