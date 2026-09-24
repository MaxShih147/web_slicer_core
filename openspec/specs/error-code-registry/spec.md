# error-code-registry Specification

## Purpose
TBD - created by archiving change unify-error-code-registry. Update Purpose after archive.
## Requirements
### Requirement: Error code 單一真值來源

系統 SHALL 以 `agent/error_codes.py` 作為所有後端 error code 的唯一真值。每一個 code MUST 恰好在此檔宣告一次，並攜帶 `code`、`http_status`、`retryable`、`owner`、`note` 五個必填欄位；`owner` 為 `engine` 者 MUST 另外攜帶 `engine_needles`。

任何其他位置（`errors.py`、`api_v2.py`、文件、測試）MUST NOT 重新宣告 code 清單。

#### Scenario: 新增一個 error code

- **WHEN** 開發者在 `error_codes.py` 新增一筆記錄
- **THEN** `err_code_spec.md` 與 `error_codes.json` 在執行 `--write` 後同時出現該 code
- **AND** 若 `errors.py` 沒有對應 factory，契約測試 MUST 失敗

#### Scenario: 在別處私自宣告 code

- **WHEN** `api_v2.py` 出現一個不在登錄檔中的 code 字串
- **THEN** 契約測試 MUST 失敗並指出該 code 未登錄

#### Scenario: owner 為 engine 的 code 缺少引擎字串

- **WHEN** 一筆記錄的 `owner` 為 `engine` 但 `engine_needles` 為空
- **THEN** 登錄檔載入 MUST 直接拋錯，不允許進入 runtime

### Requirement: 衍生文件自動產生

系統 SHALL 提供 `agent/tools/error_codes.py`，以 `--write` 由登錄檔產生 `docs/err_code_spec.md` 與 `docs/error_codes.json`。兩份產出物 MUST NOT 被手動編輯，且 MUST 在檔案開頭標明自動產生與真值位置。

`error_codes.json` MUST 包含每個 code 的 `code`、`http_status`、`retryable`、`owner`、`note`，供跨 repo 對帳使用。

#### Scenario: 執行 --write

- **WHEN** 開發者執行 `python -m agent.tools.error_codes --write`
- **THEN** 兩份產出物被覆寫，內容與登錄檔一致
- **AND** 產出物開頭含「本檔自動產生，請勿手動編輯」標頭

#### Scenario: 說明文字只在登錄檔維護

- **WHEN** 開發者需要修改某個 code 的中文說明
- **THEN** 該說明 MUST 改在 `error_codes.py` 的 `note` 欄位
- **AND** 直接編輯 `err_code_spec.md` 的改動會在下次 `--write` 被覆蓋

### Requirement: 產出物過期即失敗

系統 SHALL 提供 `--check` 模式：不寫檔，只比對產出物與登錄檔是否一致。不一致時 MUST 以非零狀態碼結束，並指出應執行 `--write`。

`--check` MUST 可掛在本地 pipeline 或 pre-commit。

#### Scenario: 改了登錄檔但忘記產生

- **WHEN** 開發者修改 `error_codes.py` 後未執行 `--write`，接著執行 `--check`
- **THEN** 指令回非零
- **AND** 訊息指出哪些產出物過期，以及應執行的指令

#### Scenario: 產出物與登錄檔一致

- **WHEN** 產出物為最新，執行 `--check`
- **THEN** 指令回零，且不修改任何檔案

### Requirement: Error code 依產生者分群

系統 SHALL 為每個 error code 標記 `owner`：`engine` 代表引擎在自身 process 內即可判斷；`python` 代表需要 job、檔案系統或 HTTP 上下文才能判斷。

分群 MUST 覆蓋全部 28 個 code，且 MUST NOT 有第三種值。

#### Scenario: 判定一個新 code 的 owner

- **WHEN** 新增的 code 需要讀取 job 目錄或 HTTP 請求內容才能判斷
- **THEN** 其 `owner` MUST 為 `python`

#### Scenario: 引擎群的 code 可被獨立篩選

- **WHEN** 後續工作需要「引擎應該自行回報的 code 清單」
- **THEN** 系統 MUST 能由登錄檔篩出 `owner == "engine"` 的完整子集，無需人工判讀

### Requirement: API 錯誤工廠由登錄檔推導

`api_v2.py` 的 code 對應 factory SHALL 於執行期由登錄檔推導，MUST NOT 維護手抄的對照 dict。推導不到 factory 的 code MUST 在載入階段即失敗，而非在請求發生時才退回 `JOB_FAILED`。

#### Scenario: 既有錯誤回應不變

- **WHEN** 一個 job 以 `error_code = "SUPPORT_HEAD_TOO_WIDE"` 失敗
- **THEN** HTTP 回應的 `code`、`http_status`、`retryable` 與本變更前完全相同

#### Scenario: 登錄檔有 code 但 errors.py 缺 factory

- **WHEN** 登錄檔新增一個 code，而 `errors.py` 尚未提供對應 factory
- **THEN** 契約測試 MUST 失敗
- **AND** 系統 MUST NOT 靜默退回 `JOB_FAILED`

### Requirement: 引擎字串契約

對每個 `owner == "engine"` 的 code，其 `engine_needles` 中的每一條英文字串 SHALL 仍存在於 `third_party/prusaslicer_fork` 的原始碼中。

#### Scenario: 引擎改寫了訊息字串

- **WHEN** 上游或去識別化改寫了某條 validate 訊息
- **THEN** 契約測試 MUST 失敗並指出該 code 與失效的字串

#### Scenario: fork submodule 未 checkout

- **WHEN** `third_party/prusaslicer_fork` 未取出
- **THEN** 契約測試 MUST 跳過（skip）而非失敗

