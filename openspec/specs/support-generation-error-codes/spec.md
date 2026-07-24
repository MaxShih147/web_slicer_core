# support-generation-error-codes Specification

## Purpose
定義 `generate-supports` 的結果分類契約——固定順序的五步決策樹、成功／中性／失敗的權威判準（以 stdout/stderr 文字標記為唯一真值來源，不依賴 CLI exit code）、完整的 error code 集合與 validate 訊息對照表，以及 `supportOutcome` API 欄位與 `hasSupportMesh` 的語意。
## Requirements
### Requirement: 支撐生成須捕捉並保存 stdout 與 stderr

支撐生成流程 SHALL 完整捕捉 PrusaSlicer CLI 的 `stdout` 與 `stderr`，兩者皆 MUST 落地為 log，並 MUST 一併提供給結果分類器。系統 MUST NOT 僅依賴 `stderr` 而丟棄 `stdout`。

#### Scenario: 同時保存兩個串流
- **WHEN** 系統執行 support-only CLI 命令並結束
- **THEN** `stdout` 與 `stderr` 的完整原文皆被寫入 job 的 log
- **AND** 分類器可讀取到兩個串流的內容

#### Scenario: 失敗時原始輸出可供除錯
- **WHEN** 支撐生成被歸因為 `SUPPORT_GENERATION_FAILED`
- **THEN** 回傳的錯誤附錄 MUST 包含原始的 `stdout` 與 `stderr` 內容

---

### Requirement: 結果分類不得依賴 CLI 的 exit code

結果分類器 SHALL 完全以 `stdout` / `stderr` 的文字標記作為判定依據，且 MUST NOT 將 CLI 的 `returncode` 數值納入任何分類分支條件。

#### Scenario: validate 失敗回傳 exit 0 仍被正確歸因為失敗
- **WHEN** CLI 因 `validate()` 錯誤而以 exit code 0 結束、且 `stderr` 含已知 validate 錯誤訊息
- **THEN** job 狀態為 `FAILED` 並回傳對應的具體 `error_code`
- **AND** 判定結果不因 exit code 為 0 而被誤判為成功

#### Scenario: exit code 非 0 但無可歸因訊息
- **WHEN** CLI 以非 0 exit code 結束、但 `stdout` / `stderr` 皆未命中任何已知標記
- **THEN** job 狀態為 `FAILED` 並回傳 fallback code `SUPPORT_GENERATION_FAILED`

---

### Requirement: 已知 validate 錯誤須歸因為具體 error code

當 `stderr` 命中已知的 `SLAPrint::validate()` 錯誤訊息時，系統 SHALL 將 job 標為 `FAILED` 並回傳對照表定義的具體 `error_code`。比對 MUST 在固定的英文語系下進行（validate 訊息為可翻譯字串）。

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

#### Scenario: 非支撐專屬的 validate 錯誤落 fallback
- **WHEN** `stderr` 含未被對照表指派專屬代碼的 validate 錯誤（如 `Exposition time is out of printer profile bounds`）
- **THEN** job 狀態為 `FAILED`，`error_code` 為 `SUPPORT_GENERATION_FAILED`，並保留原始訊息

---

### Requirement: 模型出界須歸因為 MODEL_OUT_OF_BOUNDS

當 CLI 輸出顯示沒有可列印物件或模型不在成型體積內時，系統 SHALL 將 job 標為 `FAILED` 並回傳 `MODEL_OUT_OF_BOUNDS`。此訊號出現在 `stdout`，分類器 MUST 一併比對 `stdout`。

#### Scenario: 物件完全在成型體積外
- **WHEN** `stdout` 含 `no object is fully inside the print volume`
- **THEN** job 狀態為 `FAILED`，`error_code` 為 `MODEL_OUT_OF_BOUNDS`
- **AND** 此情境 MUST NOT 被歸類為 `SUPPORT_NOT_NEEDED`

---

### Requirement: 「不需支撐」須以 stdout 正向標記認定

系統 SHALL 僅在 `stdout` 命中正向標記（`No support/pad mesh generated` 或 `(pad only)`）且未觸發任何失敗歸因時，才將結果判定為中性成功。此時 job 狀態 MUST 為 `COMPLETED`，`hasSupportMesh` MUST 為 false，並以 `supportOutcome` 欄位帶出 `SUPPORT_NOT_NEEDED`。系統 MUST NOT 以「無 STL 檔案」或「無已知錯誤」作為推定中性成功的依據。

#### Scenario: 模型完全自支撐
- **WHEN** `stdout` 含 `No support/pad mesh generated` 且未命中任何失敗標記
- **THEN** job 狀態為 `COMPLETED`，`hasSupportMesh` 為 false，`supportOutcome` 為 `SUPPORT_NOT_NEEDED`

#### Scenario: 僅產生底座、零支撐柱
- **WHEN** `stdout` 含 `(pad only)`
- **THEN** job 狀態為 `COMPLETED`，`hasSupportMesh` 為 false，`supportOutcome` 為 `SUPPORT_NOT_NEEDED`
- **AND** 系統 MUST NOT 因為輸出了含 pad 的 STL 而回報 `hasSupportMesh` 為 true

#### Scenario: 中性結果不阻擋後續切片
- **WHEN** job 以 `SUPPORT_NOT_NEEDED` 完成
- **THEN** 回應以 `success: true` / `COMPLETED` 呈現，而非走錯誤路徑
- **AND** 使用者可繼續進行後續切片流程

---

### Requirement: 「有支撐」須以 stdout 正向標記認定

系統 SHALL 僅在 `stdout` 命中 `(supports only)` 或 `(includes supports and pad)` 時，才將結果判定為含實際支撐柱的正式成功。此時 job 狀態 MUST 為 `COMPLETED`，`hasSupportMesh` MUST 為 true。

#### Scenario: 僅支撐、無底座
- **WHEN** `stdout` 含 `(supports only)`
- **THEN** job 狀態為 `COMPLETED`，`hasSupportMesh` 為 true

#### Scenario: 支撐與底座皆有
- **WHEN** `stdout` 含 `(includes supports and pad)`
- **THEN** job 狀態為 `COMPLETED`，`hasSupportMesh` 為 true

---

### Requirement: 無法歸因者一律 fail-closed

當結果無法命中任何已知的成功、中性或失敗標記時，系統 SHALL 採 fail-closed：job 狀態 MUST 為 `FAILED`，`error_code` 為 `SUPPORT_GENERATION_FAILED`，並保留原始 `stdout` / `stderr`。系統 MUST NOT 在無正向證據時將未知情況推定為成功或中性。

#### Scenario: 寫檔失敗但 exit code 為 0
- **WHEN** `stderr` 含 `Failed to export support mesh`、無支撐 STL、且未命中任何正向標記
- **THEN** job 狀態為 `FAILED`，`error_code` 為 `SUPPORT_GENERATION_FAILED`
- **AND** 此情境 MUST NOT 被歸類為 `SUPPORT_NOT_NEEDED`

#### Scenario: 同時偵測到互斥標記
- **WHEN** `stdout` 同時含成功標記與 `SUPPORT_NOT_NEEDED` 標記（例如非預期的多物件輸出）
- **THEN** 系統走 fail-closed，job 狀態為 `FAILED`，`error_code` 為 `SUPPORT_GENERATION_FAILED`
- **AND** 系統 MUST NOT 任選其一標記作為權威結論

---

### Requirement: 狀態端點須回傳 error_code 與 supportOutcome

GET 狀態端點 SHALL 對失敗 job 回傳其具體 `error_code`，並對中性完成的 job 於 `COMPLETED` 回應中帶出 `supportOutcome`。這些欄位為向後相容的新增欄位，缺省時 MUST 維持既有行為。

#### Scenario: 失敗 job 回傳具體代碼
- **WHEN** 前端輪詢一個因 `SUPPORT_HEAD_TOO_WIDE` 失敗的 job
- **THEN** 回應為 `success: false`，`code` 為 `SUPPORT_HEAD_TOO_WIDE`

#### Scenario: 中性完成 job 帶出 supportOutcome
- **WHEN** 前端輪詢一個以 `SUPPORT_NOT_NEEDED` 完成的 job
- **THEN** 回應為 `COMPLETED`，含 `supportOutcome` 為 `SUPPORT_NOT_NEEDED`，`hasSupportMesh` 為 false

#### Scenario: 舊 job 缺欄位向後相容
- **WHEN** 讀取一個沒有 `error_code` / `supportOutcome` 欄位的既有 `status.json`
- **THEN** 失敗 job 缺 `error_code` 時回退為 `JOB_FAILED`，完成 job 缺 `supportOutcome` 時不顯示中性提示

---

### Requirement: validate 與 stdout 標記字串須有契約測試

由於分類完全依賴 CLI 的文字輸出，系統 SHALL 建立契約 / golden 測試，直接對 CLI 實際輸出的 validate 訊息與 stdout 標記字串進行斷言，使引擎改版或去識別化改寫改動這些字串時能被測試擋下。

#### Scenario: 標記字串變動被偵測
- **WHEN** CLI 的 stdout 標記（如 `(pad only)`）或 validate 訊息字串被更動
- **THEN** 契約測試失敗，提示分類對照表需同步更新