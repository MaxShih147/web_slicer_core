# support-point-api Specification

## Purpose
定義後端 agent 對支撐點清單的查詢與傳遞契約：匯出流程強制啟用支撐、檔案落地於 job 目錄慣例（輸入 `input/`、輸出 `output/`）、回傳內容須為底層 JSON 原文且後端不得補值或改寫、指紋不符時的錯誤回報，以及未使用本介面的既有流程行為不變。

## Requirements

### Requirement: 後端須能回傳底層計算出的支撐點清單

後端 SHALL 提供一條途徑，使呼叫端可取得底層針對指定模型計算出的支撐點清單。回傳內容 SHALL 為底層匯出的完整 JSON，含 `version`、`model_fingerprint` 與 `points`，後端 MUST NOT 對其中的座標或尺寸值做任何改寫。

#### Scenario: 成功取得支撐點清單
- **GIVEN** 一個已上傳模型的 job
- **WHEN** 呼叫端請求計算支撐點
- **THEN** 回應 SHALL 含支撐點清單
- **AND** 清單中每個點的七個尺寸欄位 SHALL 皆為非負具體值

#### Scenario: 後端不改寫底層輸出
- **WHEN** 比對後端回傳的內容與底層寫出的 JSON 檔
- **THEN** `points` 陣列中每個點的座標與尺寸值 SHALL 逐一相等
- **AND** `model_fingerprint` SHALL 完全相同

### Requirement: 後端須能接受自訂支撐點清單並轉交底層

後端 SHALL 允許呼叫端在支撐生成與切片流程中提供一份自訂支撐點清單。後端 SHALL 將其落地為檔案並以 `--import-support-points` 傳給底層，MUST NOT 對內容做語意上的修改或補值（補預設值是底層的職責）。

#### Scenario: 自訂點清單影響支撐生成
- **GIVEN** 一份將某點 `head_back_radius_mm` 設為 0.9 的支撐點清單
- **WHEN** 呼叫端帶著該清單觸發支撐生成
- **THEN** 產生的支撐網格中該點對應的支撐柱半徑 SHALL 為 0.9 mm

#### Scenario: 後端不補值
- **GIVEN** 一份某點僅含 `pos` 與 `type` 的支撐點清單
- **WHEN** 後端落地該清單為檔案
- **THEN** 落地檔案中該點 MUST NOT 出現呼叫端未提供的尺寸 key

### Requirement: 支撐點檔案須落地於既有的 job 目錄慣例

呼叫端提供的支撐點清單 SHALL 落地於 job 目錄的 `input/` 之下（與 `support.stl` 同層）；底層匯出的支撐點清單 SHALL 落地於 `output/` 之下（與 `model_support.stl` 同層）。

#### Scenario: 輸入檔案位置
- **WHEN** 呼叫端提供支撐點清單並觸發執行
- **THEN** 該清單 SHALL 存在於該 job 的 `input/` 目錄下

#### Scenario: 輸出檔案位置
- **WHEN** 支撐點匯出成功
- **THEN** 匯出的 JSON SHALL 存在於該 job 的 `output/` 目錄下

### Requirement: 支撐點匯出流程須強制啟用支撐

後端在組裝支撐點匯出的 CLI 指令時 SHALL 強制 `supports_enable` 為真。底層在支撐停用時會直接跳過支撐點計算步驟，若不強制開啟將靜默產出空清單。

#### Scenario: 呼叫端未啟用支撐仍能匯出
- **GIVEN** 呼叫端傳入的設定中 `supports_enable` 為假
- **WHEN** 觸發支撐點匯出
- **THEN** 後端 SHALL 在傳給底層的設定中將其覆寫為真
- **AND** 匯出的清單 SHALL 含實際計算出的支撐點

### Requirement: 指紋不符須以 SUPPORT_POINTS_MODEL_MISMATCH 回報

當底層因指紋不符而拒絕時，後端 SHALL 將該 job 標為失敗並回傳 `SUPPORT_POINTS_MODEL_MISMATCH`。此錯誤 SHALL 為不可重試（`retryable` 為 false），因為重試同一組輸入必然得到相同結果。錯誤訊息 SHALL 足以讓呼叫端理解需重新產生支撐點。

#### Scenario: 指紋不符的 job 回傳專屬錯誤碼
- **GIVEN** 呼叫端提供的支撐點清單與當前模型不一致
- **WHEN** 觸發支撐生成或切片
- **THEN** job 狀態 SHALL 為 `FAILED`
- **AND** `error_code` SHALL 為 `SUPPORT_POINTS_MODEL_MISMATCH`
- **AND** `retryable` SHALL 為 false

#### Scenario: 不得誤歸類為一般支撐失敗
- **GIVEN** 同上情境
- **WHEN** 檢視回傳的錯誤碼
- **THEN** 該情境 MUST NOT 被歸類為 `SUPPORT_GENERATION_FAILED`
- **AND** MUST NOT 被歸類為 `SUPPORT_NOT_NEEDED`

### Requirement: 未使用支撐點介面的既有流程行為不變

當呼叫端未提供支撐點清單、亦未請求支撐點匯出時，後端 SHALL 完全依既有流程運作。本能力 MUST NOT 改變既有的支撐生成、切片、匯入支撐網格等路徑的任何可觀測行為。

#### Scenario: 既有支撐生成流程不受影響
- **GIVEN** 一個不使用任何支撐點介面的既有支撐生成請求
- **WHEN** 執行該請求
- **THEN** 產生的支撐網格 SHALL 與本變更前完全一致
- **AND** 回傳的 `supportOutcome` 與 `hasSupportMesh` SHALL 與本變更前一致

#### Scenario: 匯入支撐網格流程不受影響
- **GIVEN** 一個使用 `--import-support-stl` 路徑的既有切片請求
- **WHEN** 執行該請求
- **THEN** 產生的 `.sl1` SHALL 與本變更前逐層位元一致
