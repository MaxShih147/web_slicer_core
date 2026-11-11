## ADDED Requirements

### Requirement: agent 啟動時對自身關閉 EcoQoS 執行速度節流

agent 程序啟動時（FastAPI lifespan 開始處理請求之前）SHALL 在 Windows 上對自身程序呼叫 `SetProcessInformation(hProcess, ProcessPowerThrottling, PROCESS_POWER_THROTTLING_STATE)`，其中 `Version = PROCESS_POWER_THROTTLING_CURRENT_VERSION`、`ControlMask = PROCESS_POWER_THROTTLING_EXECUTION_SPEED`、`StateMask = 0`，明確關閉執行速度節流（不是交回系統自動決定）。

#### Scenario: Windows 上啟動時設定一次
- **WHEN** agent 在 Windows 上啟動
- **THEN** 系統 SHALL 以目前程序的 handle 呼叫一次 `SetProcessInformation`，參數為 `ProcessPowerThrottling`、`ControlMask = PROCESS_POWER_THROTTLING_EXECUTION_SPEED`、`StateMask = 0`
- **AND** 成功時 SHALL 記一筆 INFO log，註明對象為 agent 自身

#### Scenario: 非 Windows 平台不呼叫
- **WHEN** agent 在非 Windows 平台啟動
- **THEN** 系統 MUST NOT 載入 `kernel32` 或呼叫任何 Win32 API，且 SHALL 不記錄任何 WARNING

### Requirement: 每次啟動 slicer-engine 子程序後對子程序關閉 EcoQoS 執行速度節流

agent 每次以 `asyncio.create_subprocess_exec` 啟動 slicer-engine 後，SHALL 在 Windows 上對該子程序以同樣參數呼叫 `SetProcessInformation`。是否由父程序繼承未經驗證，因此 agent 自身與子程序 SHALL 都設定。此要求涵蓋 agent 內所有啟動 slicer-engine 的位置：`jobs.run_slicing`、`jobs` 的 3MF 匯出、`sla_operations.run_prusa_cli`（支撐、挖空、切割、支撐點匯出等所有經由它的操作）。

設定 SHALL 在子程序啟動後、等待其輸出之前進行，且 MUST NOT 延遲或改變子程序的 stdout／stderr 讀取、逾時與終止行為。

#### Scenario: 切片啟動引擎後設定子程序
- **WHEN** `run_slicing` 在 Windows 上啟動 slicer-engine
- **THEN** 系統 SHALL 以該子程序的 PID 開啟 handle（`PROCESS_SET_INFORMATION` 權限）並呼叫 `SetProcessInformation` 關閉執行速度節流
- **AND** SHALL 關閉所開啟的 handle

#### Scenario: run_prusa_cli 啟動引擎後設定子程序
- **WHEN** 任何操作經由 `run_prusa_cli` 在 Windows 上啟動 slicer-engine
- **THEN** 系統 SHALL 對該子程序關閉執行速度節流，之後才開始讀取其輸出

#### Scenario: 子程序已結束
- **WHEN** 子程序在設定前已結束，導致開啟 handle 或呼叫失敗
- **THEN** 系統 SHALL 只記 log，任務結果 SHALL 與未設定節流時相同

### Requirement: 節流設定失敗不得影響 agent 與任務

關閉節流屬最佳努力（best effort）。任何失敗——包含 `ctypes` 無法載入、Windows 版本不支援 `ProcessPowerThrottling`（Windows 10 1709 之前）、`OpenProcess` 或 `SetProcessInformation` 回傳失敗、或任何例外——SHALL 只記一筆 WARNING log（含 Win32 錯誤碼），MUST NOT 拋出例外、MUST NOT 讓 agent 啟動失敗、MUST NOT 讓任務失敗或改變任務的錯誤碼。

#### Scenario: Win32 呼叫回傳失敗
- **WHEN** `SetProcessInformation` 回傳 0
- **THEN** 系統 SHALL 記一筆 WARNING，內容含 `GetLastError()` 的值與對象（agent 自身或子程序 PID）
- **AND** 呼叫端 SHALL 照常繼續

#### Scenario: 呼叫過程拋出例外
- **WHEN** 載入 `kernel32` 或呼叫 Win32 API 時拋出任何例外
- **THEN** 該例外 SHALL 在節流模組內被攔下並記 WARNING，MUST NOT 傳遞到 lifespan 或引擎啟動的呼叫端
