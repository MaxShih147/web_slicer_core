## Why

`clean_input_for_manifold()` 在每次 `run_ortho_pipeline()` 都會無條件執行一次（位於 U-arch 判斷之前），其 boundary-edge scan（`np.unique(edges_sorted, axis=0, return_counts=True)` 後篩 `c == 1`）在既有 profiling 中佔該函式總時間的 44-57%（可影響時間約 0.04-2.17 秒），但下游其實只需要「occurrence count 恰為 1 的 edge 所包含的 vertex 集合」，不需要保留全部 unique edges 及其 occurrence counts——現行寫法為此多做了不必要的工作。經過兩輪調查（含 7 個代表模型的 A/B prototype、13+ 個 synthetic correctness case、ABBA 交錯的受控效能量測、trimesh/numpy 原始碼層級的記憶體分析、跨 trimesh 版本相容性驗證），已確認以 trimesh 既有公開 API `trimesh.grouping.group_rows(edges_sorted, require_count=1)` 取代該步驟，在維持完全相同輸出（`bd_verts` 值/dtype/順序、repair 觸發、stats、輸出 mesh）的前提下，可讓 scan 本身加速 9-11 倍、完整函式加速 1.6-1.85 倍，且不需要新增依賴或自行維護 bit-packed key／overflow guard。

## What Changes

- 將 `agent/ortho_pipeline.py::clean_input_for_manifold()` 中判定 boundary edge 的三行，從：
  ```python
  ue, c = np.unique(edges_sorted, axis=0, return_counts=True)
  bd_verts = np.unique(ue[c == 1])
  ```
  改為：
  ```python
  boundary_idx = trimesh.grouping.group_rows(edges_sorted, require_count=1)
  bd_verts = np.unique(edges_sorted[boundary_idx])
  ```
  最後一次 `np.unique()` SHALL 保留，以維持 `bd_verts` 升冪排序、去重且與現行版本逐位元組相同順序的不變式（`bd_verts` 順序會影響下游 KD-tree index、connected-component member 收集順序、代表 vertex 選擇與 remap）。
- 不改動 zero-area filtering、`merge_vertices()`、KD-tree weld、connected components、remap、face filtering、mesh rebuild、export，以及其他 Auto Process 階段。
- 新增範圍集中的 backend regression test，涵蓋 watertight closed、open boundary、duplicate/reversed-duplicate face、edge occurrence count 2/3/4+、degenerate/repeated-index face（含 `merge_vertices(digits_vertex=3)` 量化後才產生的 repeated-index／self-loop edge）、disconnected components、empty mesh/Scene 等情境，皆使用程式建立的小型 synthetic mesh，不依賴外部檔案。Reference 實作僅作為測試內的 oracle，不保留在 production path。

## Capabilities

### New Capabilities
（無）

### Modified Capabilities
- `auto-process-performance`：新增一條「純效能改動不得改變外部可觀察行為」系列下的 requirement，涵蓋 `clean_input_for_manifold()` boundary-edge scan 的實作替換，定義其專屬的等價判準（`bd_verts` 值/dtype/順序、repair 觸發、stats、輸出 mesh 一致）。既有四條 requirement（Hollow-fit repair 開關、Ortho cleaned mesh 重用、confirm-model-type 早退、Upload/save 驗證去重）不受影響。

## Impact

- **程式碼**：`agent/ortho_pipeline.py`（`clean_input_for_manifold()`，約 3 行變更 + import 調整）。
- **測試**：新增 1 個 targeted test file（暫定 `agent/tests/test_clean_input_boundary_scan.py`），不修改既有測試。
- **依賴**：無新增依賴；沿用既有 `trimesh>=4.0.0`（`trimesh.grouping.group_rows` 為公開 API，已在兩個實際可用版本 4.11.1 與 5.1.0 驗證行為一致；`>=4.0.0` 完整允許範圍未逐版驗證，正式實作只依賴 `group_rows(require_count=1)` 的公開正確性語意，不依賴特定版本細節）。
- **效能驗收**：透過 repo 外暫存 probe 人工驗證（`001_p.stl`／`DentalModel_1M.stl`／`Ushape1.stl`），不進入自動化 pytest gate。
- **不影響**：其他 Auto Process 階段（Hollow、Hex Grid、Boolean 等）、前端、C++/WASM/PrusaSlicer build、deployment dependency 版本鎖定。
