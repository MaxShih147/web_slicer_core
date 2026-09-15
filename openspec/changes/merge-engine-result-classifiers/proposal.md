## Why

`support_classifier.py` 與 `slicing_classifier.py` 的**結構完全相同**：一張「(英文字串, error code)」的表，由上往下第一個命中的贏。差別只有三點——切片版多了「輸出檔存不存在」條件、支撐版多了成功標記的正面判斷、兩張表的列不一樣。

**列不一樣正是問題。** 同一條引擎規則要登記兩次，而且已經各漏一次：支撐路徑不認得 `Pad brim size is too small`（退化成通用的支撐失敗），切片路徑不認得 `Cannot proceed without support points`（退化成 `JOB_FAILED`）。這不是巧合，是兩張平行表複製貼上的必然結果。

底墊與手動支撐參數開放後，這兩條規則從「今天踩不到」變成「最容易踩到」。

此外，`INVALID_MODEL` 與 `MODEL_OUT_OF_BOUNDS` 目前只掛在切片版的 Path B（exit code 為 0 的那條路）。引擎有 15 處 `return 1` 寫在 `bool` 函式裡，未來修正後 exit code 會變成 1，這兩個 code 會立刻退化成 `JOB_FAILED`。**這是未爆彈，要在動 C++ 之前拆掉結構相依。**

## What Changes

- 新增 `agent/engine_rules.py`：一張 `ENGINE_RULES`。每列以 **error code 為主鍵**，欄位為 `flows`（`support` / `slice`，可多選）、`stream`（`stdout` / `stderr` / `both`）、`matchers`（比對器**列表**，今天只有 `Substring`）、`priority`。
  - **`exit_code` 不是規則表的欄位。** 離開代碼只保留一個用途：判斷引擎是否被訊號殺死。
  - `matchers` 設計成列表而非單一字串，是為了讓後續 `engine-error-code-table`（C++ 出 code）能在最前面插一層 `EngineCode` 比對器，而不需要改變表的形狀。
- `support_classifier.py`、`slicing_classifier.py` 改為**薄殼**：只保留公開函式簽名，內部轉呼 `ENGINE_RULES`。既有測試零修改通過即為相容性證明。
- 補四條漏列：
  - 支撐路徑加 `PAD_CONFIG_INVALID`（`Pad brim size is too small`）
  - 切片路徑加 `SUPPORT_POINTS_REQUIRED`（`Cannot proceed without support points`）
  - 新增 `SUPPORT_POINT_SAMPLING_FAILED`（`SLA support point generator has failed.`）
  - 新增 `SHRINKAGE_COMPENSATION_INVALID`（`the object transform is not invertible`；收縮補償為 0）
- `Disabling the 'Use tilt' function` 在表上明確標成「已知但刻意歸 fallback」，讓「漏登記」與「刻意歸類」在資料上分得開。
- `sla_operations.py` 的 `generate_hollow` 與 `cut` 改為攜帶引擎原始 stderr，罐頭訊息只當後備。
- `INVALID_MODEL` / `MODEL_OUT_OF_BOUNDS` 的 exit-code 相依留在**呼叫端**的具名 legacy 分支（本單不改行為），並附一支記錄現況的測試。後續 change 刪掉該分支即可。
- 新增 `test_exit_code_independence.py`：同一組 stdout/stderr，exit code 分別餵 0 與 1，分類結果必須完全相同。此測試是後續 C++ 改動的安全網。

## Capabilities

### New Capabilities

- `engine-result-classification`：單一規則表如何分類引擎執行結果、規則的擁有欄位、比對器的分層順序、以及「分類不得依賴離開代碼」的不變量。

### Modified Capabilities

- `support-generation-error-codes`：支撐路徑新增 `PAD_CONFIG_INVALID`、`SUPPORT_POINT_SAMPLING_FAILED`、`SHRINKAGE_COMPENSATION_INVALID` 三個可回傳的 code。
- `slicing-error-codes`：切片路徑新增 `SUPPORT_POINTS_REQUIRED`、`SUPPORT_POINT_SAMPLING_FAILED`、`SHRINKAGE_COMPENSATION_INVALID` 三個可回傳的 code；挖空與切割改帶引擎原文。

## Impact

| 對象 | 影響 |
|---|---|
| `agent/engine_rules.py` | 新檔 |
| `agent/support_classifier.py` | 改薄殼，公開簽名不變 |
| `agent/slicing_classifier.py` | 改薄殼，公開簽名不變 |
| `agent/sla_operations.py` | 挖空／切割改帶原始 stderr |
| `agent/error_codes.py` | 新增 2 個 code（來自 `unify-error-code-registry`） |
| `agent/tests/` | 新增 `test_exit_code_independence.py`；既有兩支 classifier 測試**不得修改** |
| DS-Online | 需補 2 個新 code 的 i18n（由 `open-support-param-panel` 承接） |

**前置條件**：`unify-error-code-registry` 必須先完成——新增的兩個 code 要進登錄檔，`--check` 才擋得住漏補 i18n。
