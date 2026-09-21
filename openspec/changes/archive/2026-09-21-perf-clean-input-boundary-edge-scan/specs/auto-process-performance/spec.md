## ADDED Requirements

### Requirement: clean_input_for_manifold() boundary-edge 判定優化不得改變分類、repair 與輸出

`clean_input_for_manifold()` 以 `trimesh.grouping.group_rows(edges_sorted, require_count=1)` 取代 `np.unique(edges_sorted, axis=0, return_counts=True)` 判定 boundary edge 時，SHALL 只改變「哪些 edge 出現次數恰為 1」的計算方式，MUST NOT 改變分類結果、repair（KD-tree weld）是否觸發、weld 結果、`stats` 內容或最終輸出 mesh。

只有 occurrence count 恰好等於 1 的 edge SHALL 被視為 boundary edge；occurrence count 為 2、3 或更多次的 edge 的分類 SHALL 與現行版本完全一致。`mesh.edges_sorted` 的無向 edge 語意（每列已依端點排序）MUST NOT 被改變。

最終 `bd_verts` SHALL 保留現行版本呼叫 `np.unique()` 的行為（即候選演算法找出 boundary edge 之後，仍須再對攤平後的頂點集合呼叫一次 `np.unique()`），以維持與現行版本完全相同的頂點集合、dtype、升冪排序與元素順序——`bd_verts` 的順序會影響下游 KD-tree pair index、connected-component member 收集順序、每個連通分量代表 vertex 的選擇與 remap 結果，因此順序不一致 SHALL 視為不可接受的行為改變。

Duplicate face（相同 winding）、reversed duplicate face（相反 winding）與 occurrence count ≥3 的 non-manifold edge，SHALL 不被誤判為 boundary edge。`merge_vertices(digits_vertex=3)` 量化後才產生的 repeated-index face／`(v, v)` self-loop edge（zero-area 過濾只在 `merge_vertices()` 之前執行一次，不會二次過濾此類退化 face），其既有分類行為（包含被歸類為 boundary 的既有邊界情況）SHALL 維持不變，不因本次優化而被連帶修正。

Empty mesh 或 `trimesh.load()` 對空/退化 STL 回傳 `Scene` 的既有分支行為 SHALL 維持不變。

#### Scenario: occurrence count 恰為 1 才是 boundary edge
- **WHEN** 對同一份經 zero-area 過濾與 `merge_vertices(digits_vertex=3)` 處理後的 mesh，分別以現行版本（`np.unique(axis=0)` + count 篩選）與新版本（`group_rows(require_count=1)`）計算 `bd_verts`
- **THEN** 兩者回傳的 `bd_verts` 值、dtype 與元素順序 SHALL 完全相等
- **AND** 此結果 SHALL 對 watertight closed mesh、open boundary mesh、edge occurrence count 恰為 2／3／4 以上的 mesh 均成立

#### Scenario: boundary-edge 集合本身（非僅攤平後的頂點集合）逐一相等
- **WHEN** mesh 中存在 occurrence count ≥3 的 edge，且該 edge 的端點同時也是其他真正 boundary edge 的端點（即攤平去重後可能巧合得到相同的 `bd_verts`，即使誤選了 count≥3 的 edge 為 boundary）
- **THEN** 新版本與現行版本各自選出的 boundary-edge array（以 `np.unique(axis=0)` 的 canonical lexicographic 順序比較）SHALL 逐一相等，包含 dtype 與 shape，而不能只比較攤平去重後的 `bd_verts`
- **AND** 用來驗證此 scenario 的測資 SHALL 明確斷言其 occurrence count 陣列中確實存在對應的 3 或 4 以上數值，以確保測資本身在 preprocessing 後仍具有預期拓樸，而非僅憑案例名稱

#### Scenario: duplicate 與 reversed duplicate face 不被誤判為 boundary
- **WHEN** mesh 中含有相同 winding 的 duplicate face，或含有相反 winding 的 duplicate face（其三條邊的 occurrence count 因此變為 2）
- **THEN** 新版本 SHALL 與現行版本一樣，不將該 face 的任何一條邊分類為 boundary edge

#### Scenario: merge 後才產生的 repeated-index／self-loop edge 維持既有行為
- **WHEN** 某 face 的兩個頂點在輸入階段座標不同（面積 > 1e-9，通過 zero-area 過濾）但在 `merge_vertices(digits_vertex=3)` 量化後被合併為同一頂點，使該 face 產生 `(v, v)` 形式的 self-loop edge
- **THEN** 新版本對此 self-loop edge 的 boundary 分類結果（含被歸類為 boundary 的既有邊界情況）SHALL 與現行版本完全相同，不因本次優化而被連帶「修正」

#### Scenario: repair 觸發與輸出 mesh 一致（不觸發 weld 的輸入）
- **WHEN** 對同一份輸入（其 boundary vertices 彼此距離皆 ≥ `weld_tol`，因此 KD-tree weld 不會觸發），分別以現行版本與新版本執行完整 `clean_input_for_manifold()`（含 KD-tree weld、connected components、remap、face 過濾、`Trimesh(process=True)` 重建、export）
- **THEN** 兩者 KD-tree weld 皆不觸發、`stats`（`zero_area_dropped`／`merged_verts`／`boundary_welded`）、以及最終匯出 mesh 的 `vertices`／`faces` SHALL 完全相等

#### Scenario: repair 觸發與輸出 mesh 一致（實際觸發 weld 的輸入）
- **WHEN** 對同一份輸入，其中至少兩個 boundary vertices 彼此距離小於 `weld_tol`（且不會被更早的 `merge_vertices(digits_vertex=3)` 提前合併），分別以現行版本與新版本執行完整 `clean_input_for_manifold()`
- **THEN** 兩者 KD-tree `query_pairs` SHALL 皆找到至少一組 pair，實際執行 connected components、代表 vertex 選擇、remap 與 invalid-face 過濾，兩者 `stats["boundary_welded"]` SHALL 皆大於 0 且彼此相等
- **AND** `stats` 全部欄位與最終匯出 mesh 的 `vertices`／`faces` SHALL 完全相等
- **AND** 此 scenario 的驗證 MUST NOT 僅以「兩者皆為 0」的比較結果視為通過

#### Scenario: empty mesh／Scene 分支維持既有行為
- **WHEN** 輸入為空 STL（`trimesh.load()` 回傳 `Scene`）或處理後頂點/面數為零的 mesh
- **THEN** 新版本 SHALL 與現行版本走相同分支、產生相同的 `stats` 與匯出結果，不拋出未預期例外
