## 1. 實作

- [x] 1.1 修改 `agent/ortho_pipeline.py::clean_input_for_manifold()`：將 boundary-edge 判定改為 `trimesh.grouping.group_rows(edges_sorted, require_count=1)` + `bd_verts = np.unique(edges_sorted[boundary_idx])`，保留最後一次 `np.unique()`；不更動同函式內其餘步驟（zero-area filter、`merge_vertices()`、KD-tree weld、connected components、remap、face 過濾、mesh rebuild、export）。
- [x] 1.2 確認 import：沿用檔案既有風格（`trimesh` 已於檔案頂部 import；直接使用 `trimesh.grouping.group_rows`，因 `trimesh/__init__.py` 已 export `grouping`），不引入新依賴、不新增 import 行。

## 2. 正式測試（synthetic-only，不依賴 tempTest 目錄）

- [x] 2.1 新增 `agent/tests/test_clean_input_boundary_scan.py`：在測試檔內定義 reference oracle（逐字對應優化前的三行 `np.unique(axis=0)` 邏輯），僅存在於測試中，不落地為 production helper。
- [x] 2.2 測試以程式建立小型 synthetic mesh（write 成暫存 STL 後透過 `clean_input_for_manifold()` 端到端呼叫），覆蓋：watertight closed mesh、open boundary、duplicate face、reversed duplicate face、edge occurrence count 2、count 3、count 4+、degenerate／repeated-index face（輸入端直接給)、`merge_vertices(digits_vertex=3)` 後才形成的 repeated-index／self-loop、disconnected components、empty mesh／Scene、**weld_positive**（見 2.6）。
- [x] 2.3 每個 case 比較 reference 與新版：boundary vertices 的值／dtype／順序、`stats` dict、repair／weld 是否觸發、最終輸出 mesh 的 `vertices`／`faces`。測試只驗證正確性，不斷言 wall-clock 時間、加速倍率或第三方函式庫內部 scratch array。
- [x] 2.4 執行 `pytest agent/tests/test_clean_input_boundary_scan.py -v`，確認全數通過。
- [x] 2.5 執行既有 `agent/tests/` 相關子集（至少含既有 `test_ortho_clean_mesh_reuse.py`／`test_ortho_hollow_split_repair.py`）確認無 regression；記錄執行前後的 pass/fail 數字對照。
- [x] 2.6（收尾補強）新增 `_reference_boundary_edges()`／`_production_boundary_edges()` 兩個 oracle，直接比較 boundary-edge array 本身（值、dtype、shape、canonical lexicographic ordering），不再只比較攤平去重後的 `bd_verts`——避免 `edge_count_3`／`edge_count_4plus` 的過共用 edge 端點恰與其他真正 boundary edge 端點重合，使誤判也能巧合得到相同 `bd_verts` 而不被抓到。同時對 `edge_count_3`／`edge_count_4plus` 明確斷言其 occurrence count 陣列於 preprocessing 後確實含有 3／≥4，避免測資名稱與實際拓樸不符。
- [x] 2.7（收尾補強）新增 `weld_positive` synthetic case（兩個互不相連的開放三角形，其中一組頂點對距離 0.1 < `weld_tol=0.5` 且不會被 `merge_vertices(digits_vertex=3)` 提前合併），並在 end-to-end 測試中對此 case 額外斷言 `ref_stats["boundary_welded"] > 0` 與 `new_stats["boundary_welded"] == ref_stats["boundary_welded"]`——實測兩側皆為 `boundary_welded == 1`，確保先前所有 case 都只驗證到「兩側皆不觸發 weld」的問題已修正，真正走過 KD-tree pair／connected components／代表 vertex 選擇／remap／invalid-face 過濾／`Trimesh(process=True)` 重建全流程。

## 3. 效能驗收（人工，repo 外暫存 probe）

- [x] 3.1 在 repo 外暫存目錄建立探針腳本：複製（非 import）`clean_input_for_manifold()` 邏輯，reference／新版各自參數化，對 `001_p.stl`／`DentalModel_1M.stl`／`Ushape1.stl` 執行。
- [x] 3.2 採用 reference／新版各自 warm-up、ABBA 交錯順序、每組 5 次 measured runs、median-of-N；分別記錄 boundary scan 與完整 `clean_input_for_manifold()` 的中位數時間與加速比。
- [x] 3.3 確認三模型皆達成：boundary scan 加速 ≥5×（實測 9.48×–10.61×）、完整函式加速 ≥1.4×（實測 1.64×–1.93×），且 `bd_verts`／`stats`／輸出 mesh 與 reference 一致。
- [x] 3.4 驗收完成後刪除暫存探針腳本與輸出檔案，未留在 repo。

## 4. 收尾

- [x] 4.1 確認正式修改僅限於 `agent/ortho_pipeline.py`、新增的 targeted test file，以及 `openspec/changes/perf-clean-input-boundary-edge-scan/` 內的文件，未觸及其他 Auto Process 階段或無關檔案。
- [x] 4.2 彙整 diff、pytest 結果、三模型 benchmark 數字、`git status --short` 前後對照，回報尚未處理的 deployment Python 3.12／實際 trimesh 版本確認事項（已記錄於 design.md Open Questions；非本次實作阻斷項）。
