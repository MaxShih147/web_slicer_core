# support-point-interchange Specification

## Purpose
定義支撐點清單的 CLI 交換契約：只計算並匯出支撐點的停步路徑、載入自訂清單並繞過自動偵測的匯入路徑、具名 key 的 JSON 格式與版本規則（未知 key 忽略、未知版本拒絕）、匯出時的凍結策略與座標系規範，以及與 `--import-support-stl` 的互斥。

## Requirements

### Requirement: 系統須提供只計算並匯出支撐點的 CLI 介面

切片核心 SHALL 提供 `--export-support-points <path>` 參數。當它是唯一被要求的輸出時，SLA 管線 SHALL 在 `slaposSupportPoints` 步驟完成後停止，並將該步驟的計算結果寫入指定路徑。系統 MUST NOT 在此模式下執行支撐樹生成、底筏生成、支撐切片或光柵化。

#### Scenario: 匯出產生支撐點檔案
- **WHEN** 以 `--export-support-points out.json` 對一個需要支撐的模型執行 CLI
- **THEN** `out.json` SHALL 存在且含至少一個支撐點

#### Scenario: 匯出模式不產生支撐網格
- **WHEN** 以 `--export-support-points out.json` 且未指定任何其他輸出執行 CLI
- **THEN** 系統 MUST NOT 產生支撐 STL、`.sl1` 或預覽影像

#### Scenario: 匯出快於完整支撐生成
- **GIVEN** 同一份模型與同一組參數，且該模型的支撐點數足以讓支撐樹與底筏的成本可被量測（非數十點量級）
- **WHEN** 分別執行 `--export-support-points` 與 `--export-support-stl`，各取多次執行的中位數
- **THEN** 前者的耗時 SHALL 較後者節省 **20% 以上**
- **AND** 前者的輸出體積 SHALL 為後者的 **1/60 以下**

驗收門檻說明：支撐點生成本身是兩條路徑共用且最昂貴的階段（實測約佔總耗時六成），
`--export-support-points` 省下的只有支撐樹、底筏與寫檔。因此耗時的改善幅度有其上限，
真正的量級差異在輸出體積。兩項門檻須同時成立。

### Requirement: 系統須提供載入自訂支撐點的 CLI 介面

切片核心 SHALL 提供 `--import-support-points <path>` 參數。載入的點 SHALL 填入 `ModelObject::sla_support_points`，且 `sla_points_status` SHALL 設為 `UserModified`，使引擎採用傳入的點而不執行自動偵測。此處理 SHALL 發生在 `print->apply()` 之前。

#### Scenario: 傳入的點被完整採用
- **GIVEN** 一份含 N 個支撐點的 JSON
- **WHEN** 以 `--import-support-points` 載入並生成支撐
- **THEN** 引擎使用的支撐點數量 SHALL 為 N

#### Scenario: 不執行自動偵測
- **GIVEN** 一份僅含 1 個支撐點的 JSON，而該模型自動偵測會產生數百個點
- **WHEN** 以 `--import-support-points` 載入並生成支撐
- **THEN** 引擎使用的支撐點數量 SHALL 為 1

### Requirement: 交換格式須為具名 key 的 JSON 並攜帶版本

交換檔案 SHALL 為 JSON，所有欄位以名稱定位，MUST NOT 使用位置固定的數值序列。檔案 SHALL 於頂層攜帶整數 `version`。讀取端遇到未知的 key SHALL 忽略之；遇到無法辨識的 `version` SHALL 拒絕載入並回報錯誤，MUST NOT 猜測其語意。

#### Scenario: 未知欄位被忽略
- **GIVEN** 一份 JSON，其中某個支撐點含一個讀取端不認得的 key
- **WHEN** 以 `--import-support-points` 載入
- **THEN** 載入 SHALL 成功
- **AND** 其餘已知欄位 SHALL 正確生效

#### Scenario: 未知版本被拒絕
- **GIVEN** 一份 `version` 為讀取端不支援之數值的 JSON
- **WHEN** 以 `--import-support-points` 載入
- **THEN** 系統 SHALL 拒絕載入並回報錯誤
- **AND** MUST NOT 繼續執行切片

### Requirement: 支撐點類型須以字串編碼

支撐點的 `type` 欄位 SHALL 以字串編碼，取值為 `manual_add`、`island`、`slope` 之一。MUST NOT 沿用 3MF 那套以浮點數範圍比對（約等於 1.0 即為 island）的編碼。

#### Scenario: 三種類型往返不變
- **GIVEN** 三個支撐點分別為 `manual_add`、`island`、`slope`
- **WHEN** 匯出後再匯入
- **THEN** 三個點的類型 SHALL 與原始值逐一相同

### Requirement: 匯出的座標須位於輸入模型的座標系

匯出前，每個支撐點的座標 SHALL 套用 `SLAPrintObject::trafo()` 的逆矩陣，轉回輸入模型自身的座標系。實作 SHALL 使用該 accessor 本身，MUST NOT 自行重組變換矩陣（`sla_trafo()` 內含收縮補償與左手系鏡射，自行推導會遺漏）。匯入方向 MUST NOT 對座標做任何額外轉換。

#### Scenario: 匯出後原樣匯入的往返不變性
- **GIVEN** 一份模型與一組全域參數
- **WHEN** 先以 `--export-support-points` 匯出，再將該檔案原封不動以 `--import-support-points` 載入並生成支撐
- **THEN** 產生的支撐網格 SHALL 與同一參數下自動生成的支撐網格幾何一致

#### Scenario: 收縮補償下的往返不變性
- **GIVEN** 一組非 100% 的收縮補償參數
- **WHEN** 執行上述匯出再匯入的往返
- **THEN** 支撐頭 SHALL 仍貼合模型表面，MUST NOT 出現偏移或浮空

### Requirement: 匯出時尺寸欄位須凍結為具體數值

匯出的每一個支撐點，七個尺寸欄位 SHALL 全部寫入當下全域預設解析後的具體數值。匯出檔案 MUST NOT 含哨兵值 `-1`。此規則使點清單自我描述，並使階段間調整全域參數不影響已匯出的點。

#### Scenario: 匯出檔案不含哨兵值
- **WHEN** 對一個自動生成支撐點的模型執行匯出
- **THEN** 匯出 JSON 中所有支撐點的七個尺寸欄位 SHALL 皆為非負數

#### Scenario: 匯出後調整全域參數不影響已匯出的點
- **GIVEN** 一份以全域柱徑 1.0 匯出的支撐點 JSON
- **WHEN** 將全域柱徑改為 2.0，並以該 JSON 執行 `--import-support-points` 生成支撐
- **THEN** 所有支撐柱的直徑 SHALL 仍為 1.0 mm

### Requirement: 匯入時缺少的欄位須回退至全域預設

匯入時，未提供的**六個擴充尺寸 key** SHALL 等同於哨兵值 `-1`，於支撐生成階段回退至全域預設。此機制服務兩個用途：呼叫端手動新增支撐點時可只提供座標，以及未來新增欄位時的向前相容。

`head_front_radius` MUST NOT 以此方式處理。該 key 未提供時，讀入端 SHALL 直接填入當下全域 `head_front_radius_mm` 的具體數值，MUST NOT 填入 `-1`：`-1` 在該欄位上代表「標記刪除」，會使該點於 `prepare_permanent_support_points()` 被靜默移除。

#### Scenario: 只給座標的手動新增點
- **GIVEN** 一份 JSON，其中某個支撐點只有 `pos` 與 `type`，沒有任何尺寸 key
- **WHEN** 以 `--import-support-points` 載入並生成支撐
- **THEN** 該點的七項幾何 SHALL 全部取自當下的全域預設
- **AND** 該點的 `head_front_radius` SHALL 為全域預設的具體數值，MUST NOT 為 `-1`
- **AND** 該點 MUST NOT 被支撐點前處理階段移除

#### Scenario: 部分欄位缺少
- **GIVEN** 一份 JSON，其中某個支撐點只提供 `head_back_radius_mm`
- **WHEN** 以 `--import-support-points` 載入並生成支撐
- **THEN** 該點的支撐柱半徑 SHALL 為提供的值
- **AND** 其餘六項幾何 SHALL 取自全域預設

### Requirement: 交換格式不得包含不影響切片幾何的欄位

交換格式 MUST NOT 包含 `pillar_radius` 與 `weight`。前者在切片核心中無任何讀取點（實際柱徑取自 `head_back_radius_mm`），後者僅為桌面版 UI 的顯示狀態。引擎 MUST NOT 承載純 UI 欄位。

#### Scenario: 匯出檔案不含 UI 專用欄位
- **WHEN** 執行支撐點匯出
- **THEN** 匯出 JSON 中 MUST NOT 出現 `pillar_radius` 或 `weight` 這兩個 key

### Requirement: 支撐點介面與匯入支撐網格須互斥

`--import-support-points` 與 `--import-support-stl` SHALL 互斥；`--export-support-points` 與 `--import-support-stl` 亦 SHALL 互斥。同時提供時系統 SHALL 明確報錯並終止，MUST NOT 靜默忽略其中之一。

#### Scenario: 同時匯入點與支撐網格
- **WHEN** 同時提供 `--import-support-points` 與 `--import-support-stl`
- **THEN** 系統 SHALL 於執行切片前報錯並終止
- **AND** MUST NOT 產生任何輸出檔案

#### Scenario: 匯出點時同時匯入支撐網格
- **WHEN** 同時提供 `--export-support-points` 與 `--import-support-stl`
- **THEN** 系統 SHALL 報錯並終止
- **AND** MUST NOT 寫出一份空的支撐點清單
