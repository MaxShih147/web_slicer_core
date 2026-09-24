## ADDED Requirements

### Requirement: 單一引擎規則表

系統 SHALL 以單一資料表 `ENGINE_RULES` 描述所有引擎輸出到 error code 的對應。支撐流程與切片流程 MUST 共用此表，MUST NOT 各自維護平行的對照表。

每一列 MUST 以 `code` 為主鍵，並攜帶 `flows`（`support` / `slice`，可多選）、`stream`（`stdout` / `stderr` / `both`）、`matchers`（比對器列表）、`priority`。

#### Scenario: 同一條引擎規則同時服務兩條流程

- **WHEN** 一條 validate 規則同時可能在產生支撐與切片時發生
- **THEN** 該規則在表上 MUST 只出現一次，`flows` 標記為兩者
- **AND** 兩條流程對同一段 stderr 的分類結果 MUST 為同一個 code

#### Scenario: 新增一條引擎規則

- **WHEN** 開發者在 `ENGINE_RULES` 新增一列並標記 `flows`
- **THEN** 兩條流程立即依 `flows` 生效，無需在第二處登記

### Requirement: 比對器分層且可擴充

`matchers` SHALL 為有序列表，比對時依序嘗試，第一個命中者勝出。系統 MUST 支援在列表前端插入新型別的比對器，而不改變規則列的其他欄位。

#### Scenario: 舊版引擎仍可分類

- **WHEN** 引擎輸出不含結構化 code、只有英文字串
- **THEN** 字串比對器仍能命中並回傳正確 code

#### Scenario: 新增比對器型別

- **WHEN** 未來新增一種比對器並插入 `matchers` 前端
- **THEN** 規則的 `code`、`flows`、`stream` 欄位 MUST NOT 需要修改

### Requirement: 分類不得依賴 CLI exit code

`ENGINE_RULES` 的資料結構 MUST NOT 包含 `exit_code` 欄位。分類 SHALL 只依據輸出文字、串流別與流程別。

`exit_code` 僅保留一個用途：判斷引擎是否被訊號殺死。`output_file_exists` 為可信訊號，SHALL 保留使用。

#### Scenario: 相同輸出、不同 exit code

- **WHEN** 同一組 stdout 與 stderr，`exit_code` 分別為 0 與 1
- **THEN** 分類結果 MUST 完全相同

#### Scenario: 尚未拆解的歷史相依

- **WHEN** 某個 code 目前仍依賴 `exit_code == 0` 判定
- **THEN** 該相依 MUST 隔離在呼叫端具名的 legacy 分支中，MUST NOT 出現在規則表
- **AND** 該分支 MUST 附註解說明存在原因與可移除的條件

### Requirement: 刻意歸 fallback 須顯式標記

被歸入 fallback code 的已知引擎訊息 SHALL 在規則表上以顯式旗標標記，MUST NOT 以「不出現在表上」的方式表達。

#### Scenario: 已知但無專屬 code 的訊息

- **WHEN** `stderr` 含 `Disabling the 'Use tilt' function`
- **THEN** 分類結果為 fallback code
- **AND** 該訊息在規則表上以 `fallback_by_design` 標記，可與「漏登記」區分

### Requirement: 舊分類器介面須維持相容

`classify_support_result()` 與 `classify_slice_result()` 的函式簽名、回傳型別與欄位語意 SHALL 完全不變，僅內部改為查詢 `ENGINE_RULES`。

#### Scenario: 既有測試零修改通過

- **WHEN** 執行 `test_support_classifier.py` 與 `test_slicing_classifier.py`
- **THEN** 兩支測試 MUST 在未修改任何一行的情況下全數通過

### Requirement: 規則字串須納入契約測試

`ENGINE_RULES` 中每一條字串比對器的字串 SHALL 存在於 `third_party/prusaslicer_fork` 原始碼中。

#### Scenario: 新增規則但字串抄錯

- **WHEN** 新增一條規則，其字串在引擎原始碼中不存在
- **THEN** 契約測試 MUST 失敗，而非讓規則靜默永不命中
