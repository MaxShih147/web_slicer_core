## Why

`boolean_operation()` 以 manifold3d 執行布林運算時，對以下缺陷的容錯能力不足：

1. **靜默的 Manifold 轉換失敗**：`manifold3d.Manifold()` 轉換失敗時不一定拋例外，可能靜默回傳 `status=NotManifold`、`num_tri=0`、`is_empty=True` 的無效物件；原有程式碼沒有偵測這種情況，讓無效物件進入布林運算導致結果空或不確定。
2. **退化面與精確重複面**：重複索引面（三角形中任意兩個頂點索引相同）在 Trimesh 拓撲計算中產生假邊界，干擾 `fill_holes`；同繞向的循環輪換重複面同樣妨礙 manifold 轉換，但既有修補流程對這兩類缺陷均無處理。
3. **seam 拓撲缺陷**：部分 STL（常見於牙科口掃流程）存在幾何上接近但拓撲未連接的邊對（接縫），形成開放邊界但 `fill_holes` 無法有效修復。
4. **平面型開放邊界**：某些 STL 在截面位置存在平面型開放邊界，滿足平面條件時可安全封蓋，但既有流程不加判斷地交給 `fill_holes`。

本變更引入**可回退、不殘留部分狀態的修補序列**，讓布林運算對上述缺陷具備受限制且可觀測的容錯能力。原本可正常完成的布林流程完全不受影響。

## What Changes

- **靜默失敗偵測**：新增 `_manifold_props()` 與 `_is_valid_manifold()` 輔助函式；主轉換路徑在 `trimesh_to_manifold()` 後立即驗證，無效時設 fallback 旗標，防止無效物件進入布林運算。
- **退化面清理（非 volume 分支）**：當網格進入非 volume 修補分支（`not mesh.is_volume`）時，首先以 `_remove_repeated_index_faces()` 移除任意兩個頂點索引相同的三角形，再以 `_remove_exact_duplicate_faces()` 移除同繞向的循環輪換重複面；`is_volume == True` 的網格不執行此清理。
- **manifold3d Mesh.merge() 嘗試**：退化面清理後嘗試以 `manifold3d.Mesh.merge()` 直接取得有效 Manifold；成功時跳過 seam 焊接與平面封蓋。
- **可回退的 seam 焊接**：`_transactional_seam_weld()` 以 6-D KD-tree 找出幾何接近且 anti-parallel 的邊對，以 union-find 合併端點後，僅在邊界數減少、NME/SDE 未增加、繞向一致、連通分量未異常增加時才採用工作副本；否則完全回退。
- **可回退的平面邊界封蓋**：`_try_repair_planar_boundary()` 在七個前置條件均通過後，以 shapely.polygonize_full + mapbox_earcut 封蓋平面型開放邊界；結果須通過完整結構與 Manifold 驗證才採用，否則回退至 fill_holes。
- **修補後驗證與防禦性前置檢查**：修補後重試 Manifold 轉換並以 `_is_valid_manifold()` 核查；布林運算前另設防禦性核查，確保任何路徑都不讓無效 Manifold 進入運算。
- **相依更新**：`requirements.txt` 新增 `networkx>=3.0`；`scripts/run_agent.bat` 的 VCPKG_ROOT 安裝路徑同步更新。

## Capabilities

### New Capabilities

- `boolean-non-manifold-tolerance`：定義 `boolean_operation()` 對非流型網格的容錯修補序列——觸發條件、修補子步驟的執行順序（退化面清理 → Mesh.merge() → seam 焊接 → 平面邊界封蓋 → fill_holes 退路）、各子步驟的採用條件，以及回退語意（任一條件未通過時不留下部分修改）。

### Modified Capabilities

無。既有 spec 未涵蓋 `boolean_operation()` 的修補流程；布林成功路徑的語意不變。

## Impact

**受影響程式碼**

- `agent/sla_operations.py` — `boolean_operation()` 函式新增多個閉包輔助函式；修補序列改寫；修補後新增驗證步驟。

**相依**

- `requirements.txt` 新增 `networkx>=3.0`；`scripts/run_agent.bat` 同步更新。
- 修補序列使用 `scipy.spatial.cKDTree`（seam 配對）、`scipy.sparse.csgraph.connected_components`（連通分量統計）、`shapely.ops.polygonize_full`（平面封蓋多邊形化）、`mapbox_earcut`（三角化）。

**API 契約**

- `boolean_operation()` 的函式簽章與回傳值形狀 `(bool, Optional[str])` 不變。
- 原本成功的布林流程（兩個網格均能直接轉換為有效 Manifold）路徑完全不受影響。
- 原本失敗的案例，修補成功時改回傳 `(True, None)`；修補不適用或失敗時仍回傳 `(False, error_message)`。

**不在範圍**

- 前端錯誤提示或錯誤碼傳遞。
- 通用型 STL 修復 API（修補序列僅在 `boolean_operation()` 失敗路徑內觸發）。
- `mesh_b` 的 seam 焊接與平面邊界封蓋（僅 `mesh_a` 套用完整序列）。
