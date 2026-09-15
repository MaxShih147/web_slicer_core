## MODIFIED Requirements

### Requirement: 已知 validate 錯誤須歸因為具體 error code

當 `stderr` 命中已知的 `SLAPrint::validate()` 錯誤訊息時，系統 SHALL 將 job 標為 `FAILED` 並回傳對照表定義的具體 `error_code`。比對 MUST 在固定的英文語系下進行（validate 訊息為可翻譯字串）。

對照表 MUST 為支撐與切片共用的單一 `ENGINE_RULES`，MUST NOT 為支撐流程另行維護一份平行表。

#### Scenario: pinhead 直徑過大
- **WHEN** `stderr` 含 `Invalid pinhead diameter`
- **THEN** job 狀態為 `FAILED`，`error_code` 為 `SUPPORT_HEAD_TOO_WIDE`，`retryable` 為 false

#### Scenario: head penetration 非法
- **WHEN** `stderr` 含 `Invalid Head penetration`
- **THEN** job 狀態為 `FAILED`，`error_code` 為 `SUPPORT_HEAD_PENETRATION_INVALID`

#### Scenario: 抬升高度過低
- **WHEN** `stderr` 含 `Elevation is too low for object`
- **THEN** job 狀態為 `FAILED`，`error_code` 為 `SUPPORT_ELEVATION_TOO_LOW`

#### Scenario: 缺少必要支撐點
- **WHEN** `stderr` 含 `Cannot proceed without support points`
- **THEN** job 狀態為 `FAILED`，`error_code` 為 `SUPPORT_POINTS_REQUIRED`

#### Scenario: 支撐柱底與 pad 間隙衝突
- **WHEN** `stderr` 含支撐柱底部落於物件與 pad 間隙的訊息
- **THEN** job 狀態為 `FAILED`，`error_code` 為 `SUPPORT_PAD_GAP_CONFLICT`

#### Scenario: 底墊 brim 過小（本變更新增）
- **WHEN** `stderr` 含 `Pad brim size is too small`
- **THEN** job 狀態為 `FAILED`，`error_code` 為 `PAD_CONFIG_INVALID`
- **AND** MUST NOT 退化為 `SUPPORT_GENERATION_FAILED`

#### Scenario: 非支撐專屬的 validate 錯誤落 fallback
- **WHEN** `stderr` 含未被對照表指派專屬代碼的 validate 錯誤（如 `Exposition time is out of printer profile bounds`）
- **THEN** job 狀態為 `FAILED`，`error_code` 為 `SUPPORT_GENERATION_FAILED`，並保留原始訊息
- **AND** 該訊息在規則表上 MUST 以 `fallback_by_design` 顯式標記

## ADDED Requirements

### Requirement: 支撐點取樣失敗須歸因為專屬 code

當引擎回報支撐點產生器自身失敗時，系統 SHALL 回傳 `SUPPORT_POINT_SAMPLING_FAILED`，MUST NOT 退化為 `SUPPORT_GENERATION_FAILED`。引擎在此情況已提供可行的修正建議（調整模型角度），該建議 MUST 保留在 `detail` 中。

#### Scenario: 支撐點產生器失敗
- **WHEN** 輸出含 `SLA support point generator has failed.`
- **THEN** job 狀態為 `FAILED`，`error_code` 為 `SUPPORT_POINT_SAMPLING_FAILED`
- **AND** `detail` 保留引擎原始訊息

### Requirement: 收縮補償為零須歸因為專屬 code

當引擎因物件轉換矩陣不可逆（零縮放或零收縮補償）而中止時，系統 SHALL 回傳 `SHRINKAGE_COMPENSATION_INVALID`。收縮補償為使用者可調欄位，此情況可被觸發。

#### Scenario: 收縮補償設為 0
- **WHEN** 輸出含 `the object transform is not invertible`
- **THEN** job 狀態為 `FAILED`，`error_code` 為 `SHRINKAGE_COMPENSATION_INVALID`
- **AND** MUST NOT 靜默結束或退化為 fallback
