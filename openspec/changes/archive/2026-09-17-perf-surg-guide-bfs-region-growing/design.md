## Context

本提案是 Surgical Guide Auto Orient 效能優化系列的第三輪。前兩輪（`perf-surg-guide-grow-patches`、`perf-surg-guide-drill-patch-pca`，皆尚未 commit）分別處理了 `_grow_patches()` 的 per-patch statistics 與 `_is_drill_patch_by_edges()` 的 PCA projection/covariance。兩份文件都在 Non-Goals／Open Questions 中「提到」BFS，但都只是排除範圍或待辦提示的一句話，沒有做過任何拆解、量化或正確性分析——本提案是第一份針對 BFS 的正式規劃文件，不把先前的提及視為已涵蓋本輪範圍。

**採用新 change 而非調整既有 change的依據**：
1. `perf-surg-guide-grow-patches` 的 scope 明確限定在 `_grow_patches()` 的 Step 5（per-patch statistics），其 19 個 task 中 18 個已完成、對應的 spec（`surgical-guide-grow-patches-performance`）內的 3 條 Requirement 全部針對 Step 5 的統計欄位（`.area`/`.avg_normal`/`.center`/`.max_angle_deg`）——BFS（Step 4）是同一函式內完全不同的程式碼區塊、不同的正確性風險（門檻比較的浮點精度 vs. 統計欄位的浮點捨入），把它塞進同一個 change 會讓一個已經「範圍完成、只差 commit」的變更重新變成進行中狀態，且該 change 的 spec 若要涵蓋 BFS 需要新增與現有 3 條 Requirement 性質不同的內容，界線會變得模糊。
2. 前一輪（PCA）已建立明確先例：使用者當時明確要求「不要把這次 PCA 優化塞進既有的 `perf-surg-guide-grow-patches` change」，理由是每輪應可獨立驗證、獨立 commit。BFS 與 PCA 一樣是 `_grow_patches()`／`_is_drill_patch_by_edges()`之外的另一個獨立子區塊，套用相同理由：獨立 change 讓三輪（stats／PCA／BFS）可以任意順序、各自獨立地被 review 與 commit，不互相阻塞。
3. OpenSpec 的 capability-per-concern 慣例（見 `openspec/specs/auto-process-performance/`）也是每個獨立可驗證的效能改動有自己的 Requirement 集合；BFS 的驗收線（門檻比較的精度等價）與 Step 5（統計欄位捨入）、PCA（gate 判定等價）性質不同，適合各自的 spec 檔案而非合併進同一個。

**結論**：建立新 change `perf-surg-guide-bfs-region-growing`，capability 命名為 `surgical-guide-bfs-region-growing-performance`，與前兩輪並列、互不修改彼此的檔案。

## Goals / Non-Goals

**Goals（本階段，已達成）：**
- 正式界定並完成 BFS region growing 的優化範圍，不與前兩輪混淆。
- 明確驗證 BFS 特有的正確性邊界，特別是「inline dot product 精度路徑」這個前兩輪都不曾遇到、且不能直接照搬 `model_classifier.py` 寫法的風險——已用真實模型量到 5 個實際翻轉案例作為證據，而非僅止於理論推導。
- 在多個候選方案（precompute 方式 A1/A2、per-patch cache、frontier batch、classifier-style float64）之間，以動態行為量測與逐 face A/B 驗證為依據做出選擇，正式採用其中一個並落地。
- 完成對應的 regression test 與代表模型驗證。

**本階段明確不代表**：Surgical Guide Auto Orient 整體效能優化已經結束。`_grow_patches()` 完成本階段後仍是 `_find_guide_direction()` 的主要成本來源之一；`detect_concave_faces()`、`_Patch` 物件建構、BFS 迴圈自身的 Python 遍歷開銷等仍是尚未處理的候選——見下方「新的耗時分布」與 Open Questions。

**Non-Goals（本階段實際交付範圍，已確認）：**
- Step 5 per-patch statistics（`perf-surg-guide-grow-patches` 已處理，本階段不重複觸碰）。
- `_is_drill_patch_by_edges()` 的 PCA/scanline/conn-edge/turn-angle（`perf-surg-guide-drill-patch-pca` 已處理 PCA 部分；scanline/turn-angle 仍未處理但不在本階段）。
- `detect_concave_faces()`、concave vote、fallback、vertex weld、adjacency 建立本身（`_weld_and_build()`）——本階段完全未觸碰。
- 把 BFS 替換成任何形式的一般圖論 connected-components 演算法（見 D1，語意不等價，會改變分組結果）——已評估，不採用。
- **Rejected-face per-patch cache**（曾列為候選）——已評估並實測：同一 patch 內重複比較的候選僅占 unique 檢查配對的約 1%（3 個模型落在 0.65%～1.51%），實際 benchmark 顯示加入 cache 的版本比單純向量化 norm 版本**更慢**（stamp 陣列的額外檢查/寫入開銷超過所省下的計算），不採用。
- **Float32 frontier batch**（曾列為候選）——已評估並實測：BFS 的 queue/frontier 大小中位數為 1（p95 僅 4～8，max 22～50），批次向量化的 NumPy 呼叫開銷（`np.unique`、fancy indexing、陣列建構）在此批次規模下不划算，實測比 Reference **慢 3～5 倍**，不採用。
- **Classifier-style 全 float64 dot product**（曾列為候選）——已評估並實測：在 `SurgicalGuide_4.stl` 上找到 **5 個真實的 accept/reject 翻轉**（float32 生產路徑 vs. float64 classifier 路徑，對完全相同的候選比較給出不同判定），雖然這 5 個案例最終未改變 patch 分組結果（BFS 具路徑依賴性，這次剛好收斂到相同結果），但已證明該精度路徑存在真實、非假設性的正確性風險，且效能與正式採用的 A2 相近，沒有理由承擔這個風險，不採用。
- **`_Patch` 物件建構開銷、BFS 迴圈自身的 Python 遍歷/索引成本**——調查確認這兩項合計占 BFS 相當比例（見下方「新的耗時分布」），但改動 `_Patch` 建構方式或迴圈結構本身超出本階段「只做 norm 預計算 + inline dot」的最小修改範圍，留給下一階段視新的 profiling 決定。

## Decisions

### D1：BFS 的核心語意——為何不能被 connected-components 取代

`_grow_patches()`（[:289-329](../../../agent/auto_orient_surg_guide.py#L289-L329)）目前對每個新 patch 固定一個 **seed 法向量**（`n_seed = face_n[f0]`，該 patch 第一個面的法向量），BFS 過程中**每一個候選 face 都與這個固定的 seed 比較**（`_dot(n, n_seed) >= cos_grow`），而不是與觸發它的相鄰 face 比較。這與「以 2° 為邊權門檻的圖，取 connected components」不等價：後者允許法向量沿著一條路徑緩慢漂移（每步都 < 2°，但沿路徑累積可能遠超過 2°）仍被視為同一分量，而現行實作會在漂移超過 2°（相對最初 seed）的那一刻就把該 face 劃入 `-2`（不合格）或留給下一個尚未走到的 patch。任何本輪的向量化 SHALL 保留「候選 face 永遠與該 patch 固定 seed 比較」這個語意，不得改成「與相鄰 face 比較」或用一般圖論函式庫的 connected-components 取代。

### D2：inline dot product 的浮點精度路徑——本輪特有的風險，不可直接照搬 classifier

`model_classifier.py::_drill_region_growing()`（[:1583-1625](../../../agent/model_classifier.py#L1583-L1625)）的寫法是：

```python
sx = float(n_seed[0]); sy = float(n_seed[1]); sz = float(n_seed[2])
...
if _fn[0]*sx + _fn[1]*sy + _fn[2]*sz >= COS_GROW:
```

`sx/sy/sz` 經 Python `float()` 轉換後是**雙精度**（float64）純量；`_fn[0]`（`face_n` 為 float32 陣列的元素）乘上一個 Python `float`，依 numpy 的型別提升規則，乘法結果會被提升為 float64——也就是說 classifier 的這個 inline dot product，實際上**全程以 float64 計算**。

而 `agent/auto_orient_surg_guide.py` 現行的 `_dot()`：

```python
def _dot(a, b):
    return float(a[0] * b[0] + a[1] * b[1] + a[2] * b[2])
```

`a[0]*b[0]` 是兩個 float32 純量相乘，結果仍是 float32；三項相加也維持 float32；只有**最終**結果才被 `float()` 轉成 float64。也就是說，`_dot()` 目前的乘加運算全程在 **float32** 精度下進行，只在最後一步升到雙精度。

若直接照搬 classifier 的「抽出純量再 inline 乘加」寫法，會不知不覺把這個門檻比較（`>= cos_grow`，`cos_grow = cos(2°) ≈ 0.9993908...`）的運算精度從 float32 改成 float64。

**這不是理論推測——已用真實模型量到具體案例**：以完整重跑（float32 生產路徑與 float64 classifier 路徑，對 BFS 過程中實際發生的每一次比較都平行計算）在 `SurgicalGuide_4.stl` 上找到 **5 組真實的 accept/reject 翻轉**（例如 `(pid=19701, face=53925)`：float32 dot=0.9993908405303955 ≥ cos_grow → accept；float64 dot=0.9993907782182392 < cos_grow → reject）。SurgicalGuide_1～3 這三個模型上翻轉數為 0，但 SG_4 的 5 個案例已經足以證明風險是真實存在的，不是「機率極低所以可忽略」的理論假設。進一步驗證發現：把 classifier-style float64 路徑**獨立完整跑一遍**（而非只是平行記錄比較值），這 5 個翻轉最終**沒有**改變 SG_4 的最終 patch 分組結果——因為 BFS 具路徑依賴性，某個面在一次嘗試中被拒絕，仍可能透過稍後另一個 patch 的嘗試被納入相同的最終 patch。**這不代表 float64 路徑因此是安全的**：它只代表這 4 個測試模型剛好沒有讓翻轉演變成實際差異；風險本身（真實翻轉已被證實存在）並未消失，也是本階段決定不採用 classifier-style float64（見 Non-Goals）的直接依據。

**正式採用的處理方式**：inline 化 dot product 時，維持與現行 `_dot()` 相同的 float32-until-the-end 精度路徑——三項乘加在 float32 精度下完成，僅最終比較時才由 Python 數值提升規則隱含轉為 double（與 `float(...)` 顯式轉換數值等價，見下方「正式採用結果」的位元級驗證）——而非比照 classifier 直接以 Python `float()` 抽出分量。這是本階段與前兩輪「直接移植 classifier 已驗證實作」性質不同之處：**移植的是「預先抽出純量、避免重複的陣列索引與函式呼叫開銷」這個思路，不移植「精度路徑」本身**。

### D3：向量化 `_norm()` 的退化法向量檢查——風險遠低於 D2，已驗證安全

`agent/auto_orient_surg_guide.py::_norm()` 的實際實作是把每個分量先以 Python `float()` 轉成雙精度再平方相加、開根號——也就是說 `_norm()` 本身**已經是全程 float64 運算**，不是 float32。這與 D2 的 `_dot()`（全程 float32、只在最終才轉 double）是兩種不同的精度路徑，不可混為一談。

`face_n[fidx]`（`_weld_and_build()` 輸出）對非退化面永遠是單位向量（norm ≈ 1.0），對退化面永遠是零向量（norm = 0.0）——`_weld_and_build()` 的 `n[nz] = cr[nz] / L[nz, None]` 只填入非退化列，其餘保持 `np.zeros_like(cr)` 的初始值。因此 `_norm(face_n[fidx]) < 0.5` 這個檢查的兩種可能輸入相差懸殊（0.0 vs ~1.0），不像 D2 的門檻比較是「兩個獨立法向量的夾角是否小於 2°」這種本質上連續、可能貼近邊界的比較。**正式採用**：以 `face_n_norms = np.linalg.norm(mesh.face_n, axis=1)` 在 BFS 迴圈外一次性向量化算出全部 face 的法向量長度（dtype 確認為 float32，因為輸入 `mesh.face_n` 是 float32），取代迴圈內對候選 face 逐次呼叫 `_norm()`——由於輸入值域是「近 0」或「近 1」兩極，向量化 reduction（float32）與現行逐次呼叫 `_norm()`（float64）之間即使有精度差異，也不可能落在 0.5 門檻附近。四個真實模型與多組 synthetic 案例（零法向量、單位法向量）皆確認退化判定結果完全相同。

### 正式採用結果與已排除方案（本階段完成後補充）

**正式採用（production 已落地，`agent/auto_orient_surg_guide.py::_grow_patches()`）**：
1. `face_n_norms = np.linalg.norm(mesh.face_n, axis=1)`，BFS 迴圈外一次性向量化預計算（dtype float32，與 `mesh.face_n` 一致）。
2. Seed 法向量分量以 `sx = n_seed[0]; sy = n_seed[1]; sz = n_seed[2]`（`numpy.float32` 純量，**不**透過 Python `float()` 轉換）取出，BFS 內以 `n[0]*sx + n[1]*sy + n[2]*sz >= cos_grow` inline 計算，取代 `_dot(n, n_seed) >= cos_grow` 函式呼叫。

**逐項驗證**（見 `tasks.md` 第 3 節）：`mesh.face_n.dtype`／`face_n_norms.dtype`／inline 運算式每個中間值皆確認為 `float32`；對 200,000 組隨機 face pair 與 SG_4 的 5 個臨界案例，inline 運算式與現行 `_dot()` **逐 bit 相同**（0 mismatches）；4 個真實模型逐 face `patch_id` 陣列 **完全相同**（0 mismatches）；`res.dir`／`rotation_rad` **bit-exact 相同**。

**已評估、不採用的方案**（見 Non-Goals 的完整理由與量測數字）：per-patch reject cache（僅省 ~1% 比較、實測更慢）、float32 frontier batch（frontier 中位數為 1，實測慢 3～5 倍）、classifier-style 全 float64（已證實存在真實翻轉風險）。

### D4：不變更的部分（重申，已於實作與驗證中確認）

- Face/seed 遍歷順序（`for f0 in range(m)` 由小到大掃描未指派的 face 作為下一個 seed；`deque` FIFO 的 BFS 展開順序）——完全未改動，A2 只替換迴圈「內部」的兩個計算式，不改變迴圈結構或執行順序本身。
- `adj[fidx]`（adjacency list，由 `_weld_and_build()` 建立）的內容與順序——本階段完全未觸碰 `_weld_and_build()`。
- `_Patch` 物件的建構（`P = _Patch(id=pid)`）與 `P.faces.append(fidx)` 的語意——完全未改動。

## 動態行為調查與正式 Phase 0 基準

以現行（`perf-surg-guide-grow-patches` + `perf-surg-guide-drill-patch-pca` 皆已套用）程式碼為 baseline，對 4 個真實模型做了兩層量測：(1) 一次性、詳盡的動態行為統計（呼叫次數、重複比較、frontier 大小分布——這些是精確計數，與計時噪聲無關），(2) 正式的 7 次交錯執行 benchmark（用於決定是否採用）。

**動態行為統計（逐 face 精確計數，非計時）**：

| 模型 | faces | `_norm()` 呼叫次數（優化前） | `_dot()` 呼叫次數（優化前） | 同一 patch 內重複比較占 unique 配對比例 | queue 大小中位數／p95／max |
|---|---|---|---|---|---|
| SurgicalGuide_1 | 201,574 | 367,943 | 295,633 | 1.06% | 1／7／50 |
| SurgicalGuide_2 | 97,372 | 180,073 | 143,406 | 0.96% | 1／5／22 |
| SurgicalGuide_3 | 160,666 | 298,513 | 237,557 | 0.65% | 1／4／28 |
| SurgicalGuide_4 | 236,034 | 426,809 | 345,197 | 1.51% | 1／5／26 |

`_norm()` 呼叫次數是 face 數的 1.8～1.9 倍——多數重複來自**跨 patch**（不同 patch 嘗試 claim 同一個未指派 face 時各自重算一次 norm），而非同一 patch 內部重複（僅 0.65%～1.51%，且每個候選最多被重複檢查 3 次，受限於三角形恰有 3 條邊）。這解釋了為何 D3 的「全域一次性向量化」比一個「per-patch reject cache」（只消除同 patch 內的 ~1%）帶來大得多的效益。

**正式 Phase 0 + A2 benchmark（7 次交錯執行，`time.perf_counter()`，median 為主要結果，同時列出 min/max/IQR 顯示噪音；precompute 成本已計入每次量測）**：

| 模型 | 階段 | Reference median | A2 median | 改善（相對本階段 baseline，即 Round 2 結束版本） |
|---|---|---|---|---|
| SurgicalGuide_1 | BFS-only | 569.5 ms | 389.2 ms | −31.7% |
| SurgicalGuide_1 | `_grow_patches()` | 673.9 ms | 480.9 ms | −28.6% |
| SurgicalGuide_1 | `_find_guide_direction()` | 2423.7 ms | 2196.9 ms | −9.4% |
| SurgicalGuide_1 | `compute_auto_orientation_surg_guide_detail()` | 2452.6 ms | 2266.6 ms | −7.6% |
| SurgicalGuide_2 | BFS-only | 274.8 ms | 182.7 ms | −33.5% |
| SurgicalGuide_2 | `_grow_patches()` | 321.8 ms | 225.3 ms | −30.0% |
| SurgicalGuide_2 | `_find_guide_direction()` | 1102.8 ms | 1017.2 ms | −7.8% |
| SurgicalGuide_2 | `compute_auto_orientation_surg_guide_detail()` | 1136.3 ms | 1031.8 ms | −9.2% |
| SurgicalGuide_3 | BFS-only | 464.3 ms | 303.5 ms | −34.6% |
| SurgicalGuide_3 | `_grow_patches()` | 537.8 ms | 374.6 ms | −30.3% |
| SurgicalGuide_3 | `_find_guide_direction()` | 1873.6 ms | 1720.7 ms | −8.2% |
| SurgicalGuide_3 | `compute_auto_orientation_surg_guide_detail()` | 1905.5 ms | 1737.9 ms | −8.8% |
| SurgicalGuide_4 | BFS-only | 664.5 ms | 461.1 ms | −30.6% |
| SurgicalGuide_4 | `_grow_patches()` | 785.6 ms | 566.5 ms | −27.9% |
| SurgicalGuide_4 | `_find_guide_direction()` | 2815.9 ms | 2566.6 ms | −8.9% |
| SurgicalGuide_4 | `compute_auto_orientation_surg_guide_detail()` | 2764.3 ms | 2592.2 ms | −6.2% |

**這一輪的 6.2%～9.2% 核心 Auto Orient（`compute_auto_orientation_surg_guide_detail()`）改善，是相對於 Round 2（PCA）結束版本的增量改善，不是相對最原始版本的累積改善**；不同 session 量測的百分比不可直接相加。四個模型的改善方向與量級一致（BFS-only 約 30～35%、`_grow_patches()` 約 28～30%、核心 Auto Orient 約 6～9%），滿足採用門檻中的「趨勢一致」要求。`rotation_rad` 在全部 7 次重複、兩個分支（Reference/A2）、全部 4 個模型上皆 bit-exact 且穩定。

**四輪整合驗收**：本 change 與其他三輪（`perf-surg-guide-grow-patches`／`perf-surg-guide-drill-patch-pca`／`perf-surg-guide-concave-chunking`）疊加後的整合正確性與累積效能驗收記錄，見 `perf-surg-guide-concave-chunking/design.md`「四輪整合驗收」章節，避免重複記載。

## Risks / Trade-offs

- **[D2 的精度路徑若未正確處理，可能在邊界 face 上翻轉 patch 分組]**（已驗證解決）→ 逐 face 比對 patch membership（4 模型、0 mismatches）、200,000 組隨機 face pair 與 SG_4 的 5 個臨界案例皆與現行 `_dot()` bit-exact；未採用 Python `float()` 抽出分量的寫法，未引入 D2 描述的風險。
- **[BFS 向量化的一般性風險：任何改變執行順序的做法都可能意外改變分組]**（已驗證解決）→ 正式採用的 A2 完全不改變迴圈執行順序，只加速每次迭代內的計算；曾評估的 frontier batch（會改變執行順序與粒度）已實測確認在此 frontier 規模下反而更慢，不採用。
- **[量測噪聲]**（已處理）Benchmark 採 7 次交錯執行 + median 為主要結果，min/max/IQR 一併列出顯示噪音範圍，不以單次或最小值作結論。

## Migration Plan

單一階段，獨立於前兩輪，已完成：

| 階段 | 內容 | 狀態 |
|---|---|---|
| 0 | 正式 Phase 0 基準建立（動態行為統計 + 7 次交錯執行 benchmark + 正確性快照） | 已完成 |
| 1 | BFS 向量化實作（D3 法向量長度預算 + D2 精度保留的 inline dot，即 A2） | 已完成，production diff 見 Impact |
| 2 | A/B 正確性驗證（逐 face patch membership、SG_4 5 個臨界案例、synthetic 邊界案例） | 已完成，全數通過 |
| 3 | Benchmark 與 regression test | 已完成 |

本階段完成後可提交（不 commit，依使用者要求），尚未 archive。

## Open Questions（下一階段候選，本階段不處理）

- **`_Patch` 物件建構開銷**：cProfile 顯示 `_Patch.__init__` 與其兩個 `np.zeros(3)` default-factory（`avg_normal`／`center`）合計占 BFS-only 耗時約 10～12%，且對 88% 面數 `<5`、稍後即被捨棄的 patch 一樣全額付出這個成本。是否值得延遲建構、或改用更輕量的資料結構，留給下一階段視新的 profiling 決定。
- **BFS 迴圈自身的 Python 遍歷/索引成本**：A2 消除了 `_norm`/`_dot` 呼叫後，cProfile 顯示純迴圈控制流程（`adj[fidx]` 索引、`patch_id[fn]` 讀寫、inline dot 運算本身）占 BFS-only 耗時約 70%，成為新的最大單一項目。是否值得進一步優化（例如更換資料結構、減少陣列索引次數）尚未評估，可能需要專門的下一輪調查。
- **`detect_concave_faces()`**：三輪優化後，cProfile 顯示其占 `_find_guide_direction()` 的比例相對提高（因為 `_grow_patches()` 與 `_is_drill_patch_by_edges()` 都已優化），是否列入下一輪需視屆時 profiling 決定。
- **是否需要同時處理 `_weld_and_build()` 的 adjacency 建立？** BFS 的效能也部分取決於 `adj[fidx]` 這個 Python list-of-lists 的存取模式；本階段未觸碰 `_weld_and_build()`，若未來發現效益受限於此，需要另開一輪處理，不自動擴大本提案範圍。
