## 1. Phase 0：正式基準建立

- [x] 1.1 確認 working tree 與前三輪（`perf-surg-guide-grow-patches`／`perf-surg-guide-drill-patch-pca`／`perf-surg-guide-bfs-region-growing`）的既有修改與所有既有未提交項目保留不變
- [x] 1.2 自動搜尋 `C:\Users\user\Pictures\tempTest\SurgicalGuide*.stl`，確認模型集合（含約 1M faces 的 `SurgicalGuide_1M.stl`，共 5 個模型，97K～972K faces）
- [x] 1.3 以現行（Phase 1＋Round 2＋A2 皆已套用）程式碼為 baseline，沿用 scratch benchmark harness
- [x] 1.4 warm-up + 7 次交錯執行，median 為主要結果，同時記錄 min/max/IQR；chunk 建立、array 轉換、gather、accumulation 成本全部計入量測範圍
- [x] 1.5 建立正確性快照：記錄修改前每個 face 的 concave 判定、`_entrance_dir_by_concave()` 方向、`res.dir`、`rotation_rad`（透過 scratch Reference 實作，保留原始逐 edge `@` 運算子迴圈供比對）

## 2. 實作：Chunked C（16K edges）

- [x] 2.1 將 `detect_concave_faces()` 的 edge 累加迴圈改為固定 16384 edges 分批處理（`_accumulate_chunk()`），沿用驗證過的數學與累加語意
- [x] 2.2 確認未變更：dtype（全程 float64）、`> 1e-6`／`>= 0.55` 門檻、boundary edge 跳過、非流型 edge 既有登記語意、cylinder exclusion 時機與 `<=` 邊界慣例
- [x] 2.3 確認暫存陣列大小由 chunk size 決定（`_accumulate_chunk()` 內的陣列長度恆等於當批次的 edge 數），任何時間點不具現化「全部 interior edges」規模的暫存陣列

## 3. A/B 正確性驗證

- [x] 3.1 現有真實 Surgical Guide 模型（5 個，97K～972K faces）
- [x] 3.2 約 1M faces 模型（`SurgicalGuide_1M.stl`，972,248 faces）
- [x] 3.3 boundary edge（`f1 < 0`）
- [x] 3.4 非流型 edge（既有 first-two-faces-only 登記語意）
- [x] 3.5 degenerate normal（零向量法向量）
- [x] 3.6 concavity threshold 兩側及恰好等於 threshold（`> 1e-6` 嚴格大於）
- [x] 3.7 同一 face 由多 edge 累加（單一 chunk 內）
- [x] 3.8 累加跨越 chunk 邊界（刻意構造跨越生產環境實際 16384 邊界的案例，含最後一批 partial chunk）
- [x] 3.9 cylinder 內、外及邊界（`radial <= radius` 視為 inside）
- [x] 3.10 空結果與全部通過結果
- [x] 3.11 face-level votes／total／concave indices（透過可觀察行為間接驗證：合成案例的精確 vote 計數與 ratio 邊界，加上真實模型的 concave 集合逐一比對）
- [x] 3.12 最終 direction 與 rotation（5 個真實模型 `_entrance_dir_by_concave()` 方向與 `rotation_rad` 皆 bit-exact）
- [x] 3.13 速度驗證（見第 4 節）；本階段未發現任何差異，未觸發「還原本項優化」的分支

## 4. Benchmark 與正式測試

- [x] 4.1 以 5 個真實模型、相同環境 benchmark：`detect_concave_faces()`、`_entrance_dir_by_concave()`、`_find_guide_direction()`、`compute_auto_orientation_surg_guide_detail()`；7 次交錯執行，median 為主要數字，min/max/IQR 一併記錄
- [x] 4.2 計算相對「Phase 1＋Round 2＋A2」baseline 的增量改善（`detect_concave_faces()` 約 92%～94%；核心 Auto Orient 約 35%～39%），未與其他 session 的百分比相加宣稱累積改善
- [x] 4.3 記憶體驗證：以方法論修正後的 subprocess 隔離量測完成（每模型獨立 subprocess；呼叫前 current RSS baseline + 執行期間背景執行緒持續採樣峰值，取代先前 scratch 階段已知會低估的歷史 `PeakWorkingSetSize` 前後差方法；量測方法先以已知大小的合成配置校準，誤差穩定在 5%）。5 個真實模型（97K～972K faces）增量峰值 per-face 維持在 99～108 bytes 的窄幅範圍，未出現隨模型增大而系統性上升的訊號；搭配程式碼審查確認 `detect_concave_faces()` 全函式範圍內無 `list(mesh.edge_faces.values())` 或任何等價的完整 edge 具現化操作，`_accumulate_chunk()` 陣列長度恆等於當批次大小（≤16384）。已知侷限：5 個測試模型的 edge/face 比例恰好都等於 1.5，實測資料本身無法單獨區分「隨 face 數成長」與「隨 edge 數成長」，但此侷限不影響驗收結論，因為批次暫存陣列的邊界已由程式碼審查獨立確認，不依賴這批模型的巧合比例。詳見 `design.md`「記憶體（正式驗證，已完成）」。
- [x] 4.4 新增正式 regression test `agent/tests/test_auto_orient_surg_guide_detect_concave_chunking.py`（13 tests，合成 `_Mesh`，涵蓋第 3 節列出的驗證範圍；未加入 wall-time assertion）
- [x] 4.5 執行 `pytest agent/tests/ -q --continue-on-collection-errors`：699 passed（686 既有基準 + 13 新增）、1 failed、3 errors——既有 failure/errors 數字未增加
- [x] 4.6 執行本 change 與前三個既有 change 的 `openspec validate --strict`，確認互不影響

## 5. 收尾

- [x] 5.1 design.md 已補齊實際量測數字與 A/B 正確性比對結果
- [x] 5.2 記錄下一階段候選（`_weld_and_build()` 的 edge/adjacency 建立，視屆時 profiling 決定）於 design.md Open Questions
- [x] 5.3 正式的 subprocess 隔離絕對記憶體峰值量測（見 4.3，已於後續補做並完成）

**本 change 範圍之外的後續工作**（`_weld_and_build()` 的 edge/adjacency 建立或其他剩餘瓶頸的後續優化）不屬於本提案的實作任務，記錄於 `design.md` 的 Open Questions（第 124～125 行），留待未來 profiling 決定是否處理。
