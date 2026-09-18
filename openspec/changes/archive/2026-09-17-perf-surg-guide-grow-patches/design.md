## Context

Surgical Guide Auto Orient（`POST /api/v2/auto-orient` mode=2）先前的效能調查（見 `openspec/changes/archive/2026-09-15-optimize-auto-process-performance/design.md` Non-Goals）已定位 `_grow_patches()`（[agent/auto_orient_surg_guide.py:289](../../../agent/auto_orient_surg_guide.py#L289)）約占 `_find_guide_direction()` 執行時間的 50～57%，但當時範圍未界定、亦未建立可重現的 benchmark，明確排除在該提案之外。

本提案是該調查的後續、獨立變更，範圍限定在 Phase 0（建立可重現的 benchmark／A-B 正確性基準）與 Phase 1（`_grow_patches()` per-patch statistics 的最小修改優化）。BFS region growing、PCA／scanline 導孔判定、concave vote、vertex weld／adjacency 建立留待下一輪視新的 profiling 結果決定範圍，本提案不預先承諾。

`agent/model_classifier.py::detect_drill_holes()` 是同一段 C++（`isDrillPatchByEdges`）的另一份 1:1 port，且已在 `2da36f1 perf(classifier): optimize drill hole detection` 完成完全相同性質的優化（pre-filter `>=5` faces、重用 `face_area`、略過 `max_angle_deg`）並穩定運行於生產環境——這是本提案優化方向已被驗證安全的直接先例。

## Goals / Non-Goals

**Goals:**
- 建立一次性、可重跑的 benchmark／正確性快照 harness（僅存在於 scratchpad，不落地為 production code 或永久測試基礎設施），供 Phase 1 前後量測與 A/B 比對。
- 以最小修改優化 `_grow_patches()` 的 per-patch statistics（Step 5）：面數 `<5` 的 patch 略過統計、重用 `mesh.face_area`、停止計算無讀取者的 `max_angle_deg`。
- 不改變 fixed seed normal 的 patch 成長語意、BFS assignment、face/seed traversal 規則、adjacency 建立方式、vertex weld `eps=1e-4`、非流型 edge 行為、導孔判定 threshold、fallback 與 orientation 決策流程。

**Non-Goals（本輪不處理，留待下一輪視 profiling 決定）：**
- BFS region growing 本身的向量化（Step 4）。
- `_is_drill_patch_by_edges()` 的 PCA 投影／`np.cov` 向量化。
- `_patch_has_hole_by_scanlines()` 的 scanline 向量化。
- `detect_concave_faces()` 的 edge-loop 向量化。
- `_weld_and_build()` 的 vertex weld／adjacency 建立向量化。

## Decisions

### D1：`_grow_patches()` Step 5 只對 `len(faces) >= 5` 的 patch 計算統計

**根因**：Step 5（[:331-358](../../../agent/auto_orient_surg_guide.py#L331-L358)，修改前）對**每一個** BFS 產生的 patch 無條件計算 `area`／`avg_normal`／`center`／`max_angle_deg`，即使該 patch 稍後會被 `_find_guide_direction()`（[:809](../../../agent/auto_orient_surg_guide.py#L809)）與 `_refine_up_with_quasi_candidates()`（[:1011](../../../agent/auto_orient_surg_guide.py#L1011)）以 `len(P.faces) < 5 or P.area <= 0.0` 短路捨棄。以真實手術導板模型量測（`SurgicalGuide_1.stl`，201,574 faces），BFS 產生 72,310 個 patch，其中 63,364 個（88%）面數 `<5`。

**為何安全**：全 repo grep 確認 `.area`／`.avg_normal`／`.center` 的**所有**讀取點（`_is_drill_patch_by_edges()` 內部自身的 `len(P.faces) < 5` 早退、`_pick_best_drill_patch_stage3()`／`_entrance_dir_by_concave()`／`_build_drill_cylinders()` 只接收已通過完整導孔篩選的 `drill_patches`、`_refine_up_with_quasi_candidates()` 的 `len(P.faces) < 5 or P.area <= 0.0` 短路）皆在讀取這些欄位前已先檢查面數門檻，Python 的 `or` 短路求值保證 `P.area` 在 `len(P.faces) < 5` 為真時**不會被求值**。因此面數 `<5` 的 patch 保留 `_Patch` dataclass 預設值（`area=0.0`、`avg_normal=zeros`、`center=zeros`）不影響任何既有行為。`_choose_entrance_direction()`（[:732](../../../agent/auto_orient_surg_guide.py#L732)）雖也讀取這些欄位但全 repo 確認未被任何呼叫端使用（死函式），不在安全性論證範圍內，也不受本次修改影響。

### D2：重用 `mesh.face_area`，移除逐 face 的 `_norm(_cross(...))` 面積重算

**根因**：Step 5（修改前）以 `A = 0.5 * _norm(_cross(p1 - p0, p2 - p0))` 逐 face 重新計算面積，而 `mesh.face_area`（[_weld_and_build:263](../../../agent/auto_orient_surg_guide.py#L263)）已用完全相同的公式（`0.5 * norm(cross(e1, e2))`）向量化算好，且已是 `detect_concave_faces()`（[:918](../../../agent/auto_orient_surg_guide.py#L918)）、`_entrance_dir_by_concave()`（[:968](../../../agent/auto_orient_surg_guide.py#L968)）等既有生產路徑的既有輸入——本項只是讓 Step 5 與這些既有消費者使用同一份資料，不引入新的數值來源。

**已知的浮點差異來源（量測，非假設）**：`mesh.face_area` 是 `np.linalg.norm`（float32 陣列的向量化 reduction）算出，修改前的逐 face 重算則透過 `_norm()` 把每個分量先轉成 Python `float`（double）再開根號（double precision）；`sum_n`／`sum_c` 的累加方式也從 Python 逐面 `+=`（固定累加順序）改為 `numpy.ndarray.sum(axis=0)`（pairwise 累加，順序不同）。這兩者都只造成浮點捨入層級的差異，不改變任何數值路徑的選擇邏輯。

### D3：停止計算 `max_angle_deg`

**根因**：全 repo grep 確認 `_Patch.max_angle_deg` 除了定義處（dataclass 欄位）與被賦值處（修改前的 Step 5）之外，沒有任何讀取者——`model_classifier.py` 對應的 `_DrillPatchInfo.max_angle_deg` 欄位也是相同狀態（該檔案的既有註解明確寫著「not computed (unused by caller; field kept)」），是本項改動已被驗證安全的先例。

**修法**：欄位定義保留於 `_Patch` dataclass（相容性），Step 5 不再計算其值，維持 dataclass 預設值 `0.0`。

## 實作與驗證記錄

**Benchmark harness**：僅存在於 scratchpad（`surg_guide_harness.py`），未落地為 repo 內的檔案或永久 profiling framework，符合既有 `auto-process-performance` 能力「不建立永久性效能監控框架」的慣例。自動搜尋 `C:\Users\user\Pictures\tempTest\SurgicalGuide*.stl` 找到 **4 個**模型（`SurgicalGuide_1.stl` ~ `SurgicalGuide_4.stl`），而非原先預期的 3 個；本輪 Phase 0／Phase 1 的量測與 A/B 驗證涵蓋全部 4 個。

| 模型 | faces | verts |
|---|---|---|
| `SurgicalGuide_1.stl` | 201,574 | 100,777 |
| `SurgicalGuide_2.stl` | 97,372 | 48,678 |
| `SurgicalGuide_3.stl` | 160,666 | 80,315 |
| `SurgicalGuide_4.stl` | 236,034 | 117,955 |

**Benchmark（每模型 warm-up ×1 + 正式 5 runs，median wall time；`time.perf_counter()`，非 cProfile）**：

| 模型 | 階段 | before (median) | after (median) | 改善 |
|---|---|---|---|---|
| SurgicalGuide_1 | `compute_auto_orientation_surg_guide_detail()` | 3973.1 ms | 2643.4 ms | 33.5% |
| SurgicalGuide_1 | `_grow_patches()`（BFS+stats 整體） | 2405.2 ms | 1033.7 ms | 57.0% |
| SurgicalGuide_2 | `compute_auto_orientation_surg_guide_detail()` | 1896.0 ms | 1216.3 ms | 35.8% |
| SurgicalGuide_2 | `_grow_patches()` | 1179.8 ms | 505.2 ms | 57.2% |
| SurgicalGuide_3 | `compute_auto_orientation_surg_guide_detail()` | 3221.2 ms | 2022.0 ms | 37.2% |
| SurgicalGuide_3 | `_grow_patches()` | 1996.6 ms | 824.4 ms | 58.7% |
| SurgicalGuide_4 | `compute_auto_orientation_surg_guide_detail()` | 4696.5 ms | 3012.0 ms | 35.9% |
| SurgicalGuide_4 | `_grow_patches()` | 2957.0 ms | 1238.9 ms | 58.1% |

`_weld_and_build()`（未修改）與「concave/fallback + best-patch 挑選」（未修改）兩段耗時在 before/after 之間的差異落在 ±5% 的機器負載雜訊範圍內（例如 SurgicalGuide_1 的 weld_and_build 358.6ms→363.3ms），確認本次改動未觸及、也未意外影響這兩段。

**A/B 正確性比對（全部 4 模型）**：patch face membership 100% 相同（0 mismatches）；drill candidate patch id 集合、分支（drill vs fallback）、`decision_faces`、`candidate_faces` 完全相同；`res.dir`／`rotation_rad` **bit-exact 相同（max diff = 0.000e+00）**。`area`／`avg_normal`／`center` 的浮點差異量級：`area` 最大 5.4e-7、`avg_normal` 最大 1.2e-7、`center` 最大 3.8e-6——全部落在 D2 已知的精度來源範圍內，未造成任何 gate（PCA 直徑/aspect、scanline、conn-edge、220° turn-angle）或候選判定的改變。

**重要澄清（後續四輪整合驗收時更新，2026-09-17）**：上一段的數字是本提案落地當時、對該次量測所用模型組合觀察到的極值，**不是本提案 spec 的正式驗收界線**——`specs/surgical-guide-grow-patches-performance/spec.md` 明確寫明「MUST NOT 以『數值完全相同』作為驗收線；驗收線改以『該差異不改變任何 gate、候選判定或最終方向』表達」，即本來就沒有承諾 `area`／`avg_normal`／`center` 的絕對差異會被限制在某個固定數值以下。四輪整合驗收（`perf-surg-guide-grow-patches`＋`perf-surg-guide-drill-patch-pca`＋`perf-surg-guide-bfs-region-growing`＋`perf-surg-guide-concave-chunking`）以獨立 `git worktree`隔離原始 HEAD 重新量測 `SurgicalGuide_1.stl` 時，發現 `area` 的實際最大差異為 **1.802e-6**（並非先前記錄的 5.4e-7），來源已定位到具體 patch：

| 項目 | 數值 |
|---|---|
| patch id（base／opt 兩版排序與 id 分配相同） | 2917 |
| 面數 | 845 |
| 原始（HEAD）`P.area` | 341.2449932425358 |
| 優化後（working tree）`P.area` | 341.24499504447886 |
| 絕對誤差 `|base − opt|` | 1.8019430285676208e-06 |
| 相對誤差 `絕對誤差 / |base 值|` | 5.280e-09 |

重新以相同方法（僅比較面數 `>=5`、依 face-index 集合對應的 patch；`area`／`avg_normal`／`center` 各自取全模型最大絕對差）掃過現有 5 個真實模型（含 `SurgicalGuide_1M.stl`）確認全模型真正極值：`area` 最大 1.802e-6（`SurgicalGuide_1`，即上表這個 845-face patch）、`avg_normal` 最大 1.192e-7（與先前記錄一致）、`center` 最大 3.815e-6（與先前記錄同量級，`SurgicalGuide_4`／`SurgicalGuide_1M`）。`area` 的相對誤差在所有極值案例中都落在 `1e-9`～`1e-8` 量級，與 D2 記載的根因（`mesh.face_area` 向量化 reduction 的浮點路徑 + `numpy.sum(axis=0)` pairwise 累加順序 vs. 原本逐 patch Python `+=` 累加順序不同）完全吻合——845 個 face 相加的面數更多、面積量級更大（約 341），比先前極值案例累積更多浮點捨入量級上是合理的，不是新的數值路徑或邏輯分支。此次重新量測的 `drill_patch_accept_set_match`、`entrance_dir_match`、`rotation_rad_match`（`compute_auto_orientation_surg_guide_detail()`）在 `SurgicalGuide_1` 上皆為 **True／bit-exact**，與本提案 spec 的實際驗收線（行為等價，非數值相同）一致，未發現任何 gate 翻轉或決策改變。

**回歸測試**：新增 `agent/tests/test_auto_orient_surg_guide_grow_patches.py`（5 tests，合成幾何，不依賴外部 STL 檔案）：pin 住「面數 `<5` 的 patch 維持 dataclass 預設值」「符合門檻的 patch 統計值與 `mesh.face_area` reuse 一致」「`_grow_patches()` 內部 `_cross()` 呼叫次數為 0（直接驗證『不再重算面積』本身）」「`max_angle_deg` 欄位保留但恆為預設值 0.0」。

**回歸範圍**：`pytest agent/tests/ -q --continue-on-collection-errors`：670 passed、1 failed、3 errors——與 D4/D5 完成時的既有基準（665 passed、1 failed、3 errors）相比，新增的 670−665=5 即本項新增測試；既有的 1 failed（`test_prz_print_time.py`，斷言 11.0≠14.0）與 3 collection errors（缺少 `httpx`）數字不變，確認非本項引入。

**四輪整合驗收**：本 change 與後續三輪（`perf-surg-guide-drill-patch-pca`／`perf-surg-guide-bfs-region-growing`／`perf-surg-guide-concave-chunking`）疊加後的整合正確性與累積效能驗收記錄，見 `perf-surg-guide-concave-chunking/design.md`「四輪整合驗收」章節，避免重複記載。

## Risks / Trade-offs

- **[面數 `<5` 的 patch 未來被新呼叫端讀取 `.area`/`.avg_normal`/`.center`]** 若未來新增的呼叫端忘記先檢查 `len(P.faces) < 5`，會靜默讀到預設值（0.0/zeros）而非「未計算」的顯式訊號。→ 已在程式碼註解中明確記載此不變量（`_grow_patches()` 內的說明註解），且本提案的 spec（見 `specs/surgical-guide-grow-patches-performance/spec.md`）將此列為明確的正確性契約，未來若違反可作為可測試的回歸點。
- **[浮點路徑改變導致邊界情況下的 gate 翻轉]**（已驗證未發生）改用 `mesh.face_area` 與向量化累加，理論上可能在某個 patch 的統計值恰好落在 PCA 直徑/aspect 或其他 gate 的邊界時翻轉判定。→ 4 個真實模型的 A/B 比對顯示 drill candidate 集合、分支、最終 `rotation_rad` 完全相同（`rotation_rad` bit-exact），未觀察到任何翻轉；若未來遇到邊界模型出現差異，本提案的量測方法（snapshot 比對）可直接重跑定位。
- **[本輪範圍刻意限縮，未觸及 `_grow_patches()` 57% 改善後仍占約 39-40% 的 `_find_guide_direction()` 時間]**（已知，非本輪目標）BFS 本身、`_is_drill_patch_by_edges()`（PCA/scanline）、`detect_concave_faces()` 仍是下一輪候選——見下方「剩餘瓶頸」。此為刻意的範圍切分，非遺漏。

## Migration Plan

單一階段，可獨立驗證與獨立 commit：

| 階段 | 內容 | 回滾方式 |
|---|---|---|
| 0 | Benchmark／A-B harness 建立與修改前基準量測（scratchpad，不落地） | — |
| 1 | `_grow_patches()` Step 5 優化（`agent/auto_orient_surg_guide.py`） | 單一 commit revert |

## Open Questions

- **下一輪範圍如何界定？** 本輪完成後，`_grow_patches()` 仍占 `_find_guide_direction()` 約 39～41%（`_is_drill_patch_by_edges()` 的 PCA/`np.cov` 開銷、`detect_concave_faces()` 的 Python edge-loop 隨之成為相對占比更高的區塊）。建議下一輪先针對 `_is_drill_patch_by_edges()` 的 PCA 投影向量化（可直接參考 `model_classifier.py::_drill_is_drill_patch` 的既有實作），再視新的 profiling 決定是否處理 `detect_concave_faces()` 或 BFS 本身。
