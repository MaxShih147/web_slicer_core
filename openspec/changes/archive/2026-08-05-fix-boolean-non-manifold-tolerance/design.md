## Context

`boolean_operation()` 的現行流程：
1. 以 Trimesh 載入兩個 STL
2. `trimesh_to_manifold()` 轉換為 `manifold3d.Manifold`
3. 呼叫 `man_a + man_b`（或 difference/intersection）
4. `manifold_to_trimesh()` 轉回 Trimesh 後匯出

當步驟 2 拋出例外時，原有失敗路徑對 `mesh.is_volume == False` 的網格呼叫 `trimesh.repair.fill_holes / fix_winding / fix_normals / merge_vertices` 後重試。此路徑有三個已知盲點：

- **靜默失敗**：`manifold3d.Manifold()` 在某些非流型輸入下不拋例外，直接回傳 `status=NotManifold`、`num_tri=0`、`is_empty=True` 的殼物件；原有碼讓這樣的物件進入布林運算，結果為空或不確定。此外，`_need_fallback` 旗標未能涵蓋「未拋例外但無效」的情況。
- **退化面**：`fill_holes` 以邊界邊（boundary edges）計算開放孔洞；重複索引面（`face[i]==face[j]`）在 Trimesh 的邊結構中產生長度為零的假邊，可能被誤計為邊界邊並誤導修補方向。精確重複面（同繞向的循環輪換）在 manifold3d 層級產生重疊面，同樣妨礙轉換。
- **seam 拓撲缺陷**：牙科口掃 STL 常有幾何上重合但拓撲未連接的邊對（接縫），這類開放邊界 `fill_holes` 無法有效修復，因為它嘗試填三角而非合併端點。

## Goals / Non-Goals

**Goals:**
- 在主轉換路徑與修補後重試均執行 Manifold 有效性核查，消除靜默失敗路徑。
- 在非 volume 修補分支中，呼叫 `fill_holes` 前清除可明確判定為無效的退化面與精確重複面。
- 對幾何接近但拓撲未連接的 seam 邊對執行受控焊接，且僅在結構驗證通過時採用。
- 對符合條件的平面開放邊界嘗試封蓋，且僅在完整流形驗證通過時採用。
- 不影響原本可正常完成的布林流程（主路徑兩個 Manifold 均有效）。
- 修補不適用或失敗時，不留下部分修改，維持原有失敗行為與回傳訊息格式。

**Non-Goals:**
- `mesh_b` 的 seam 焊接與平面邊界封蓋。
- 修補多分離組件網格（本序列以單連通 mesh 為設計假設）。
- 通用型 STL 清理 API 或新增對外端點。
- 前端錯誤碼傳遞。

## Decisions

### D1. 靜默失敗偵測：轉換後立即查詢 Manifold 屬性

`_manifold_props()` 以 try/except 逐一安全讀取 `man.status() / num_tri() / is_empty()`，任一讀取失敗即將 `valid` 設為 `False`（保守策略）。`_is_valid_manifold()` 組合三個條件：`status_str == "Error.NoError"` AND `isinstance(num_tri, int) and num_tri > 0` AND `is_empty is False`。

主轉換路徑改為：`trimesh_to_manifold()` 後立即呼叫 `_manifold_props()`；任一網格的 `valid == False`（例外或靜默）即設 `_need_fallback = True`，防止無效 Manifold 進入布林運算。

- **理由**：例外未必被拋出；三個屬性的組合比任一單一屬性更穩健，且均可在不知道 manifold3d 內部類型的情況下由純 duck-typing 讀取。

### D2. 退化面清理先於其他修補

`_remove_repeated_index_faces()` 以純索引比對（`face[:,0]==face[:,1]` 等三個組合）找出並批次移除重複索引面，呼叫 `remove_unreferenced_vertices()` 觸發 Trimesh 快取失效。不使用座標門檻，避免浮點精度問題。

`_remove_exact_duplicate_faces()` 以正規化最小循環輪換（min-cyclic canonical form）找出同繞向重複面，保留每組的第一個代表；對向繞向對（identical vertex set, opposite winding）僅統計不移除。

- **不移除對向繞向對的理由**：這類對在 seam 焊接後可能因頂點合併而消解，過早移除其中一個面可能在拓撲上留下漏洞。

### D3. manifold3d Mesh.merge() 作為輕量修補路徑

退化面清理後，若 `manifold3d.Mesh` 具備 `.merge()` API，嘗試以 float32 頂點與 int32 面建構 `manifold3d.Mesh`、呼叫 `.merge()`、包裝為 `Manifold` 並以 `_is_valid_manifold()` 驗證。成功時直接採用，跳過 seam 焊接、平面封蓋與 fill_holes。

- **理由**：`Mesh.merge()` 在 manifold3d 層級合併幾何重合頂點，對 seam 型缺陷常可直接修復，效率高於 Trimesh 側的多步修補。
- **必須驗證**：`Mesh.merge()` 可能同樣靜默回傳無效 Manifold；採用前必須通過 `_is_valid_manifold()`。

### D4. 可回退的 seam 焊接

`_transactional_seam_weld()` 分為三個階段：

1. **配對（_compute_boundary_seam_pairs）**：以 6-D KD-tree（存放 `(pos[d], pos[c])` 供邊 `(a,b)` 以 `(pos[a], pos[b])` 查詢）找出 mutual-best anti-parallel 邊對，閾值為端點距離 ≤ 2% median edge length、邊長比 ≤ 5%，且不允許任何模糊配對（n_ambiguous=0）。
2. **前置驗證**：以 union-find 的初步重映射面陣列執行 `_ei_stats()` 檢查 NME/SDE；若會引入新問題立即退出，不建構 working copy。
3. **Working copy 建構與後置驗證**：合併端點至類別平均位置、重映射面、移除因合併退化的面，再呼叫 `fix_winding / fix_normals`。後置採用條件（全部須滿足）：
   - `boundary_edges_after < boundary_edges_before`（邊界有實際收斂）
   - `nme_after <= nme_before`
   - `sde_after <= sde_before`
   - `is_winding_consistent == True`
   - `components_after <= components_before + 1`

任一條件未通過則完全回退，返回原始 `mesh` 物件。即使後續 Manifold 轉換仍失敗（如多扇頂點殘留），已焊接的副本仍被保留以便平面封蓋路徑使用。

- **閾值保守設計**：2%/5% 針對幾何接近但拓撲斷開的真正 seam，不適用於大型幾何偏差或非線性補間。

### D5. 可回退的平面邊界封蓋（7 前置條件）

`_try_repair_planar_boundary()` 的前置條件按序評估，任一失敗即立即回傳（不嘗試後續步驟）：

1. 網格有面與頂點
2. 退化面總數為零（重複索引 | 座標坍縮 | 近共線，使用與修補序列一致的分類門檻）
3. NME = 0 且 SDE = 0
4. boundary_edges > 0
5. 無 degree-1 邊界頂點（boundary vertex 的 degree 必須 ≥ 2，即不存在孤立鏈端點）
6. 邊界頂點近乎共面（SVD 最佳擬合平面；最大偏差 ≤ max(bbox_diagonal × 1e-3, 1e-6)）
7. 邊界平面位於網格沿法向的某一極端（邊界平面至最近 mesh 極端的距離 ≤ max(mesh_diagonal × 0.05, planarity_tol)）

管線：邊界頂點投影至 2D → `shapely.MultiLineString` → `polygonize_full`（無 dangling edges / invalid rings 才繼續）→ `mapbox_earcut` 三角化 → 繞向定向（outward direction 以中心點與邊界平面相對位置決定）→ 工作副本驗證（boundary_edges=0, NME=0, SDE=0, 退化面=0, is_watertight, is_volume）→ Manifold 驗證。

全部驗證通過才採用工作副本；否則原始 `mesh` 不變，回退至 fill_holes 路徑。

- **前置條件 7 的理由**：若邊界平面不在網格極端，封蓋後可能把網格切成兩個殼，拓撲語意不確定；限制在極端可確保封蓋的幾何語意為「填補截面」。

### D6. 修補序列僅對 mesh_a 套用完整路徑

`mesh_b` 僅執行 `_remove_repeated_index_faces()` + 標準 trimesh 修補（fill_holes / fix_winding / fix_normals / merge_vertices）。完整序列（Mesh.merge / seam 焊接 / 平面封蓋）僅套用於 `mesh_a`。

- **理由**：引入不對稱修補保持行為可預測；在已知的牙科場景中，問題網格通常為 `mesh_a`（牙冠/底座 STL）。

### D7. 修補後重試與防禦性前置檢查

修補後立即呼叫 `trimesh_to_manifold()` 並以 `_is_valid_manifold()` 核查，任一網格仍無效則以明確訊息提前回傳失敗：

```
"mesh_a repair failed: still invalid after repair"
"mesh_b repair failed: still invalid after repair"
```

布林運算前另設防禦性核查（`union pre-check`），作為第二道保障確保無效 Manifold 不進入運算。

## Risks / Trade-offs

- **seam 焊接移動頂點**：端點合併至類別平均位置，最大位移在 2% median edge length 量級；對牙科 STL 尺寸精度影響預期可忽略，但嚴格公差場景應留意。
- **平面封蓋改變網格體積**：新增三角形填補了開放邊界；若原始 STL 的開放邊界是刻意設計的（如需後處理的截面），應在布林運算前確保該端不開放。
- **shapely / mapbox_earcut 相依**：這兩個套件的 `ImportError` 會讓 `_try_repair_planar_boundary()` 靜默跳過（回退至 fill_holes），不影響布林整體可用性。
- **mesh_b 缺少完整序列**：若 `mesh_b` 存在 seam 缺陷，現行序列無法修復；但加入對稱修補的架構已備妥，可在需要時擴充。
