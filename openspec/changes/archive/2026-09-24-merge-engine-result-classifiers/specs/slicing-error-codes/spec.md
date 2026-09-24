## MODIFIED Requirements

### Requirement: Path A — validate() 錯誤須在 process() 例外之前優先比對

Path A 的分類順序 SHALL 固定為：validate() 對照表 → process() 例外對照表 → STL parse error → unclassified fallback。validate() 訊息比對 MUST 在固定英文語系下進行（訊息為可翻譯字串，見 design D5）。

對照表 MUST 為支撐與切片共用的單一 `ENGINE_RULES`，MUST NOT 為切片流程另行維護一份平行表。

> **Web API 可達性更新**：`PAD_CONFIG_INVALID` 與 `SUPPORT_PAD_GAP_CONFLICT` 原先因 `SLAConfig` 未暴露 pad 幾何參數而對 Web API 不可達。支撐參數面板開放 30 個欄位後，這兩者**已可由 Web API 觸發**，原註記作廢。

#### Scenario: pad brim 過小
- **WHEN** stderr 含 `Pad brim size is too small`
- **THEN** job 狀態為 `FAILED`，`error_code` 為 `PAD_CONFIG_INVALID`，`retryable` 為 false

#### Scenario: 曝光時間超出範圍
- **WHEN** stderr 含 `xposition time is out of printer profile bounds`（涵蓋 `Exposition time…` 與 `Initial exposition time…`）
- **THEN** job 狀態為 `FAILED`，`error_code` 為 `EXPOSURE_TIME_OUT_OF_RANGE`

#### Scenario: 抬升高度過低
- **WHEN** stderr 含 `Elevation is too low for object`
- **THEN** job 狀態為 `FAILED`，`error_code` 為 `SUPPORT_ELEVATION_TOO_LOW`

#### Scenario: 支撐柱底與 pad 間隙衝突
- **WHEN** stderr 含 `The endings of the support pillars`
- **THEN** job 狀態為 `FAILED`，`error_code` 為 `SUPPORT_PAD_GAP_CONFLICT`

#### Scenario: head penetration 非法
- **WHEN** stderr 含 `Invalid Head penetration`
- **THEN** job 狀態為 `FAILED`，`error_code` 為 `SUPPORT_HEAD_PENETRATION_INVALID`

#### Scenario: pinhead 直徑無效
- **WHEN** stderr 含 `Invalid pinhead diameter`
- **THEN** job 狀態為 `FAILED`，`error_code` 為 `SUPPORT_HEAD_TOO_WIDE`

#### Scenario: 缺少必要支撐點（本變更新增）
- **WHEN** stderr 含 `Cannot proceed without support points`
- **THEN** job 狀態為 `FAILED`，`error_code` 為 `SUPPORT_POINTS_REQUIRED`
- **AND** MUST NOT 退化為 `JOB_FAILED`

## ADDED Requirements

### Requirement: 挖空與切割須攜帶引擎原始錯誤

`generate_hollow` 與 `cut` 失敗時，系統 SHALL 將引擎的原始 stderr 納入 `detail`。寫死的罐頭訊息 MUST 只作為原始輸出為空時的後備，MUST NOT 猜測失敗原因。

#### Scenario: 挖空失敗
- **WHEN** 挖空流程失敗且引擎 stderr 非空
- **THEN** `detail` 含引擎原文
- **AND** MUST NOT 只回傳罐頭訊息

#### Scenario: 切割失敗且引擎無輸出
- **WHEN** 切割失敗但引擎 stderr 為空
- **THEN** 回傳罐頭訊息作為後備
- **AND** 該訊息 MUST NOT 宣稱特定原因（如「切割高度超出範圍」）

### Requirement: 切片路徑須支援支撐專屬的新 code

切片流程 SHALL 能回傳 `SUPPORT_POINT_SAMPLING_FAILED` 與 `SHRINKAGE_COMPENSATION_INVALID`，語意與支撐流程一致。

#### Scenario: 切片時支撐點取樣失敗
- **WHEN** 切片流程的輸出含 `SLA support point generator has failed.`
- **THEN** `error_code` 為 `SUPPORT_POINT_SAMPLING_FAILED`，與支撐流程同一個 code
