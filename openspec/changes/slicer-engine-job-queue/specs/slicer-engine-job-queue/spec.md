## ADDED Requirements

### Requirement: 本機切片／engine 指令進入全域 FIFO

`web_slicer_core` MUST 將同一行程內對 Prusa／engine 的切片、找支撐及其他同等 CPU／檔案密集指令排入**單一全域佇列**，依到達順序執行（FIFO）。系統 MUST NOT 讓兩個 engine 作業在未完成前並行搶同一引擎資源（本 change 定義為：不得同時有兩個 running 的 engine job）。

#### Scenario: 兩帳連續送切片

- **WHEN** 呼叫端 A 建立切片 job，隨後呼叫端 B 在 A 仍 pending／running 時建立另一切片 job
- **THEN** B 的 job 進入佇列，狀態為既有 pending（或等價）
- **AND** 僅在 A 的 engine 作業結束後 B 才變為 running

#### Scenario: 結果回到正確 job

- **WHEN** A、B 各持有自己的 `job_id`
- **THEN** `GET /api/jobs/{job_id}`（及既有取檔端點）回傳該 `job_id` 的產物與狀態
- **AND** MUST NOT 把 A 的輸出當成 B 的成功結果

### Requirement: 沿用既有 job 狀態契約

系統 MUST 繼續以既有 `job_id` 與狀態查詢讓呼叫端輪詢。本 change MUST NOT 要求新增「前方還有 N 個」欄位，MUST NOT 新增 cancel／終止端點。

#### Scenario: 既有狀態查詢仍可用

- **WHEN** 佇列中的 job 被查詢
- **THEN** 回應含該 job 的既有狀態欄位（至少能區分等待／執行／成功／失敗）
- **AND** 不因 FIFO 而改變既有成功／失敗 JSON 形狀（除等待時間可能變長）
