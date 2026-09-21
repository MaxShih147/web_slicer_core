## Context

`agent/ortho_pipeline.py::clean_input_for_manifold()` 是 `run_ortho_pipeline()` 無條件執行的前置清理步驟（U-arch 判斷之前）。其第三步（boundary vertex 判定）現行實作：

```python
edges_sorted = mesh.edges_sorted                              # (3F,2) int64, face-major
ue, c = np.unique(edges_sorted, axis=0, return_counts=True)   # 全量 unique edges + counts
bd_verts = np.unique(ue[c == 1])                               # 篩 occurrence==1 再攤平去重
```

下游（KD-tree weld → connected components → remap → face 過濾 → `Trimesh(process=True)` 重建）只讀取 `bd_verts`，`ue`／`c` 本身從未被其他地方使用。

本變更基於兩輪獨立調查（source tracing、7 模型 A/B prototype、13+ synthetic correctness case、ABBA 交錯受控 benchmark、trimesh/numpy 原始碼層級記憶體分析、trimesh 4.11.1↔5.1.0 跨版本驗證），已收斂到單一候選方案，本次 design 只記錄該方案的技術決策，不重新比較其他候選。

## Goals / Non-Goals

**Goals:**
- 用 `trimesh.grouping.group_rows(edges_sorted, require_count=1)` 取代 `np.unique(edges_sorted, axis=0, return_counts=True)` + count 篩選，只計算下游實際需要的「occurrence==1 的 edge」。
- 維持 `bd_verts` 的值、dtype、升冪排序與現行版本逐位元組相同（保留最後一次 `np.unique()`）。
- 額外空間複雜度維持 O(n)（n = edge occurrence 數 = 3×face_count），不引入與 vertex-index 值域相關的巨型配置。
- 不新增外部依賴，不自行實作或維護 bit-packed key／overflow guard。

**Non-Goals:**
- 不加入 `is_watertight` 或任何基於 mesh 屬性的 fast-path 以跳過完整清理流程。
- 不更動 zero-area filtering、`merge_vertices()`、KD-tree weld、connected components、remap、face filtering、mesh rebuild。
- 不處理其他 Auto Process 階段（Hollow、Hex Grid、Boolean 等）。
- 不調整 Python／NumPy／trimesh 版本，不處理 deployment dependency locking。
- 不宣稱新版比 reference 更省記憶體；不對 NumPy／trimesh 內部 scratch array 做測試或保證。

## Decisions

### 決策 1：採用 `trimesh.grouping.group_rows(require_count=1)`，不自行實作 packed integer key

**理由**：
- `trimesh.grouping` 是 trimesh 明確 export 的公開模組（`trimesh/__init__.py`），`group_rows`／`hashable_rows` 被 trimesh 自身在 `base.py`／`repair.py`／`graph.py`／`creation.py` 內部大量使用（`repair.py` 甚至就是用 `group_rows(mesh.edges_sorted, require_count=1)` 找 boundary edge，與本次場景完全對應）。
- overflow guard 與 fallback 已內建於 `hashable_rows()`：當 pair 的整數值超出 32-bit-per-column 安全範圍時，自動切換到 void-view 路徑，不會拋例外、不需要我方撰寫任何 guard 或 fallback 程式碼。已在真實資料（`vmax` 達 3×10⁹ 的合成測試）與空輸入（`n=0`）上驗證此行為。
- 已在兩個實際可用版本——trimesh 4.11.1（pinned dev 環境）與 5.1.0（`requirements.txt` 允許區間內可全新解析到的版本）——逐行 diff 確認 `group_rows`／`hashable_rows` 原始碼完全相同，並在 3 個真實模型上實測兩版本行為一致。`requirements.txt` 僅宣告 `trimesh>=4.0.0`，這兩個版本點不構成該允許範圍的「兩端點」，`>=4.0.0` 的完整允許範圍並未逐版驗證；正式實作因此只依賴 `group_rows(require_count=1)` 的公開正確性語意，不依賴任何特定版本的內部細節。
- 相較於手刻 packed key（曾在調查階段測得快 1.3-2×），維護面積最小（正式程式碼變更僅 2-3 行），把版本相容性責任交給 trimesh 的公開 API 語意，而非自行維護的位元編碼細節——這是使用者與本次調查共同認定的最低風險選擇。

**已考慮但不採用的替代方案**（皆在前兩輪調查中驗證過，僅記錄結論，不重新比較）：
- 手刻 bit-packed uint64 key + 手寫 overflow guard：效能略優，但需自行撰寫並維護 guard/fallback 邏輯，維護風險高於直接複用 trimesh 既有實作。
- `np.lexsort` + 手動 run-length 偵測：不需整數編碼，但實測比 `group_rows` 慢，且程式碼量更大。
- structured/void view 手動攤平：實測是四個候選中最慢的一個。

### 決策 2：保留最後一次 `np.unique(edges_sorted[boundary_idx])`

`bd_verts` 的順序會被 KD-tree `query_pairs` 的 pair index、connected-component member 收集順序、以及「每個連通分量代表點＝該分量中 `bd_verts` 索引最小者」的邏輯直接消費。不論候選演算法內部用什麼順序找出 boundary edge，只要最後仍呼叫 `np.unique()`（保證 ascending、去重、`int64`），`bd_verts` 即與 reference 逐位元組相同，下游不需要任何調整。此不變式已在 7 個真實模型與 10+ 個 synthetic case（含全流程 STL load → weld → rebuild → export）上驗證。

### 決策 3：不宣稱記憶體優劣，僅承諾複雜度量級

原始碼層級分析（`numpy/lib/_arraysetops_impl.py::_unique1d` 與 trimesh `grouping.py::hashable_rows`）顯示：
- Reference 因 `return_counts=True` 而跳過 numpy 2.x 的 hash-table 快速路徑，內部 `.flatten()` 會產生一份 n×16 bytes 的結構化拷貝，並持續持有到函式返回；回傳後 `ue`／`c`（合計約 12n bytes）也會一路存活到 `clean_input_for_manifold()` 結束才釋放。
- `group_rows()` 內部 `hashable_rows()` 的 bitbang 路徑在建構階段瞬時峰值約 40n bytes，但函式返回後只留下極小的 boundary edge 索引陣列（大小＝boundary edge 數，本專案實測 0-146），不會像 reference 一樣把 12n bytes 的中介陣列一路帶到函式結尾。
- Reference 與 candidate A 的額外空間複雜度都是 O(n)。以 `DentalModel_1M`（n≈307 萬 edge occurrence）量級估算，candidate A 在 scan 執行「當下」的瞬時暫存峰值可能比 reference 高約 21–30 MB；但 scan 結束後，candidate A 不再保留完整 `ue`／`c`（只留下大小＝boundary edge 數的極小索引陣列），reference 則會把 `ue`／`c`（合計約 12n bytes）一路帶到 `clean_input_for_manifold()` 函式結尾才釋放。**本 change 不宣稱 candidate A 的 process peak memory 較低**，也不對兩者記憶體高低下結論；代表模型上觀察到的暫存增量（約數十 MB）判定為可接受，但這是基於觀察到的量級做出的工程判斷，不以「暫存遠小於 mesh vertices/faces」作為理由或驗收條件，也不以任何 NumPy／trimesh 內部 allocation 的具體數字作為正式驗收條件；驗收只檢查「額外空間複雜度為 O(n)」且「不引入與 vertex-index 值域相關的巨型配置」（這點由直接複用 trimesh 既有實作自動滿足，不需要新增程式碼證明）。

## Risks / Trade-offs

- **[Risk] Production 實際安裝的 Python／NumPy／trimesh 版本未知** → repo 內無 lock file／Dockerfile／CI 版本鎖定，`deploy/.env.example` 僅顯示部署機使用 Homebrew 的 Python 3.12，實際 `pip install -r requirements.txt` 解析到的版本無法從 repo 判定。**Mitigation**：已在兩個實際可用版本（trimesh 4.11.1 與 5.1.0）驗證原始碼一致且行為一致；`requirements.txt` 僅宣告 `trimesh>=4.0.0`，這兩個版本並非該允許範圍的「兩端點」，`>=4.0.0` 完整允許範圍未逐版驗證。`group_rows` 只使用穩定、長期存在的 numpy 基礎運算（位元運算、`astype`、`argsort`、boolean indexing），正式實作只依賴其公開正確性語意，不依賴特定版本的內部細節。Production 實際 Python／NumPy／trimesh 版本仍留待部署前確認；此項不是本次實作的阻斷條件，記錄於 Open Questions。
- **[Risk] Scan 執行當下的暫時記憶體峰值可能比 reference 高約 21–30 MB（同一 O(n) 數量級內，以 DentalModel_1M 量級估算）** → 已於決策 3 說明成因與量級；scan 結束後 candidate A 不再保留完整 `ue`／`c`。此增量在代表模型上觀察判定為可接受，但不對兩者記憶體高低下正式結論，也不以第三方（NumPy／trimesh）內部 allocation 的具體數字作為正式驗收條件，不需要額外優化或 guard。
- **[Risk] `bd_verts` 順序若被錯誤簡化（例如省略最後的 `np.unique()`）會靜默改變下游 weld 代表點選擇** → Mitigation：決策 2 明確要求保留最後一次 `np.unique()`；新增測試會直接比較 reference／新版在多個 synthetic case 下的 `bd_verts` 值/dtype/順序，任何順序偏差都會被測試捕捉。

## Migration Plan

無需資料遷移。此為單一函式內部的演算法替換，行為對呼叫端（`run_ortho_pipeline()`）完全透明。若需回滾，只需將 `clean_input_for_manifold()` 內的三行改回 `np.unique(edges_sorted, axis=0, return_counts=True)` 版本即可，不涉及資料格式或 API 變更。

## Open Questions

- Production 實際安裝的 Python／NumPy／trimesh 版本尚未取得（本機無 Python 3.12 直譯器、無法存取部署容器）。目前只在兩個實際可用版本（trimesh 4.11.1 與 5.1.0）驗證過行為一致，`requirements.txt` 宣告的 `trimesh>=4.0.0` 完整允許範圍未逐版驗證。建議後續向持有部署主機的人索取 `pip freeze` 輸出以完成最終確認；若實際版本明顯偏離這兩個已驗證版本點，建議在該版本下重跑本 change 的 synthetic regression test。不需要為此安裝 Python 3.12、逐版測試 trimesh 或修改 dependency 版本。此項不是本次實作與合併的阻斷條件。
