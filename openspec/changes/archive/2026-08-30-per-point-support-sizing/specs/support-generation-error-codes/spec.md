## ADDED Requirements

### Requirement: 支撐點與模型不一致須歸因為 SUPPORT_POINTS_MODEL_MISMATCH

當 CLI 輸出顯示傳入的支撐點清單與當前模型的指紋不符時，系統 SHALL 將 job 標為 `FAILED` 並回傳 `SUPPORT_POINTS_MODEL_MISMATCH`，`retryable` MUST 為 false。此歸因 SHALL 優先於 fail-closed 的 `SUPPORT_GENERATION_FAILED`，使呼叫端能區分「模型已變更」與「支撐生成本身失敗」這兩種本質不同的情況。

此錯誤不可重試的理由是：重試同一組輸入必然得到相同的指紋比對結果，唯一的解法是重新產生支撐點。

#### Scenario: 指紋不符歸因為專屬代碼
- **WHEN** CLI 輸出命中支撐點指紋不符的標記
- **THEN** job 狀態 SHALL 為 `FAILED`，`error_code` SHALL 為 `SUPPORT_POINTS_MODEL_MISMATCH`，`retryable` SHALL 為 false

#### Scenario: 不得落入 fail-closed 的泛用代碼
- **WHEN** CLI 輸出命中支撐點指紋不符的標記且未命中任何其他失敗標記
- **THEN** `error_code` MUST NOT 為 `SUPPORT_GENERATION_FAILED`

#### Scenario: 不得被誤判為中性成功
- **WHEN** CLI 因指紋不符而終止，因此未產出支撐 STL 也未輸出任何正向標記
- **THEN** 此情境 MUST NOT 被歸類為 `SUPPORT_NOT_NEEDED`
- **AND** `hasSupportMesh` SHALL 為 false

### Requirement: 指紋不符的標記須為不可翻譯的原始字串

CLI 用以宣告指紋不符的輸出標記 SHALL 為原始英文字串字面值，MUST NOT 包在 `_u8L()` 或 `I18N::translate` 之內。分類器對此標記的比對 SHALL 與既有標記一致地以英文子字串進行，且 MUST NOT 將 CLI 的 `returncode` 納入判定條件。

#### Scenario: 標記不隨語系改變
- **GIVEN** 引擎在非英文語系下執行
- **WHEN** 發生支撐點指紋不符
- **THEN** 輸出的標記字串 SHALL 與英文語系下完全相同
- **AND** 分類器 SHALL 仍能正確歸因

#### Scenario: 分類不依賴 exit code
- **WHEN** CLI 因指紋不符終止且 `returncode` 為 0
- **THEN** 分類器 SHALL 仍歸因為 `SUPPORT_POINTS_MODEL_MISMATCH`

### Requirement: 指紋不符標記須納入契約測試

指紋不符的標記字串 SHALL 納入既有的契約 / golden 測試，直接對 CLI 實際輸出進行斷言，使該字串被更動時能被測試擋下。

#### Scenario: 標記字串變動被偵測
- **WHEN** CLI 的指紋不符標記字串被更動
- **THEN** 契約測試 SHALL 失敗，並提示分類對照表需同步更新
