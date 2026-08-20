## ADDED Requirements

### Requirement: 切片結果分類須覆蓋兩條 exit 路徑

切片結果分類器 SHALL 區分兩條路徑進行歸因：

- **Path A**（`exit_code != 0`）：依 stderr 文字歸因為具體 code，未命中則 fallback JOB_FAILED。
- **Path B**（`exit_code == 0` 且輸出檔不存在）：依 stdout/stderr 文字歸因為具體 code，未命中則 fallback JOB_FAILED。

exit code 0 且輸出檔存在視為成功，分類器 MUST 回傳 `None`，`run_slicing()` 走正常完成路徑。

#### Scenario: 非零退出進入 Path A
- **WHEN** CLI 以非零 exit code 結束
- **THEN** 分類器依 stderr 逐步歸因，不受輸出檔是否存在影響

#### Scenario: exit 0 + 輸出存在 = 成功
- **WHEN** CLI 以 exit code 0 結束且輸出檔存在
- **THEN** 分類器回傳 `None`，job 走正常完成路徑

#### Scenario: exit 0 + 輸出不存在進入 Path B
- **WHEN** CLI 以 exit code 0 結束且輸出檔不存在
- **THEN** 分類器依 stdout/stderr 逐步歸因

---

### Requirement: Path A — validate() 錯誤須在 process() 例外之前優先比對

Path A 的分類順序 SHALL 固定為：validate() 對照表 → process() 例外對照表 → STL parse error → unclassified fallback。validate() 訊息比對 MUST 在固定英文語系下進行（訊息為可翻譯字串，見 design D5）。

> **Web API 可達性說明**：以下所有 Scenario 描述的是分類器的正確行為（若 CLI 輸出對應訊息，分類器即回傳對應 code）。其中 `PAD_CONFIG_INVALID` 與 `SUPPORT_PAD_GAP_CONFLICT` 目前因 `SLAConfig` 未暴露必要欄位（pad 幾何參數、`pad_around_object`）而對 Web API 不可達；其餘 code 均可由 Web API 觸發。

#### Scenario: pad brim 過小（分類器支援；目前 Web API 不可達）
- **WHEN** stderr 含 `Pad brim size is too small`
- **THEN** job 狀態為 `FAILED`，`error_code` 為 `PAD_CONFIG_INVALID`，`retryable` 為 false

#### Scenario: 曝光時間超出範圍
- **WHEN** stderr 含 `xposition time is out of printer profile bounds`（涵蓋 `Exposition time…` 與 `Initial exposition time…`）
- **THEN** job 狀態為 `FAILED`，`error_code` 為 `EXPOSURE_TIME_OUT_OF_RANGE`

#### Scenario: 抬升高度過低
- **WHEN** stderr 含 `Elevation is too low for object`
- **THEN** job 狀態為 `FAILED`，`error_code` 為 `SUPPORT_ELEVATION_TOO_LOW`

#### Scenario: 支撐柱底與 pad 間隙衝突（分類器支援；目前 Web API 不可達）
- **WHEN** stderr 含 `The endings of the support pillars`
- **THEN** job 狀態為 `FAILED`，`error_code` 為 `SUPPORT_PAD_GAP_CONFLICT`

#### Scenario: head penetration 非法
- **WHEN** stderr 含 `Invalid Head penetration`
- **THEN** job 狀態為 `FAILED`，`error_code` 為 `SUPPORT_HEAD_PENETRATION_INVALID`

#### Scenario: pinhead 直徑無效
- **WHEN** stderr 含 `Invalid pinhead diameter`
- **THEN** job 狀態為 `FAILED`，`error_code` 為 `SUPPORT_HEAD_TOO_WIDE`

---

### Requirement: Path A — process() 例外須歸因為具體 code

當 `stderr` 命中已知的 `SLAPrint::process()` 例外訊息時，系統 SHALL 將 job 標為 `FAILED` 並回傳對應的具體 `error_code`。此步驟 MUST 在 validate() 對照表未命中後才執行。

#### Scenario: 幾何無法切片
- **WHEN** stderr 含 `can not be sliced`（且未命中 validate 對照表）
- **THEN** job 狀態為 `FAILED`，`error_code` 為 `MODEL_MESH_UNSLICEABLE`

#### Scenario: 模型含無法列印的層
- **WHEN** stderr 含 `There are unprintable objects`
- **THEN** job 狀態為 `FAILED`，`error_code` 為 `UNPRINTABLE_OBJECT`

#### Scenario: 底座無法生成
- **WHEN** stderr 含 `No pad can be generated`
- **THEN** job 狀態為 `FAILED`，`error_code` 為 `PAD_GENERATION_FAILED`

---

### Requirement: Path A — STL parse 錯誤須歸因為 INVALID_MODEL

當 `stderr` 含 `"{input_filename}:"` 前綴（`LoadPrintData.cpp` 的 STL parse 例外格式），且 validate / process 對照表均未先命中時，系統 SHALL 將 job 標為 `FAILED` 並回傳 `INVALID_MODEL`。

#### Scenario: STL 格式無效（parse 失敗）
- **WHEN** stderr 含 `"{model_filename}:"` 前綴，且未命中 validate 或 process 對照表
- **THEN** job 狀態為 `FAILED`，`error_code` 為 `INVALID_MODEL`

---

### Requirement: Path A — 未命中任何對照表的非零退出走 JOB_FAILED

當非零退出且 stderr 未命中任何已知模式時，系統 SHALL 以 `JOB_FAILED`（無具體 code）回傳，並保留原始訊息。

#### Scenario: 未知非零退出
- **WHEN** CLI 以非零 exit code 結束，且 stderr 未命中任何對照條目
- **THEN** job 狀態為 `FAILED`，`error_code` 缺省，前端收到 `JOB_FAILED`

---

### Requirement: Path B — 模型超出成型體積須歸因為 MODEL_OUT_OF_BOUNDS

當 exit 0 + 無輸出檔，且 stdout 或 stderr 含 `"no object is fully inside the print volume"` 時，系統 SHALL 將 job 標為 `FAILED` 並回傳 `MODEL_OUT_OF_BOUNDS`。此訊號出現在 stdout，分類器 MUST 一併比對 stdout（不得只掃 stderr）。

此情境成因為 `ProcessActions.cpp` 在 `print->empty()` 後繼續執行（未 `return false`），exit code 維持 0。

#### Scenario: 模型完全在成型體積外
- **WHEN** exit code 0，輸出檔不存在，stdout 含 `no object is fully inside the print volume`
- **THEN** job 狀態為 `FAILED`，`error_code` 為 `MODEL_OUT_OF_BOUNDS`
- **AND** 此情境 MUST NOT 因 exit code 為 0 而被誤判為成功

---

### Requirement: Path B — 空模型須歸因為 INVALID_MODEL

當 exit 0 + 無輸出檔，且 stderr 含 `"Error: file is empty:"` 時，系統 SHALL 將 job 標為 `FAILED` 並回傳 `INVALID_MODEL`。此情境成因為 `LoadPrintData.cpp` 在偵測到空模型後寫入 stderr 並 `continue`（非 `return false`），exit code 維持 0。

#### Scenario: 上傳的 STL 為空模型
- **WHEN** exit code 0，輸出檔不存在，stderr 含 `Error: file is empty:`
- **THEN** job 狀態為 `FAILED`，`error_code` 為 `INVALID_MODEL`
- **AND** 此情境 MUST NOT 因 exit code 為 0 而被誤判為成功

---

### Requirement: Path B — 其餘 zero-exit / no-output 走 JOB_FAILED

未命中任何已知 Path B 標記時，系統 SHALL 以 `JOB_FAILED`（無具體 code）回傳，MUST NOT 在無正向證據時將未知情況推定為成功。

#### Scenario: 無法歸因的 zero-exit 失敗
- **WHEN** exit code 0，輸出檔不存在，stdout 與 stderr 均未命中已知標記
- **THEN** job 狀態為 `FAILED`，`error_code` 缺省，前端收到 `JOB_FAILED`

---

### Requirement: 分類結果須透過 error_code 欄位傳遞至 API

`run_slicing()` SHALL 將 `SliceClassification.error_code` 帶入 `write_job_status(error_code=...)` 寫入 `status.json`；`_error_from_status()` SHALL 能經由 `_ERROR_CODE_FACTORIES` 查找所有已知切片 error code 並回傳具體 `APIError`。

#### Scenario: 具體 code 傳遞至前端
- **WHEN** `run_slicing()` 呼叫 `write_job_status(FAILED, error_code="MODEL_MESH_UNSLICEABLE")`
- **THEN** GET 狀態端點回傳 `success: false`，`code` 為 `MODEL_MESH_UNSLICEABLE`，`retryable` 為 false

#### Scenario: 舊 status.json 缺 error_code 向後相容
- **WHEN** 讀取無 `error_code` 欄位的既有 `status.json`（FAILED 狀態）
- **THEN** 回傳 `JOB_FAILED`（回退行為），不報錯

---

### Requirement: validate 與 stderr/stdout 標記字串須有契約測試

由於分類完全依賴 CLI 的文字輸出，系統 SHALL 建立契約 / golden 測試，直接對 CLI 實際輸出的 validate 訊息與 stderr/stdout 標記字串進行斷言，使引擎改版或去識別化改寫改動這些字串時能被測試擋下。

#### Scenario: 標記字串變動被偵測
- **WHEN** CLI 的 validate 訊息（如 `Pad brim size is too small`）或 stderr 標記字串被更動
- **THEN** 契約測試失敗，提示分類對照表需同步更新
