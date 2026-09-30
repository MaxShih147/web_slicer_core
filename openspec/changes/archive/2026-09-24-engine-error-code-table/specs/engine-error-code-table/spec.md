## ADDED Requirements

### Requirement: 引擎持有 error code 對照表

切片引擎 SHALL 持有一張 `code → message` 的對照表，涵蓋所有 `owner=engine` 的錯誤代號。該表 SHALL 為引擎側代號清單的唯一真值。

message SHALL 只用於 log 與 CLI 使用者，MUST NOT 作為傳遞給 Python 或前端的人類可讀文案。

#### Scenario: 引擎新增一個錯誤情境
- **WHEN** 引擎新增一條失敗路徑
- **THEN** 該路徑的代號 MUST 先登錄於引擎對照表
- **AND** 對帳契約測試 MUST 要求 Python 登錄檔同步新增

#### Scenario: message 不上前端
- **WHEN** 引擎回報一個失敗
- **THEN** 使用者看到的文案 SHALL 來自前端四語系
- **AND** 引擎的英文 message MUST NOT 出現在 UI

### Requirement: 引擎以結構化單行回報失敗

引擎失敗時 SHALL 在 **stdout** 輸出一行 `PHZ_ERROR ` 前綴加 JSON 的結構化錯誤行。

JSON MUST 含 `code`；MAY 含 `fields`（後端 `SLAConfig` 的 snake_case 欄位名）與 `values`（動態門檻與實際值）。

#### Scenario: 底墊參數違規
- **WHEN** `PadConfig::validate()` 因外擴不足而失敗
- **THEN** stdout 含 `PHZ_ERROR` 行，`code` 為 `PAD_CONFIG_INVALID`
- **AND** `fields` 含 `pad_wall_slope`、`pad_brim_size`、`pad_wall_thickness`
- **AND** `values` 含當下算出的最小合法角度與實際值

#### Scenario: 輸出到 stdout 而非 stderr
- **WHEN** 任何結構化錯誤行被輸出
- **THEN** 它 MUST 出現在 stdout
- **AND** MUST NOT 只出現在 stderr

#### Scenario: 欄位命名不需轉換
- **WHEN** 前端收到 `fields`
- **THEN** 其值 MUST 可直接對應面板的 `data-field` 屬性，無需命名轉換

### Requirement: Python 優先讀取引擎代號

`ENGINE_RULES` 每列的 `matchers` SHALL 以 `EngineCode` 比對器為首、字串比對器為次。命中 `EngineCode` 時 SHALL 直接採用該代號。

本變更 MUST NOT 移除字串比對層。

#### Scenario: 新引擎輸出代號
- **WHEN** 輸出含 `PHZ_ERROR` 行且代號已登錄
- **THEN** 分類結果採用該代號
- **AND** 不再比對英文字串

#### Scenario: 舊引擎只有英文字串
- **WHEN** 輸出不含 `PHZ_ERROR` 行
- **THEN** 字串比對層 MUST 仍能命中並回傳正確代號

#### Scenario: 兩層結果須一致
- **WHEN** 同一個失敗情境分別由新引擎與舊引擎產生輸出
- **THEN** 兩者的分類結果 MUST 為同一個代號

### Requirement: 引擎回報的數值須送達前端

當分類出的代號就是引擎在 `PHZ_ERROR` 行宣告的代號時，系統 SHALL 把該行的 `fields` 與 `values` 原樣存進 job 狀態，並在 job 狀態端點的失敗回應 `data` 中帶出。分類出的代號與引擎宣告的不同時（例如字串層命中、或引擎代號未登錄而退回 fallback），MUST NOT 帶出這兩欄。

前端 SHALL 在數值齊全時顯示帶數值的文案；數值不全或沒有數值時 SHALL 顯示該代號原本的固定文案，MUST NOT 顯示未替換的參數佔位字。

#### Scenario: 底墊角度不足
- **WHEN** 一個 job（支撐生成或切片）因 `PAD_CONFIG_INVALID` 失敗，引擎回報 `min_pad_wall_slope` 51.4、`pad_wall_slope` 50
- **THEN** job 狀態端點的失敗回應 `data.values` 含這兩個值，`data.fields` 含 `pad_wall_slope`、`pad_wall_thickness`、`pad_brim_size`
- **AND** 切片失敗的 toast 與卡片顯示的訊息含 `51.4°`

（前端目前的切片流程會先把支撐烘焙進模型、以 `supports_enable=0`／`pad_enable=0` 切片，底墊參數到不了引擎。四個帶數值的代號裡，切片流程可能實際碰到的是曝光時間（它是切片參數），此情境未實測。支撐生成失敗的 toast 不在本變更範圍。）

#### Scenario: 舊版引擎沒有數值
- **WHEN** 同一個失敗由不輸出 `PHZ_ERROR` 行的引擎產生
- **THEN** 失敗回應不帶 `fields`／`values`
- **AND** 前端顯示該代號原本的固定文案

#### Scenario: 舊的 job 狀態檔
- **WHEN** 讀取一個沒有 `error_fields`／`error_values` 的既有 `status.json`
- **THEN** 讀取 MUST 成功，兩欄視為沒有

### Requirement: 未登錄的引擎代號須退回 fallback

當引擎輸出的代號不存在於 `agent/error_codes.py` 登錄檔時，系統 SHALL 退回 fallback 代號，MUST NOT 將未登錄的代號原封不動傳給前端。

#### Scenario: 引擎比 Python 新
- **WHEN** 引擎輸出一個 Python 登錄檔沒有的代號
- **THEN** 分類結果為 fallback
- **AND** 原始輸出保留於 `detail` 供除錯

### Requirement: 兩側代號清單須對帳

引擎的代號清單 SHALL 可匯出為機器可讀格式。契約測試 SHALL 逐項比對引擎清單與 `agent/error_codes.py` 中 `owner=engine` 的子集。

#### Scenario: 引擎新增代號但 Python 未跟進
- **WHEN** 引擎清單含一個 Python 登錄檔沒有的代號
- **THEN** 契約測試 MUST 失敗並指出該代號

#### Scenario: Python 標為 engine 但引擎沒有
- **WHEN** Python 登錄檔有一個 `owner=engine` 的代號，引擎清單沒有
- **THEN** 契約測試 MUST 失敗

### Requirement: 建置成果與版控指標須一致

打包進 bundle 的引擎 binary、實際建置所用的 fork commit、以及 superproject 記錄的 submodule 指標，三者 SHALL 指向同一個 commit。

submodule 指標的更新 MUST 與依賴它的 Python 改動落在同一個 commit 或 PR。

#### Scenario: 交付前的一致性驗證
- **WHEN** 準備關單
- **THEN** `git submodule status` 的 commit、fork 的 `git rev-parse HEAD`、`slicer-engine/source-chain.json` 記載的 commit MUST 相同

#### Scenario: 指標與 Python 改動分批進
- **WHEN** 有人只更新 Python 而未同批更新 submodule 指標
- **THEN** 其他人的契約測試會對舊 fork code 執行並誤判通過
- **AND** 此情形 MUST 由 review 擋下

### Requirement: 供應鏈紀錄須與 binary 同步

更換 `slicer-engine/bin/` 底下的執行檔時，SHALL 同步更新 `engine_build_id.txt`、`artifact-manifest.json`、`engine-artifact-manifest.json`、`sbom.spdx.json`、`source-chain.json`、`scan-report.json`。

#### Scenario: 只換執行檔
- **WHEN** 有人只替換 binary 而未更新紀錄
- **THEN** 稽核紀錄與實物不符，MUST 由交付檢查擋下
