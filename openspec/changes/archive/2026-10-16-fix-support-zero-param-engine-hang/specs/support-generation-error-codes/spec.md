## ADDED Requirements

### Requirement: 支撐生成引擎逾時須終止並以 SUPPORT_GENERATION_FAILED 回報

支撐生成（`generate-supports` 觸發的 support-only CLI 命令）的引擎子程序 SHALL 有 120 秒的執行上限。超過上限時：

- 系統 SHALL 強制終止該子程序，並等待它結束、回收其輸出管線，MUST NOT 留下仍在執行的引擎程序。
- 若程序在判定逾時與終止之間已自行結束，系統 MUST NOT 因此拋出例外。
- job 狀態 SHALL 為 `FAILED`，`error_code` 為 `SUPPORT_GENERATION_FAILED`，錯誤訊息 MUST 說明引擎因超過時限而被終止。
- 終止前已取得的 `stdout` 與 `stderr` SHALL 寫入 job 的 log，且 log 中 MUST 註明引擎是被 agent 終止的。
- 這次終止 MUST NOT 被當成引擎當機通報給 Launcher。
- 該 job 結束後，引擎佇列 SHALL 立即可以執行下一個工作。

逾時上限 SHALL 只套用在支撐生成。切片、鏤空、切割、匯出支撐點，以及其他執行 CLI 的流程 MUST NOT 被加上逾時，其行為 SHALL 與本變更前完全相同。

本 agent 行程被取消（例如伺服器關閉）而支撐生成仍在執行時，系統 SHALL 一併終止該引擎子程序。

#### Scenario: 引擎卡住超過 120 秒
- **GIVEN** 支撐生成的引擎子程序一直沒有結束
- **WHEN** 從子程序啟動起算超過 120 秒
- **THEN** 該子程序被終止，且系統等待它結束後才繼續
- **AND** job 狀態為 `FAILED`，`error_code` 為 `SUPPORT_GENERATION_FAILED`
- **AND** 錯誤訊息說明引擎因超過時限而被終止

#### Scenario: 後續工作不再被卡住
- **GIVEN** 工作 A 的支撐生成引擎卡住，工作 B 的支撐生成已送出並在佇列中等待
- **WHEN** 工作 A 的引擎因逾時被終止
- **THEN** 工作 A 為 `FAILED`
- **AND** 工作 B 接著開始執行，並依它自己的結果完成
- **AND** 任何時刻同時執行中的引擎工作 MUST NOT 超過一個

#### Scenario: 時限內完成不受影響
- **WHEN** 支撐生成的引擎在 120 秒內結束
- **THEN** 結果分類、job 狀態、log 內容與本變更前完全相同

#### Scenario: 程序剛好在終止前自行結束
- **GIVEN** 逾時已被判定，但引擎在系統送出終止指令前剛好自行結束
- **WHEN** 系統嘗試終止它
- **THEN** 系統 MUST NOT 拋出例外
- **AND** job 仍依逾時的規則標記為 `FAILED`、`SUPPORT_GENERATION_FAILED`

#### Scenario: 逾時的 log 可供除錯
- **WHEN** 支撐生成因逾時被終止
- **THEN** job 的 stderr log 末尾含一行說明引擎被 agent 在 120 秒後終止
- **AND** 終止前已取得的輸出也在 log 中

#### Scenario: 不誤報為當機
- **GIVEN** Launcher 的當機測試模式已開啟
- **WHEN** 支撐生成因逾時被終止
- **THEN** 系統 MUST NOT 寫出引擎當機的通知檔

#### Scenario: 其他 CLI 流程不加逾時
- **WHEN** 鏤空、切割、匯出支撐點或切片的引擎執行超過 120 秒
- **THEN** 系統 MUST NOT 終止它，繼續等待它自行結束
