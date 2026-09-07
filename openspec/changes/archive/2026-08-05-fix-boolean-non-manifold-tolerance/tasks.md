## 1. 靜默失敗偵測

- [x] 1.1 新增 `_manifold_props(man)` 輔助函式，以 try/except 安全讀取 `status() / num_tri() / is_empty()`，任一讀取失敗即回傳 `valid=False`
- [x] 1.2 新增 `_is_valid_manifold(man)` 輔助函式，組合三個條件（status=NoError, num_tri>0, not empty）
- [x] 1.3 改寫主轉換路徑：`trimesh_to_manifold()` 後立即呼叫 `_manifold_props()`；任一網格無效（例外或靜默）設 `_need_fallback = True`
- [x] 1.4 新增 `_stage` 追蹤變數，在 except 區塊記錄失敗發生的階段

## 2. 退化面清理

- [x] 2.1 新增 `_remove_repeated_index_faces(mesh, label)`：純索引比對找出 `face[:,0]==face[:,1]` 等三個組合的三角形，批次移除後呼叫 `remove_unreferenced_vertices()`；不使用座標門檻；回傳統計 dict；無退化面時回傳 no-op
- [x] 2.2 新增 `_remove_exact_duplicate_faces(mesh, label)`：以 min-cyclic canonical form 找出同繞向重複面，保留每組第一個代表；對向繞向對僅統計不移除；呼叫 `remove_unreferenced_vertices()` 後回傳統計 dict
- [x] 2.3 在修補序列中對 mesh_a 先執行 2.1 再執行 2.2；移除後若 mesh_a 無剩餘面則提前回傳失敗
- [x] 2.4 對 mesh_b 執行 2.1（repeated-index cleanup）；移除後若 mesh_b 無剩餘面則提前回傳失敗

## 3. manifold3d Mesh.merge() 嘗試

- [x] 3.1 在退化面清理後，以 `hasattr(manifold3d.Mesh, "merge")` 判斷 API 可用性
- [x] 3.2 嘗試以 float32 頂點與 int32 面建構 `manifold3d.Mesh`，呼叫 `.merge()`，包裝為 `Manifold`，並以 `_is_valid_manifold()` 驗證
- [x] 3.3 驗證通過時設 `_merge_man_a`，讓重試路徑直接採用，跳過 seam 焊接與平面封蓋；任何例外均 pass 並繼續後續步驟

## 4. 可回退的 seam 焊接

- [x] 4.1 新增 `_compute_boundary_seam_pairs(mesh, match_factor, len_rel_tol, eps_floor)`：以 6-D KD-tree 找 mutual-best anti-parallel 邊對；回傳含 `ok / matched_pairs / n_ambiguous / coverage` 的 dict；永不拋例外
- [x] 4.2 新增 `_ei_stats(faces)`：計算 boundary_edges / non_manifold_edges / same_direction_shared_edges；出錯回傳 (-1,-1,-1)
- [x] 4.3 新增 `_count_multi_fan(faces)`：統計 incident faces > 1 fan 的頂點數；出錯回傳 -1
- [x] 4.4 新增 `_count_components(mesh)`：以 scipy.sparse.csgraph 計算連通面組件數；出錯回傳 -1
- [x] 4.5 新增 `_transactional_seam_weld(mesh, label)` 實作完整 transactional 流程：保守閾值（match_factor=0.02, len_rel_tol=0.05）→ 前置驗證（NME/SDE 不增加）→ working copy 建構（union-find + 類別平均位置）→ 後置採用條件（boundary 減少、NME/SDE 未增加、winding 一致、components 未異常增加）；任一條件未通過回傳 `adopted=False`
- [x] 4.6 Mesh.merge() 未成功時，在修補序列中呼叫 `_transactional_seam_weld(mesh_a, "mesh_a")`；若 adopted，以焊接副本取代 mesh_a；若 weld 同時產出有效 Manifold 則設 `_merge_man_a`

## 5. 可回退的平面邊界封蓋

- [x] 5.1 新增 `_try_repair_planar_boundary(mesh, label)` 實作七個前置條件的順序評估（faces > 0、無退化面、NME=0 and SDE=0、boundary > 0、無 degree-1 邊界頂點、邊界近乎共面、邊界平面在網格極端）
- [x] 5.2 實作封蓋管線：邊界頂點投影 2D → shapely.polygonize_full（不容許 dangles / invalid rings）→ mapbox_earcut 三角化 → 繞向定向
- [x] 5.3 實作工作副本驗證（boundary=0, NME=0, SDE=0, 退化面=0, is_watertight, is_volume）+ Manifold 驗證；全部通過才採用；否則回傳原始 mesh
- [x] 5.4 在修補序列中（seam 焊接未成功時）呼叫 `_try_repair_planar_boundary(mesh_a, "mesh_a")`；若 applied 以封蓋副本取代 mesh_a；否則繼續 fill_holes 路徑

## 6. 修補後重試與防禦性前置檢查

- [x] 6.1 修補後重試 `trimesh_to_manifold(mesh_a)`：若 `_merge_man_a` 存在直接使用，否則重轉換；以 `_is_valid_manifold()` 核查，仍無效則提前回傳失敗訊息
- [x] 6.2 修補後重試 `trimesh_to_manifold(mesh_b)` 並以 `_is_valid_manifold()` 核查
- [x] 6.3 布林運算前新增防禦性核查（union pre-check）：任一 Manifold 無效則提前回傳失敗

## 7. 相依更新

- [x] 7.1 `requirements.txt` 新增 `networkx>=3.0`
- [x] 7.2 `scripts/run_agent.bat` 的 VCPKG_ROOT 安裝路徑新增 `"networkx>=3.0"`
