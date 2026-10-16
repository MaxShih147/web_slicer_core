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

### Requirement: 自訂支撐點的底座半徑不可為零

`POST /api/v2/slices/{job_id}/support-points` SHALL 在收下支撐點清單之前，逐點檢查 `base_radius_mm`。

- 若某點的 `base_radius_mm` 是數值，且 `0 <= base_radius_mm`、又小於 `1e-4` 的單精度浮點值（`9.999999747378752e-05`），該點 SHALL 被視為不合法。這個範圍包含 `0`、`-0.0`，以及讀進底層單精度浮點後會變成 0 的極小正數（例如 `1e-50`）。
- 門檻以單精度為界，是因為引擎把匯入的 `base_radius_mm` 存成單精度浮點，之後匯出時寫的是單精度值；半徑剛好 `1e-4` 的點，再匯出一次會變成 `9.999999747378752e-05`。引擎匯出的半徑（第一次匯出的雙精度值與之後匯出的單精度值）SHALL 都能原樣送回而被接受。
- 負數 SHALL 被接受。負數代表「沿用全域 Base Diameter」，是合法值。
- 缺少 `base_radius_mm` 的點 SHALL 被接受，同樣代表沿用全域設定。
- `NaN` SHALL 被本檢查放行（`0 <= NaN` 不成立）。注意這不代表它是有效值：`NaN` 字面值不是合法 JSON，引擎讀取支撐點檔時會判定整份檔案無效（`support point file is not valid JSON`），工作因此失敗，但不會卡死。
- 非物件的點，或 `base_radius_mm` 不是數值（包括布林值）的點，本需求不檢查，維持本變更前的行為。

只要有任何一點不合法：

- 系統 SHALL 回傳 HTTP 422，錯誤碼為 `SUPPORT_POINT_PARAM_INVALID`，`retryable: false`。
- 回應的 `data.errors[]` SHALL 列出**所有**不合法的點，每一筆的 `loc` 為 `["points", <點的索引>, "base_radius_mm"]`，索引從 0 開始，與請求中 `points` 陣列的位置一致。
- 訊息 MUST 指出不合法的點的位置與欄位名。不合法的點超過 10 個時，訊息 SHALL 只列出前 10 個，並註明剩餘數量；修正提示文字在訊息中 SHALL 只出現一次。`data.errors[]` 不受此限制，仍列出所有不合法的點。
- 系統 MUST NOT 存下這份清單；先前已存下的清單（若有）SHALL 保持不變。

檢查通過時，系統 SHALL 存下原始請求的 bytes，MUST NOT 改寫任何點的內容（沿用「後端須能接受自訂支撐點清單並轉交底層」的不補值原則）。

#### Scenario: 單點底座半徑為 0
- **GIVEN** 一個待處理的切片工作
- **WHEN** 呼叫 `POST /support-points`，`points` 有三點，索引 1 的 `base_radius_mm` 為 0
- **THEN** 回應 HTTP 422，錯誤碼為 `SUPPORT_POINT_PARAM_INVALID`
- **AND** `retryable` 為 false
- **AND** `data.errors[]` 恰有一筆，`loc` 為 `["points", 1, "base_radius_mm"]`
- **AND** 這份清單 MUST NOT 被存下

#### Scenario: 負零被拒絕
- **WHEN** 某點的 `base_radius_mm` 為 `-0.0`
- **THEN** 回應 HTTP 422，錯誤碼為 `SUPPORT_POINT_PARAM_INVALID`，`loc` 指向該點

#### Scenario: 極小正數被拒絕
- **WHEN** 某點的 `base_radius_mm` 為 `1e-50`
- **THEN** 回應 HTTP 422，錯誤碼為 `SUPPORT_POINT_PARAM_INVALID`，`loc` 指向該點

#### Scenario: 門檻邊界
- **WHEN** 兩份清單分別有一點的 `base_radius_mm` 為 `0.00009` 與 `0.0001`
- **THEN** `0.00009` 那份回應 HTTP 422
- **AND** `0.0001` 那份被接受

#### Scenario: 引擎匯出的半徑送回可通過
- **GIVEN** 全域 `support_base_diameter` 為下限 `0.0002`，引擎匯出的點半徑為 `0.0001`；匯入後再匯出時為 `9.999999747378752e-05`
- **WHEN** 分別以這兩個值作為某點的 `base_radius_mm` 呼叫 `POST /support-points`
- **THEN** 兩份清單都被接受
- **AND** `base_radius_mm` 為 `9.9999e-05`（低於單精度門檻）的清單仍回應 HTTP 422

#### Scenario: 一次回報所有不合法的點
- **WHEN** 索引 0 與索引 4 兩點的 `base_radius_mm` 都為 0
- **THEN** `data.errors[]` 恰有兩筆，`loc` 分別為 `["points", 0, "base_radius_mm"]` 與 `["points", 4, "base_radius_mm"]`

#### Scenario: 超過 10 點時訊息只列前 10 點
- **WHEN** 15 個點的 `base_radius_mm` 都為 0
- **THEN** 訊息含索引 0 到 9 的位置，不含索引 10 之後的位置，並註明另有 5 個
- **AND** 修正提示文字在訊息中只出現一次
- **AND** `data.errors[]` 恰有 15 筆

#### Scenario: 負數代表沿用全域
- **WHEN** 某點的 `base_radius_mm` 為 -1，另一點為 -0.00005
- **THEN** 清單被接受，回應成功

#### Scenario: 缺欄位代表沿用全域
- **WHEN** 每一點都只有 `pos` 與 `type`，沒有 `base_radius_mm`
- **THEN** 清單被接受，回應成功

#### Scenario: 合法正值
- **WHEN** 每一點的 `base_radius_mm` 都為 2.0
- **THEN** 清單被接受，回應成功

#### Scenario: 被拒絕時不覆蓋先前的清單
- **GIVEN** 該工作先前已成功存下一份合法清單 A
- **WHEN** 再送出一份含 `base_radius_mm` 為 0 的清單 B
- **THEN** 回應 HTTP 422
- **AND** 該工作存下的仍是清單 A 的原始 bytes

#### Scenario: 通過時原樣存下
- **WHEN** 送出一份合法清單，其中數值寫法為 `2.50`、key 順序任意
- **THEN** 存下的內容與請求本體的 bytes 完全相同
