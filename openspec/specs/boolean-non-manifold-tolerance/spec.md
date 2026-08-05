# boolean-non-manifold-tolerance Specification

## Purpose
定義 `boolean_operation()` 對非流型網格的容錯修補序列——Manifold 靜默失敗的偵測方式、非 volume 分支中退化面清理的執行時機、manifold3d Mesh.merge() 作為輕量修補路徑的採用條件、seam 焊接與平面邊界封蓋的 transactional 採用條件（任一結構條件未通過即完全回退），以及修補不適用時維持原有失敗行為、不留部分修改的語意保證。亦定義 `boolean_operation()` 的回傳型別 `(bool, Optional[str], Optional[str])` 與 `error_code` 的設定條件。
## Requirements
### Requirement: 靜默的 Manifold 轉換失敗必須被偵測

`boolean_operation()` SHALL 在呼叫 `trimesh_to_manifold()` 後，以 `status / num_tri / is_empty` 三個屬性核查所得的 `Manifold` 物件是否有效，且 MUST NOT 讓 `status≠NoError`、`num_tri=0` 或 `is_empty=True` 的物件進入布林運算。任一屬性讀取失敗時 SHALL 保守地視為無效。

#### Scenario: Manifold 轉換拋出例外時觸發 fallback
- **WHEN** `trimesh_to_manifold()` 拋出任何例外
- **THEN** 系統 SHALL 觸發修補序列，不讓例外直接導致布林運算失敗

#### Scenario: Manifold 靜默回傳無效物件時觸發 fallback
- **WHEN** `trimesh_to_manifold()` 成功執行但所得 Manifold 的 `status != "Error.NoError"` 或 `num_tri == 0` 或 `is_empty is True`
- **THEN** 系統 SHALL 進入 fallback 路徑
- **AND** 該無效 Manifold MUST NOT 進入後續的布林運算

#### Scenario: Manifold 靜默失敗但網格為 is_volume 時不執行退化面清理
- **WHEN** `trimesh_to_manifold()` 靜默回傳無效 Manifold，且該網格的 `is_volume` 為 True
- **THEN** 系統 SHALL 進入 fallback 路徑，但 MUST NOT 對此網格執行退化面清理或後續修補步驟
- **AND** 重試 Manifold 轉換後仍無效時，SHALL 以明確訊息回傳失敗

#### Scenario: 兩個網格均有效時主路徑不受影響
- **WHEN** 兩個網格皆能直接轉換為有效 Manifold（status=NoError, num_tri>0, not empty）
- **THEN** 系統 SHALL 直接執行布林運算，不觸發任何修補步驟

---

### Requirement: 非 volume 分支中須先清除退化面再執行修補

當網格進入非 volume 修補分支（`not mesh.is_volume`）時，系統 SHALL 在呼叫任何進一步修補（Mesh.merge / seam 焊接 / 平面封蓋 / fill_holes）前先移除可明確判定為無效的退化面。`is_volume == True` 的網格不進入此分支，退化面清理不執行。

#### Scenario: 重複索引面被移除
- **WHEN** mesh_a 或 mesh_b 進入非 volume 修補分支，且存在任意兩個頂點索引相同的三角形（`face[i]==face[j]` for i≠j）
- **THEN** 這些三角形 SHALL 被移除，且不使用座標門檻判定
- **AND** 移除後 SHALL 呼叫 `remove_unreferenced_vertices()` 使快取失效

#### Scenario: 同繞向精確重複面被移除
- **WHEN** mesh_a 進入非 volume 修補分支，且存在兩個或更多面，其頂點為彼此的循環輪換（cyclic rotation，即同繞向重複）
- **THEN** 每組中僅保留一個代表面，其餘被移除

#### Scenario: 對向繞向對不被移除
- **WHEN** mesh_a 進入非 volume 修補分支，且存在頂點集相同但繞向相反的兩個面（opposite-winding pair）
- **THEN** 這兩個面 SHALL NOT 在此步驟被移除

#### Scenario: 退化面清理後網格無面時提前失敗
- **WHEN** 網格進入非 volume 修補分支，且退化面清理後 mesh_a 或 mesh_b 的面數歸零
- **THEN** 系統 SHALL 立即回傳失敗，MUST NOT 繼續後續修補步驟

---

### Requirement: manifold3d Mesh.merge() 優先作為輕量修補路徑

退化面清理後，若 `manifold3d.Mesh.merge()` API 可用，系統 SHALL 嘗試以其取得有效 Manifold，並在驗證通過時跳過 seam 焊接與平面封蓋。

#### Scenario: Mesh.merge() 成功時採用並跳過後續修補
- **WHEN** 以退化面清理後的 mesh_a 建構 `manifold3d.Mesh` 並呼叫 `.merge()`，所得 Manifold 通過 `_is_valid_manifold()` 驗證
- **THEN** 系統 SHALL 採用此 Manifold，MUST NOT 再執行 seam 焊接或平面封蓋
- **AND** seam 焊接與平面封蓋 SHALL NOT 被執行

#### Scenario: Mesh.merge() 失敗或結果無效時繼續後續步驟
- **WHEN** `Mesh.merge()` 拋出例外，或所得 Manifold 未通過 `_is_valid_manifold()` 驗證
- **THEN** 系統 SHALL 繼續嘗試 seam 焊接，不因此回傳失敗

---

### Requirement: seam 焊接僅在結構條件全部通過時採用

`_transactional_seam_weld()` SHALL 在工作副本上執行，且僅在以下條件全部滿足時才以工作副本取代原始網格，否則 MUST 完全回退至原始網格，MUST NOT 留下任何部分修改。

#### Scenario: 邊界未減少時回退
- **WHEN** 焊接工作副本的 boundary_edges ≥ 原始 boundary_edges
- **THEN** 工作副本 SHALL 被捨棄，原始 mesh 不被修改

#### Scenario: 焊接引入新的非流型邊時回退
- **WHEN** 工作副本的 non_manifold_edges > 原始 non_manifold_edges
- **THEN** 工作副本 SHALL 被捨棄，原始 mesh 不被修改

#### Scenario: 焊接引入新的同向共享邊時回退
- **WHEN** 工作副本的 same_direction_shared_edges > 原始 same_direction_shared_edges
- **THEN** 工作副本 SHALL 被捨棄，原始 mesh 不被修改

#### Scenario: 焊接後繞向不一致時回退
- **WHEN** 工作副本的 `is_winding_consistent` 為 False
- **THEN** 工作副本 SHALL 被捨棄，原始 mesh 不被修改

#### Scenario: 連通分量異常增加時回退
- **WHEN** 工作副本的連通面組件數 > 原始連通面組件數 + 1
- **THEN** 工作副本 SHALL 被捨棄，原始 mesh 不被修改

#### Scenario: 前置驗證發現焊接將引入 NME 或 SDE 時立即退出
- **WHEN** 初步重映射的面陣列（pre-validation）顯示焊接後 NME > 0 或 SDE > 0
- **THEN** 系統 SHALL 立即退出，MUST NOT 建構完整工作副本

#### Scenario: 模糊配對存在時不執行焊接
- **WHEN** 配對計算發現任何模糊配對（n_ambiguous > 0）
- **THEN** 焊接 SHALL NOT 被執行

#### Scenario: 焊接成功時採用工作副本
- **WHEN** 所有採用條件均滿足
- **THEN** 工作副本 SHALL 取代 mesh_a
- **AND** 若工作副本同時產出有效 Manifold，該 Manifold SHALL 被採用供後續重試使用

---

### Requirement: 平面邊界封蓋僅在七個前置條件全部通過時執行

`_try_repair_planar_boundary()` SHALL 以工作副本執行，且僅在所有結構與 Manifold 驗證通過時採用，否則 MUST 完全回退，不修改原始網格。

#### Scenario: 存在退化面時不執行封蓋
- **WHEN** mesh_a 存在任何退化面（重複索引、座標坍縮或近共線）
- **THEN** 封蓋 SHALL NOT 被執行，系統繼續 fill_holes 路徑

#### Scenario: 存在非流型邊或同向共享邊時不執行封蓋
- **WHEN** mesh_a 的 non_manifold_edges > 0 或 same_direction_shared_edges > 0
- **THEN** 封蓋 SHALL NOT 被執行

#### Scenario: 邊界頂點存在 degree-1 頂點時不執行封蓋
- **WHEN** 任何邊界頂點的 boundary degree 為 1（開鏈端點）
- **THEN** 封蓋 SHALL NOT 被執行

#### Scenario: 邊界頂點不共面時不執行封蓋
- **WHEN** 邊界頂點的 SVD 最佳擬合平面偏差 > max(bbox_diagonal × 1e-3, 1e-6)
- **THEN** 封蓋 SHALL NOT 被執行

#### Scenario: 邊界平面不在網格極端時不執行封蓋
- **WHEN** 邊界平面沿法向至最近的網格極端距離 > max(mesh_diagonal × 0.05, planarity_tol)
- **THEN** 封蓋 SHALL NOT 被執行

#### Scenario: 多邊形化產生 dangling edges 或 invalid rings 時不採用
- **WHEN** `shapely.polygonize_full` 產生 dangling edges 或 invalid rings
- **THEN** 封蓋結果 SHALL 被捨棄，原始 mesh 不被修改

#### Scenario: 工作副本驗證失敗時回退
- **WHEN** 封蓋後工作副本的 boundary_edges > 0，或 NME > 0，或 SDE > 0，或退化面 > 0，或非 watertight，或非 volume，或 Manifold 驗證失敗
- **THEN** 工作副本 SHALL 被捨棄，原始 mesh 不被修改，繼續 fill_holes 路徑

#### Scenario: 所有條件通過時採用封蓋副本
- **WHEN** 七個前置條件均通過，多邊形化無異常，工作副本通過完整結構與 Manifold 驗證
- **THEN** 工作副本 SHALL 取代 mesh_a，後續直接進入 Manifold 重試

---

### Requirement: `boolean_operation()` 回傳型別

`boolean_operation()` 的回傳型別 SHALL 為 `tuple[bool, Optional[str], Optional[str]]`，格式為 `(success, error_message, error_code)`。成功路徑 SHALL 回傳 `(True, None, None)`。`error_code` 在多數失敗路徑為 `None`；僅在「幾何問題無法修復」的四個出口設為 `"BOOLEAN_INVALID_MESH"`（定義於下方 Requirement）。

#### Scenario: 成功時回傳三元素 tuple
- **WHEN** 布林運算完成並成功匯出結果 STL
- **THEN** `boolean_operation()` SHALL 回傳 `(True, None, None)`

#### Scenario: 幾何問題無法修復時回傳 BOOLEAN_INVALID_MESH
- **WHEN** 修補序列後 mesh 仍無效，或防禦性核查發現無效 Manifold
- **THEN** 回傳的第三元素 `error_code` SHALL 為 `"BOOLEAN_INVALID_MESH"`

#### Scenario: 其他失敗路徑的 error_code 為 None
- **WHEN** 失敗原因為 trimesh 未安裝、退化面清理後無 faces、未知 operation、布林結果為空或未預期例外
- **THEN** 回傳的第三元素 `error_code` SHALL 為 `None`

---

### Requirement: 修補後必須驗證 Manifold 有效性再進行布林運算

修補序列執行後，系統 SHALL 重試 Manifold 轉換並以 `_is_valid_manifold()` 核查，任一網格仍無效時 SHALL 提前回傳失敗，MUST NOT 讓無效 Manifold 進入布林運算。

#### Scenario: mesh_a 修補後仍無效時提前失敗
- **WHEN** 修補序列完成後 `_is_valid_manifold(man_a)` 為 False
- **THEN** 系統 SHALL 回傳 `(False, "mesh_a repair failed: still invalid after repair", "BOOLEAN_INVALID_MESH")`

#### Scenario: mesh_b 修補後仍無效時提前失敗
- **WHEN** 修補序列完成後 `_is_valid_manifold(man_b)` 為 False
- **THEN** 系統 SHALL 回傳 `(False, "mesh_b repair failed: still invalid after repair", "BOOLEAN_INVALID_MESH")`

#### Scenario: 布林運算前的防禦性核查
- **WHEN** 任何路徑的 Manifold 在進入布林運算前被偵測為無效
- **THEN** 系統 SHALL 提前回傳失敗，MUST NOT 執行布林運算
- **AND** 回傳的 `error_code` SHALL 為 `"BOOLEAN_INVALID_MESH"`

---

### Requirement: 修補不適用或失敗時不留下部分修改

當修補序列中的任一子步驟不適用或失敗，系統 SHALL 維持原有失敗行為，且 MUST NOT 在原始網格物件上殘留部分修改。

#### Scenario: seam 焊接回退後原始網格不變
- **WHEN** seam 焊接因任何採用條件未通過而回退
- **THEN** `mesh_a` 物件 SHALL 與進入焊接前相同，MUST NOT 含有任何焊接操作的副作用

#### Scenario: 平面封蓋回退後原始網格不變
- **WHEN** 平面封蓋因任何前置條件或驗證未通過而回退
- **THEN** `mesh_a` 物件 SHALL 與進入封蓋前相同，MUST NOT 含有任何封蓋操作的副作用

