## ADDED Requirements

### Requirement: boolean 以 numpy 讀取 binary STL 並合併頂點

`boolean_operation()` 讀取 `mesh_a`、`mesh_b` 時，對 binary STL（長度恰為 `84 + n × 50` 且 `n > 0`）SHALL 以 numpy 直接讀取三角形頂點，並以 numpy 合併頂點，MUST NOT 呼叫 `trimesh.load()`。頂點合併的判準 SHALL 與 trimesh `merge_vertices` 預設行為相同：座標四捨五入到 `trimesh.tol.merge` 對應的小數位數後完全相同者視為同一頂點。含非有限座標（NaN／Inf）頂點的面 SHALL 移除，與 trimesh `remove_infinite_values` 相同；其餘面的順序與每個面的頂點順序（繞序）SHALL 保留，MUST NOT 移除退化面或重複面（`trimesh.load` 預設 `validate=False`，同樣不移除）。

合併後的頂點陣列 SHALL 依「第一次出現」的順序排列，與 trimesh `unique_rows(keep_order=True)` 相同，MUST NOT 依座標排序。如此 numpy 路徑產生的頂點陣列與面索引陣列 SHALL 與 `trimesh.load(process=True)` 的 `vertices`、`faces` 逐元素相同，修補序列（其中部分步驟受頂點順序影響）的輸入與改前完全一致。

不符合 binary 公式的檔案（ASCII STL 等）SHALL 退回 `trimesh.load()`，行為與改前相同。

#### Scenario: binary STL 讀取結果與 trimesh 等價
- **WHEN** 以 numpy 路徑與 `trimesh.load(process=True)` 分別讀取同一個 binary STL
- **THEN** 兩者的 `vertices` 陣列 SHALL 逐元素相同（含順序）
- **AND** 兩者的 `faces` 陣列 SHALL 逐元素相同

#### Scenario: 含 NaN 面、重複面、退化面時仍與 trimesh 相同
- **WHEN** binary STL 含 NaN 座標的面、完全重複的面、以及三點共線的退化面
- **THEN** numpy 路徑的 `vertices`、`faces` SHALL 與 `trimesh.load(process=True)` 逐元素相同

#### Scenario: ASCII STL 退回 trimesh
- **WHEN** `mesh_a` 或 `mesh_b` 為 ASCII STL
- **THEN** 系統 SHALL 以 `trimesh.load()` 讀取該檔，後續流程與改前相同

### Requirement: 主路徑直接以陣列建立 Manifold，修補路徑行為不變

兩個網格皆能以合併後的陣列直接建立有效 `Manifold` 時，`boolean_operation()` SHALL 不建立 `trimesh.Trimesh` 物件。主路徑轉換失敗或得到無效 `Manifold`（依 `boolean-non-manifold-tolerance` 的判定）時，SHALL 以改前相同的 `trimesh.load()` 讀入該兩個網格並進入現有修補序列（修補序列拿到的物件與改前完全相同，包含 STL 檔內的面法向量）；修補序列的步驟、採用條件與錯誤回傳 SHALL 與改前相同。

#### Scenario: 有效網格不經 trimesh
- **WHEN** 兩個輸入皆為封閉流形的 binary STL
- **THEN** 布林運算 SHALL 成功，且過程中 SHALL 不呼叫 `trimesh.load()` 或建立 `trimesh.Trimesh`

#### Scenario: 非流形輸入仍走修補序列
- **WHEN** `mesh_a` 為無法直接轉為有效 Manifold 的網格（例如有開口）
- **THEN** 系統 SHALL 進入與改前相同的修補序列，成功與否及回傳的錯誤訊息、錯誤碼 SHALL 與改前相同
- **AND** 修補成功時，輸出 STL 的三角形 SHALL 與改前輸出逐面相同（座標與繞序）

### Requirement: 結果直接以 numpy 寫成 binary STL，且與改前等價

布林運算的結果 SHALL 直接取 `Manifold.to_mesh()` 的 `vert_properties[:, :3]` 與 `tri_verts` 陣列，以 numpy 寫成 binary STL（每面法向量由頂點以右手定則計算並正規化，退化面法向量為 0），MUST NOT 經過 `trimesh.Trimesh(process=True)`、`is_watertight` 或 `export()`。結果面數為 0 時 SHALL 以「Boolean operation resulted in empty mesh」回傳失敗，與改前相同。

輸出 STL 與改前輸出 SHALL 在下列判準下等價（不要求 byte-for-byte 相同）：三角形數相等；以 trimesh 重新讀取後 `is_watertight` 相同；繞序方向相同（`is_winding_consistent` 相同且 `volume` 同號、數值相對誤差 ≤ 1e-6）。

#### Scenario: union 結果與改前等價
- **WHEN** 以同一組封閉流形的 `mesh_a`、`mesh_b` 分別用改前與改後的 `boolean_operation()` 做 union
- **THEN** 兩份輸出的三角形數 SHALL 相等
- **AND** 以 trimesh 讀回後 `is_watertight` SHALL 皆為 True
- **AND** `volume` SHALL 同號且相對誤差 ≤ 1e-6

#### Scenario: difference 與 intersection 結果與改前等價
- **WHEN** 以同一組輸入做 difference 或 intersection
- **THEN** 輸出 SHALL 符合上述三項等價判準

#### Scenario: 結果為空
- **WHEN** 布林運算結果沒有任何三角形（例如兩個不相交網格的 intersection）
- **THEN** `boolean_operation()` SHALL 回傳 `(False, "Boolean operation resulted in empty mesh", None)`，不寫出檔案
