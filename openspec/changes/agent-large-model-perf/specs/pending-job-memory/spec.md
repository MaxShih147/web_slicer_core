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

`_save_model_to_job(model_data, input_path)` 遇到不含 `stl_data`、但記錄了已落地路徑的模型項目時（暫存檔的處理見下一個 requirement），SHALL 沿用該檔案：路徑與 `input_path` 相同時不重寫；不同時 SHALL 複製該檔案到 `input_path`；檔案不存在時 SHALL 回傳 `MODEL_NOT_FOUND`。已落地的檔案先前已通過驗證，SHALL 不再驗證。

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

### Requirement: 閒置 pending job 的模型 bytes 移到磁碟暫存，job 本身不刪除

每個 pending job SHALL 記錄最後存取時間（建立時，以及每次經由 `/slices/{job_id}/…` 端點讀寫該 pending job 時更新）。agent SHALL 在背景定期（每 60 秒）檢查：仍以 `stl_data` 持有模型 bytes、且閒置超過門檻的 pending job，SHALL 把該 bytes 寫到暫存目錄 `JOBS_DIR/.pending_spool/<job_id>.stl`，然後改以伺服器端標記記錄暫存檔、移除 `stl_data`。門檻預設 600 秒，可由環境變數 `AGENT_PENDING_SPOOL_IDLE_SEC` 覆寫（非正數或無法解析時使用預設值）。

暫存 MUST NOT 刪除或使 pending job 失效：之後對該 job 的任何操作 SHALL 與未暫存時得到相同結果（同樣的 `modelCount`、同樣的 `input/model.stl` 內容、同樣的驗證規則——`validated` 標記保留原值，未驗證的內容在落地時仍會驗證）。暫存目錄名稱含 `.`，不可能與 job id（只允許英數、`_`、`-`）衝突，`GET /slices/{job_id}` 的回應 SHALL 不受影響。

暫存檔 SHALL 在下列時機刪除：該模型落地為 `input/model.stl` 後（落地方式為移動或複製後刪除）、pending job 被 `execute`／`ortho-process` 移除後、agent 啟動時（重啟後 `_pending_jobs` 本來就是空的，殘留暫存檔沒有對應的 job）。

#### Scenario: 閒置的 pending job 模型移到磁碟
- **WHEN** 一個 pending job 上傳模型後閒置超過門檻，且背景檢查執行
- **THEN** 其模型 bytes SHALL 寫入 `JOBS_DIR/.pending_spool/<job_id>.stl`，`stl_data` SHALL 移除
- **AND** 該 job SHALL 仍在 `_pending_jobs` 中，`GET /slices/{job_id}` 的回應 SHALL 與暫存前相同

#### Scenario: 暫存後照常切片
- **WHEN** 已暫存的 pending job 之後呼叫 `execute`
- **THEN** 切片 SHALL 成功啟動，`input/model.stl` 內容 SHALL 與原上傳的 bytes 相同
- **AND** 暫存檔 SHALL 在落地後刪除

#### Scenario: 未驗證的內容暫存後仍會驗證
- **WHEN** 經 `use-model-from` 或 `add_models_to_slice_job()` 加入、`validated` 為 False 的內容被暫存
- **THEN** 落地時 SHALL 仍執行 `_validate_stl_bytes()`，內容無效時 SHALL 回 `INVALID_MODEL`

#### Scenario: 仍在使用的 pending job 不暫存
- **WHEN** 一個 pending job 在門檻內有任何存取
- **THEN** 背景檢查 SHALL 不動它

#### Scenario: agent 重啟後清掉殘留暫存
- **WHEN** agent 啟動時 `JOBS_DIR/.pending_spool/` 內有檔案
- **THEN** 系統 SHALL 刪除這些檔案

#### Scenario: 暫存失敗不影響服務
- **WHEN** 寫入暫存檔失敗（例如磁碟已滿）或背景檢查發生例外
- **THEN** 該 job SHALL 保持原狀（bytes 仍在記憶體），系統 SHALL 記 WARNING 並在下一輪繼續，MUST NOT 終止背景迴圈或影響請求處理
