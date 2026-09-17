## Context

本提案是 Surgical Guide Auto Orient 效能優化系列的第四輪，緊接在 `perf-surg-guide-grow-patches`（Step 5 統計）、`perf-surg-guide-drill-patch-pca`（PCA）、`perf-surg-guide-bfs-region-growing`（BFS A2）之後。三輪皆尚未 commit，彼此獨立、互不重疊。以三輪疊加後的程式碼重新 profiling，`detect_concave_faces()`（經 `_entrance_dir_by_concave()` 呼叫）現在是 `_find_guide_direction()` 中最大的單一項目（約 40%～44%），大於已優化過的 `_grow_patches()`（約 22%～23%）與 `_is_drill_patch_by_edges()`（約 18%～22%）。

本輪之前已完成獨立的 scratch 調查（未落地為 production code），依序涵蓋：既有語意與 dtype 的逐項實測確認、Prototype A（inline float64 dot）、Full C（batch + `np.add.at`）、以及本提案的核心——Chunked C（4K／16K／64K／256K 四種固定 chunk size）在 5 個真實模型（約 97K～972K faces）與 10 個 synthetic 案例上的正確性與效能／記憶體比較。本提案把該調查的結論（固定 16K edges 的 Chunked C）正式轉為下一實作階段的規劃。

**採用新 change 而非調整既有三個 change 的依據**：與前三輪建立的先例一致——`detect_concave_faces()` 是 `_grow_patches()`／`_is_drill_patch_by_edges()`／BFS 之外完全獨立的函式與正確性風險面（累加語意、cylinder exclusion 時機、chunk 邊界），把它併入任一既有 change 會讓一個「範圍已完成、只差 commit」的變更重新變成進行中狀態，且四者的驗收線性質不同（統計欄位捨入 vs. PCA gate 等價 vs. BFS 離散門檻精度 vs. 本提案的分批累加等價），適合各自獨立的 spec 檔案。

## Goals / Non-Goals

**Goals（本階段，文件規劃）：**
- 把 scratch 階段已驗證的 Chunked C（16K edges）正式規劃為下一實作階段的目標算法，記錄其相對 Full C 與 Prototype A 的取捨依據。
- 完整定義本階段 SHALL 保留的既有語意（見 D3／spec.md），涵蓋 dtype、threshold、累加規則、非流型/boundary edge 處理、cylinder exclusion 時機、chunk 邊界行為。
- 以規格層級（而非不可靠的絕對數字）描述記憶體目標：暫存工作集受固定 chunk size 限制，不隨模型 edge 數線性成長。
- 規劃下一實作階段的驗證範圍（tasks.md），本階段不執行。

**Non-Goals**：見 `proposal.md` 完整清單（adaptive chunk size、Full C、動態 chunk 選擇、BFS/PCA/`_Patch` 後續優化、vertex weld/adjacency 重寫、edge map 語意修改、cylinder 演算法修改、其他剩餘瓶頸、整體完成宣告）。

## Decisions

### D1：為何選擇 Chunked C 而非 Full C

Full C（一次性 gather 全部 edge 對應的 face-index array，批次計算，`np.add.at` scatter）在函式層級量到約 89%～90% 的改善，但其暫存陣列（`f0_arr`／`f1_arr`／`fc0`／`fc1`／`fn0`／`fn1`／`dx`／`dy`／`dz`／`dot0`／`dot1`／`mask0`／`mask1`）皆以「模型的 interior edge 總數」為長度——在 5 個真實模型（約 97K～972K faces，edge 數約 146K～1.46M）上的測量確認，這些暫存陣列造成的額外記憶體隨 edge 數增加而增加。

Chunked C 沿用 Full C 完全相同的數學與累加語意，只把「一次處理全部 edges」改為「固定大小的批次，處理完釋放暫存，再處理下一批」。Scratch 測量顯示：Chunked C 在所有測試的 chunk size（4K／16K／64K／256K）上速度都優於或相當於 Full C，且暫存陣列大小由 chunk size（一個常數）決定，不再隨模型規模成長。這是本提案採用分批處理、放棄 Full C 的直接依據。

### D2：為何選擇 16K 而非 4K／64K／256K

Scratch 比較顯示：
- 4K 與 16K 在所有測試模型上的執行時間非常接近，兩者都明顯快於 64K 與 256K。
- 隨 chunk size 增加（64K、256K），執行時間與暫存記憶體都逐漸趨近 Full C 的量級——256K 是四個測試尺寸中最接近 Full C 兩種代價（速度變慢、記憶體增加）的一個，不具備「兼顧速度又省記憶體」的折衷優勢。
- 4K 與 16K 之間，16K 的 chunk 迴圈次數較少（處理同樣數量的 edges 所需的批次數是 4K 的四分之一），在效能幾乎相同的前提下降低了 Python 層級的迴圈開銷來源數量。

**本提案選擇固定 16K edges**，作為 4K 與 16K 這組效能相近的選擇中，迴圈次數較少的一個；不採用 64K／256K（更接近 Full C 的缺點）；不做自適應選擇（見 Non-Goals，缺乏證據支持需要動態調整）。

### D3：正確性邊界（本階段的核心，SHALL 逐項保留）

以下語意在 Chunked C 的實作與驗證中 SHALL 完全保留，任一項改變都視為需要調整實作或還原本項優化的訊號：

1. **dtype**：face centers（`mesh.face_c`）與 face normals（`mesh.face_n`）進入本函式後 SHALL 轉為 float64（`.astype(np.float64)`），全程 float64 運算——這與 BFS 的 `_dot()`（float32-until-final-cast）是不同的精度路徑，不應混淆或誤植。
2. **算術語意**：edge concavity 的計算（face-center 差向量與各自 face normal 的三分量點積）SHALL 維持與現行 `d @ fn[f0]` 數學等價的明確三分量運算式，不引入會改變加總順序或 dtype 的 `einsum`、`sum(axis=...)` 或其他 reduction。
3. **concavity 判斷**：SHALL 維持嚴格的 `> 1e-6`（不得改為 `>=`或其他容忍值）。
4. **ratio 判斷**：per-face `votes/total >= 0.55` SHALL 不變。
5. **累加規則**：每一條有效（`f1 >= 0`）interior edge SHALL 對其兩側 face 的 `total` 各自累加恰好 1.0；兩側的 `votes` SHALL 各自根據該側 face 自己的 normal 獨立判斷，不得假設兩側對稱或共用同一次判斷結果。
6. **boundary edge**：`f1 < 0`（無第二個 face）的 edge SHALL 維持現行的完全跳過（不進入 votes/total 累加），不因分批處理而改變判斷時機或方式。
7. **非流型 edge**：`mesh.edge_faces` 既有的 first-two-faces-only 語意（第三個以上共用同一 edge 的 face 從不被登記）SHALL 原樣繼承，不在本函式內重新定義或補償這個拓撲來源的既有行為。
8. **cylinder exclusion 時機**：SHALL 繼續在**所有** edge 的 votes/total 累加完成、且 `ratio >= 0.55` 篩選出候選 `concave` 集合**之後**才執行，不得提前、不得與累加或分批處理交錯。
9. **cylinder 邊界慣例**：`radial <= radius` 的邊界情況 SHALL 繼續視為 inside（被排除），維持現行 `<=` 慣例。
10. **跨 chunk 累加**：同一個 face 若其累加邊被分配到不同的 chunk（該 face 的邊在批次邊界前後都有出現），最終 `votes`／`total` SHALL 與所有邊在同一批次處理時完全一致——累加目標是持久化的 `votes`/`total` 陣列（貫穿所有 chunk），不因批次切換而重置或遺漏。
11. **partial chunk**：最後一批不足 16K edges 的批次（chunk 大小 = 剩餘 edge 數）SHALL 正確處理，不得因為批次未滿而跳過、截斷或以未初始化資料計算。
12. **輸出等價**：最終 `concave` face 集合（含順序，若既有實作有隱含順序）、`_entrance_dir_by_concave()` 的方向、`res.dir`、`rotation_rad` SHALL 與現行實作完全相同。

### D4：記憶體目標的表達方式——規格層級描述，不使用不可靠的絕對數字

Scratch 階段的量測顯示：在部分模型／chunk size 組合下，量到的「增量峰值記憶體」看起來是 0（因為分批的暫存陣列大小小於模型載入與前置步驟已經達到的記憶體高點，量測方法本身無法讓這類情況顯示出正的增量）。**這不代表分批處理實際上零成本**，只代表在該次量測條件下，分批的暫存陣列沒有把「整個 process 的峰值工作集」推得比已有的高點更高。因此本提案的效能／記憶體契約 SHALL 以下列方式表達，不引用可能失真的絕對數字：

- 分批處理 **MUST NOT** 在任何時間點同時具現化「一次容納模型全部 interior edges」所需的完整 Full C 暫存陣列組合。
- 分批處理造成的暫存工作集 **SHALL** 由固定的 chunk size（16K edges）決定量級，**SHALL NOT** 隨模型的總 edge 數等比例成長。
- 具體驗收方式留待實作階段的正式 Phase 0／驗證基準決定（例如：在不同規模模型上量測增量峰值記憶體，確認其量級不隨模型 edge 數增加而等比例成長），本提案不預先承諾某個絕對 MB 數字或每 edge 的 byte 數，因為 scratch 階段的估算存在量測方法本身的侷限（見上），不應被當作正式驗收基準。

## 實作與驗證記錄（已完成）

**落地方式**：`detect_concave_faces()` 的逐 edge Python 迴圈改為固定 `chunk_edges = 16384` 分批處理，內部 `_accumulate_chunk()` 沿用 scratch 階段驗證過的數學（batch gather face centers/normals、明確三分量運算、`np.add.at` 累加），`votes`/`total` 陣列貫穿所有 chunk 持久化。Cylinder exclusion 區塊完全未變動。

**正式 regression test**（`agent/tests/test_auto_orient_surg_guide_detect_concave_chunking.py`，13 tests，合成 `_Mesh`，不依賴外部 STL）：涵蓋 concavity `> 1e-6` 嚴格大於（含恰好等於 threshold）、ratio `>= 0.55`（含恰好等於 0.55）、boundary edge 跳過、非流型 edge 既有登記語意、degenerate 法向量、同一 face 單一 chunk 內多 edge 累加、**同一 face 累加邊刻意跨越生產環境實際的 16384 chunk 邊界**（`n_neighbors = 2*16384+11`，最後一批為 11 個 edge 的 partial chunk）、cylinder inside/outside/邊界（`<=` 視為 inside）、cylinder exclusion 在完整累加後才執行（面對橫跨 2 個 chunk 的累加，排除判斷仍正確）、空結果、全部通過、跨呼叫確定性。全部 13 項 **PASS**。

**代表模型 A/B（5 個真實模型，97K～972K faces，含約 1M faces 的 `SurgicalGuide_1M.stl`）**：scratch Reference（原始逐 edge `@` 運算子迴圈，保留於 scratch 供比對）與現行 production（16K chunked）的 `concave` 面索引集合、`_entrance_dir_by_concave()` 方向 **全數 bit-exact**；`compute_auto_orientation_surg_guide_detail()` 的 `rotation_rad` 在全部 5 個模型上 **完全相同**。

**Benchmark（7 次交錯執行，median 為主要結果；chunk 建立、face-index array 轉換、gather、`np.add.at` scatter 成本皆計入量測邊界）**：

| 模型 | `detect_concave_faces()` | `_entrance_dir_by_concave()` | `_find_guide_direction()` | `compute_..._detail()` |
|---|---|---|---|---|
| SurgicalGuide_2 (146K edges) | 428.7→27.9ms（−93.5%） | 438.1→27.6ms（−93.7%） | 1019.7→627.5ms（−38.5%） | 1025.3→625.1ms（−39.0%） |
| SurgicalGuide_3 (241K edges) | 692.2→44.9ms（−93.5%） | 689.9→45.6ms（−93.4%） | 1733.7→1091.2ms（−37.1%） | 1742.3→1064.7ms（−38.9%） |
| SurgicalGuide_1 (302K edges) | 876.4→60.6ms（−93.1%） | 873.5→61.6ms（−92.9%） | 2253.8→1428.7ms（−36.6%） | 2220.3→1435.1ms（−35.4%） |
| SurgicalGuide_4 (354K edges) | 1036.8→67.9ms（−93.4%） | 1024.5→71.0ms（−93.1%） | 2603.0→1617.7ms（−37.9%） | 2579.7→1587.5ms（−38.5%） |
| SurgicalGuide_1M (1.46M edges) | 4213.9→329.2ms（−92.2%） | 4222.6→327.6ms（−92.2%） | 10450.7→6486.7ms（−37.9%） | 10263.5→6395.9ms（−37.7%） |

**上表數字為相對「Phase 1＋Round 2＋A2」版本的增量改善**，與其他階段的改善百分比屬不同 session 量測，不可直接相加宣稱累積改善。量測期間觀察到明顯的機器負載噪聲（部分執行的 max 達 median 的 5 倍以上），但 5 次獨立量測（本階段 1 次 + 先前 scratch 調查 4 次）的 median 彼此高度一致（例如 1M 模型 `detect_concave_faces()` 的 median 在不同次量測中落在 320～330ms 區間），驗證了「以 median 而非單次或最小值作為主要結論」這個方法論本身的必要性與有效性。

**記憶體（正式驗證，已完成）**：

**量測方法**：先前 scratch 階段用 `PeakWorkingSetSize`（Windows 對整個 process 生命週期追蹤的歷史峰值）前後相減估算「增量峰值」，已知會在模型載入／`_weld_and_build()`／`_grow_patches()` 等前置步驟已經把峰值推得很高時，把 `detect_concave_faces()` 自身的實際成本錯誤地顯示為 0——這不是真的零，只是量測方法本身的侷限。本次改採方法：每個模型獨立 subprocess（避免跨模型污染），在呼叫 `detect_concave_faces()` **之前**讀取當下的 `WorkingSetSize`（current RSS，非歷史峰值）作為 baseline，呼叫**期間**由背景執行緒以緊迴圈持續輪詢 current RSS 記錄峰值，呼叫後再取一次確保不漏掉呼叫結束瞬間的尖峰，最終以「執行期間峰值 − 呼叫前 baseline」作為增量。

**方法可信度校準**：以已知大小（50／100／200／400 MB）、刻意極短生命週期（配置後立即釋放，不額外持留）的 numpy 陣列配置作為 ground truth 測試這套採樣方法，量到的增量與目標大小的比值穩定落在 **1.05**（5% 誤差，來自陣列物件本身的額外開銷），對短至數十毫秒的尖峰同樣準確——確認此方法能可靠捕捉短生命週期尖峰，不依賴 `PeakWorkingSetSize` 的歷史語意。

**5 個真實模型（97K～972K faces）的量測結果**（每模型 5 次重複呼叫，同一 subprocess 內；取 median）：

| 模型 | faces | edges | 呼叫前 baseline RSS | 執行期間峰值 RSS | 增量峰值（median） | 增量／face |
|---|---|---|---|---|---|---|
| SurgicalGuide_2 | 97,372 | 146,056 | 204.74MB | 214.54MB | 9.80MB | 100.6 bytes |
| SurgicalGuide_3 | 160,666 | 240,997 | 253.70MB | 269.64MB | 15.94MB | 99.2 bytes |
| SurgicalGuide_1 | 201,574 | 302,361 | 304.95MB | 326.61MB | 21.66MB | 107.5 bytes |
| SurgicalGuide_4 | 236,034 | 354,051 | 328.31MB | 353.60MB | 25.29MB | 107.1 bytes |
| SurgicalGuide_1M | 972,248 | 1,458,362 | 896.80MB | 997.07MB | 100.27MB | 103.1 bytes |

正確性交叉檢查（同一次量測，透過既有 scratch Reference helper，未修改 production code）：5 個模型的 `concave` 面索引集合、`_entrance_dir_by_concave()` 方向 **全數 bit-exact**（`concave_match=True`／`dir_match=True`），與本 change 先前的實作驗證記錄一致。

**增量峰值隨模型規模成長，但每 face 的增量在跨越約 10 倍模型規模範圍下維持在 99～108 bytes 的窄幅範圍內**——這與必要輸出陣列（`fc`／`fn`／`votes`／`total`，理論上每 face 恰好 64 bytes：`fc`+`fn` 各 3 分量、`votes`+`total` 各 1 分量，皆為 float64）乘上一個穩定的配置器／OS 開銷倍率（約 1.55～1.68 倍，經另一組校準測試確認：`np.zeros()` 配置的陣列在 Windows 上採用延遲頁面提交，實際頁面提交發生在第一次寫入時——即 `np.add.at` 累加當下——而非配置當下；這個「首次寫入才提交實體頁面」的行為，加上 `.astype(float64)` 轉型建立新陣列的開銷，合理解釋了理論值與實測值之間的差距）完全吻合，**沒有出現任何暗示「暫存陣列隨 edge 數額外成長」的訊號**（若存在，bytes/face 應隨模型增大而系統性上升，而非維持平坦）。

**已知的量測侷限**：這 5 個真實模型的 edge/face 比例剛好都精確等於 1.5（封閉流形三角網格的典型值），意味著 face 數與 edge 數在這組模型上完全共線，單靠這個實測資料本身，無法把「隨 face 數成長」和「隨 edge 數成長」兩種假設完全區分開來。**但這個侷限不影響本項要求的驗收結論**，因為分批暫存陣列（`f0_arr`／`f1_arr`／`fc0`／`fc1`／`fn0`／`fn1`／`dx`／`dy`／`dz`／`dot0`／`dot1`／`mask0`／`mask1`）是否受 edge 數量成長影響，已直接以程式碼審查獨立確認：`detect_concave_faces()` 全函式範圍內沒有 `list(mesh.edge_faces.values())` 或任何等價的完整 edge 具現化操作；`mesh.edge_faces.values()` 是直接疊代（dict view，不建立新 list）；`buf_f0`／`buf_f1` 兩個緩衝區在每累積滿 `chunk_edges = 16384` 筆後立即處理並重置為空列表，`_accumulate_chunk()` 內的每個中間陣列長度恆等於當批次大小（最後一批 partial chunk 除外，其大小 ≤ 16384）——這個結構性保證不依賴、也不受這批測試模型 edge/face 比例巧合的影響。

## 四輪整合驗收（已完成，2026-09-17）

本節記錄 Surgical Guide Auto Orient 效能優化系列四個獨立 change——`perf-surg-guide-grow-patches`（`_grow_patches()` per-patch statistics）、`perf-surg-guide-drill-patch-pca`（PCA projection/covariance）、`perf-surg-guide-bfs-region-growing`（BFS region growing）、本提案（`detect_concave_faces()` chunking）——疊加在同一份 working tree 上，相對原始 HEAD 基準的整合驗收結果。放在本文件（四輪中最後落地的一個）以避免同一份證據在四份 design.md 中重複記載；其餘三份文件僅留一句指向本節的交叉參照。

**方法**：以獨立 `git worktree` 隔離原始 HEAD（未使用 `checkout`／`reset`／`stash` 觸碰 production 檔案），對 5 個真實模型（`SurgicalGuide_1`／`_2`／`_3`／`_4`／`_1M.stl`，97K～972K faces）在獨立 subprocess 中分別對 HEAD 版本與目前 working tree 版本執行 A/B 正確性比對與交錯（interleaved）效能量測。

**A/B 正確性（5 個模型全數通過）**：`_grow_patches()` 的 face-level patch membership 100% 相同；導孔 patch 的 accept/reject 判定完全一致；`detect_concave_faces()` 的 `votes`／`total`／`concave` 面索引集合全數 bit-exact；entrance direction 與最終 `rotation_rad`（`compute_auto_orientation_surg_guide_detail()`）在全部 5 個模型上皆一致。面數 `>=5`（實際被下游消費）的 patch 統計值（`area`／`avg_normal`／`center`）存在微小浮點差異，來源為 `perf-surg-guide-grow-patches/design.md` D2 已記載的加總順序改變（`numpy.sum(axis=0)` pairwise 累加 vs. 原本逐 patch Python `+=` 序列累加），非新的數值路徑或邏輯分支；全 5 模型重新掃描後的真實極值為 `area` 最大絕對誤差 **1.802e-6**（相對誤差 **5.28e-9**，出現在 `SurgicalGuide_1` 一個 845-face 的 patch，id 2917）、`avg_normal` 最大 1.192e-7、`center` 最大 3.815e-6，詳細推導與根因分析見 `perf-surg-guide-grow-patches/design.md`「重要澄清」段落。這些差異未在任何模型上造成 PCA 直徑/aspect gate、scanline、conn-edge、220° turn-angle 或 concavity/cylinder gate 的判定改變。

**累積效能改善（原始 HEAD → 四項優化疊加後，5 個模型、7 次交錯執行取 median）**：

| 階段 | 改善範圍（5 模型） |
|---|---|
| `_grow_patches()` | 約 76%～79% |
| `_is_drill_patch_by_edges()`（累積呼叫成本） | 約 34%～36% |
| `detect_concave_faces()` | 約 92%～94% |
| `_find_guide_direction()` | 約 65%～66% |
| 完整核心入口 `compute_auto_orientation_surg_guide_detail()` | 約 64.6%～67.9% |

此為原始版本到目前最終版本的一次性實測累積改善，並非四輪各自的增量改善百分比相加所得。

**測試**：四項優化的目標 regression test（`test_auto_orient_surg_guide_grow_patches.py`／`test_auto_orient_surg_guide_drill_patch_pca.py`／`test_auto_orient_surg_guide_bfs_region_growing.py`／`test_auto_orient_surg_guide_detect_concave_chunking.py`）合計 **34/34 全數通過**；完整套件 `pytest agent/tests/ -q --continue-on-collection-errors`：**699 passed、1 failed、3 errors**，與四輪優化開始前即存在的既有基準（`test_prz_print_time.py` 既有斷言失敗、3 個缺少 `httpx` 的 collection error）完全相同，**未新增任何失敗**。

**範圍聲明**：以上確認的是「四個獨立優化階段完成、彼此相容、疊加後行為與原始版本等價」，**不代表 Surgical Guide Auto Orient 整體效能優化已經全部結束**——`_weld_and_build()` 的 edge/adjacency 建立與其他未來瓶頸仍是待評估的候選，見上方與各自 change 的 Open Questions；是否需要進一步優化留待下一輪視新的 profiling 決定。

## Risks / Trade-offs

- **[跨 chunk 累加正確性]**（已解決）→ 正式 regression test 以刻意跨越生產環境實際 16384 chunk 邊界的合成案例驗證，結果與單一批次處理完全一致；5 個真實模型的完整流程 A/B 亦確認 bit-exact。
- **[16K 是否對所有模型規模都適用]**（已用 97K～972K faces 的 5 個模型驗證方向一致，含實作後的完整流程 A/B）→ 證據涵蓋約一個數量級的模型規模範圍，方向支持固定 16K；若未來出現遠超出此範圍的模型（例如遠大於 972K faces 或遠小於 97K faces），SHALL 用該規模的真實或代表性模型重新確認，不假設外推有效。
- **[記憶體驗收線的表達方式]**（已完成正式驗證）→ D4 的規格層級表達（不引用絕對數字作為契約本身）維持不變，但本階段已用方法論修正過的 subprocess 隔離量測（呼叫前 current RSS baseline + 執行期間持續採樣峰值，而非先前 scratch 階段依賴、已知會低估的歷史 `PeakWorkingSetSize` 前後差）取得正式數字：5 個模型的增量峰值per-face 維持在 99～108 bytes 的窄幅範圍，搭配程式碼審查確認的「無完整 edge 具現化」結構性保證，兩者共同構成本項要求的驗收證據。

## Migration Plan

| 階段 | 內容 | 狀態 |
|---|---|---|
| 0 | OpenSpec 規劃（proposal/design/specs/tasks），記錄 scratch 調查結論與正確性邊界 | 已完成 |
| 1 | 正式基準建立與 A/B 快照（5 個真實模型，97K～972K faces） | 已完成 |
| 2 | Chunked C（16K）實作 | 已完成 |
| 3 | A/B 正確性驗證（5 個真實模型 + 13 項合成 regression test，含 chunk 邊界/partial chunk/cylinder 時機） | 已完成，全數 PASS |
| 4 | Benchmark（速度）與 regression test | 已完成——速度見上方「實作與驗證記錄」 |
| 5 | 記憶體正式驗證（方法論修正：呼叫前 current RSS baseline + 執行期間峰值採樣） | 已完成——見上方「記憶體（正式驗證，已完成）」 |

**本階段完成 = `detect_concave_faces()` 這一個效能候選完成規劃、實作、驗證與收斂；不代表 Surgical Guide Auto Orient 整體效能優化已經結束。** 見 `proposal.md` Non-Goals 與下方 Open Questions。

## Open Questions（下一階段之後的候選，本階段不處理）

- **`_weld_and_build()` 的 edge/adjacency 建立**：三輪優化與本提案完成後，`_weld_and_build()` 佔 `_find_guide_direction()` 的相對比例可能因分母縮小而提高，是否列入未來某一輪需視屆時新的 profiling 決定。
- **是否需要重新評估 adaptive chunk size**：本階段的 Non-Goals 明確排除，但若未來出現遠超出目前測試範圍（97K～972K faces）的模型規模，可能需要重新蒐證，不應假設本階段的結論無限外推。
