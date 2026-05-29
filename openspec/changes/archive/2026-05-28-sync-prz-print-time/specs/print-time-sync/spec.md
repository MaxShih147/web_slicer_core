## ADDED Requirements

### Requirement: Web API 列印時間以 PRZ 物理公式為單一真值來源

切片完成後，`status.json["estimated_print_time"]`（Web API `estimatedPrintTime` 的資料來源）SHALL 等於 `_compute_print_time(prz_config, total_layers, timing)` 的回傳值，其中 `prz_config` 為持久化的前端 config、`total_layers` 為 `parse_sl1_metadata()` 取得的層數、`timing` 為 `_extract_prz_timing_config(prz_config)` 的萃取結果。此值 SHALL 與 PRZ 下載端使用**同一公式與同一份 config**，確保 Web API 顯示值與 PRZ binary 內列印時間一致。`estimated_print_time` SHALL NOT 直接沿用 fork SL1 估值作為正常情況下的回傳值。

#### Scenario: 正常同步 — API 數值等於公式計算值
- **GIVEN** 一個切片成功的 job，其 `jobs/{id}/prz_config.json` 存在且含有效 timing / lift / retract 參數
- **AND** `parse_sl1_metadata()` 回傳層數 `N`
- **WHEN** `run_slicing()` 完成並寫入 `status.json`
- **THEN** `status.json["estimated_print_time"]` SHALL 等於 `_compute_print_time(prz_config, N, _extract_prz_timing_config(prz_config))` 的回傳值
- **AND** 該值 SHALL NOT 等於 `parse_sl1_metadata()` 解出的 fork SL1 估值（兩者公式不同）

#### Scenario: 與 PRZ binary 列印時間同源一致
- **GIVEN** 同一個 job 的 `prz_config.json` 與層數 `N`
- **WHEN** 透過 PRZ 下載端產生 PRZ binary
- **THEN** PRZ binary 的 `print_time` 欄位 SHALL 由相同的 `_compute_print_time(prz_config, N, timing)` 推導（PRZ binary 端額外的 `int()` 截斷除外）
- **AND** Web API 回傳的時間與 PRZ 列印時間 SHALL 來自單一真值來源，不再各自獨立計算

### Requirement: 持久化 Mechado prz_config 為 prz_config.json

前端 SHALL 透過獨立的選填欄位 `prz_config`（內容為 `uiToDefaultConfig(uiParams)` 產出的完整 Mechado config，含 `Print.*` Title Case key）在 `createJob` 與 `updateJobConfig` 兩端點傳遞（雙保險，避免「未經 update 即 execute」漏接）。`execute_slice_job()` SHALL 在排程 `run_slicing` 背景任務之前，將該 `prz_config`（**而非** snake_case 切片 `config`）持久化為 `jobs/{id}/prz_config.json`，作為切片完成後計算物理列印時間的唯一輸入來源。落檔前 SHALL 套用與 PRZ 下載端相同的 `_inject_retract_overrides()` 前處理，使持久化內容與下載端逐位元一致。切片用的 snake_case `config` SHALL NOT 被混入或污染。

#### Scenario: 獨立 prz_config 欄位來源（不混用 snake_case 切片 config）
- **GIVEN** 前端以 `createJob` 或 `updateJobConfig` 送出 request body，同時含選填欄位 `prz_config`（Mechado `Print.*`）與切片用 `config`（snake_case）
- **WHEN** 後端接應該請求
- **THEN** `prz_config` SHALL 被存入 `pending["prz_config"]`，與 `pending["config"]`（切片設定）分離保存
- **AND** 切片用 `config` SHALL 維持原樣，SHALL NOT 因 `prz_config` 而被覆寫或被注入 `Print` 區段（避免 `_convert_v2_config_to_sla` 的 `print_config = config.get("Print", config)` 解析翻轉而破壞切片幾何）

#### Scenario: 切片啟動時落檔（內容為 Mechado prz_config）
- **GIVEN** 前端已提交模型並附帶 `prz_config`，觸發 `execute_slice_job()`
- **WHEN** job 目錄建立完成、切片背景任務排程之前
- **THEN** `jobs/{id}/prz_config.json` SHALL 存在
- **AND** 其內容 SHALL 為 Mechado `prz_config`（保留 `Print.*` Title Case key），可被 `_extract_prz_timing_config()` 萃取
- **AND** 其內容 SHALL NOT 為 snake_case 切片 config（杜絕 `_compute_print_time` 因缺 `Print.*` 而全跑預設值的情形）

#### Scenario: 落檔前 Pre-inject — 與 PRZ 下載端二進位一致
- **GIVEN** 前端送來的 `prz_config` 之 `Print` 區段缺少 `Retract Distance`（僅有 `Retract Second Distance`，與預設 profile 一致）
- **WHEN** `execute_slice_job()` 落檔 `prz_config.json`
- **THEN** 落檔前 SHALL 對該 config 套用 `_inject_retract_overrides()`（與 [download.prz 端](agent/api_v2.py#L965) 完全相同的前處理）
- **AND** 後續 `run_slicing()` 以該檔計算所得 `estimated_print_time` SHALL 與 PRZ 下載端對相同 config 計算所得逐位元一致（PRZ binary 端 `int()` 截斷除外）

### Requirement: config 缺失或計算失敗時退回 fork 估值

當 `prz_config.json` 不存在、無法解析為合法 JSON、或萃取 / 計算過程拋出任何例外時，`estimated_print_time` SHALL 退回 `parse_sl1_metadata()` 取得的 fork SL1 估值（fallback）。同步失敗 SHALL NOT 使已成功的切片狀態由 `COMPLETED` 轉為 `FAILED`，亦 SHALL NOT 向上拋出例外中斷流程。當 `prz_config.json` 缺失時，`run_slicing()` SHALL 記一筆 `info` 等級 log（靜默降級 + 可觀測性），以追蹤前端是否漏送 `prz_config`。

#### Scenario: prz_config.json 缺失 → 使用 fork 估值
- **GIVEN** 一個切片成功的 job，但 `jobs/{id}/prz_config.json` 不存在
- **AND** `parse_sl1_metadata()` 回傳 fork 估值 `T_fork`
- **WHEN** `run_slicing()` 解析時間同步
- **THEN** `status.json["estimated_print_time"]` SHALL 等於 `T_fork`
- **AND** job 狀態 SHALL 為 `COMPLETED`
- **AND** `run_slicing()` SHALL 記一筆 `info` 等級 log：`"prz_config missing, falling back to fork time"`（含 `job_id`）

#### Scenario: prz_config.json 損毀（非合法 JSON）→ 使用 fork 估值
- **GIVEN** `jobs/{id}/prz_config.json` 內容無法被 `json.load` 解析（檔案損毀）
- **AND** fork 估值為 `T_fork`
- **WHEN** `_load_prz_config()` 讀取該檔
- **THEN** `_load_prz_config()` SHALL 回傳 `None`（吞掉 `OSError` / `ValueError`，不拋出）
- **AND** `status.json["estimated_print_time"]` SHALL 等於 `T_fork`

#### Scenario: 萃取或計算過程拋例外 → 使用 fork 估值
- **GIVEN** `prz_config` 存在但內容使 `_extract_prz_timing_config()` 或 `_compute_print_time()` 拋出例外（如型別錯誤、缺必要結構）
- **AND** fallback 值為 `T_fork`
- **WHEN** `resolve_estimated_print_time(prz_config, N, T_fork)` 執行
- **THEN** 回傳值 SHALL 等於 `T_fork`
- **AND** SHALL NOT 向 `run_slicing()` 主流程拋出例外

#### Scenario: fork 估值亦為 None → 維持 None（不退化）
- **GIVEN** `prz_config.json` 缺失且 `parse_sl1_metadata()` 的 fork 估值為 `None`
- **WHEN** 解析時間同步
- **THEN** `status.json["estimated_print_time"]` SHALL 為 `None`（與現狀一致，不報錯）

### Requirement: 極端邊界輸入處理

`resolve_estimated_print_time(prz_config, total_layers, fallback)` 為純函式，SHALL 在 `total_layers` 為 `0` 或 `None`、或 `prz_config` 為空 dict（`{}`）或 `None` 時，跳過物理計算並直接回傳 `fallback`，且 SHALL NOT 拋出例外或回傳 `NaN`。

#### Scenario: 層數為 0 → 退回 fallback
- **GIVEN** `prz_config` 為有效 dict，但 `total_layers == 0`
- **WHEN** `resolve_estimated_print_time(prz_config, 0, T_fork)` 執行
- **THEN** 回傳值 SHALL 等於 `T_fork`
- **AND** SHALL NOT 呼叫 `_compute_print_time()`，亦 SHALL NOT 拋出例外

#### Scenario: config 為空字典 → 退回 fallback
- **GIVEN** `prz_config == {}`（空字典）且 `total_layers == N`（N > 0）
- **WHEN** `resolve_estimated_print_time({}, N, T_fork)` 執行
- **THEN** 回傳值 SHALL 等於 `T_fork`
- **AND** SHALL NOT 拋出例外

#### Scenario: prz_config 為 None → 退回 fallback
- **GIVEN** `prz_config is None`（對應檔案缺失 / 損毀後 `_load_prz_config()` 的回傳）
- **WHEN** `resolve_estimated_print_time(None, N, T_fork)` 執行
- **THEN** 回傳值 SHALL 等於 `T_fork`
