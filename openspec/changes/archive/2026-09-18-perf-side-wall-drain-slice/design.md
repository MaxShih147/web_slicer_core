## Context

`agent/ortho_pipeline.py::generate_side_wall_drains()` 是 Ortho pipeline Step 6：對 outer shell（原始輸入模型）與 inner shell（hollow）各自在指定 Z 高度呼叫 `agent/ortho_pipeline.py::slice_mesh_at_z()` 取得 2D 輪廓，再據以搜尋側壁排液孔位置。`slice_mesh_at_z()` 改動前對 mesh 的**每一個三角形**都跑一次 Python scalar 迴圈（三條邊各自算 `d0 = p0[2] - z_world`、`d1 = p1[2] - z_world`，`d0 * d1 < 0` 才算交點），無論該三角形的 Z 範圍是否可能與切平面相交都會被檢查一次。

`generate_side_wall_drains()` 呼叫 `slice_mesh_at_z()` 共 2～4 次：inner shell 一次（`z_drain`），outer shell 1～3 次（`z_drain+1.0` 失敗才 retry `+0.5`，再失敗才 retry `+2.0`）。outer shell 的三次 retry 是同一份未修改的 mesh，理論上可以共用同一份預先計算好的資料。

前置調查（source tracing + 真實模型 baseline，`001_p.stl`／`005_p.stl`／`DentalModel_1M.stl`／`DentalModel_NeedRotate.stl` 四個代表模型）確認：`slice_mesh_at_z()` 的這個全量掃描是 Step 6 目前最大且最普遍的成本。**兩項數字來源不同，分開陳述**：在這 4 個代表模型的真實 Step 6 執行中，`slice_inner + slice_outer` 合計佔該次 Step 6 wall time 的 67%～99%（001_p.stl 66.6%、005_p.stl 72.9%、DentalModel_1M.stl 69.7%、DentalModel_NeedRotate.stl 98.6%，詳見下方「實作與驗證記錄」表格）；另外以 16 組真實 mesh／z-level 組合（inner 一個 z-level + outer 三個 retry z-level）做獨立的 slicing diagnostic，量測候選面比例、各子階段耗時與正確性——outer 的 `+0.5`／`+2.0` 這兩個 z-level 在這 4 個模型的真實 pipeline 執行中從未被觸發（`+1.0` 皆直接成功），只是 diagnostic 額外涵蓋的量測對象，不代表這 4 個模型的真實執行路徑。

## Goals / Non-Goals

**Goals:**
- 用三角形 Z min/max 的向量化 NumPy broad-phase 篩選，取代「對全部三角形跑 scalar 迴圈」，保留既有 scalar edge/intersection 判定與 spatial-hash loop chaining **完全不變**。
- 篩選條件 SHALL 與既有 `d0*d1<0` 判定式數學等價，但等價的對象要精確界定：`face_z_min < z_world < face_z_max` 等價於「該三角形至少存在一條端點嚴格分處切面兩側的邊」（即至少一條邊滿足 `d0*d1<0`），SHALL NOT 產生 false negative（不會漏掉任何原演算法可能找到的 strict edge crossing，也不會漏掉任何原本會產生 segment 的三角形）。但這**不等價於「該三角形一定會產生 segment」**——候選集合中仍可能保留只找到 1 個交點、不滿足既有「恰需 2 個交點才算 segment」規則的三角形，此為候選篩選允許的正常情況，不影響最終輸出正確性（詳見下方 D1）。
- 縮短 `generate_side_wall_drains()` 持有 Z-bounds 的生命週期：inner shell 只切一次，其 bounds 不跨越單次 `slice_mesh_at_z()` 呼叫被外層持有；outer shell bounds 建立一次，持有至 `generate_side_wall_drains()` 返回，供三次 retry 共用（不使用全域或 Trimesh 快取，避免 mesh 被修改後取得過期 bounds）。
- 用真實模型（含至少一個候選評估幾乎全免的低產出案例）與合成邊界案例，驗證篩選前後 `slice_mesh_at_z()`／`generate_side_wall_drains()` 輸出等價；`generate_side_wall_drains()` 本身的回傳值（未經 Step 9/10 Boolean）驗收線為 `.vertices`／`.faces` `np.array_equal`、孔數一致、`None` 判定一致，完整 pipeline 最終 `ortho_result.stl`（經 Boolean）則採等價語意驗收（faces/vertices count、volume、bounds、`is_watertight`），原因見下方 D3。

**Non-Goals（本輪不處理）：**
- 不對 edge/segment 求交本身（`d0*d1<0` 判定與交點座標計算）做向量化——本輪的候選集合縮減已使這段 scalar 迴圈的絕對耗時降到個位數毫秒等級（見下方量測），暫無急迫性。
- 不建立 Z-bucket 或其他空間索引——候選集合的產生只需要一次向量化布林遮罩，不需要額外資料結構。
- 不處理已識別但本輪排除的其他 Step 6 成本：`evaluate_sample_idx()` 內對 inner-poly 的 ray/segment 迴圈（3 個正常產出案例中穩定佔 Step 6 的 20～28%）、對 outer-poly 的 `point_in_polygon_2d` 迴圈（在 outer 輪廓點數特別多的模型如 `DentalModel_1M.stl` 上曾觀察到佔候選評估階段 72%）。兩者留待後續獨立提案評估。
- 不改變候選點選取、angle-bin、slide search、孔幾何、Boolean（Step 7～10）。
- 不處理 `agent/boundary_detection.py` 的 Base sidewall 相關問題（不同模組、不同 capability 範圍）。
- 不處理 Hex Grid raycast（已由 `hex-grid-raycast-performance` 涵蓋，範圍不重疊）。
- 不對 `DentalModel_1M.stl` 完整 pipeline 輸出非 watertight 的既有狀況做根因調查或修正（見下方 Risks／Open Questions；本次只驗證該狀況在改動前後一致，不代表本次變更「決定」該模型未來必須維持非 watertight）。

## Decisions

### D1：Broad-phase 改為三角形 Z min/max 向量化篩選

**根因與等價性證明（精確界定等價對象）**：對三角形三頂點的 Z 值 `z0, z1, z2`，若 `z_world <= min(z0,z1,z2)`，則三個 `d_i = z_i - z_world >= 0`，任兩者乘積恆 `>= 0`，不可能有任何一邊 `d0*d1<0`；若 `z_world >= max(z0,z1,z2)`，同理三個 `d_i <= 0`，乘積恆 `>= 0`。反之，若 `face_z_min < z_world < face_z_max`，則三頂點中至少有一個 `z_i < z_world`、至少有一個 `z_j > z_world`；由於三角形只有 3 條邊構成一個環，兩種類別的頂點都存在時，環上必存在至少一條邊直接連接一個「低於切面」與一個「高於切面」的頂點，該邊的 `d0`、`d1` 異號，滿足 `d0*d1<0`。

因此 `face_z_min < z_world < face_z_max`（嚴格不等式，與既有 `d0*d1<0` 的嚴格 `<0` 語意一致）精確等價於「這個三角形的三條邊中**至少存在一條**滿足 `d0*d1<0` 的 strict edge crossing」——不是保守估計，而是完全等價的重述，SHALL NOT 漏掉任何原本存在 strict edge crossing 的三角形。

**此等價性的界限（避免過度推論）**：上述等價性僅止於「存在候選交點邊」，**不等價於「該三角形一定會產生 segment」**——既有演算法要求恰好找到 2 個交點才建立 segment（`if len(pts) == 2`）。例如頂點 Z 為 `(-1, 0, +1)`、切平面 `z_world=0` 時：`face_z_min=-1 < 0 < face_z_max=1` 成立，三角形被納入候選；但三條邊中，只有連接 Z=+1 與 Z=-1 的那條邊滿足嚴格 `d0*d1<0`（另兩條邊因端點之一恰為 0，`d0*d1=0`，不滿足嚴格不等式），最終只找到 1 個交點，不形成 segment。這是候選篩選允許的正常情況：候選集合只決定哪些三角形進入既有 scalar 迴圈，SHALL NOT 漏掉任何原本會產生 segment 的三角形（因為會產生 segment 的三角形必定至少有一條 strict edge crossing，因而必定通過候選篩選），但候選集合本身可能包含一些最終不產生 segment 的三角形——這些三角形會被既有、本輪完全不變的 `len(pts) == 2` 判斷正確排除，不影響最終輸出。

**實作**：新增 `compute_face_z_bounds(mesh)`，直接用 `vertex_z = mesh.vertices[:, 2]` 配合 `faces[:, i]` 花式索引與 `np.minimum`/`np.maximum`（`out=` 就地運算）算出 `(face_z_min, face_z_max)`，刻意不使用 `mesh.triangles`（避免多配置一份 `(F,3,3)` 陣列）、不轉 `float32`（維持 mesh 原生 Z dtype，本次真實模型皆為 `float64`）。`slice_mesh_at_z()` 用 `candidate_face_ids = np.flatnonzero((face_z_min < z_world) & (face_z_max > z_world))` 取得候選，僅對候選子集合（依 `np.flatnonzero` 保證的遞增順序）執行**逐行不變**的既有 scalar 迴圈。

**考慮過的替代方案**：
- Z-bucket／完整空間索引——候選篩選只需要一次向量化布林遮罩即可把候選比例壓到 0.03%～0.71%（見下方量測），本輪判斷不需要更複雜的資料結構；列為未來若場景改變（例如切平面數量大增）再評估的方向。
- 向量化 edge/segment 求交本身——候選集合縮減後這段 scalar 迴圈已降到個位數毫秒，暫不列入本輪範圍（見 Non-Goals）。

### D2：Z-bounds 生命週期縮短——inner 不跨呼叫持有、outer 建立一次持有至函式返回

`generate_side_wall_drains()` 只在需要「跨多次呼叫重用」時才在自己的 scope 持有 bounds。inner shell 只切一次（沒有 retry），因此改為直接呼叫 `slice_mesh_at_z(inner_shell, z_drain)`，不傳入 `face_z_bounds`——bounds 由 `slice_mesh_at_z()` 內部呼叫 `compute_face_z_bounds()` 建立，該次呼叫返回後，`generate_side_wall_drains()` 的 scope 中沒有 `inner_face_z_bounds` 這個名稱、不持有跨越該次呼叫的具名參照。outer shell 的 bounds 則在 inner slice 完成「之後」才建立一次（`outer_face_z_bounds = compute_face_z_bounds(outer_shell)`），持有至 `generate_side_wall_drains()` 返回為止，供 `+1.0 → +0.5 → +2.0` 三次 retry 共用同一份，因為這三次呼叫的 `outer_shell` 本身未被修改。

刻意不使用 `del`、`gc.collect()`，或掛在 mesh 物件（`mesh._cache` 之類）／模組層級的快取——後者會在 mesh 被後續修改（例如上游的 `apply_translation()`）後仍回傳過期 bounds，而純 Python 區域變數在不再被參照後即符合垃圾回收條件，已足以達到「不長期持有具名參照」的目標，不需要額外的手動記憶體操作。**這只保證 Python 物件不再被 `generate_side_wall_drains()`／`slice_mesh_at_z()` 的作用域持有參照，不代表 CPython/NumPy allocator 會立即把底層記憶體歸還給作業系統**——實際 RSS 下降時機由 Python 記憶體管理機制決定，本設計不對此做任何保證，詳見下方「記憶體」小節。

### D3：驗收線——`generate_side_wall_drains()` 以 `np.array_equal` 判準，完整 pipeline 語意等價

與 `hex-grid-raycast-performance`（純向量化候選搜尋、不牽涉 Boolean）不同，本次改動的下游（Step 9/10）會經過 `boolean_meshes()`——其內部把頂點轉成 `float32` 餵給 `manifold3d.Manifold` 再重建 `trimesh.Trimesh`，即使輸入完全相同，Boolean 中間表示法本身就不保證兩次執行的頂點/面陣列相同。因此：
- `slice_mesh_at_z()` 與 `generate_side_wall_drains()`（Step 9/10 之前）的輸出，驗收線為 `.vertices`／`.faces` 陣列 `np.array_equal`、`None` 判定一致、孔數一致——這段程式碼路徑本身是純 Python/NumPy 幾何運算，沒有引入不確定性來源，理應可以做到陣列逐元素完全相同，也已在真實模型上驗證成立（僅驗證過記憶體中的 numpy 陣列，未比較過任何序列化檔案的 bytes，本文件與 spec 一律以 `np.array_equal` 表達，不使用「byte-for-byte」字樣以免與檔案層級比對混淆）。
- 完整 pipeline 最終 `ortho_result.stl`（已經過 Step 9/10 Boolean）驗收線改為等價語意判準：faces/vertices count、volume（相對誤差 ≤1e-6）、bounds（絕對誤差 ≤1e-6mm）、`is_watertight`——與 `auto-process-performance` capability 對牽涉 Boolean 改動的既有驗收慣例一致。`is_watertight` 的判準是「驗收本次效能變更時，prototype 與固定的 pre-change reference 一致」，不是「is_watertight 永遠必須為 True」——若某模型的 pre-change reference 本來就是 `False`（本次觀察到 `DentalModel_1M.stl` 即屬此況），這是該模型在既有實作下的既有狀況，本次驗收只需確認改動前後一致（沒有因本次效能變更而劣化），不代表本次變更把該既有狀況固化為永久必須維持的行為，也不限制未來另案修正該模型 watertightness 問題的工作。

## 實作與驗證記錄

**代表模型**（真實 PrusaSlicer CLI hollow 輸出，經 `load_trimesh()` 相同流程載入；沿用前置調查的 4 個代表模型）：

| 模型 | outer faces | inner (hollow) faces |
|---|---|---|
| `001_p.stl` | 32,138 | 427,868 |
| `005_p.stl` | 166,672 | 353,164 |
| `DentalModel_1M.stl` | 1,024,996 | 626,192 |
| `DentalModel_NeedRotate.stl` | 37,470 | 570,108 |

**`slice_inner + slice_outer` 佔真實 Step 6 執行的比例（4 個代表模型，各自單次真實 Step 6 執行的逐階段量測；分母為該次執行量測到的全部階段耗時總和）**：

| 模型 | `slice_inner` | `slice_outer`（該次執行實際成功的 z-level，皆為 `+1.0`，未觸發 retry） | 該次 Step 6 量測總耗時 | `slice_inner+slice_outer` 佔比 |
|---|---|---|---|---|
| `001_p.stl` | 0.8195s | 0.0622s | 1.3243s | **66.6%** |
| `005_p.stl` | 0.6810s | 0.3152s | 1.3669s | **72.9%** |
| `DentalModel_1M.stl` | 1.1977s | 1.9786s | 4.5596s | **69.7%** |
| `DentalModel_NeedRotate.stl` | 1.0823s | 0.0740s | 1.1722s | **98.6%** |

（範圍 **67%～99%**。此表格與下方「16 組真實 mesh／z-level 組合」表格是**兩個獨立量測**：本表只取每個模型真實會用到的 z-level（`slice_outer` 一律是 `+1.0` 的單次嘗試，因為這 4 個模型從未觸發 retry），下方 16 組表格則額外涵蓋 outer 的 `+0.5`／`+2.0`——這兩個 z-level 是 diagnostic 額外量測的對象，不是這 4 個模型真實 Step 6 執行會經過的路徑，不能與本表的 67%～99% 混算。）

**候選面比例（16 組真實 mesh／z-level 組合，涵蓋 inner 的單一 z-level 與 outer 的 `+1.0`／`+0.5`／`+2.0` 三個 z-level——後兩者是獨立 diagnostic 額外涵蓋的量測對象，用於驗證候選篩選在不同 z-level 下都正確，不代表這 4 個模型的真實 pipeline 執行路徑）**：候選比例介於 0.03%～0.71%，即排除 99.29%～99.97% 的三角形不必進入 scalar 迴圈。代表性子集：

| 模型 / z-level | 總面數 | 候選面數（比例） | 修改前 scalar+chaining | 修改後 bounds+mask+scalar+chaining | 加速 |
|---|---|---|---|---|---|
| `001_p` inner z=0.0 | 427,868 | 2,270（0.53%） | 0.7998s | 0.0281s | 28.4x |
| `001_p` outer z=1.0 | 32,138 | 227（0.71%） | 0.0615s | 0.0022s | 28.4x |
| `005_p` inner z=0.0 | 353,164 | 1,798（0.51%） | 0.6601s | 0.0221s | 29.8x |
| `005_p` outer z=1.0 | 166,672 | 261（0.16%） | 0.3130s | 0.0059s | 52.7x |
| `DentalModel_1M` inner z=0.0 | 626,192 | 2,256（0.36%） | 1.1876s | 0.0343s | 34.6x |
| `DentalModel_1M` outer z=1.0 | 1,024,996 | 4,723（0.46%） | 1.9687s | 0.0741s | 26.6x |
| `DentalModel_NeedRotate` inner z=0.0 | 570,108 | 169（0.03%） | 1.0423s | 0.0153s | 68.2x |
| `DentalModel_NeedRotate` outer z=1.0 | 37,470 | 23（0.06%） | 0.0687s | 0.0007s | 96.1x |

（完整 16 組數字含 outer `z=0.5`／`2.0` retry，見本次調查 scratchpad 的 `diagnostic_ab_results.json`；chaining 階段耗時修改前後在誤差範圍內相同，確認未改動的 loop chaining 程式碼行為一致，篩選未把成本轉移到別處。）

**正式 Auto Process 端到端量測**（1 次 warm-up + 3 次計時真實 pipeline 執行，`time.perf_counter()`，取 median，代表模型 `001_p.stl`／`DentalModel_1M.stl`；與上述兩個診斷用表格為不同批次的獨立量測，過程不含逐階段 instrumentation）：

| 模型 | Step 6 wall（修改前 → 修改後） | Step 6 改善 | 完整 pipeline wall（修改前 → 修改後） | 完整 pipeline 改善 |
|---|---|---|---|---|
| `001_p.stl` | 1.3708s → 0.4465s | **−67.4%（3.07x）** | 6.2544s → 5.2489s | −16.1% |
| `DentalModel_1M.stl` | 4.6870s → 1.5485s | **−67.0%（3.03x）** | 20.6984s → 17.5579s | −15.2% |

Step 6 未降到接近零，是因為 Step 6 內還有 Non-Goals 中列出、本輪刻意不處理的其他成本（inner-poly ray/segment 迴圈、outer-poly point-in-polygon 迴圈）——本輪只針對已確認的最大單一成本動手，未宣稱涵蓋 Step 6 全部耗時。

**正確性驗證**：
- Reference＝修改前 `slice_mesh_at_z()`／`generate_side_wall_drains()` 的逐行複製（已用 `np.array_equal` 對照修改前 production code 驗證輸出一致，才作為後續比對基準）；Prototype＝目前 production code。
- 16 組真實（mesh、z-level）組合：`slice_mesh_at_z()` 回傳的 loop 數量、順序、每個 loop 的 shape 與座標，`np.array_equal` 全部通過，含 `DentalModel_1M.stl` outer 切面在 `z=1.0`／`0.5`／`2.0` 分別產生 14／5／10 個不連通 loop 的情況。
- 4 個真實案例（`001_p.stl`／`005_p.stl`／`DentalModel_1M.stl`／`DentalModel_NeedRotate.stl`）：`generate_side_wall_drains()` 回傳的 `None`/非 `None` 判定一致、`.vertices`／`.faces` `np.array_equal`（此即蘊含孔數與內部候選 gate 結果相同——最終 mesh 完全由通過哪些 gate 的候選決定，若 gate 結果不同，最終 vertices／faces 不可能仍然逐元素相同）；孔數另外對照本次調查最初一輪自真實 pipeline 擷取的 baseline production log 一致（`001_p.stl`／`005_p.stl`／`DentalModel_1M.stl`／`DentalModel_NeedRotate.stl` 分別為 11／10／11／1 孔）。**此階段（4 個真實案例逐一驗證 `slice_mesh_at_z()` 與 `generate_side_wall_drains()`）並未逐一比對 `no_bin`／`no_inner_hit`／`too_close` 各自的 gate 計數細項或原始 logger 輸出字串，只比對了總孔數與 vertices／faces 陣列相等（後者已可蘊含 gate 結果一致，見上）。**
- 完整 pipeline gate 計數細項（`no_bin`／`no_inner_hit`／`too_close`）與原始 production log 字串的直接比對，只在下方「完整 pipeline 端到端最終幾何比較」（`001_p.stl`／`DentalModel_1M.stl` 兩個模型）中執行，且 reference 側的顯示文字是由已驗證的 probe counters 重建（因為 probe 回傳 counters 而非呼叫 `logger.info()`），不是 reference pipeline 直接捕捉到的原始 logger 輸出；prototype 側則是直接捕捉的真實 production log。
- Z-bounds 生命週期縮短後重跑上述全部檢查，結果不變（見 `agent/tests/` 與 scratchpad `validation_after_lifetime_change.log`）。
- 新增合成幾何單元測試（`agent/tests/test_slice_mesh_at_z_broad_phase.py`，8 tests）：全高於平面、全低於平面、正常穿越並成功閉合 loop（用 box mesh 驗證候選篩選不遺漏 chaining 所需的任何三角形）、vertex 恰在切平面（確認既有「恰需 2 點才算 segment」的既有行為不受篩選影響——這是修改前就存在、本輪不處理的既有語意特性，非本次引入的行為，與上方 D1 討論的 `(-1,0,+1)` 邊界案例一致）、coplanar 三角形、degenerate（零面積）三角形不當機、空 mesh、`face_z_bounds` 外部傳入與內部自算結果一致。
- 完整 pipeline 端到端最終幾何比較（`001_p.stl`／`DentalModel_1M.stl`，reference 與 prototype 各自跑完整真實 `run_ortho_pipeline()`，各自獨立 temp job 目錄）：兩模型的 `ortho_result.stl` faces／vertices count、volume（相對誤差 0.0）、bounds（絕對誤差 0.0mm）相同；placed/skip counters（`no_bin`／`no_inner_hit`／`too_close`）與 prototype 實際 production log 所表達的結果一致——reference 側的顯示文字由已驗證的 probe counters 重建（如上所述），prototype 側是直接捕捉的真實 logger 輸出，兩者內容（孔數與各 gate 計數）相符，但不是「兩邊原始 logger 呼叫產生的字串直接比對」；`is_watertight`：`001_p.stl` 兩者皆 `True`（達成 D3 定義的驗收門檻），`DentalModel_1M.stl` 兩者皆 `False`——此為該模型在目前 HEAD 下經 Step 9/10 Boolean 後的既有狀況（reference 與 prototype 完全一致，證明非本次改動引入的退化，但也不代表本次變更把這個既有狀況定為該模型永久必須維持的行為）。
- `pytest agent/tests/test_slice_mesh_at_z_broad_phase.py agent/tests/test_ortho_clean_mesh_reuse.py agent/tests/test_ortho_hollow_split_repair.py`：18 passed，無回歸。

**記憶體（估算持有量級，非直接量測的完整 peak）**：`compute_face_z_bounds()` 傳回的兩個 `(F,)` 陣列，dtype 與 mesh 原生 Z dtype 相同。最大代表模型（`DentalModel_1M.stl` outer shell，1,024,996 faces，`float64`）這兩個**持續存活**的 bounds 陣列合計約 16.4MB——這是本次唯一直接算出的數字，只涵蓋這兩個陣列本身，不是完整 peak memory。`compute_face_z_bounds()` 內部的花式索引（`vertex_z[faces[:, i]]`）、`.copy()`，以及 `slice_mesh_at_z()` 的布林遮罩與 `np.flatnonzero()` 還會產生額外的短期暫存配置（例如花式索引結果、遮罩陣列本身），這些未被逐一加總或直接量測，因此實際 peak memory 未被本次直接量測，但仍屬數十 MB 等級（與已知的 16.4MB 持續存活量級同數量級，不會高出一個數量級）。生命週期上：inner bounds 在單次 `slice_mesh_at_z()` 呼叫返回後不再被 `generate_side_wall_drains()` 的作用域持有參照；outer bounds 持有至 `generate_side_wall_drains()` 返回為止。這只描述 Python 物件參照的生命週期，不代表 CPython/NumPy allocator 會在參照歸零後立即把底層記憶體歸還給作業系統——程序 RSS 的實際下降時機不受本次改動保證或控制。未觀察到需要 chunking 的量級。

## Risks / Trade-offs

- **[Step 6 剩餘成本未被本輪處理]** 本輪只處理已確認的最大單一成本（slicing），Step 6 中已識別但未處理的 inner-poly ray/segment 迴圈與 outer-poly point-in-polygon 迴圈仍是全量 Python scalar 迴圈，在候選評估活躍的正常產出案例上會成為新的相對最大成本。→ 已在提案與本文件中明確標示為 Non-Goal，留待後續獨立提案評估；不影響本次改動本身的正確性或可採用性。
- **[`DentalModel_1M.stl` 完整 pipeline 最終輸出非 watertight]**（非本次改動引入）reference 與 prototype 在此模型上經 Step 9/10 Boolean 後的最終輸出皆為 `is_watertight=False`，兩者完全一致，證明是既有狀況而非本次改動的退化。→ 記錄於此供未來追蹤，若要修正需另行調查 Boolean 鏈或該模型本身的網格品質，不在本提案範圍內；本次驗收判準（見 D3）只要求改動前後與固定的 pre-change reference 一致，不把這個既有狀況定為該模型未來必須永久維持的行為，未來另案修正時不受本提案限制。
- **[Z 恰好等於三角形頂點值的邊界情況]** `face_z_min < z_world` 與 `face_z_max > z_world` 皆為嚴格不等式，與既有 `d0*d1<0` 的嚴格語意一致，理論上不會有邊界不一致；本輪已用「vertex 恰在切平面」的合成測試（見上方 D1 的 `(-1,0,+1)` 案例）與真實模型驗證此邊界情況行為不變。→ 風險已透過測試覆蓋降低到可接受程度。
- **[記憶體 peak 未直接量測]** 本次只直接算出兩個持續存活 bounds 陣列的大小（約 16.4MB），未逐一加總花式索引／布林遮罩等短期暫存配置，也未用系統工具量測完整 process peak（不同於 `perf-hex-grid-raycast` 曾用 Windows `GetProcessMemoryInfo` 量測 peak working set）。→ 已知的兩個持續存活陣列量級（數十 MB 以內）加上短期暫存配置，預期仍在數十 MB 等級，與 `DentalModel_1M.stl` 這類百萬面模型載入本身的記憶體佔用相比屬小量；若未來需要精確 peak 數字，可比照 `perf-hex-grid-raycast` 的方法另行量測，不阻擋本次採用。

## Migration Plan

單一階段，可獨立驗證與獨立 commit：

| 階段 | 內容 | 回滾方式 |
|---|---|---|
| 0 | Baseline 重現與 A/B benchmark harness 建立（scratchpad，不落地） | — |
| 1 | `compute_face_z_bounds()` 新增、`slice_mesh_at_z()` broad-phase 篩選、`generate_side_wall_drains()` bounds 生命週期調整（`agent/ortho_pipeline.py`） | 單一 commit revert |

## Open Questions

以下為刻意保留給未來的後續工作，非本次採用的前提條件，也都不影響本次的實作範圍或驗收判準：

- **Step 6 剩餘的 inner-poly ray/segment 迴圈與 outer-poly point-in-polygon 迴圈是否值得作為下一個獨立 prototype？** 前置調查已量測前者在 3 個正常產出案例穩定佔 Step 6 的 20～28%，後者在 outer 輪廓點數特別多的模型（`DentalModel_1M.stl`，4,644 點）上曾佔候選評估階段 72%、在輪廓點數少的模型上可忽略。是否值得投入，留待下一輪視當時的整體優先順序決定。
- **`DentalModel_1M.stl` 完整 pipeline 輸出非 watertight 的根因是否需要另案調查？** 本次已確認 reference／prototype 行為一致（非本次改動引入），但根因（是模型本身網格品質問題、還是 Boolean 鏈某一步驟的既有限制）尚未調查，留待未來若有需求再行處理；本提案的驗收判準（D3）不因這個既有狀況而受影響，未來若另案修正也不受本提案任何條文限制。
- **記憶體 peak 的精確量測是否需要補做？** 本次只估算了持續存活 bounds 陣列的量級，未量測完整 process peak；若未來場景（例如更大的代表模型）需要精確數字，可比照 `perf-hex-grid-raycast` 使用系統工具另行量測。
