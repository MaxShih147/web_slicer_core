## ADDED Requirements

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
