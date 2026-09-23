## 1. Production 實作

- [x] 1.1 新增私有 vectorized helper `_ray_polygon_nearest_hit_t(ox, oy, dx, dy, ax, ay, ex, ey)`（`agent/ortho_pipeline.py`，緊接在 `ray_seg_intersect_2d()` 之後）：對單一 ray 與預先計算好的 polygon 邊陣列一次性計算 `denom`/`t`/`u`，用遮罩篩選合格邊，取最小 `t`
- [x] 1.2 `generate_side_wall_drains()` 選定 `inner_poly` 後，一次性預計算 `inner_ax`/`inner_ay`/`inner_ex`/`inner_ey`（`b` 為下一個 polygon 點，最後一點連回第一點，用 `np.roll(..., -1)`）
- [x] 1.3 `evaluate_sample_idx()` 內原本的 scalar ray 迴圈改為呼叫 `_ray_polygon_nearest_hit_t(sx, sy, nx, ny, inner_ax, inner_ay, inner_ex, inner_ey)`
- [x] 1.4 安全除數：以 `np.where(valid, denom, 1.0)` 遮罩非必要除數，避免對 parallel/collinear/zero-length edge 計算真正的 `0/0`（不使用 `np.errstate` 事後壓制警告）
- [x] 1.5 確認未改動：`ray_seg_intersect_2d()`、`point_in_polygon_2d()`、`slice_mesh_at_z()`、candidate/slide search、wall score、spacing gate、hole 幾何建立、Step 7～10 Boolean
- [x] 1.6 確認未新增快取、全域狀態、第三方依賴，未對特定模型 polygon 點數做硬編碼 fast path，未做 dtype 強制轉換，未建立 candidate×edge 全矩陣

## 2. 專項測試

- [x] 2.1 新增 `agent/tests/test_side_wall_inner_poly_ray_vectorized.py`：一般單一/多重 hit、無 hit、空/單點 polygon、parallel/collinear/zero-length edge、segment endpoint（`u=0`／`u=1`）、`u` 超出範圍、`t` 邊界（`t=0`／`t=0.01`／略大於 `0.01`）、`abs(denom)` 相對 `1e-12` 的邊界（低於/等於/高於）、同 `t` tie-break（保留較低 edge index）、最後一點連回第一點、2000 組固定 seed 隨機 polygon/ray 壓力對照、正常輸入與 500 組隨機壓力測試皆不新增 NumPy runtime warning、輸入陣列不被原地修改、對內部 float32 downcast 敏感的精度測試（24 tests）
- [x] 2.2 測試內的 scalar oracle 直接使用既有、未修改的 `ray_seg_intersect_2d()` 逐邊呼叫，套用原本 `t > 0.01 and t < best_t` 邏輯，僅作為測試 oracle，不進入 production code
- [x] 2.3 執行 `pytest agent/tests/test_side_wall_inner_poly_ray_vectorized.py -v`，確認全數通過
- [x] 2.4 執行 `pytest agent/tests/test_point_in_polygon_2d_vectorized.py agent/tests/test_slice_mesh_at_z_broad_phase.py agent/tests/test_ortho_clean_mesh_reuse.py agent/tests/test_ortho_hollow_split_repair.py agent/tests/test_side_wall_inner_poly_ray_vectorized.py -v`，確認無回歸
- [x] 2.5 執行 `pytest agent/tests/ -q --continue-on-collection-errors`，確認與既有 baseline（`test_prz_print_time.py` 1 failed、3 collection errors 缺 httpx）相符，無新增失敗

## 3. 真實模型正確性驗證

- [x] 3.1 用真實 PrusaSlicer CLI hollow 輸出（`001_p.stl`／`005_p.stl`／`DentalModel_1M.stl`／`DentalModel_NeedRotate.stl`，經 Step 2 extend_bottom_vertices／Step 3 align hollow to input，不經 STL round-trip）建立 in-memory `outer_shell`／`inner_shell`／`bottom_z`
- [x] 3.2 直接呼叫真實 production `agent.ortho_pipeline.generate_side_wall_drains()`，僅 monkeypatch 模組層級 `_ray_polygon_nearest_hit_t` 名稱在 reference（scalar-loop 等價實作，使用預計算 `ex`/`ey` 陣列直接計算、不透過端點重建）與 implementation（目前 production 向量化版本）間切換，其餘呼叫路徑完全是 production 程式碼本身
- [x] 3.3 比對 ray 查詢次數、逐次查詢結果、skip reasons（直接解析 production 真實 log 訊息）、hole 數量：四個模型全部一致
- [x] 3.4 比對 `generate_side_wall_drains()` 回傳 mesh 的 `.vertices`／`.faces`：四個模型 `np.array_equal` 全數通過

## 4. Step 6 效能量測

- [x] 4.1（初版，已由 8.2 取代）正式 Step 6 timing 最初以 precomputed-edge scalar control monkeypatch 為 reference；審查後確認此 control 已先套用本輪才新增的 `inner_poly` 邊陣列一次性預計算、且跳過逐邊 `ray_seg_intersect_2d()` 函式呼叫開銷，不能代表真正 HEAD `7d3e439`，故改採 8.2 的 git worktree 方法重新量測，本節結果以 8.2 為準
- [x] 4.2 診斷用 instrumented 執行（與正式 timing 分開）：inner ray/segment aggregate time 與其佔候選評估階段（instrumented 版本）的比例——此處沿用 precomputed-edge scalar control 作為量測基準是可接受的，因為這是診斷用途、非正式效能宣稱，已在 `design.md` 明確標示
- [x] 4.3 `tracemalloc` 量測最大代表模型（`DentalModel_1M.stl`）單次呼叫的 Python-level peak allocation，確認向量化版本未新增明顯記憶體

## 5. 完整 Auto Process 效能量測

- [x] 5.1（初版，已由 8.3 取代）完整 Auto Process 最初同樣誤用 precomputed-edge scalar control monkeypatch 為 reference；審查後改採 8.3 的 git worktree 方法重新量測，本節結果以 8.3 為準
- [x] 5.2（見 8.3）記錄完整 Auto Process 節省秒數與百分比
- [x] 5.3（見 8.3）比較最終 `ortho_result.stl` 的 faces／vertices count、volume、bounds、`is_watertight`（語意等價，不宣稱 Boolean 後 STL byte equality）

## 6. OpenSpec

- [x] 6.1 `openspec new change perf-side-wall-inner-poly-ray-segment` 建立 change 目錄
- [x] 6.2 撰寫 `proposal.md`：Why／What Changes／Capabilities（新增 `side-wall-inner-poly-ray-segment-performance`，無 Modified Capabilities）／Impact
- [x] 6.3 撰寫 `design.md`：Context／Goals-Non-Goals／Decisions（D1 單次呼叫向量化+邊陣列一次性預計算、不建立 candidate×edge 矩陣；D2 安全除數遮罩不用 errstate）／Risks-Trade-offs／實作與驗證記錄（含實際量測表格）
- [x] 6.4 撰寫 `specs/side-wall-inner-poly-ray-segment-performance/spec.md`：ADDED Requirements 涵蓋 scalar 組合一致性、邊界/退化輸入行為、除以零與 warning 防護、dtype 與跨呼叫狀態限制、`generate_side_wall_drains()` array-exact 等價
- [x] 6.5 撰寫本 `tasks.md`
- [x] 6.6 執行 `openspec validate perf-side-wall-inner-poly-ray-segment --strict`，確認通過

## 7. 收尾（本輪停在未提交狀態）

- [x] 7.1 確認 production 程式碼中無殘留 temporary profiling／debug log／benchmark 程式（`git diff agent/ortho_pipeline.py` 掃描確認）
- [x] 7.2 清除本輪 scratchpad 的 captured meshes、驗證/計時腳本、scratch job 目錄、暫存產物
- [x] 7.3 檢查 branch/HEAD/working tree/diff，確認本輪只涉及 `agent/ortho_pipeline.py`、`agent/tests/test_side_wall_inner_poly_ray_vectorized.py`、`openspec/changes/perf-side-wall-inner-poly-ray-segment/`；既有 unrelated modified／untracked 項目（`third_party/prusaslicer_fork` submodule pointer、多個既有 untracked files）維持不變；已封存的 `perf-side-wall-point-in-polygon` 正式 spec 未被修改
- [ ] 7.4（不在本輪範圍）`openspec archive perf-side-wall-inner-poly-ray-segment`
- [ ] 7.5（不在本輪範圍）commit
- [ ] 7.6（不在本輪範圍）push

## 8. 審查回應（本輪：正式 Reference 路徑與 dtype fixture 說明）

- [x] 8.1 審查意見一（正式效能 reference 是否不是原始 HEAD 路徑）：確認成立——先前 monkeypatch 進 `_ray_polygon_nearest_hit_t()` 的 precomputed-edge scalar control 已享有本輪才新增的 `inner_poly` 邊陣列一次性預計算（真正 HEAD `7d3e439` 每次 `evaluate_sample_idx()` 呼叫都重新走訪 `inner_poly`），且完全跳過逐邊呼叫 `ray_seg_intersect_2d()` 的函式呼叫與其內部每次重新計算 `ex`/`ey` 的開銷，故不能代表 HEAD `7d3e439` 的正式效能路徑
- [x] 8.2 以 `git worktree add C:\wt\ref_7d3e439 7d3e439`（repo 外短路徑，避開 Windows MAX_PATH 限制；未 checkout／reset／stash 主 working tree）簽出真正 HEAD `7d3e439`，reference（worktree）與 implementation（目前 working tree）各自在獨立 Python 子行程執行（避免同一行程內兩份 `agent` package 匯入衝突，且保證 reference 執行的是 git 記錄的原始位元組碼），交錯執行降低系統時間漂移，重新量測四模型 Step 6：`001_p.stl` 0.4012s→0.0506s（−87.4%）、`005_p.stl` 0.3193s→0.0475s（−85.1%）、`DentalModel_1M.stl` 0.4769s→0.1295s（−72.8%）、`DentalModel_NeedRotate.stl` 0.0305s→0.0213s（−30.2%），四模型三次計時皆緊密收斂
- [x] 8.3 同法重新量測完整 Auto Process（`001_p.stl`／`DentalModel_1M.stl`，scratch `BUNDLE_JOBS_DIR`、worktree 側以 `SLICER_ENGINE_BIN` 指回主 repo 既有可執行檔）：見本檔案結尾或 `design.md` 的更新結果
- [x] 8.4 更新 `proposal.md`／`design.md`：新增「量測方法澄清」段落，明確區分「真正 HEAD `7d3e439` production reference」（正式 Step 6／完整 Auto Process 表格採用）vs.「precomputed-edge scalar control」（僅用於正確性驗證的 oracle 與診斷用 instrumented 執行，已加註不代表正式效能）vs. vectorized implementation；正確性 array-exact 部分保留使用 precomputed scalar control 的結果不變
- [x] 8.5 審查意見二（dtype precision 測試描述是否精確）：確認成立——實測 fixture 在 float64 下最近值為 `t≈0.9999999949999991`，模擬僅 `ax/ay/ex/ey` 邊陣列降為 `float32` 後仍為 hit，但 `t` 變為精確的 `1.0`（並非「寬度消失、無 hit」）；已修正 `test_float64_precision_is_not_downcast_internally()` 的 docstring，並新增明確的 downcast-control 呼叫（`ax.astype(np.float32)` 等），斷言其結果與 `ref64` 不同，實際證明 fixture 對降精度敏感，production helper 未被修改
- [x] 8.6 執行 `pytest agent/tests/test_side_wall_inner_poly_ray_vectorized.py -v`，確認 24 passed
- [x] 8.7 執行相關 Ortho 測試組合與 `openspec validate perf-side-wall-inner-poly-ray-segment --strict`，確認通過
- [x] 8.8 移除 `git worktree`（`git worktree remove`），清除本輪所有 scratchpad harness、captured arrays、logs、profiling、scratch jobs 目錄
- [x] 8.9 確認 `agent/ortho_pipeline.py` 正式 diff 與審查前完全一致；確認既有 unrelated modified／untracked 項目完全未動
