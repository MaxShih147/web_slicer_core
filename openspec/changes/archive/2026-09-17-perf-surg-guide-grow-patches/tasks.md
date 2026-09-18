## 1. Phase 0：修改前基準

- [x] 1.1 自動搜尋 `C:\Users\user\Pictures\tempTest\SurgicalGuide*.stl`，記錄每個模型的 faces/verts（找到 4 個：`SurgicalGuide_1~4.stl`，非原先預期的 3 個）
- [x] 1.2 建立 scratchpad benchmark harness（`surg_guide_harness.py`），直接呼叫 `compute_auto_orientation_surg_guide_detail()`／`_find_guide_direction()`／`_weld_and_build()`／`_grow_patches()`／drill-candidate 篩選／concave-fallback 分支／最終方向計算，不透過前端或 HTTP
- [x] 1.3 每模型 warm-up ×1 + 正式 5 runs，`time.perf_counter()` 記錄 median wall time；另跑一次 cProfile 供分布參考（不計入正式 benchmark）
- [x] 1.4 建立 scratchpad 正確性快照 harness，記錄修改前的 patch 數量、`>=5` face patch 的 face membership/area/avg_normal/center、drill candidate membership、分支、最佳 patch、`res.dir`、`rotation_rad`（`snapshot_before.json`）

## 2. Phase 1：`_grow_patches()` per-patch statistics 優化

- [x] 2.1 全 repo 確認 `.area`／`.avg_normal`／`.center` 的所有讀取點皆已先檢查 `len(P.faces) < 5`（或等價條件）短路
- [x] 2.2 Step 5 改為只對 `len(P.faces) >= 5` 的 patch 計算統計；`<5` 的 patch 保留 dataclass 預設值
- [x] 2.3 面積計算改為索引 `mesh.face_area`（向量化），移除逐 face `_norm(_cross(...))` 重算
- [x] 2.4 移除 `max_angle_deg` 的計算迴圈；欄位定義保留在 `_Patch` dataclass
- [x] 2.5 確認未變更：fixed seed normal 語意、BFS assignment、adjacency 建立、vertex weld `eps=1e-4`、導孔判定 threshold、fallback/orientation 決策流程（僅 diff `_grow_patches()` 內 Step 5 區塊）

## 3. 驗證

- [x] 3.1 以相同模型/參數/環境/次數重新 benchmark（`benchmark_after.json`）
- [x] 3.2 重新建立正確性快照（`snapshot_after.json`），比對 patch face membership、drill candidates、分支、最佳 patch、`decision_faces`/`candidate_faces`、`res.dir`、`rotation_rad`
- [x] 3.3 列出 area/avg_normal/center 的最大浮點差異與原因（`mesh.face_area` 的向量化 reduction 精度路徑差異 + `numpy.sum` pairwise 累加順序差異）
- [x] 3.4 確認浮點差異未造成任何 gate/candidate/方向改變（4 模型 `rotation_rad` bit-exact 相同）
- [x] 3.5 新增 regression test（`agent/tests/test_auto_orient_surg_guide_grow_patches.py`，合成幾何，5 tests）
- [x] 3.6 執行 `pytest agent/tests/ -q --continue-on-collection-errors`，確認除新增測試外無新增失敗（670 passed vs. 既有基準 665 passed，既有 1 failed/3 errors 數字不變）
- [x] 3.7 執行 `openspec validate perf-surg-guide-grow-patches --strict`

## 4. 收尾

- [x] 4.1 design.md 補齊實際量測數字（4 模型 benchmark 表格、A/B 正確性比對結果）
- [x] 4.2 記錄剩餘瓶頸與下一輪候選範圍（Open Questions）

**本 change 範圍之外的後續工作**（BFS／PCA／scanline/concave vote/vertex weld 向量化）不屬於本提案的實作任務，記錄於 `design.md` 的 Non-Goals（第 16 行）與 Open Questions（第 103～105 行），依各自的後續 profiling 結果另立新的 change 處理；此後三輪（`perf-surg-guide-drill-patch-pca`／`perf-surg-guide-bfs-region-growing`／`perf-surg-guide-concave-chunking`）已依序落地其中的 PCA、BFS、concave vote 部分。
