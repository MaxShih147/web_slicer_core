## Why

通用模式自動長支撐時，把 Max Connector Length（`support_max_bridge_length`）或 Base Diameter（`support_base_diameter`）設成 0，切片引擎會在支撐點分群（`Clustering.cpp` 的 `cluster()`）進入無窮迴圈，記憶體持續暴增。因為引擎工作走單線 FIFO 佇列，而 `run_prusa_cli()` 等待子程序時沒有逾時，這個卡死的程序會一直佔住佇列。使用者即使 F5 重新整理、把參數重設為預設值再送一次，新的 job 也只能排在後面等，整台 Local Agent 看起來永久卡死，只能重啟才會恢復。

後端目前沒有任何一層擋住這兩個 0 值，手動支撐點的單點 `base_radius_mm = 0` 也會原封不動送進引擎。這次先在後端堵住所有進入點，再替支撐生成加一條逾時兜底，讓未來任何引擎卡死都不會再鎖死佇列。

## What Changes

- **全域參數下限**：`SLAConfig`（`agent/models.py`）的 `support_max_bridge_length` 必須是不小於 `1e-4` 的有限數值，`support_base_diameter` 必須是不小於 `2e-4` 的有限數值（皆 `allow_inf_nan=False`），0、負數、小於下限的極小正數、NaN、正負 inf 一律拒絕。底座直徑的下限是手動支撐點半徑門檻（`1e-4`）的 2 倍：引擎把直徑折半成半徑寫進匯出的每個支撐點，這樣匯出的清單一定能原樣送回。`support_max_pillar_link_distance` 維持允許 0，不得誤擋。
- **錯誤碼特化**：`SLAConfig` 驗證失敗時，若失敗欄位含上述兩個欄位，錯誤碼由通用的 `CONFIG_VALIDATION_ERROR` 改為新的 `SUPPORT_PARAM_INVALID`（HTTP 422）；其他欄位維持 `CONFIG_VALIDATION_ERROR`。所有把 `ValidationError` 轉成 API 錯誤的地方共用同一套轉換，包括 `PUT /config`、`/support-params/validate`、`generate-supports`、`execute` 等。
- **`POST /slices` 補驗證**：建立 job 時帶入的初始 config，存入前先經過與既有流程相同的轉換並建一次 `SLAConfig`，不合法就回 422。只做 `SLAConfig` 驗證，不跑 `param_rules`。
- **手動支撐點單點檢查**：`POST /slices/{job_id}/support-points` 逐點檢查 `base_radius_mm`，`0 <= v` 且小於 `1e-4`（以單精度浮點的 `1e-4` 為界，含 `-0.0`）即回 422 與新的 `SUPPORT_POINT_PARAM_INVALID`，並在錯誤內容標出點的索引與欄位（如 `points[i].base_radius_mm`）。負數代表「沿用全域設定」，必須放行；欄位不存在也放行。儲存的仍是原始 bytes，不做任何改寫。
- **支撐生成逾時兜底**：`run_prusa_cli()` 新增可選參數 `timeout_sec`（預設 `None`，行為與現在完全相同）。只有生成支撐的呼叫點傳入 120 秒（前端輪詢上限也是 120 秒，但後端從引擎啟動才計時，前端通常會先放棄；見 tasks.md 4.10 第 6 點）。逾時時強制終止子程序並回收，job 標記為 `failed`、錯誤碼沿用 `SUPPORT_GENERATION_FAILED`，佇列隨 job 結束自然釋放。切片、鏤空、切割、匯出支撐點一律不加逾時。
- **錯誤碼登錄**：在 `agent/error_codes.py` 註冊 `SUPPORT_PARAM_INVALID` 與 `SUPPORT_POINT_PARAM_INVALID`，並重新產生衍生文件。
- **不在範圍內**：前端 DS-Online 不動（滑桿下限、錯誤碼對照、四語 i18n 另開 task）；引擎 `Clustering.cpp` 演算法不修；`param_rules.py` 不新增規則（`SLAConfig` 會先失敗，規則永遠跑不到）；不新增取消 job 的端點。

## Capabilities

### New Capabilities

（無）

### Modified Capabilities

- `support-param-validation`：新增「Max Connector Length 必須是不小於 `1e-4`、Base Diameter 必須是不小於 `2e-4` 的有限數值（含 NaN 與 inf 防護）」的範圍防護需求，違反時回 422 與 `SUPPORT_PARAM_INVALID`；明定 Max Pillar Link Distance 為 0 仍合法。
- `slice-config-intake`：「儲存設定當下即驗證」延伸到 `POST /slices` 的初始 config，不合法的 config 不得存入 job。
- `support-point-api`：接受自訂支撐點清單時，須拒絕 `base_radius_mm` 為 0 的點並回報點索引；負數與缺欄位維持「回退全域」語意。
- `support-generation-error-codes`：新增「支撐生成引擎逾時須終止子程序、標記 failed 並以 `SUPPORT_GENERATION_FAILED` 回報」的需求。

## Impact

- **程式碼**：`agent/models.py`、`agent/api_v2.py`（`POST /slices`、`PUT /config`、`_run_param_validation`、`generate-supports`、`execute`、`support-points` 等 `ValidationError` 轉換點）、`agent/errors.py`、`agent/error_codes.py`、`agent/sla_operations.py`（`run_prusa_cli`、`generate_supports`）、`agent/jobs.py`（`run_support_generation` 的失敗處理）。
- **衍生文件**：`docs/error_codes.json`、`docs/err_code_spec.md` 由工具重新產生。
- **API 行為**：
  - 兩個欄位為 0、負數或 NaN 時，原本會被接受並卡死引擎，改為立即回 422。這對 API 呼叫端是行為變更，但原本的結果就是卡死，沒有合法用途受影響。
  - 單點 `base_radius_mm = 0` 原本會被接受，改為 422。
  - 舊專案或外部呼叫端若帶著這兩個 0 值，切片與 PRZ 下載也會改回 422，而不是卡住。
- **前端過渡期**：DS-Online 尚未認得兩個新錯誤碼，會顯示「未預期錯誤」toast。請求在進入佇列前就被擋下，引擎與佇列不會卡死，這個過渡狀態可以接受。
- **與進行中變更 `slicer-engine-job-queue` 的關係**：該變更規定 engine job 全域 FIFO、不新增 cancel 端點、不改變 job 狀態 JSON 形狀。本變更不改 `engine_job_queue.py`；逾時是在 job 內部終止子程序，不是新增 cancel 端點；job 結束後由既有的 `async with` 釋放佇列，狀態仍走既有的 `failed` 與 `error_code` 欄位。兩者不衝突。
- **平台**：Windows 上引擎是直接執行 `slicer-engine.exe`，`process.kill()` 即可終止；被終止的退出碼不會觸發 Launcher 的當機通報（僅在測試模式且退出碼為負或 ≥128 時才觸發）。
