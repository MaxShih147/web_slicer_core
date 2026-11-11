## ADDED Requirements

### Requirement: 模型落地後 pending job 不再持有模型 bytes

`generate-supports`、`export-support-points`、`generate-hollow`、`cut` 這四個「把模型寫入 `input/model.stl` 但保留 pending job」的端點，在 `_save_model_to_job()` 成功寫檔、背景任務排入之後，SHALL 將 `pending["models"][0]` 的 `stl_data` 移除，改記錄已落地檔案的路徑；agent MUST NOT 在之後繼續持有該份模型 bytes 的任何參照。

`pending["models"]` 的項目數 SHALL 不變，`GET /slices/{job_id}` 回應中的 `modelCount` SHALL 與釋放前相同。

#### Scenario: generate-supports 後釋放 bytes
- **WHEN** 呼叫端上傳模型後呼叫 `POST /slices/{job_id}/generate-supports` 並成功
- **THEN** `_pending_jobs[job_id]["models"][0]` SHALL 不再含有 `stl_data`
- **AND** SHALL 記錄已落地的 `input/model.stl` 路徑
- **AND** `GET /slices/{job_id}` 回傳的 `modelCount` SHALL 不變

#### Scenario: 寫檔失敗時不釋放
- **WHEN** `_save_model_to_job()` 拋出錯誤（例如 `INVALID_MODEL`）或設定驗證失敗
- **THEN** `pending["models"][0]` SHALL 保持原狀，呼叫端修正後可重試

#### Scenario: 重複產生支撐不累積記憶體
- **WHEN** 對多個 job 反覆執行「上傳 → generate-supports」10 次
- **THEN** 每個 job 在 generate-supports 成功後 SHALL 不再持有模型 bytes，agent 記憶體 SHALL 不隨次數持續上升

### Requirement: 已落地模型之後的操作沿用落地檔案

`_save_model_to_job(model_data, input_path)` 遇到不含 `stl_data`、但記錄了已落地路徑的模型項目時，SHALL 沿用該檔案：路徑與 `input_path` 相同時不重寫；不同時 SHALL 複製該檔案到 `input_path`；檔案不存在時 SHALL 回傳 `MODEL_NOT_FOUND`。已落地的檔案先前已通過驗證，SHALL 不再驗證。

同一 job 在 generate-supports 之後呼叫 `execute`、`ortho-process`，或再次呼叫 `generate-supports`／`export-support-points`／`generate-hollow`／`cut`，SHALL 與改前得到相同的 `input/model.stl` 內容與相同結果。

#### Scenario: generate-supports 後在同一 job 執行切片
- **WHEN** 同一 job 先 generate-supports、再 `execute`
- **THEN** `execute` SHALL 成功啟動切片，`input/model.stl` 內容 SHALL 與上傳的 bytes 相同

#### Scenario: 同一 job 再次產生支撐
- **WHEN** 同一 job 在 generate-supports 之後再次呼叫 generate-supports
- **THEN** 系統 SHALL 沿用已落地的 `input/model.stl`，不回傳錯誤

#### Scenario: 呼叫端無法偽造已落地標記
- **WHEN** 呼叫端透過 `add_models_to_slice_job()` 的 request body 提交與已落地標記同名的欄位（例如指向 job 目錄以外的檔案路徑）
- **THEN** `_save_model_to_job()` MUST NOT 把它當成已落地檔案讀取或複製，SHALL 依「需要驗證的 `stl_data`」或「缺少 `stl_data`」的既有規則處理
- **AND** 已落地標記 SHALL 只能由伺服器端以 JSON 無法產生的型別建立

#### Scenario: 落地檔案遺失
- **WHEN** 模型項目記錄的落地檔案已不存在
- **THEN** `_save_model_to_job()` SHALL 拋出 `MODEL_NOT_FOUND`

#### Scenario: use-model-from 流程不受影響
- **WHEN** 呼叫端以 `use-model-from/{source_job_id}` 引用另一個 job 的輸出作為模型
- **THEN** 該模型項目 SHALL 仍以 `stl_data` 加 `validated: False` 存入，落地時 SHALL 仍完整驗證，行為與改前相同

### Requirement: 閒置的 pending job 逾時清理

每個 pending job SHALL 記錄最後存取時間（建立時，以及每次經由 `/slices/{job_id}/…` 端點讀寫該 pending job 時更新）。agent SHALL 在背景定期（每 5 分鐘）移除閒置超過時限的 pending job；時限預設 2 小時，可由環境變數 `AGENT_PENDING_JOB_TTL_SEC` 覆寫（非正數或無法解析時使用預設值）。

被移除的 pending job 之後的請求 SHALL 依現有規則回應：job 目錄存在時沿用現有 `JOB_ALREADY_EXECUTED`／「already generated」判斷，不存在時回 `JOB_NOT_FOUND`。清理 MUST NOT 刪除磁碟上的 job 目錄。

#### Scenario: 閒置超過時限的 pending job 被移除
- **WHEN** 一個 pending job 最後存取時間距今超過時限，且清理執行
- **THEN** 該 job SHALL 從 `_pending_jobs` 移除，其 job 目錄（若存在）SHALL 保留

#### Scenario: 仍在使用的 pending job 不被移除
- **WHEN** 一個 pending job 在時限內有任何存取
- **THEN** 清理 SHALL 不移除它

#### Scenario: 清理失敗不影響服務
- **WHEN** 清理過程發生例外
- **THEN** 系統 SHALL 記 log 並在下一輪繼續，MUST NOT 終止清理迴圈或影響請求處理
