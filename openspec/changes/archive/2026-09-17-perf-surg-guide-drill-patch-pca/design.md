## Context

本提案是 Surgical Guide Auto Orient 效能優化系列的第二輪，緊接在 `perf-surg-guide-grow-patches`（Phase 1，`_grow_patches()` per-patch statistics 優化）之後。以 Phase 1 完成後的程式碼為新 baseline 重新 profiling，確認 `_is_drill_patch_by_edges()` 已成為 `_find_guide_direction()` 中最大的單一候選之一（cumulative ~1.3 秒，`SurgicalGuide_1.stl`）。

本輪範圍嚴格限定於該函式的 PCA projection／covariance 區段，不觸及 scanline、BFS、concave vote、fallback、vertex weld、adjacency、turn-angle chain walk。

## Goals / Non-Goals

**Goals：**
- 以逐段計時（非僅 cumulative time）確認 1.3 秒具體來自哪個子階段，避免誤判。
- 只向量化 PCA projection 與 covariance/eigen decomposition 兩段，移植 `model_classifier.py::_drill_is_drill_patch()` 已驗證安全的等價實作。
- 保留函式的輸入/輸出契約、orthonormal basis 規則、thresholds、eigenvector 排序語意、long/short axis 判定、early rejection 順序、scanline 與 turn-angle 呼叫方式、debug/candidate/decision face 資料、最終 orientation 流程。

**Non-Goals（本輪不處理，留待下一輪視 profiling 決定）：**
- `_patch_has_hole_by_scanlines()` 的向量化。
- BFS region growing、`detect_concave_faces()`、concave vote、fallback、vertex weld、adjacency、turn-angle chain walk 本身。

## Decisions

### D1：PCA projection 改為批次矩陣運算

**根因**：修改前，`vids2d`（patch 邊界的唯一頂點集合）透過 Python 迴圈逐一呼叫 `project_to_plane(vid)` 建立 `pts2d`（[:527-531](../../../agent/auto_orient_surg_guide.py#L527-L531)，Phase-1-baseline 行號）。逐段計時確認：對 `SurgicalGuide_1.stl` 的 8,946 個候選 patch，`vertex_set`（`np.unique` 建立 `vids2d`）與 `pca_projection`（該 Python 迴圈）合計約占 `_is_drill_patch_by_edges()` 總時間的 28%；4 個模型的合計占比落在 23～28% 區間。

**修法**：`q = v[vids2d].astype(np.float64) - center.astype(np.float64)`，再以 `q @ ex.astype(np.float64)` 與 `q @ ey.astype(np.float64)` 一次性算出所有點的 u/v 座標。與原本 `project_to_plane()` 相同——`qx/qy/qz` 與 `ex/ey` 分量皆先轉為 double 再相乘相加——只是從逐 vertex 的 Python 迴圈改為批次矩陣運算，數值路徑完全相同（3 項相加的浮點加總順序也相同，故 A/B 驗證得到 bit-exact 結果，見下方「實作與驗證記錄」）。

`project_to_plane()` 函式定義本身保留不變，供 conn-edge bbox 收集（[:587-589](../../../agent/auto_orient_surg_guide.py#L587-L589)）與 turn-angle chain walk（[:667-669](../../../agent/auto_orient_surg_guide.py#L667-L669)）沿用既有的逐 vertex 呼叫方式——本輪不改動這兩處。

### D2：covariance 改為直接的 2×2 dot-product 公式

**根因**：修改前使用 `np.cov(centered.T)`（[:534](../../../agent/auto_orient_surg_guide.py#L534)，Phase-1-baseline 行號），逐段計時確認 `covariance_eigen`（`np.cov` + `np.linalg.eigh`）單獨占 `_is_drill_patch_by_edges()` 總時間的 36～47%，是所有子階段中最大的單一項目。

**修法**：`cxx = np.dot(cx,cx)/denom`、`cxy = np.dot(cx,cy)/denom`、`cyy = np.dot(cy,cy)/denom`（`denom = N-1`，與 `np.cov` 預設 `ddof=1` 一致），組成 `[[cxx,cxy],[cxy,cyy]]` 餵給同一個 `np.linalg.eigh()`。`eigh()` 呼叫本身、其回傳的 eigenvalue 升冪排序語意、以及下游 `proj.max(axis=0)-proj.min(axis=0)` 取 `long_edge`/`short_edge`（不依賴 eigenvalue 排序，只取兩個 extent 的 max/min）完全不變。

**為何安全**：`np.cov(X.T)`（X 為 (N,2)）的定義本身就是 `dot(X_centered.T, X_centered) / (N-1)`（`ddof=1` 為 numpy 預設值）——直接公式與 `np.cov` 在數學上完全等價，只是省去 `np.cov` 為支援任意形狀輸入、加權、masked array 等通用情境所做的額外檢查與中間物件配置。

### D3：不觸及 scanline／turn-angle 的呼叫方式與資料流

`_patch_has_hole_by_scanlines(mesh, P, ex, ey)`（[:549](../../../agent/auto_orient_surg_guide.py#L549)）與 turn-angle chain walk 的呼叫簽章、輸入資料完全不變——兩者仍是在 gate 通過後才執行的既有邏輯，本輪只確保餵給它們的 `ex`/`ey`（正交基底，未變動）與 gate 判定本身（`long_edge`/`short_edge`）數值正確。

## 實作與驗證記錄

**Baseline**：以 Phase 1 完成後（尚未 commit）的程式碼為 baseline，重用 `perf-surg-guide-grow-patches` 的模型集合（`SurgicalGuide_1~4.stl`，同一個 tempTest 目錄，本輪確認為 4 個模型，`SurgicalGuide_4.stl` 為刻意加入，非異常）。

**`_is_drill_patch_by_edges()` 子階段逐段計時（修改前，4 模型累計於各自的候選 patch 上，`time.perf_counter()`，非 cProfile）**：

| 子階段 | SurgicalGuide_1 (8,946 patches) | SurgicalGuide_2 (3,852) | SurgicalGuide_3 (6,468) | SurgicalGuide_4 (10,704) |
|---|---|---|---|---|
| vertex_set | 61.1 ms (8.8%) | 132.3 ms (10.3%) | 231.8 ms (9.8%) | 373.7 ms (10.3%) |
| pca_projection | 130.1 ms (18.7%) | 191.4 ms (14.9%) | 327.9 ms (13.8%) | 519.9 ms (14.3%) |
| covariance_eigen | 248.3 ms (35.7%) | 583.7 ms (45.4%) | 1028.5 ms (43.4%) | 1686.0 ms (46.5%) |
| orthonormal_basis | 66.6 ms (9.6%) | 126.5 ms (9.8%) | 224.3 ms (9.5%) | 375.7 ms (10.4%) |
| diameter_aspect_gate | 50.7 ms | 116.4 ms | 204.8 ms | 345.3 ms |
| scanline | 80.4 ms | 47.3 ms | 183.9 ms | 76.9 ms |
| conn_edge_collect | 10.3 ms | 6.4 ms | 26.1 ms | 6.4 ms |
| turn_angle_walk | 7.3 ms | 1.8 ms | 6.2 ms | 1.8 ms |
| **本輪範圍合計**（vertex_set+pca_projection+covariance_eigen+orthonormal_basis） | **506.1 ms (72.7%)** | **1033.9 ms (80.4%)** | **1812.4 ms (76.5%)** | **2955.3 ms (81.5%)** |
| **總計** | 696.4 ms | 1285.9 ms | 2369.6 ms | 3624.3 ms |

結論：本輪範圍（PCA projection + covariance/eigen + 其直接前置作業）占 `_is_drill_patch_by_edges()` 總時間的 73～82%，其中 covariance/eigen 單項就占 36～47%，確認為最大的單一子階段，優先處理順序正確。子階段計時透過 scratchpad 專用的 instrumented 複製函式量測（僅呼叫真實的 `_build_orthonormal_basis`／`_patch_has_hole_by_scanlines`／`_norm`／`_dot`／`_clampf`，外層計時邊界為量測專用複製），未落地為 production code 或永久測試基礎設施。

**Benchmark（同一 4 模型，warm-up ×1 + 正式 5 runs 取 median；因量測期間偵測到偶發背景負載尖峰，額外重跑 3～4 次獨立 script invocation 並取每個指標的最小值，抑制單次尖峰對結果的干擾；`time.perf_counter()`，非 cProfile）**：

| 模型 | 階段 | Phase 1 baseline | 本輪後 | 本輪改善 |
|---|---|---|---|---|
| SurgicalGuide_1 | `_is_drill_patch_by_edges()`（候選加總） | 681.6 ms | 458.6 ms | 32.7% |
| SurgicalGuide_1 | `_find_guide_direction()` | 2603.9 ms | 2413.7 ms | 7.3% |
| SurgicalGuide_1 | `compute_auto_orientation_surg_guide_detail()` | 2594.3 ms | 2391.9 ms | 7.8% |
| SurgicalGuide_2 | `_is_drill_patch_by_edges()`（候選加總） | 279.1 ms | 178.2 ms | 36.1% |
| SurgicalGuide_2 | `_find_guide_direction()` | 1211.8 ms | 1103.8 ms | 8.9% |
| SurgicalGuide_2 | `compute_auto_orientation_surg_guide_detail()` | 1201.4 ms | 1097.5 ms | 8.7% |
| SurgicalGuide_3 | `_is_drill_patch_by_edges()`（候選加總） | 479.1 ms | 330.6 ms | 31.0% |
| SurgicalGuide_3 | `_find_guide_direction()` | 2018.4 ms | 1867.7 ms | 7.5% |
| SurgicalGuide_3 | `compute_auto_orientation_surg_guide_detail()` | 1991.0 ms | 1859.8 ms | 6.6% |
| SurgicalGuide_4 | `_is_drill_patch_by_edges()`（候選加總） | 724.8 ms | 461.7 ms | 36.3% |
| SurgicalGuide_4 | `_find_guide_direction()` | 3026.3 ms | 2740.8 ms | 9.4% |
| SurgicalGuide_4 | `compute_auto_orientation_surg_guide_detail()` | 2994.4 ms | 2734.2 ms | 8.7% |

**累積改善（相對最原始版本，Phase 1 之前；兩輪量測分屬不同 script 執行/時間點，跨執行的絕對 ms 存在機器負載差異，此處只用於呈現量級，不應與上表「本輪改善」百分比混用或直接相減）**：

| 模型 | 最原始版本 | Phase 1 後 | Phase 1+2 後 | 累積改善 |
|---|---|---|---|---|
| SurgicalGuide_1 | 3973.1 ms | 2643.4 ms (33.5%) | 2391.9 ms | 39.8% |
| SurgicalGuide_2 | 1896.0 ms | 1216.3 ms (35.8%) | 1097.5 ms | 42.1% |
| SurgicalGuide_3 | 3221.2 ms | 2022.0 ms (37.2%) | 1859.8 ms | 42.3% |
| SurgicalGuide_4 | 4696.5 ms | 3012.0 ms (35.9%) | 2734.2 ms | 41.8% |

**A/B 正確性比對（全部 4 模型，逐 patch）**：對每個 `>=5`-face patch 比較 face membership、投影後的 pts2d bounding range、covariance matrix、eigenvalues、long_edge/short_edge、aspect ratio、diameter gate 結果、是否進入 scanline、scanline 結果、是否成為 drill candidate——**全部 4 模型、所有比較項目皆為 bit-exact 相同（max diff = 0.000e+00）**，0 mismatches。整體流程的 drill candidate patch IDs、分支（drill/fallback）、`decision_faces`/`candidate_faces`、`res.dir`、`rotation_rad` 同樣 bit-exact 相同。

bit-exact（而非僅在容許誤差內相同）的原因：`(K,3)@(3,)` 矩陣乘法對長度為 3 的向量退化為與原本 `qx*ex[0]+qy*ex[1]+qz*ex[2]` 相同的三項循序浮點加總；直接 2×2 covariance 公式與 `np.cov` 的內部計算在數學上是同一個 `dot(X,X)/(N-1)` 運算，對這個固定小尺寸情境沒有引入不同的浮點路徑。

**回歸測試**：新增 `agent/tests/test_auto_orient_surg_guide_drill_patch_pca.py`（5 tests，合成矩形 patch 幾何，不依賴外部 STL）：以已知精確尺寸的矩形（PCA 主軸與全域 X/Y 軸重合，故 extents 精確等於寬高）pin 住「diameter/aspect gate 的 accept/reject 邊界」（8×6mm 矩形通過 gate 並進入 scanline；3×2mm 因 long_edge<5.5 在 gate 被拒絕；12×2mm 因 aspect>1.5 在 gate 被拒絕，兩者皆不應呼叫 scanline）、`ignore_angle=True` 路徑不受影響、以及直接以 mock 確認 `np.cov()` 不再被呼叫。

**回歸範圍**：`pytest agent/tests/ -q --continue-on-collection-errors`：675 passed、1 failed、3 errors——與 Phase 1 完成時的既有基準（670 passed、1 failed、3 errors）相比，新增的 675−670=5 即本項新增測試；既有的 1 failed（`test_prz_print_time.py`）與 3 collection errors（缺少 `httpx`）數字不變。

**四輪整合驗收**：本 change 與其他三輪（`perf-surg-guide-grow-patches`／`perf-surg-guide-bfs-region-growing`／`perf-surg-guide-concave-chunking`）疊加後的整合正確性與累積效能驗收記錄，見 `perf-surg-guide-concave-chunking/design.md`「四輪整合驗收」章節，避免重複記載。

## Risks / Trade-offs

- **[量測噪聲]**（已處理）量測期間觀察到偶發的背景負載尖峰（單一模型的 benchmark 一度膨脹 3～5 倍），判定為機器層級的暫時性負載，非程式碼問題（同一支未修改的 instrumented 腳本前後兩次執行對同一模型出現數倍差異，重跑後恢復正常）。→ 每個 benchmark 數字取 3～4 次獨立 script 執行的最小值，抑制尖峰對結果的干擾；正式報告的百分比皆基於這組取最小值後的數字。
- **[本輪範圍刻意限縮，`_is_drill_patch_by_edges()` 改善後仍占 `_find_guide_direction()` 相當比例]**（已知，非本輪目標）scanline、conn-edge collect、turn-angle walk 目前占比很小（因大多數 patch 在 diameter/aspect gate 就被拒絕），但 `detect_concave_faces()`（Python edge-loop）在兩輪優化後占比相對提高，是下一輪的候選之一——見下方「新的耗時分布」。此為刻意的範圍切分，非遺漏。

## Migration Plan

單一階段，可獨立驗證與獨立 commit，且獨立於 `perf-surg-guide-grow-patches`（Phase 1）：

| 階段 | 內容 | 回滾方式 |
|---|---|---|
| 0 | 以 Phase 1 baseline 重新 profiling，拆解 `_is_drill_patch_by_edges()` 子階段耗時 | — |
| 1 | PCA projection + covariance 向量化（`agent/auto_orient_surg_guide.py`） | 單一 commit revert（不影響 Phase 1 的獨立 commit） |

## Open Questions

- **下一輪範圍如何界定？** 本輪完成後的 cProfile 顯示：`detect_concave_faces()`（Python edge-loop，[agent/auto_orient_surg_guide.py:904](../../../agent/auto_orient_surg_guide.py#L904)）與 `_grow_patches()` 的 BFS 部分（未向量化的 `_norm`/`_dot` 呼叫）相對占比提高。建議下一輪 profiling 時把這兩者列為主要候選，其餘（scanline、vertex weld、turn-angle chain walk）視新數據決定。
