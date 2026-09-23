## Context

`agent/ortho_pipeline.py::generate_side_wall_drains()` 的候選評估（`evaluate_sample_idx()`）每次呼叫都對 `inner_poly`（inner shell 的 2D 輪廓）全部邊逐一呼叫 `ray_seg_intersect_2d()`，取最近正向 hit 作為到 inner wall 的距離。`perf-side-wall-point-in-polygon`（已 archive）處理了同一函式內 outer-poly 的 `point_in_polygon_2d()`，並明確把這段 inner-poly ray/segment 迴圈列為獨立 Non-Goal，留待本輪處理。

獨立的本輪前置調查（4 個真實代表模型：`001_p.stl`／`005_p.stl`／`DentalModel_1M.stl`／`DentalModel_NeedRotate.stl`，reference 與 implementation 使用完全相同的 in-memory `outer_shell`／`inner_shell` 輸入，經同一次 PrusaSlicer CLI hollow 輸出＋Step 2 extend_bottom_vertices＋Step 3 align hollow to input，未經 STL round-trip；HEAD 已含 `perf-side-wall-point-in-polygon` 的 PIP 向量化）確認：

- inner-poly ray 迴圈的成本是 `O(len(inner_poly))` 的 Python scalar 迴圈，每個成功 bin 最多呼叫 11 次（1 次原始 candidate + 10 次 slide attempts），12 bins 上限 132 次。
- 四個模型上，這段迴圈的 aggregate time 佔候選評估階段（診斷用 instrumented 執行）約 63.2%～80.5%。

## Goals / Non-Goals

**Goals:**
- 新增私有 vectorized helper `_ray_polygon_nearest_hit_t()`，對單一 ray 與預先計算好的 polygon 邊陣列一次性以 NumPy 計算最近正向 hit，取代 `evaluate_sample_idx()` 內對 `inner_poly` 逐邊呼叫 `ray_seg_intersect_2d()` 的 Python `for` 迴圈。
- 在 `generate_side_wall_drains()` 選定 `inner_poly` 後，一次性預計算邊陣列（`ax`/`ay`/`ex`/`ey`），供該次呼叫內全部 `evaluate_sample_idx()` 呼叫重用，不逐 candidate 重建。
- 保留與修改前 scalar 組合（逐邊呼叫既有 `ray_seg_intersect_2d()` + `t > 0.01 and t < best_t`）完全一致的數值語意：`abs(denom) >= 1e-12` 才視為有效邊、`u` 含端點的 `[0,1]`、`t` 嚴格大於 `0.01`、取最小 `t`。
- 避免對無效 edge（parallel／collinear／zero-length）無條件除法而新增 NumPy runtime warning——用遮罩後的安全除數結構性避免，而非事後用 `errstate` 壓制警告。
- 用四個真實模型的真實 production `generate_side_wall_drains()` 呼叫（僅 monkeypatch 新 helper 這一個模組層級名稱作為 reference/implementation 切換點）驗證等價；另對 `001_p.stl`／`DentalModel_1M.stl` 量測完整 Auto Process（`run_ortho_pipeline()`）端到端改善。

**Non-Goals（本輪不處理）：**
- 不修改 `point_in_polygon_2d()`（上一輪已完成）、`ray_seg_intersect_2d()`（維持既有函式與語意，不順便改寫或刪除）。
- 不修改 `slice_mesh_at_z()`、candidate/slide search、angle bins、wall score、spacing gate、hole 幾何建立、Step 7～10 Boolean。
- 不新增第三方依賴，不針對特定模型的 polygon 點數做硬編碼 fast path。
- 不建立 candidate×edge 全矩陣——每個 candidate 仍只建立 O(inner edges) 的一維暫存陣列，`inner_poly` 邊陣列本身跨 candidate 共用（一次性預計算），但每次 ray 查詢的 `t`/`u`/`denom` 計算結果不跨 candidate 保留。

## Decisions

### D1：單次呼叫內向量化 + inner_poly 邊陣列一次性預計算，不建立 candidate×edge 矩陣

**根因**：`inner_poly` 在單次 `generate_side_wall_drains()` 呼叫中固定不變，但先前（scalar）版本每次 `evaluate_sample_idx()` 呼叫都重新走訪 `inner_poly` 的原始陣列與 Python `range()` 迴圈。既然邊的起點/向量（`ax`/`ay`/`ex`/`ey`）與 candidate 無關，一次性預計算並在該次呼叫的全部 `evaluate_sample_idx()` 呼叫間重用，避免了重複的 `np.roll`／減法運算；每次 candidate 呼叫時，只需對這組固定陣列與該 candidate 的 `(ox,oy,dx,dy)` 做一次 O(inner edges) 的 elementwise 計算，不需要、也没有建立 candidate×edge 的完整矩陣（12 bins × 11 slide attempts × inner edges 全部攤平在單一矩陣中，對大模型會是不必要的記憶體開銷，且與已驗證的逐 candidate 向量化相比沒有额外實證效益）。

**實作**：`_ray_polygon_nearest_hit_t(ox, oy, dx, dy, ax, ay, ex, ey)` 對全部邊一次性計算 `denom = dx*ey - dy*ex`、`t`、`u`，用遮罩 `hit = valid & (u>=0) & (u<=1) & (t>0.01)` 篩選合格邊，`best_t = float(np.min(np.where(hit, t, np.inf)))`。只回傳 `best_t`（不回傳 edge index）——這足以滿足 `evaluate_sample_idx()` 的下游需求（`pi_x = sx + nx*best_t`），且同 `t` 的 tie 在數值上必然相同，不需要追蹤是哪一條邊產生的（scalar 版本本身也只保留 `best_t` 數值，未曾對外暴露 tie-break 選中的 edge index）。

**考慮過的替代方案**：
- Candidate×edge 全矩陣批次化——會對 inner 輪廓點數多的模型（如 `001_p.stl` inner 2,271 點）建立不必要的大陣列（132 candidates × 2,271 edges），且與逐 candidate 向量化相比，這批次化本身不會減少總運算量，只是改變迴圈巢狀順序，故不採用。
- 每次 `evaluate_sample_idx()` 呼叫時才建立邊陣列——會讓 132 次呼叫各自重複 `np.roll`／減法運算 132 次，故改為在 `generate_side_wall_drains()` 層級一次性預計算。

### D2：安全除數用遮罩，不用 `errstate` 壓制警告

與 `point_in_polygon_2d()` 向量化（`perf-side-wall-point-in-polygon`）採用的方案一致：`safe_denom = np.where(valid, denom, 1.0)`，對 `abs(denom) < 1e-12` 的邊（parallel／collinear／zero-length）替換成無意義但安全的除數，因為這些位置最終會被 `hit` 遮罩排除，其 `t`/`u` 值不影響最終結果。結構性避免除以零，而非用 `np.errstate(divide='ignore')` 事後壓制警告。

## Risks / Trade-offs

- **[本輪是 Step 6 兩個 2D 幾何優化的最後一項]** `point_in_polygon_2d()`（上一輪）與本輪的 inner-poly ray/segment 迴圈是 Step 6 內僅有的兩個已識別、獨立的 Python scalar 迴圈成本點；本輪完成後兩者皆已處理。
- **[改善幅度依賴 inner 輪廓點數與該模型的候選評估活躍度]** 在候選評估幾乎全被跳過的模型（`DentalModel_NeedRotate.stl`，多數 bin 因 `no_inner_hit` 提早跳過 slide search）上，Step 6 改善幅度明顯低於候選評估活躍的模型——已在四個模型上如實記錄，不誇大宣稱。

## 量測方法澄清（審查後修正）

本文件先前版本的「正式 Step 6 timing」誤用了一個 monkeypatch 進 `_ray_polygon_nearest_hit_t()` 的 **precomputed-edge scalar control**（逐邊直接以預先算好的 `ax`/`ay`/`ex`/`ey` 陣列計算 `denom`/`t`/`u`，不透過函式呼叫）作為「reference」。這個 control 存在兩個問題：(1) 它仍然享有本輪才新增的 `inner_poly` 邊陣列一次性預計算（`generate_side_wall_drains()` 中，選定 `inner_poly` 後立即建立、供全部 132 次 `evaluate_sample_idx()` 呼叫共用），而真正的 HEAD `7d3e439` 對每一次 `evaluate_sample_idx()` 呼叫都重新走訪 `inner_poly`、重新索引 `inner_poly[i][0]`／`inner_poly[i][1]`；(2) 它完全跳過了逐邊呼叫 `ray_seg_intersect_2d()` 的函式呼叫開銷，而該函式內部每次都重新計算 `ex = bx-ax`／`ey = by-ay`。這兩項合計的開銷差異足以讓量出的「reference」時間系統性偏低，低估真正的改善幅度。

修正後的正式 timing 改用 **git worktree 簽出的真正 HEAD `7d3e439`**（`git worktree add`，未 checkout／reset／stash 主 working tree）作為 reference——與 implementation（目前 working tree）分別在獨立的 Python 子行程中執行，並交錯執行（reference/implementation 依序交替各跑 1 次，而非先跑完全部 reference 再跑全部 implementation）以降低系統時間漂移；子行程之間不共享 Python 行程，避免 `agent` package 重複匯入的衝突，同時保證 reference 執行的是 git 記錄的原始位元組碼，而非手寫的等價重現。Precomputed-edge scalar control 保留用於「正確性驗證」小節（見下）——因為它與向量化版本共用同一組 `ax`/`ex` 數學式，適合單獨隔離向量化本身在數值上是否等價，不受「是否重複計算邊陣列」這個效能面向差異的干擾；但它 **不能、也不再被稱為「目前 HEAD 的正式效能 Reference」**。

## 實作與驗證記錄

**inner ray/segment aggregate time / candidate 評估階段佔比**（診斷用 instrumented 執行，與正式 timing 分開量測；此處的 reference 仍是 precomputed-edge scalar control，只用於估計 ray 查詢本身在候選評估階段的佔比，不代表正式效能改善數字）：

| 模型 | Reference (precomputed scalar control) ray_time | Implementation (vectorized) ray_time | ray_share: ref → impl |
|---|---:|---:|---|
| `001_p.stl` | 0.2242s | 0.0043s | 80.5% → 8.2% |
| `005_p.stl` | 0.1722s | 0.0041s | 79.0% → 8.5% |
| `DentalModel_1M.stl` | 0.2199s | 0.0044s | 63.2% → 3.2% |
| `DentalModel_NeedRotate.stl` | 0.0068s | 0.0009s | 26.0% → 4.5% |

**正式 Step 6 timing**（reference＝git worktree 簽出的真正 HEAD `7d3e439`、implementation＝目前 working tree，各自獨立子行程執行、交錯執行降低系統時間漂移，1 次 warm-up + 3 次計時，取 median，過程不含逐次 instrumentation；四個模型的三次計時皆緊密收斂，未見明顯變異，未需加測）：

| 模型 | Reference（真正 HEAD `7d3e439`）median | Implementation median | 改善 |
|---|---:|---:|---:|
| `001_p.stl` | 0.4012s | 0.0506s | **−87.4%** |
| `005_p.stl` | 0.3193s | 0.0475s | **−85.1%** |
| `DentalModel_1M.stl` | 0.4769s | 0.1295s | **−72.8%** |
| `DentalModel_NeedRotate.stl` | 0.0305s | 0.0213s | **−30.2%** |

**記憶體**：`tracemalloc` 量測最大代表模型（`DentalModel_1M.stl`）單次 `generate_side_wall_drains()` 呼叫的 Python-level peak allocation，reference（precomputed scalar control）23.63MB、implementation（vectorized）23.62MB，差異 <0.1MB——peak 由既有 slicing（未改動）主導，向量化 ray 查詢與 inner_poly 邊陣列預計算本身只配置 O(inner 輪廓點數) 的小型暫存陣列，未建立 candidate×edge 矩陣。此數字未重新以真正 HEAD `7d3e439` 量測，但由於記憶體差異已在 <0.1MB 等級、peak 由未改動的 slicing 主導，預期真正 reference 的記憶體量級不會有實質差異。

**正確性驗證**（4 個真實模型，直接呼叫 production `agent.ortho_pipeline.generate_side_wall_drains()`，僅 monkeypatch 模組層級的 `_ray_polygon_nearest_hit_t` 名稱作為 reference/implementation 切換點，其餘呼叫路徑為 production 程式碼本身；reference 使用 precomputed-edge scalar control——直接以預計算 `ex`/`ey` 陣列重寫的 scalar-loop 等價實作，刻意不透過 `a+e` 重建端點座標，因為浮點加法不保證精確逆推減法，改用與 `_ray_polygon_nearest_hit_t()` 相同的公式逐邊計算，與逐邊呼叫 `ray_seg_intersect_2d()` 原始頂點座標的結果數學上等價；此處使用該 control 是刻意選擇，用於隔離向量化本身的數值等價性，非效能 reference）：

| 模型 | ray 查詢次數（ref/impl） | 逐次查詢結果 | Skip reasons（真實 log 解析） | Hole 數量 | vertices/faces array-exact |
|---|---|---|---|---|---|
| `001_p.stl` | 132 / 132 | 完全一致 | `{no_bin:0, no_inner_hit:0, too_close:1}` 兩者相同，placed=11 | 11 | ✅ |
| `005_p.stl` | 132 / 132 | 完全一致 | `{no_bin:0, no_inner_hit:0, too_close:2}` 兩者相同，placed=10 | 10 | ✅ |
| `DentalModel_1M.stl` | 132 / 132 | 完全一致 | `{no_bin:0, no_inner_hit:0, too_close:1}` 兩者相同，placed=11 | 11 | ✅ |
| `DentalModel_NeedRotate.stl` | 52 / 52 | 完全一致 | `{no_bin:0, no_inner_hit:8, too_close:3}` 兩者相同，placed=1 | 1 | ✅ |

四個模型的孔數（11/10/11/1）與 `perf-side-wall-point-in-polygon`、production baseline log 一致。

**完整 Auto Process 端到端量測**（reference＝git worktree 簽出的真正 HEAD `7d3e439`、implementation＝目前 working tree，各自獨立子行程執行 `run_ortho_pipeline()` 完整流程含 PrusaSlicer CLI hollow 生成與 Step 7～10 Boolean，使用 scratch `BUNDLE_JOBS_DIR` 不觸碰真實 `agent/jobs/`，worktree 側以 `SLICER_ENGINE_BIN` 環境變數指回主 repo 既有的 PrusaSlicer 執行檔（worktree 本身不含編譯產物），交錯執行降低系統時間漂移，1 次 warm-up + 3 次計時取 median）：

| 模型 | Reference（真正 HEAD `7d3e439`）median | Implementation median | 改善 |
|---|---:|---:|---:|
| `001_p.stl` | 5.416s | 5.044s | **−6.9%**（−0.372s） |
| `DentalModel_1M.stl` | 14.222s | 13.982s | **−1.7%**（−0.240s） |

（此前使用 precomputed-edge scalar control 作為 reference 時，`001_p.stl` 曾誤判為「雜訊範圍內、無可測量差異」——修正為真正 HEAD `7d3e439` 後，兩模型皆可測得一致方向、量級與 Step 6 節省相符的正向改善。）

**量測意義**：Step 6 本身分別節省約 `0.351s`（`001_p.stl`：`0.4012s → 0.0506s`）與 `0.347s`（`DentalModel_1M.stl`：`0.4769s → 0.1295s`）；完整 Auto Process 實測則分別節省 `0.372s`（`001_p.stl`）與 `0.240s`（`DentalModel_1M.stl`）——兩層量測來自不同次的獨立計時（Step 6 單獨量測、完整 pipeline 端到端量測），數字接近但不強求逐位吻合，皆在正常量測噪訊範圍內。完整 Auto Process 由 PrusaSlicer CLI hollow 生成（Step 1）與多次 Boolean 運算（Step 7～10）主導，這兩者在本次改動範圍之外、未被觸及。兩模型的 Step 6 絕對節省秒數其實相近（`0.351s`／`0.347s`），但完整 pipeline 總時間差異懸殊（`001_p.stl` ~5.4s、`DentalModel_1M.stl` ~14.2s），所以同樣的絕對節省換算成整體改善比例時，`DentalModel_1M.stl`（1.7%）明顯低於 `001_p.stl`（6.9%）——`DentalModel_1M.stl` 的完整 pipeline 由 Boolean 運算（在 100 萬面等級的網格上）主導，同一段 Step 6 節省相對於更長的總時間佔比自然更小。本次改動的價值在於 Step 6 本身 72.8%～87.4% 的局部改善，而非宣稱對完整 Auto Process 有巨大的整體加速——這點與 `perf-side-wall-point-in-polygon`／`perf-side-wall-drain-slice` 兩輪的完整 pipeline 量測結論一致（Step 6 從未是完整 pipeline 的主要成本來源）。

**最終輸出等價性**（兩模型的 reference／implementation 兩次獨立端到端執行，各自完整 `ortho_result.stl`）：faces／vertices count 完全相同（`001_p.stl` 205,904／102,928；`DentalModel_1M.stl` 970,266／485,124）、volume 完全相同（非僅在容忍誤差內）、bounds 完全相同、`is_watertight` 相同（`001_p.stl` 皆 `True`；`DentalModel_1M.stl` 皆 `False`——此為該模型在目前 HEAD 下經 Step 9/10 Boolean 後的既有狀況，`perf-side-wall-drain-slice` 已記錄並確認非本輪或上一輪改動引入，reference 與 implementation 在此狀況上完全一致）。未比對、也不宣稱 Boolean 後 `ortho_result.stl` 的 STL bytes 完全相同。

另補充：`agent/tests/test_side_wall_inner_poly_ray_vectorized.py`（24 tests）涵蓋一般單一/多重 hit、無 hit、空/單點 polygon、parallel/collinear/zero-length edge、segment endpoint（`u=0`／`u=1`）、`u` 超出範圍、`t` 邊界（`t=0`／`t=0.01`／略大於 `0.01`）、`abs(denom)` 相對 `1e-12` 的邊界、同 `t` tie-break（保留較低 edge index）、最後一點連回第一點、2000 組固定 seed 隨機 polygon/ray 壓力對照（0 mismatch）、正常輸入與 500 組隨機壓力測試皆不新增 NumPy runtime warning、輸入陣列不被原地修改、對內部 float32 downcast 敏感的精度測試。
