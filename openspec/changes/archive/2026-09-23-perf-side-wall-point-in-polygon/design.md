## Context

`agent/ortho_pipeline.py::generate_side_wall_drains()` 的候選評估（`evaluate_sample_idx()`）每次呼叫都用 `point_in_polygon_2d()` 對 outer_poly（fine outer contour）做一次法向翻轉判定。上一輪（`perf-side-wall-drain-slice`，已 archive）處理了 Step 6 內最大的單一成本（`slice_mesh_at_z()` 的三角形掃描），並明確把 `point_in_polygon_2d()`（outer-poly parity 判定）與 inner-poly ray/segment 迴圈列為 Non-Goal，留待後續獨立提案。

獨立的本輪前置調查（4 個真實代表模型：`001_p.stl`／`005_p.stl`／`DentalModel_1M.stl`／`DentalModel_NeedRotate.stl`，reference 與 prototype 使用完全相同的 in-memory `outer_shell`／`inner_shell` 輸入，經同一次 PrusaSlicer CLI hollow 輸出＋Step 2 extend_bottom_vertices＋Step 3 align hollow to input，未經 STL round-trip）確認：

- `point_in_polygon_2d()` 每次呼叫的成本是 `O(len(outer_poly))` 的 Python scalar 迴圈，outer 輪廓點數越多成本越高——`DentalModel_1M.stl` outer 輪廓有 4,644 點，是四個模型中最密的。
- 每個成功 bin 最多呼叫 11 次（1 次原始 candidate + 10 次 slide attempts），12 bins 上限為 132 次呼叫。
- 呼叫的 query point 完全重複比例只有 0%～15.4%（4 個模型量測），代表快取空間有限；真正的成本是「每次呼叫內部的 Python scalar 迴圈」本身。

## Goals / Non-Goals

**Goals:**
- 用 NumPy 對 polygon 邊做 elementwise parity 判定，取代 `point_in_polygon_2d()` 內對每條邊逐一執行的 Python `for` 迴圈，函式簽章、回傳型態、呼叫方式完全不變。
- 保留與修改前 scalar 版本完全一致的數值語意：ray-casting parity 的 `>`/`<` 比較方向、point-on-boundary 行為、horizontal/vertical edge 行為、degenerate（<3 點）與空 polygon 的既有回傳值。
- 避免對不滿足 crossing 條件的邊（含 horizontal edge）無條件執行除法而新增 NumPy runtime warning——用遮罩後的安全除數（`np.where` 替換非必要的除數，而非事後用 `errstate` 壓制警告）結構性避免，而非僅壓制警告輸出。
- 用四個真實模型的真實 production `generate_side_wall_drains()` 呼叫（僅 monkeypatch `point_in_polygon_2d` 這一個模組層級名稱作為 reference/implementation 切換點，其餘呼叫路徑完全是 production 程式碼本身）驗證：呼叫次數、逐次查詢點與翻轉結果、skip reasons（直接從 production 真實 log 解析）、hole 數量，以及 pre-Boolean 的 `.vertices`／`.faces` 皆 `np.array_equal`。

**Non-Goals（本輪不處理）：**
- 不處理 inner-poly ray/segment 迴圈（`evaluate_sample_idx()` 內對 `inner_poly` 的迴圈、`ray_seg_intersect_2d()`）——上一輪調查已確認這是獨立、不重疊的成本點，留待後續獨立提案。
- 不加入 query point 快取（已量測重複比例僅 0%～15.4%，快取價值有限）。
- 不建立 candidate×edge 或其他跨呼叫批次矩陣（會引入不必要的記憶體與控制流複雜度，且與已驗證的單次呼叫向量化方案相比沒有额外實證效益）。
- 不改變 `slice_mesh_at_z()`、candidate/slide search、angle-bin、wall score、spacing gate、hole 幾何建立、Step 7～10 Boolean。
- 不新增第三方依賴，不針對特定模型的 polygon 點數做硬編碼 fast path。

## Decisions

### D1：單次呼叫內向量化，不做跨呼叫快取或批次化

**根因**：呼叫重複型態量測（4 個真實模型）顯示同一 query point 完全重複的比例只有 0%（`001_p`）～15.4%（`DentalModel_NeedRotate`），代表可快取的「命中」空間很小；真正的成本集中在「每次呼叫內部對 outer_poly 全部邊執行的 Python scalar 迴圈」，且成本隨 outer 輪廓點數線性增長（`DentalModel_1M.stl` 4,644 點時，單一 helper 的 aggregate time 達 0.99s，佔候選評估階段真實量測 67.8%）。

**實作**：用 `np.roll(x, 1)`／`np.roll(y, 1)` 取得每個頂點的「前一個頂點」（`j = i-1 mod n`，與原 scalar 迴圈「`j` 從 `n-1` 起始、隨 `i` 遞增變成 `i-1`」完全對應），對全部邊一次性計算 crossing 條件與 x-intercept，最後用 `np.count_nonzero(hits) % 2` 取代原本「逐邊 `inside = not inside`」的連續 XOR 翻轉——這是數學上完全等價的重述（parity 的奇偶性與連續 XOR 翻轉結果相同），且每條邊的布林/浮點運算都彼此獨立（無 reduction 順序問題），與 scalar 版本逐點比較時不會有浮點運算順序差異。

**考慮過的替代方案**：
- 跨呼叫快取（LRU 或 dict）——已用實測數字（重複比例 0%～15.4%）證明價值有限，故不採用。
- Candidate×edge 全矩陣批次化（同一 bin 內 11 次呼叫一次算完）——會需要重構 `evaluate_sample_idx()` 的呼叫順序（原本每次呼叫的 query point 依賴前一次 slide 的結果選擇下一個 idx？實際上 slide 的 11 個 idx 彼此獨立可預先算出，但這樣的重構會擴大本輪改動範圍到候選搜尋的控制流本身，且已驗證的單次呼叫向量化已能把 PIP aggregate time 從 0.99s 壓到 0.007s（`DentalModel_1M.stl`），邊際效益不足以抵銷控制流重構的風險，故本輪不採用。

### D2：安全除數用 `np.where` 遮罩，不用 `errstate` 壓制警告

原 scalar 版本靠 Python 的短路 `and`：`(yi > py) != (yj > py)` 為 `False` 時，右側的除法表達式根本不會被求值，因此 horizontal edge（`yi == yj`）永遠不會觸發除以零。NumPy 向量化後若對全部邊無條件計算 `xints`，horizontal edge 會產生真正的 `0/0`。

**實作**：`denom = np.where(crosses, yj - y, 1.0)`——`crosses` 為 `False` 的位置，除數被替換成無意義但安全的 `1.0`，因為這些位置最終會被 `crosses & (...)` 的 `crosses=False` 遮蔽掉，其 `xints` 值不影響最終結果。這是結構性避免除以零，而非用 `np.errstate(divide='ignore')` 事後壓制警告——後者仍會產生真正的 `0/0`（值為 `nan`）只是不印出來，前者從根本上不會計算出無效值。

**考慮過的替代方案**：
- `np.errstate` 壓制警告——技術上可行但被要求的「避免新增 warning」精神是「不產生」而非「產生後隱藏」，且 `nan` 值即使被遮蔽也可能在未來維護時造成困惑；`np.where` 遮罩版本更明確、更安全。

## Risks / Trade-offs

- **[本輪只處理 outer-poly PIP，inner-poly ray/segment 迴圈仍是 Step 6 的另一個成本點]** 已在上一輪與本輪調查中明確記錄為獨立、不重疊的 Non-Goal，留待後續獨立提案；不影響本次改動本身的正確性或可採用性。
- **[改善幅度高度依賴 outer 輪廓點數]** 在 outer 輪廓稀疏的模型（`001_p.stl` 228 點、`005_p.stl` 262 點、`DentalModel_NeedRotate.stl` 23 點）上，Step 6 改善幅度只有 5.8%～11.7%；在 outer 輪廓極密的模型（`DentalModel_1M.stl` 4,644 點）上達 66.9%。→ 這是預期中的行為（PIP 成本本就正比於 outer 輪廓點數），已在四個模型上如實記錄，不誇大宣稱。

## 實作與驗證記錄

**PIP helper aggregate time / candidate 評估階段佔比**（診斷用 instrumented 執行，與正式 timing 分開量測）：

| 模型 | Reference (scalar) pip_time | Implementation (vectorized) pip_time | pip_share: ref → impl |
|---|---:|---:|---|
| `001_p.stl` | 0.0502s | 0.0048s | 11.1% → 1.2% |
| `005_p.stl` | 0.0567s | 0.0037s | 15.0% → 1.2% |
| `DentalModel_1M.stl` | 0.9894s | 0.0073s | 67.8% → 1.5% |
| `DentalModel_NeedRotate.stl` | 0.0020s | 0.0011s | 6.4% → 3.7% |

**正式 Step 6 timing**（1 次 warm-up + 3 次計時，`time.perf_counter()`，取 median，對真實 production `generate_side_wall_drains()`，過程不含逐次 instrumentation）：

| 模型 | Reference (scalar) median | Implementation (vectorized) median | 改善 |
|---|---:|---:|---:|
| `001_p.stl` | 0.4354s | 0.3940s | **−9.5%** |
| `005_p.stl` | 0.3715s | 0.3281s | **−11.7%** |
| `DentalModel_1M.stl` | 1.4709s | 0.4872s | **−66.9%** |
| `DentalModel_NeedRotate.stl` | 0.0312s | 0.0294s | **−5.8%** |

**記憶體**：`tracemalloc` 量測最大代表模型（`DentalModel_1M.stl`）單次 `generate_side_wall_drains()` 呼叫的 Python-level peak allocation，reference（scalar）23.63MB、implementation（vectorized）23.62MB，差異 <0.1MB——peak 由既有 slicing（未改動）主導，向量化 PIP 本身只在單次呼叫內配置 O(outer 輪廓點數) 的小型暫存陣列（最大 4,644 點，數十 KB 等級），未建立 candidate×edge 矩陣。

**正確性驗證**（4 個真實模型，直接呼叫 production `agent.ortho_pipeline.generate_side_wall_drains()`，僅 monkeypatch 模組層級的 `point_in_polygon_2d` 名稱作為 reference/implementation 切換點，其餘呼叫路徑為 production 程式碼本身；reference 使用凍結的修改前 scalar 版本，implementation 使用目前 production 的向量化版本）：

| 模型 | PIP 呼叫數（ref/impl） | 逐次查詢點+翻轉結果 | Skip reasons（真實 log 解析） | Hole 數量 | vertices/faces array-exact |
|---|---|---|---|---|---|
| `001_p.stl` | 132 / 132 | 完全一致 | `{no_bin:0, no_inner_hit:0, too_close:1}` 兩者相同，placed=11 | 11 | ✅ |
| `005_p.stl` | 132 / 132 | 完全一致 | `{no_bin:0, no_inner_hit:0, too_close:2}` 兩者相同，placed=10 | 10 | ✅ |
| `DentalModel_1M.stl` | 132 / 132 | 完全一致 | `{no_bin:0, no_inner_hit:0, too_close:1}` 兩者相同，placed=11 | 11 | ✅ |
| `DentalModel_NeedRotate.stl` | 52 / 52 | 完全一致 | `{no_bin:0, no_inner_hit:8, too_close:3}` 兩者相同，placed=1 | 1 | ✅ |

四個模型的孔數（11/10/11/1）與上一輪調查、production baseline log 一致。

另補充：`agent/tests/test_point_in_polygon_2d_vectorized.py`（27 tests）涵蓋 convex/concave polygon、orientation 反轉、內部/外部/edge/vertex query、horizontal/vertical edge、repeated vertex、zero-length edge、空 polygon、<3 點 degenerate polygon、固定資料表、2000 組固定 seed 隨機 polygon/query parity 對照（0 mismatch）、正常輸入與 500 組隨機壓力測試皆不新增 NumPy runtime warning、輸入陣列不被原地修改（`test_input_dtype_not_mutated`），以及一個對內部 float32 downcast 敏感的精度測試（`test_float64_precision_is_not_downcast_internally`：polygon 寬度 1e-8，低於 float32 在該量級的精度，若內部曾被降為 float32 會使 polygon 寬度塌陷、結果由 `True` 變 `False`；已確認此 fixture 在目前 NumPy 環境下確實具區分力）——後者是本輪審查補強項目，因為單純比對「呼叫前後輸入 dtype 不變」無法偵測函式內部 `poly = poly.astype(np.float32)` 這種只重新綁定區域變數、不會反映到呼叫端陣列的降精度。
