## 1. Production 實作

- [x] 1.1 只修改 `point_in_polygon_2d()`（`agent/ortho_pipeline.py`）內部實作：用 `np.roll` 取得每個頂點的「前一個頂點」座標，對全部邊一次性計算 crossing 條件與 x-intercept，取代原本逐邊執行的 Python `for` 迴圈；函式簽章、回傳型態、`evaluate_sample_idx()` 唯一呼叫點完全不變
- [x] 1.2 安全除數：以 `np.where(crosses, yj - y, 1.0)` 遮罩非必要除數，避免對 horizontal edge 或其他不滿足 crossing 條件的邊計算真正的 `0/0`（不使用 `np.errstate` 事後壓制警告）
- [x] 1.3 確認未改動：`ray_seg_intersect_2d()`、`evaluate_sample_idx()` 內 inner-poly ray/segment 迴圈、`slice_mesh_at_z()`、candidate/slide search、wall score、spacing gate、hole 幾何建立、Step 7～10 Boolean
- [x] 1.4 確認未新增快取、全域狀態、第三方依賴，未對特定模型 polygon 點數做硬編碼 fast path，未做 dtype 強制轉換

## 2. 專項測試

- [x] 2.1 新增 `agent/tests/test_point_in_polygon_2d_vectorized.py`：convex/concave polygon、orientation 反轉、內部/外部/edge/vertex query、horizontal/vertical edge、repeated vertex、zero-length edge、空 polygon、<3 點 degenerate polygon、固定資料表、固定 seed 隨機 polygon/query parity 對照（2000 組）、正常輸入與隨機壓力測試（500 組）皆不新增 NumPy runtime warning、輸入陣列不被原地修改（27 tests，含第 7 節審查補強的精度測試）
- [x] 2.2 測試內凍結的 scalar reference 僅作為測試 oracle，忠實複製修改前語意，不進入 production code
- [x] 2.3 執行 `pytest agent/tests/test_point_in_polygon_2d_vectorized.py -v`，確認全數通過
- [x] 2.4 執行 `pytest agent/tests/test_slice_mesh_at_z_broad_phase.py agent/tests/test_ortho_clean_mesh_reuse.py agent/tests/test_ortho_hollow_split_repair.py agent/tests/test_point_in_polygon_2d_vectorized.py -v`，確認無回歸（45 passed，因第 7 節新增 1 個精度測試，由原本的 44 passed 增為 45 passed）
- [x] 2.5 執行 `pytest agent/tests/ -q --continue-on-collection-errors`，確認與既有 baseline（`test_prz_print_time.py` 1 failed、3 collection errors 缺 httpx）相符，無新增失敗

## 3. 真實模型正確性驗證

- [x] 3.1 用真實 PrusaSlicer CLI hollow 輸出（`001_p.stl`／`005_p.stl`／`DentalModel_1M.stl`／`DentalModel_NeedRotate.stl`，經 Step 2 extend_bottom_vertices／Step 3 align hollow to input，不經 STL round-trip）建立 in-memory `outer_shell`／`inner_shell`／`bottom_z`
- [x] 3.2 直接呼叫真實 production `agent.ortho_pipeline.generate_side_wall_drains()`，僅 monkeypatch 模組層級 `point_in_polygon_2d` 名稱在 reference（凍結 scalar）與 implementation（目前 production 向量化版本）間切換，其餘呼叫路徑完全是 production 程式碼本身
- [x] 3.3 比對 PIP 呼叫次數、逐次查詢點與布林結果、skip reasons（直接解析 production 真實 log 訊息）、hole 數量：四個模型全部一致
- [x] 3.4 比對 `generate_side_wall_drains()` 回傳 mesh 的 `.vertices`／`.faces`：四個模型 `np.array_equal` 全數通過

## 4. 效能量測

- [x] 4.1 正式 Step 6 timing（1 次 warm-up + 3 次計時，`time.perf_counter()`，取 median，對真實 production `generate_side_wall_drains()`，不含逐次 instrumentation）：四個模型 reference vs. implementation
- [x] 4.2 診斷用 instrumented 執行（與正式 timing 分開）：`point_in_polygon_2d()` aggregate time 與其佔候選評估階段（instrumented 版本）的比例
- [x] 4.3 `tracemalloc` 量測最大代表模型（`DentalModel_1M.stl`）單次呼叫的 Python-level peak allocation，確認向量化版本未新增明顯記憶體
- [x] 4.4 確認四個模型的改善幅度與本輪前置調查的 prototype 數字量級一致（001_p/005_p/NeedRotate 個位數至十餘 % 改善，DentalModel_1M 六成以上改善），無需額外根因調查

## 5. OpenSpec

- [x] 5.1 `openspec new change perf-side-wall-point-in-polygon` 建立 change 目錄
- [x] 5.2 撰寫 `proposal.md`：Why／What Changes／Capabilities（新增 `side-wall-point-in-polygon-performance`，無 Modified Capabilities）／Impact
- [x] 5.3 撰寫 `design.md`：Context／Goals-Non-Goals／Decisions（D1 單次呼叫向量化不快取不批次化、D2 安全除數遮罩不用 errstate）／Risks-Trade-offs／實作與驗證記錄（含實際量測表格）
- [x] 5.4 撰寫 `specs/side-wall-point-in-polygon-performance/spec.md`：ADDED Requirements 涵蓋一般 polygon parity 一致性、邊界/頂點/horizontal edge 行為、除以零與 warning 防護、dtype 與跨呼叫狀態限制、`generate_side_wall_drains()` array-exact 等價
- [x] 5.5 撰寫本 `tasks.md`
- [x] 5.6 執行 `openspec validate perf-side-wall-point-in-polygon --strict`，確認通過

## 6. 收尾（本輪停在未提交狀態）

- [x] 6.1 確認 production 程式碼中無殘留 temporary profiling／debug log／benchmark 程式（`git diff agent/ortho_pipeline.py` 掃描確認）
- [x] 6.2 清除本輪 scratchpad 的 captured meshes、驗證/計時腳本、暫存產物
- [x] 6.3 檢查 branch/HEAD/working tree/diff，確認本輪只涉及 `agent/ortho_pipeline.py`、`agent/tests/test_point_in_polygon_2d_vectorized.py`、`openspec/changes/perf-side-wall-point-in-polygon/`；既有 unrelated modified／untracked 項目（`third_party/prusaslicer_fork` submodule pointer、多個既有 untracked files）維持不變
- [ ] 6.4（不在本輪範圍）`openspec archive perf-side-wall-point-in-polygon`
- [ ] 6.5（不在本輪範圍）commit
- [ ] 6.6（不在本輪範圍）push

## 7. 審查回應（本輪）

- [x] 7.1 審查意見 1（dtype 測試是否真正防止內部 downcast）：確認成立——原 `test_dtype_preserved_not_downcast()` 只驗證輸入陣列本身未被原地修改，若 production 內部改成 `poly = poly.astype(np.float32)`（區域變數重新綁定，不觸及呼叫端陣列），該測試仍會通過，已用最小重現腳本驗證此偽陰性
- [x] 7.2 將該測試更名為 `test_input_dtype_not_mutated()` 並補上說明其涵蓋範圍的 docstring；新增 `test_float64_precision_is_not_downcast_internally()`，用寬度 1e-8（低於 float64→float32 在該量級的精度）的狹長 polygon 驗證：production 結果為 `True` 且與凍結 scalar reference 一致；測試內同時驗證 fixture 本身確實對 float32 downcast 敏感（`poly.astype(np.float32)` 後兩個 x 座標塌陷為同一值，且 scalar oracle 在塌陷座標上的結果與 float64 結果不同），不僅是靠註解宣稱
- [x] 7.3 審查意見 2（OpenSpec 效能數字是否混用量測階段）：確認成立——`proposal.md`「Why」段落的 74%、8.5%～13.9%、`1.4869s→0.4855s(-67.4%)` 三個數字源自本輪最初、獨立於本 change 記錄之外的前置探索 harness（非本 change `design.md` 記錄的正式 production 量測），且 8.5%～13.9% 的稀疏 outer 範圍遺漏了同批前置探索中 `DentalModel_NeedRotate` 的 4.0%，讀者無法從本 change 文件追溯 74% 的來源
- [x] 7.4 將 `proposal.md`「Why」段落改為只引用 `design.md`「實作與驗證記錄」已記錄的正式數字：candidate phase share 67.8%（診斷用 instrumented 執行）、`DentalModel_1M.stl` Step 6 1.4709s→0.4872s(−66.9%)、稀疏 outer 範圍改為三個模型的正式數字 5.8%～11.7%（`NeedRotate` 5.8%、`001_p` 9.5%、`005_p` 11.7%），並明確標示為「本 change 針對真實 production `generate_side_wall_drains()` 的正式量測」
- [x] 7.5 同步更新 `design.md` 與本檔案中因新增第 27 個測試而過時的「26 tests」計數為「27 tests」
- [x] 7.6 執行 `pytest agent/tests/test_point_in_polygon_2d_vectorized.py -v`，確認 27 passed
- [x] 7.7 執行 `openspec validate perf-side-wall-point-in-polygon --strict`，確認通過
- [x] 7.8 確認 `agent/ortho_pipeline.py` 無任何修改；確認既有 unrelated modified／untracked 項目完全未動

## 8. 收尾覆核（本輪）

- [x] 8.1 重新執行 2.4 原指令確認實際結果：`pytest agent/tests/test_slice_mesh_at_z_broad_phase.py agent/tests/test_ortho_clean_mesh_reuse.py agent/tests/test_ortho_hollow_split_repair.py agent/tests/test_point_in_polygon_2d_vectorized.py -v` 實測為 45 passed（因第 7 節新增 1 個精度測試，由原本的 44 passed 增為 45 passed），已更新 2.4 記錄
- [x] 8.2 判斷正式 spec 的 dtype requirement 是否應補 precision-sensitive Scenario：確認成立——既有 Scenario「輸入陣列 dtype 不被修改」只涵蓋 requirement 文字中「dtype 在呼叫前後 SHALL 保持不變」這一半，未涵蓋 requirement 明確點名的「尤其 SHALL NOT 降為 float32」；比照同檔案內另一個 requirement（除以零／warning）用兩個 Scenario 分別涵蓋不同行為面向的既有慣例，於 `specs/side-wall-point-in-polygon-performance/spec.md` 的 dtype requirement 下新增「float64 精度不得因內部 downcast 而遺失」Scenario，文字不綁定特定測試函式名稱或 fixture 數值
- [x] 8.3 執行 `openspec validate perf-side-wall-point-in-polygon --strict`，確認通過
- [x] 8.4 確認 `agent/ortho_pipeline.py` 與測試程式（`agent/tests/test_point_in_polygon_2d_vectorized.py`）本輪未被修改；確認既有 unrelated modified／untracked 項目完全未動
