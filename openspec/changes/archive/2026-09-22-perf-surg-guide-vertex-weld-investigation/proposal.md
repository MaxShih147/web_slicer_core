## Why

Surgical Guide Auto Orient（`POST /api/v2/auto-orient` mode=2 → `compute_auto_orientation_surg_guide_detail()`）的 edge-map／adjacency 效能路線已於獨立調查中結案（`STOP_EDGE_MAP`：該輪調查已實際建立並完整量測 Candidate #3 prototype，但其效能未達預先設定的採用門檻，因此決定不採用、不併入 production，也不再繼續 edge-map 方向的後續最佳化——並非「未建立 prototype 就判定不值得投入」）。同一輪調查的 corrected report 指出，`_weld_and_build()`（[agent/auto_orient_surg_guide.py:225](../../../agent/auto_orient_surg_guide.py#L225)）內僅次於 edge-map 的第二大子階段是 vertex quantization／weld（[:227-243](../../../agent/auto_orient_surg_guide.py#L227-L243)，約占 `_weld_and_build()` 10～13%、完整 core 3.1～3.5%），因此需要一輪獨立、只讀（read-only）的後續調查，確認該子階段是否值得投入 prototype 化。

本提案的目的**不是導入任何程式碼變更**，而是把該輪調查（含一次算術錯誤的補正）的結論、量化依據與決策邊界，以 OpenSpec 形式正式留存，供未來重新評估時依循，並明確劃定其與既有四輪已完成優化、以及 `STOP_EDGE_MAP` 決策之間的關係。

## What Changes

- **新增一份決策紀錄 capability**，記載 vertex quantization／weld 調查的結論：
  - 即使**完全消除**整個 vertex-weld 階段，完整 core（`compute_auto_orientation_surg_guide_detail()`）理論上限改善也僅約 **3.14～3.49%**（五個代表模型皆然）；此數字以既有、未受本輪執行環境干擾之基準量測為依據，是 `STOP_VERTEX_WELD` 的主要判斷根據。
  - 針對候選方案（`np.unique(axis=0, return_index=True, return_inverse=True)` 向量化分組）：其**分組公式產生的 `rep_of_vertex` 輸出**已通過正確性驗證（與 production／mirror 的 `rep_of_vertex` 逐元素比對，6 個 synthetic cases + 2 個真實模型，合計 8/8 cases exact match）——此驗證範圍僅止於該公式本身的輸出，**不包含**完整 `_weld_and_build()` production 整合、downstream（`_grow_patches()`／`_is_drill_patch_by_edges()`／`detect_concave_faces()`／最終 `rotation_rad`）bit-exact A/B，也**不包含**該候選方案的 peak-memory A/B（見 Non-Goals）。依公式 `stage/core × loop/stage × candidate loop improvement` 重新計算之預估完整 core 改善為：SurgicalGuide_1～4 約 **0.61～0.82%**；SurgicalGuide_1M 約 **0.146%**，但其量測受當次執行環境（thermal／contention）干擾，僅能視為不穩定估算，不得當作精確 production 預測。舊版報告曾誤算為 0.16～0.22%，屬換算時的算術錯誤；現有資料無法可靠還原舊計算的確切步驟，本提案不推定具體錯誤成因，只記錄補正後數值與公式本身。
  - 記憶體面向：`quant`（約 11.13 MiB，量測）、`rep_of_vertex`（約 1.85 MiB，量測）、`vmap`（約 108.5 MiB，**結構性估算**，非 measured RSS）三者在 SurgicalGuide_1M 上合計約 **121.5 MiB**，是「在進入 edge-map 前已不再需要卻仍存活」的 dead-object 機會，但本輪**未執行** early-release 或 `np.unique` 候選的 peak-memory A/B，因此這只是 structural dead-object estimate，不是已證實可回收的 peak-memory 數字。
  - 效能澄清：`del vmap` 若使該 dict 的 reference count 歸零，CPython 需解構約 486K 筆 dict entries／tuple／int object，其容器解構成本應視為約 **O(N)**，不可寫成 `O(1)`；提前刪除主要只是把「函式結束時本來就會發生」的清理時點提前，並非保證降低 wall time 或 peak memory。
  - 明確排除 edge-map Candidate #3 prototype 的 `≥5%` 驗收門檻作為 vertex-weld 的共用正式門檻——該門檻僅屬於 edge-map 那一輪自己的驗收設計，本決策單純依據 vertex-weld 自身的理論上限（3.14～3.49%）與目前缺乏明確記憶體需求作出停止判斷。
  - 明示本決策**不影響**先前四輪已完成的 Surgical Guide Auto Orient 效能優化（`_grow_patches()` patch statistics、`_is_drill_patch_by_edges()` PCA、fixed-seed BFS region growing、`detect_concave_faces()` 16K chunking），也**不重新開啟** `STOP_EDGE_MAP` 決策。
- **不變更任何 production 程式碼、測試或既有 spec**：`agent/auto_orient_surg_guide.py` 本身未被修改；本提案純粹是把既有只讀調查的結論正式化、可追溯化。
- **不新增／不修改任何 API、前端、分類器或其他 pipeline 行為**。

## Capabilities

### New Capabilities
- `surgical-guide-vertex-weld-performance-decision`：記載 vertex quantization／weld 效能調查的量化結論（完整 core 理論上限、候選方案補正後預估收益、記憶體與複雜度風險）與「目前不值得投入 production prototype」的停止決策（本輪為只讀調查，未如 edge-map 該輪建立效能 prototype——見 Impact），作為未來重新評估此子階段時的既定基準與觸發條件。

### Modified Capabilities
（無。本提案不變更任何既有 capability 之 requirement-level 行為——`_grow_patches()`、`_is_drill_patch_by_edges()`、fixed-seed BFS、`detect_concave_faces()` 16K chunking 對應的既有 spec 維持原狀，不受本決策影響；edge-map／adjacency 之 `STOP_EDGE_MAP` 決策亦維持原狀，本提案不重新開啟。）

## Impact

- `agent/auto_orient_surg_guide.py`：**未修改**（本提案為純文件／決策留存）。
- 測試：**未新增／未修改**（無程式碼行為變更，無需回歸測試）。
- 受影響範圍：僅新增 `openspec/specs/surgical-guide-vertex-weld-performance-decision/spec.md` 一份決策紀錄型 spec；不觸及任何既有 spec 或程式碼路徑。
- 調查依據（唯讀，不納入本次程式碼變更，僅作為佐證留存於 repo 外）：
  - `C:\D\phrozen_slicer\weld_and_build_vertex_weld_investigation_2026-09-22.md`（含 2026-09-22 補正版本）
  - `C:\D\phrozen_slicer\weld_and_build_vertex_weld_investigation_results.json`（含 `post_review_correction_2026_09_22` 節點）
  - `C:\D\phrozen_slicer\weld_and_build_edge_map_investigation_2026-09-21_corrected.md`（`_weld_and_build()` 各子階段占比基準）
