## 1. Dependency 宣告修正

- [x] 1.1 於 `requirements.txt` 新增 `shapely`（無版本號，比照 `rtree` 先例；`agent/sla_operations.py`、`agent/boundary_detection.py` 已直接 import）
- [ ] 1.2 於 `requirements.txt` 新增 `httpx>=0.27.0,<0.29.0`（版本區間取自已安裝 `starlette==0.50.0` 的 `full` extra 宣告）—— **Deferred**：httpx / pytest 的 dependency declaration 方式本輪保留不動，待另行決定
- [ ] 1.3 於 `requirements.txt` 新增 `pytest`（無版本號，測試執行器本身）—— **Deferred**：同上
- [ ] 1.4 驗證：`pytest agent/tests/test_slice_progress_endpoint.py agent/tests/test_support_e2e.py agent/tests/test_support_status_endpoint.py -q` → 0 collection errors —— **Deferred**：依賴 1.2/1.3，本輪不處理

## 2. `test_slice_progress_streams.py` 斷言修正

- [x] 2.1 比對 `test_drain_stdout_progress.py` 既有寫法，將 5 個測試改為正確 unpack `_drain_stdout_progress()` 現行的 `(finalizing_at, stdout)` tuple 回傳值
- [x] 2.2 驗證：`pytest agent/tests/test_slice_progress_streams.py -q` → 全數 passed（34 passed）

## 3. `test_subprocess_boundary_5_11.py` 慣例對齊

- [x] 3.1 移除 `test_engine_runs_as_separate_process` 的 `@pytest.mark.asyncio`，改用 `asyncio.run()` 包裹測試主體（比照 `test_run_prusa_cli_streams.py` 既有寫法）
- [x] 3.2 驗證：`pytest agent/tests/test_subprocess_boundary_5_11.py -q` → 全數 passed（3 passed）

## 4. `prz-motion-time` spec delta 對應的測試修正

**Deferred**：`test_6_11` 的判定與 `prz-motion-time` spec delta / `skip-specs` 決策本輪保留不動，待另行決定，本組任務全數未執行。

- [ ] 4.1 核對本 change 的 `specs/prz-motion-time/spec.md` 新增 scenario 與 `test_6_11` 新期望值一致（`_compute_print_time()` 回傳 `11.0`）
- [ ] 4.2 更新 `test_prz_print_time.py::test_6_11_single_normal_layer_full_params` 的手算註解與斷言為 `11.0`，註解說明 Case 2（僅傳 `Retract Distance`）drop2 固定為 `0.0`
- [ ] 4.3 驗證：`pytest agent/tests/test_prz_print_time.py -q` → 全數 passed

## 5. 全域回歸驗證

**部分完成**：本輪已執行 `pytest agent/tests/ -q --continue-on-collection-errors`，結果為 `632 passed, 1 failed, 3 errors`——1 failed 為第 4 組 deferred 的 `test_6_11`，3 errors 為第 1 組 deferred 的 httpx collection errors，其餘先前的 6 個 failed（5 個 progress 測試 + 1 個 async 測試）已全數轉為 passed。0 failed / 0 collection errors 的最終驗收線待第 1、4 組完成後才成立，故本組任務維持未勾選。

- [ ] 5.1 執行 `pytest agent/tests/ -q`，如實記錄實際 passed / failed / collection error 數字
- [ ] 5.2 確認結果為 0 failed、0 collection errors
- [ ] 5.3 `git status` / `git diff` 確認改動範圍僅限 `requirements.txt` 與 `agent/tests/**`，未觸及任何 production 檔案（`agent/prz_encoder.py`、`agent/jobs.py`、`agent/config.py` 等）
