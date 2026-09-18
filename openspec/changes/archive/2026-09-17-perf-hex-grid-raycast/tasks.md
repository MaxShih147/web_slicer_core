## 1. Phase 0：Baseline 重現與 harness 建立

- [x] 1.1 確認 `.venv` 實際使用的 ray backend（`trimesh==4.11.1`，`has_embree=False`，未安裝 `embreex`／`pyembree`）
- [x] 1.2 用 `generate_hollow()`（真實 PrusaSlicer CLI，預設 `hollowing_quality=0.5`）為 `001_p.stl`／`005_p.stl`／`DentalModel_1M.stl`／`DentalModel_NeedRotate.stl` 產生真實 hollow mesh，記錄 input／hollow face count
- [x] 1.3 建立 scratchpad A/B benchmark harness（`single_run.py`／`driver.py`），以獨立 subprocess 執行每次量測，確保每次都是冷 mesh（不會誤用已建立的熱 r-tree cache）
- [x] 1.4 建立 scratchpad 逐位元組正確性比對腳本（`byte_for_byte_check.py`），monkeypatch 回 trimesh 原生 `intersects_location()` 取得參考基準

## 2. Phase 1：候選三角形搜尋（broad-phase）優化

- [x] 2.1 推導並確認：對於方向恰為 `(0, 0, 1)` 的 ray，trimesh r-tree query box 的 Z 軸範圍恆涵蓋整個 mesh 全域邊界，篩選條件等價於 XY bounding-box 重疊測試
- [x] 2.2 新增 `_hex_grid_vertical_ray_intersects_location()`（`agent/sla_operations.py`）：三角形分塊（`chunk_size=16384`）計算 XY bounding box，與 ray 的 `(x, y)` 座標（padded by `buffer_dist=1e-5`）做向量化重疊測試
- [x] 2.3 narrow-phase 逐行沿用 trimesh 4.11.1 `ray_triangle.ray_triangle_id()` / `RayMeshIntersector.intersects_id()` 的 plane intersection、barycentric 判定、epsilon、forward-distance 篩選、`multiple_hits=True`、重複 hit 去重
- [x] 2.4 非全部 `(0, 0, 1)` 方向的 ray 走 fallback，直接呼叫 `mesh.ray.intersects_location()`
- [x] 2.5 `generate_hex_grid()` 唯一一處 raycast 呼叫點改用新 helper；確認未變更 layout、ray origins/directions、cell height／`h_val < 1`、cell mesh assembly、drain holes、Boolean 流程

## 3. 正確性驗證

- [x] 3.1 新增合成幾何單元測試（`agent/tests/test_hex_grid_vertical_ray_intersect.py`，11 tests）：single/multi-hit、無 hit、共享邊界去重、垂直退化三角形、重複三角形、跨多 ray 的大三角形、chunk 邊界與 partial final chunk（chunk_size 1/3/8/16/100000）、非垂直 ray fallback 逐位元組相同、空三角形
- [x] 3.2 對 4 個真實代表模型執行「新版 vs. monkeypatch 回 trimesh 原生」的完整 `generate_hex_grid()`，確認最終 mesh 的 vertices／faces 逐位元組相同
- [x] 3.3 確認 `DentalModel_NeedRotate.stl` 新舊路徑結果一致
- [x] 3.4 執行 `pytest agent/tests/ -q --continue-on-collection-errors`，確認除新增測試外無新增失敗（710 passed vs. 既有基準 699 passed，既有 1 failed/3 errors 數字不變）

## 4. 效能驗證

- [x] 4.1 old/new interleaved 執行，每模型至少 5 次取 median：舊版 tree build/query、新版 xy_bbox/broadphase/narrowphase/hit_grouping、完整 `generate_hex_grid()`
- [x] 4.2 以 Windows `GetProcessMemoryInfo`（純 `ctypes`，未新增依賴）量測各獨立 subprocess 的 Peak Working Set
- [x] 4.3 確認 `DentalModel_1M.stl` hollow 後的實際 face count（626,192，非百萬面級），於 design.md 明確記載此限制
- [x] 4.4 確認 `001_p.stl`／`005_p.stl` 完整 `generate_hex_grid()` 改善幅度：001_p −70.4%/−922ms、005_p −72.9%/−773ms，達到「≥40% 或 ≥0.5 秒」採用門檻；其餘兩模型（−69.4%、−71.3%）無明顯退化

## 5. 收尾（初版 prototype）

- [x] 5.1 design.md 補齊實際量測數字（4 模型 benchmark 表格、正確性比對結果、記憶體量測）
- [x] 5.2 確認 production 程式碼中無殘留 temporary profiling code（所有量測腳本僅存在於 scratchpad）
- [x] 5.3 執行 `openspec validate perf-hex-grid-raycast --strict`（通過：`Change 'perf-hex-grid-raycast' is valid`）

## 6. 最終收尾（review、archive、commit）

- [x] 6.1 檢查 branch/HEAD/working tree/diff，確認本項只涉及 `agent/sla_operations.py`、`agent/tests/test_hex_grid_vertical_ray_intersect.py`、`openspec/changes/perf-hex-grid-raycast/`
- [x] 6.2 最終文字審閱：broad-phase 改為明確描述為原候選集合的「保守超集合」（允許 false positive、禁止 false negative），不宣稱候選集合完全相同；ray 數量問題記錄為非目前 blocker（一鍵處理 cell size 不可調、牙模尺寸範圍有限）；`DentalModel_1M.stl` 百萬面 hollow 限制降為未來 stress test，不阻擋本次採用；未來若開放更小 cell size 需重新 profiling
- [x] 6.3 確認 production 程式碼無殘留 temporary profiling／debug log／benchmark／記憶體量測程式（`git diff agent/sla_operations.py` 掃描確認）
- [x] 6.4 最終驗證：`pytest agent/tests/test_hex_grid_vertical_ray_intersect.py -q`（11 passed）、`pytest agent/tests/ -q --continue-on-collection-errors`（710 passed／1 failed／3 errors，與修改前基準相同，未修正無關的 `test_prz_print_time.py`／缺少 `httpx` 問題）、`openspec validate perf-hex-grid-raycast --strict`（通過）
- [ ] 6.5 使用 `openspec archive perf-hex-grid-raycast` 正式 archive，確認 `openspec/specs/hex-grid-raycast-performance/spec.md` 正確生成
- [ ] 6.6 Archive 後執行 `openspec validate hex-grid-raycast-performance --strict` 與 `openspec validate --all --strict`，確認除既有 `dental-model-classification` 既有 failure 外無新增問題（若有，記錄但不修改）
- [ ] 6.7 Final diff review，確認 archive 沒有產生非預期或無關變更
- [ ] 6.8 分兩個 commits：production+tests（`perf: optimize hex grid vertical raycast`）、openspec archive+正式 spec（`chore(openspec): archive perf-hex-grid-raycast`）
- [ ] 6.9 push 目前分支（不 force push）
