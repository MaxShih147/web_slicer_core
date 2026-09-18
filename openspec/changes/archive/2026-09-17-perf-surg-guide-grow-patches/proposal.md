## Why

Surgical Guide Auto Orient（`POST /api/v2/auto-orient` mode=2 → `compute_auto_orientation_surg_guide_detail()`）先前的效能調查（見 `openspec/changes/archive/2026-09-15-optimize-auto-process-performance/design.md` Non-Goals：「不處理 Surgical Guide `_grow_patches` 等」）已確認 `_grow_patches()`（[agent/auto_orient_surg_guide.py:289](../../../agent/auto_orient_surg_guide.py#L289)）約占 `_find_guide_direction()` 執行時間的 50～57%，但當時範圍尚未界定，明確排除在該提案之外。

以真實手術導板模型（`SurgicalGuide_1.stl`）重新 profiling 確認：`_grow_patches()` 內部的 per-patch statistics 迴圈（[:334-358](../../../agent/auto_orient_surg_guide.py#L334-L358)）對**每一個** patch（含 88% 面數 <5、稍後必定被捨棄的小 patch）都重新以 `_norm(_cross(...))` 逐 face 計算面積，而非重用 `_weld_and_build()`（[:225](../../../agent/auto_orient_surg_guide.py#L225)）已向量化算好的 `mesh.face_area`；同時無條件計算一個沒有任何讀取者的欄位 `max_angle_deg`。量測顯示這段 statistics 迴圈若改為「只對 ≥5 face 的 patch 計算、重用 `mesh.face_area`」，耗時可從約 1.3 秒降至約 0.09 秒（SurgicalGuide_1.stl，15 倍量級）。

`agent/model_classifier.py::detect_drill_holes()` 是同一段 C++（`isDrillPatchByEdges`）的另一份 1:1 port，且已在 `2da36f1 perf(classifier): optimize drill hole detection` 完成完全相同性質的優化（pre-filter `>=5` faces、重用 `face_area`、略過 `max_angle_deg`）並穩定運行於生產環境——這是本提案的優化方向已被驗證安全的直接先例。

## What Changes

- **`_grow_patches()` per-patch statistics 只在 patch 面數 `>=5` 時計算**：面數 `<5` 的 patch 保留 `_Patch` 預設值（`area=0.0`、`avg_normal=zeros`、`center=zeros`），不執行任何額外運算。所有已知呼叫端（`_find_guide_direction()` 的 drill-candidate 篩選、`_refine_up_with_quasi_candidates()` 的 quasi-candidate 篩選）在讀取這些欄位前已各自套用 `len(P.faces) < 5` 或等價的門檻，因此此變更 SHALL 不改變任何可觀察輸出。
- **重用 `mesh.face_area`，移除逐 face 的 `_norm(_cross(...))` 面積重算**：`mesh.face_area` 已由 `_weld_and_build()` 以相同公式（`0.5 * norm(cross(e1,e2))`）向量化算好，且已是 `detect_concave_faces()`／`_entrance_dir_by_concave()` 等既有生產路徑的既有輸入——本項只是讓 `_grow_patches()` 的 statistics 迴圈與這些既有消費者使用同一份資料，不引入新的數值路徑。
- **停止計算 `max_angle_deg`**：全 repo 確認此欄位無任何讀取者（`_Patch` dataclass 定義處與 model_classifier.py 對應欄位皆為唯一出現處）。欄位定義保留（相容性），只移除計算本身。
- **不變更**：fixed seed normal 的 patch 成長語意、BFS assignment、face/seed traversal 規則、adjacency 建立方式、vertex weld `eps=1e-4`、非流型 edge 行為、導孔判定 threshold（PCA、scanline、conn-edge、turn-angle）、fallback 與 orientation 決策流程。這些留待後續 profiling 後再決定是否列入下一輪，本提案不預先承諾。

## Capabilities

### New Capabilities
- `surgical-guide-grow-patches-performance`：定義 `_grow_patches()` per-patch statistics 這項純效能改動必須維持的正確性契約（patch face membership、drill candidate 集合、fallback 分支、最終 orientation 等價）。

### Modified Capabilities
（無。本提案不修改任何既有 capability 的 spec 層級行為——`_grow_patches()` 目前沒有對應的既有 spec；本提案為其新增一份範圍限定於本輪改動的 spec。）

## Impact

- `agent/auto_orient_surg_guide.py`：`_grow_patches()`（[:289-360](../../../agent/auto_orient_surg_guide.py#L289-L360)）。
- 測試：新增 `agent/tests/test_auto_orient_surg_guide_grow_patches.py`（regression，覆蓋本輪行為與正確性邊界）。
- 不觸及：BFS region growing、adjacency/edge map 建立、vertex weld、`_is_drill_patch_by_edges()`（PCA／scanline／conn-edge／turn-angle）、concave vote、fallback 決策——留待下一輪視 profiling 結果決定範圍，不在本提案預先承諾。
- 測試模型（唯讀，不納入 Git）：`C:\Users\user\Pictures\tempTest\SurgicalGuide_1.stl` ~ `SurgicalGuide_4.stl`（自動搜尋實際找到 4 個，非原先預期的 3 個，已於 `design.md` 註記）。
