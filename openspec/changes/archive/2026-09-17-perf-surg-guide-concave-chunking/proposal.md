## Why

Surgical Guide Auto Orient 已完成三輪效能優化（`perf-surg-guide-grow-patches`：`_grow_patches()` per-patch statistics；`perf-surg-guide-drill-patch-pca`：`_is_drill_patch_by_edges()` PCA projection/covariance；`perf-surg-guide-bfs-region-growing`：BFS region growing 的 A2 向量化；三者皆尚未 commit）。以 Phase 1＋Round 2＋A2 疊加後的程式碼重新 profiling 確認：**`detect_concave_faces()`（經由 `_entrance_dir_by_concave()` 呼叫）現在占 `_find_guide_direction()` 約 40%～44%，是目前最大的單一瓶頸**——大於已優化過的 `_grow_patches()`（約 22%～23%）與 `_is_drill_patch_by_edges()`（約 18%～22%）。

針對此函式已完成獨立的 scratch 調查與 prototype 比較（未落地為 production code），依序驗證：
1. **既有語意的精確 dtype／算術確認**：`detect_concave_faces()` 的 face centers／normals 進入函式後即轉為 float64，全程 float64 運算（與 BFS 的 `_dot()` float32-until-the-end 路徑不同，逐項實測確認，不依賴類比假設）；edge 累加對 votes/total 的貢獻已證明與 dict 疊代順序無關（浮點精確整數累加，非近似）。
2. **Prototype A**（inline 三分量 float64 dot，取代 `@` 運算子）：函式層級改善約 38%～40%。
3. **Full C**（batch gather + `np.add.at` scatter，一次處理全部 edges）：函式層級改善約 89%～90%，但暫存陣列大小隨模型 edge 數線性成長，已在 5 個真實模型（約 97K～972K faces）上實測確認其額外記憶體隨 edge 數增加。
4. **Chunked C**（沿用 Full C 的數學與累加語意，改為固定大小分批處理 edge，測試 4K／16K／64K／256K 四種 chunk size）：在全部 5 個真實模型與 10 個 synthetic 案例（含刻意跨越 chunk 邊界的同 face 累加）上 **bit-exact** 於 Reference；速度與 Full C 相當或更快；暫存工作集不隨模型 edge 數成長，而是由 chunk size 決定量級。16K 與 4K 效能接近，但 chunk 迴圈次數較少，作為正式候選的折衷點。

本提案的目標是把 Chunked C（固定 16K edges）正式規劃為下一個實作階段，取代目前逐 edge 的 Python `@` 迴圈。

## What Changes

- **`detect_concave_faces()` 的 edge concavity 累加計算改為固定 16K edges 分批處理**：沿用已於 scratch 驗證過的數學與累加語意（float64 全程運算、批次 gather face centers/normals、明確三分量運算取代 `@`、`np.add.at` 累加 votes/total），只將處理粒度從「一次全部 edges」（Full C）改為「固定大小的批次」，避免建立與模型 edge 數等比例成長的完整暫存陣列。
- **不改變**：任何幾何判定邏輯、threshold 數值、跳過規則、cylinder exclusion 的時機與語意——完整清單見 `design.md` D3 與 `specs/surgical-guide-concave-chunking-performance/spec.md`。
- **本階段（文件規劃）不做**：不修改 production code、不新增/修改測試、不執行正式 benchmark（沿用 scratch 階段已完成的探索性數據作為設計依據，正式 Phase 0 基準留待實作階段重新建立）、不 commit、不 push。

## Capabilities

### New Capabilities
- `surgical-guide-concave-chunking-performance`：定義 `detect_concave_faces()` 分批處理這項純效能改動必須維持的正確性契約（逐 edge 判定、逐 face votes/total、concave 集合、cylinder exclusion、最終 orientation 等價），以及暫存工作集必須受固定 chunk size 限制、不得隨模型 edge 數線性成長的效能契約。

### Modified Capabilities
（無。本提案獨立於前三輪——`surgical-guide-grow-patches-performance`（Step 5 統計）、`surgical-guide-drill-patch-pca-performance`（PCA）、`surgical-guide-bfs-region-growing-performance`（BFS A2）——互不重疊、可各自獨立驗證與 commit，本提案不修改上述任一既有 change 或其檔案。）

## Impact

- `agent/auto_orient_surg_guide.py`：`detect_concave_faces()`。**本提案階段尚未修改此檔案**——見 Non-Goals。
- 測試：規劃新增 regression test（實作階段補上，本階段不新增），涵蓋範圍見 `tasks.md`。
- 不觸及：`_grow_patches()`、`_is_drill_patch_by_edges()`、`_weld_and_build()`、edge map（`mesh.edge_faces`）建立語意、cylinder 演算法本身、`_entrance_dir_by_concave()` 以外的呼叫端。
- 測試模型（唯讀，不納入 Git）：`C:\Users\user\Pictures\tempTest\SurgicalGuide*.stl`，目前已知涵蓋約 97K～972K faces 的 5 個模型。

## Non-Goals

- **Adaptive chunk size**：本階段固定 16K，不研究依模型大小動態調整 chunk size 的演算法——scratch 證據顯示固定 16K 已能在 97K～972K faces 的範圍內取得接近最佳效能，未發現需要自適應的證據。
- **Full C（不分批的完整 batch + scatter）**：已評估，記憶體隨 edge 數線性成長，不採用。
- **動態在 4K／16K／64K／256K 之間選擇 chunk size**：本階段固定採用 16K，不引入執行期選擇邏輯。
- **BFS、PCA 或 `_Patch` 的後續優化**：分屬前三輪已完成或已評估的範圍，本階段不重複觸碰。
- **vertex weld 或 adjacency 重寫**：`_weld_and_build()` 不在本階段範圍。
- **edge map（`mesh.edge_faces`）語意修改**：非流型 edge 的 first-two-faces-only 規則、boundary edge 表示方式維持現狀，不重新定義拓撲來源。
- **cylinder 演算法修改**：cylinder inside/outside 判定公式與邊界慣例（`<=` 視為 inside）維持現狀，只有 exclusion 執行時機的既有語意需要保留（見正確性邊界），不改變判定邏輯本身。
- **其他 Auto Orient 剩餘瓶頸**：`_weld_and_build()` 的 edge/adjacency 建立、其他尚未處理的成本來源留待未來視新 profiling 決定，不在本階段自動擴大範圍。
- **宣告整體 Auto Process／Surgical Guide Auto Orient 效能優化全部完成**：本階段只完成 `detect_concave_faces()` 這一個效能候選，不代表整體優化結束。
