## Why

`pytest agent/tests/ -q --continue-on-collection-errors` 目前呈現 **7 failed + 3 collection errors**。逐項追查（git blame、archived change 記錄、直接執行程式碼、比對現行 `openspec/specs/`）後確認：全部 10 項都不是新的 production regression，而是三類非行為性問題長期累積造成：

1. **Dependency 宣告缺口**：`requirements.txt` 只跟著「production 直接 import」走，從未涵蓋 shapely（production 已直接 import，純屬遺漏）與測試相關套件（httpx、pytest）；本機 `.venv` 早已裝好這些套件，掩蓋了宣告缺口，讓問題只在乾淨環境重建時才會現形。
2. **Stale tests**：`test_slice_progress_streams.py` 5 個測試仍以「單一純量」方式 unpack `_drain_stdout_progress()`，但該函式已在 `ea6646e` 修正為回傳 `(finalizing_at, stdout)` tuple，且已有 `test_drain_stdout_progress.py` 驗證新行為——這 5 個測試只是沒跟著更新。`test_prz_print_time.py::test_6_11_single_normal_layer_full_params` 則是寫死了 Case 2 retract 的**舊版**公式（`drop2 = max(0, lift+lift2-dist)`），但這個公式已被 `openspec/changes/archive/2026-05-22-fix-prz-retract-zero-falsy-supersede` 明確判定為 BREAKING 並取代（新行為：僅傳 dist 時 drop2 固定為 `0.0`），現行 `openspec/specs/prz-motion-time/spec.md` 也是這樣記載的——這個測試是 2026-05-21 建立、隔天就被那次 spec 決策取代，但沒人回頭更新它，此後被四輪 archived change（`fix-rle-layer-count-sync`、`add-slicing-progress`、`optimize-slice-performance`、`slice-preview-quantized-scale`）依序記成「已知但延後處理的既存缺陷」，卻沒有人追溯到那次 BREAKING 決策。
3. **測試框架慣例不一致**：`test_subprocess_boundary_5_11.py::test_engine_runs_as_separate_process` 使用 `@pytest.mark.asyncio`，但本 repo 從未安裝 `pytest-asyncio`，也已有明文既定慣例（`test_run_prusa_cli_streams.py` + `openspec/changes/archive/2026-08-04-add-slicing-progress/tasks.md:4`）改用 `asyncio.run()` 同步驅動 async 測試。

這批「已知失敗」目前掩蓋了測試套件的真實訊號——任何人跑 `pytest agent/tests/` 都無法單靠失敗數量判斷是否引入了新的 regression。需要獨立處理，讓 `agent/tests/` 恢復到 0 failed / 0 collection errors 的乾淨 baseline。

## What Changes

- `requirements.txt` 補齊三個缺漏宣告：`shapely`（production 直接 import）、`httpx`（`starlette.testclient.TestClient` 的必要相依，讓 3 個 collection error 檔案能被正常收集）、`pytest`（測試執行器本身，先前只存在於本機 `.venv`，從未被宣告）。
- 重寫 `test_slice_progress_streams.py` 5 個測試，改為正確 unpack 現行 `_drain_stdout_progress()` 的 `(finalizing_at, stdout)` tuple。
- 重寫 `test_subprocess_boundary_5_11.py::test_engine_runs_as_separate_process`，移除 `@pytest.mark.asyncio`，改用本 repo 既定的 `asyncio.run()` 慣例，不引入 `pytest-asyncio`。
- 更新 `test_prz_print_time.py::test_6_11_single_normal_layer_full_params` 的期望值與手算註解，改為現行 `prz-motion-time` spec 已定義的 Case 2 行為。
- 在 `prz-motion-time` capability 補上先前一直缺漏的端對端 scenario：「Case 2 時 `_compute_print_time()` SHALL 排除 drop2 時間」（先前只有 Case 4 的端對端 scenario，Case 2 自 2026-05-22 BREAKING 決策後從未被驗證過，這正是 `test_6_11` 長期失敗卻沒人抓到根因的原因）。

本 change **不修改任何 production 行為**——`agent/prz_encoder.py`、`agent/jobs.py`、`agent/config.py` 等檔案的邏輯維持現狀；`_compute_print_time()` 目前算出的 `11.0` 就是現行 spec 認定的正確值，需要修正的是測試斷言，不是程式碼。

## Capabilities

### New Capabilities

（無）

### Modified Capabilities

- `prz-motion-time`：「print_time 計算 SHALL 重用 retract 4-case override」需求補上 Case 2 情境下 `_compute_print_time()` 排除 drop2 時間的 scenario。這是既有需求下先前被遺漏的驗證缺口，不涉及任何行為變更——`_compute_print_time()` 的實作與輸出完全不變。

## Impact

| 受影響項目 | 類型 | 說明 |
|---|---|---|
| `requirements.txt` | Dependency 宣告 | 新增 `shapely`、`httpx>=0.27.0,<0.29.0`、`pytest` |
| `agent/tests/test_slice_progress_streams.py` | 測試修正 | 5 處改為 tuple unpack |
| `agent/tests/test_subprocess_boundary_5_11.py` | 測試修正 | 1 處移除 `@pytest.mark.asyncio`，改用 `asyncio.run()` |
| `agent/tests/test_prz_print_time.py` | 測試修正 | `test_6_11_single_normal_layer_full_params` 期望值與註解更新 |
| `openspec/specs/prz-motion-time/spec.md` | Delta spec | 新增 Case 2 端對端 scenario |
| `agent/tests/test_slice_progress_endpoint.py`、`test_support_e2e.py`、`test_support_status_endpoint.py` | 間接受益 | 不需修改，httpx 補齊宣告後即可正常 collection |
| Production 程式碼（`agent/prz_encoder.py`、`agent/jobs.py`、`agent/config.py` 等） | **不變更** | 本 change 明確排除任何行為變更 |
