## MODIFIED Requirements

### Requirement: 分類不得依賴 CLI exit code

`ENGINE_RULES` 的資料結構 MUST NOT 包含 `exit_code` 欄位。分類 SHALL 只依據輸出文字、串流別與流程別。

`exit_code` 僅保留一個用途：判斷引擎是否被訊號殺死。`output_file_exists` 為可信訊號，SHALL 保留使用。

**本變更移除最後一處歷史相依**：`_LEGACY_EXIT0_ONLY_CODES` 分支刪除後，MUST NOT 有任何代號需要 `exit_code == 0` 才能判定。

#### Scenario: 相同輸出、不同 exit code

- **WHEN** 同一組 stdout 與 stderr，`exit_code` 分別為 0 與 1
- **THEN** 分類結果 MUST 完全相同

#### Scenario: legacy 分支已移除

- **WHEN** 檢視 `slicing_classifier.py`
- **THEN** MUST NOT 存在 `_LEGACY_EXIT0_ONLY_CODES` 或任何等效的 exit-code 條件分支

#### Scenario: 安全網測試轉為正常斷言

- **WHEN** 執行 `test_exit_code_independence.py`
- **THEN** `INVALID_MODEL` 與 `MODEL_OUT_OF_BOUNDS` 兩例 MUST 以正常斷言通過
- **AND** MUST NOT 再標記為 `xfail`

### Requirement: 比對器分層且可擴充

`matchers` SHALL 為有序列表，比對時依序嘗試，第一個命中者勝出。系統 MUST 支援在列表前端插入新型別的比對器，而不改變規則列的其他欄位。

**本變更新增 `EngineCode` 型別並置於列表最前**，字串比對降為第二層。規則列的 `code`、`flows`、`stream` 欄位 MUST NOT 因此修改。

#### Scenario: 舊版引擎仍可分類

- **WHEN** 引擎輸出不含結構化 code、只有英文字串
- **THEN** 字串比對器仍能命中並回傳正確 code

#### Scenario: 新增比對器型別

- **WHEN** `EngineCode` 插入 `matchers` 前端
- **THEN** 規則的 `code`、`flows`、`stream` 欄位 MUST NOT 需要修改
- **AND** 既有規則測試 MUST 零修改通過
