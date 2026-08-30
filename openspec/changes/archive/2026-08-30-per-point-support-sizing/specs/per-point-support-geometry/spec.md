## ADDED Requirements

### Requirement: 支撐點須攜帶七個獨立的幾何尺寸欄位

`sla::SupportPoint` SHALL 攜帶七個描述該點支撐幾何的尺寸欄位：既有的 `head_front_radius`，以及六個新擴充欄位 `head_back_radius_mm`、`head_width_mm`、`head_penetration_mm`、`contact_sphere_radius`、`base_radius_mm`、`support_bracing_angle_deg`。支撐樹建構流程 SHALL 對每一個支撐點分別讀取其自身的欄位值，MUST NOT 對整個物件套用單一組全域尺寸。

`contact_sphere_radius` 在本 fork 為**保留欄位**：底層不存在接觸球幾何與對應的全域設定，因此該欄位 SHALL 被完整攜帶、序列化與往返，但 MAY 不具任何幾何消費點。

#### Scenario: 單點加粗不影響其他支撐柱
- **GIVEN** 一組支撐點，其中僅第 N 點的 `head_back_radius_mm` 設為 0.6，其餘皆未設定
- **WHEN** 生成支撐樹
- **THEN** 第 N 點對應的支撐柱半徑 SHALL 為 0.6 mm
- **AND** 其餘支撐柱的半徑 SHALL 為全域預設值

#### Scenario: 多點各自設定不同尺寸
- **GIVEN** 三個支撐點分別將 `head_back_radius_mm` 設為 0.3、0.6、0.9
- **WHEN** 生成支撐樹
- **THEN** 三根支撐柱的半徑 SHALL 分別為 0.3、0.6、0.9 mm

### Requirement: 未設定的擴充尺寸欄位須回退至全域預設

六個新擴充尺寸欄位 SHALL 以數值本身判定是否為自訂值：大於等於 0 時 SHALL 套用該點的自訂值；小於 0（哨兵值 `-1`）時 SHALL 回退至對應的全域預設設定。判定 MUST NOT 依賴任何額外的旗標欄位。

`head_front_radius` MUST NOT 納入此哨兵機制，且 MUST NOT 提供以 `-1` 回退全域預設的解析函式。該欄位的 `-1` 在 `prepare_permanent_support_points()` 中另有「標記刪除」的既存語意，並被用作貼面距離容差。任何填寫 `sla::SupportPoint` 的路徑 SHALL 為該欄位寫入解析後的具體半徑。

#### Scenario: 六個擴充欄位皆為哨兵值
- **GIVEN** 一個支撐點的六個擴充尺寸欄位皆為 `-1`，`head_front_radius` 為具體值
- **WHEN** 生成支撐樹
- **THEN** 該點的支撐幾何 SHALL 與未導入本功能前、以相同全域設定生成的幾何完全一致

#### Scenario: head_front_radius 的 -1 仍為刪除標記
- **GIVEN** 一個 `type` 為 `manual_add` 的支撐點，其 `head_front_radius` 為 `-1`
- **WHEN** 執行 `prepare_permanent_support_points()`
- **THEN** 該點 SHALL 被移除
- **AND** 系統 MUST NOT 將該 `-1` 解讀為「回退至全域頭部半徑」

#### Scenario: 部分欄位自訂
- **GIVEN** 一個支撐點僅設定 `head_width_mm` 為 2.5，其餘六個欄位為 `-1`
- **WHEN** 生成支撐樹
- **THEN** 該點的支撐頭連接段長度 SHALL 為 2.5 mm
- **AND** 其餘六項幾何 SHALL 取自全域預設

### Requirement: contact_sphere_radius 的零值須視為實值而非未設定

`contact_sphere_radius` SHALL 具有三種語意：小於 0 代表未設定並回退全域預設；等於 0 代表該點明確不使用接觸球；大於 0 代表接觸球半徑。系統 MUST NOT 將 0 與哨兵值混為一談，MUST NOT 以「小於等於 0 即視為未設定」的判斷式處理此欄位。

本 fork 的底層不存在接觸球幾何與對應的全域設定，因此此規則於本變更中 SHALL 由解析函式層級落實並以單元測試驗證；幾何層級的驗收 SHALL 延後至底層具備該幾何時。

#### Scenario: 零值解析為明確關閉
- **GIVEN** 全域設定啟用接觸球且半徑為 0.4，某支撐點的 `contact_sphere_radius` 為 0
- **WHEN** 解析該點的接觸球設定
- **THEN** 解析結果 SHALL 為「不使用接觸球」

#### Scenario: 哨兵值解析為沿用全域設定
- **GIVEN** 全域設定啟用接觸球且半徑為 0.4，某支撐點的 `contact_sphere_radius` 為 `-1`
- **WHEN** 解析該點的接觸球設定
- **THEN** 解析結果 SHALL 為「使用接觸球，半徑 0.4」

### Requirement: 尺寸欄位的生效與否不得依支撐點類型而異

七個尺寸欄位的生效判定 SHALL 只依據欄位數值，MUST NOT 依據 `SupportPointType`。自動生成的 `island` 與 `slope` 點，與手動新增的 `manual_add` 點，在套用自訂尺寸上 SHALL 一視同仁。

#### Scenario: 自動生成點的底座直徑生效
- **GIVEN** 一個 `type` 為 `slope` 的支撐點，其 `base_radius_mm` 設為 3.0，全域底座半徑為 2.0
- **WHEN** 生成支撐樹
- **THEN** 該點對應支撐柱的底座半徑 SHALL 為 3.0 mm

#### Scenario: 自動生成點的支撐角度生效
- **GIVEN** 一個 `type` 為 `island` 的支撐點，其 `support_bracing_angle_deg` 設為 30，全域角度為 45
- **WHEN** 生成支撐樹
- **THEN** 該點使用的支撐角度 SHALL 為 30 度

#### Scenario: 手動新增點行為不變
- **GIVEN** 一個 `type` 為 `manual_add` 的支撐點，其 `base_radius_mm` 設為 3.0
- **WHEN** 生成支撐樹
- **THEN** 該點對應支撐柱的底座半徑 SHALL 為 3.0 mm

### Requirement: 解除類型限制不得改變既有的切片輸出

當所有支撐點的六個擴充尺寸欄位皆為哨兵值時，支撐幾何與切片產出 SHALL 與本變更前完全一致。解除類型限制 MUST NOT 在既有輸入下產生任何可觀測的差異。

#### Scenario: 預設輸入下的逐位元回歸
- **GIVEN** 同一份模型與同一組全域參數，所有支撐點皆為自動生成且擴充尺寸欄位皆未設定
- **WHEN** 在本變更前後分別執行完整切片
- **THEN** 兩份 `.sl1` 的層檔數量 SHALL 相等
- **AND** 對應層檔的 SHA-256 SHALL 逐一相等

### Requirement: 支撐尺寸為絕對毫米值，不隨模型縮放

七個尺寸欄位 SHALL 一律以絕對毫米為單位。座標變換 MUST NOT 對尺寸欄位套用任何縮放；模型的 scale 變更 SHALL 只影響支撐點的位置，不影響其尺寸。

#### Scenario: 模型放大後柱徑不變
- **GIVEN** 一個支撐點的 `head_back_radius_mm` 設為 0.6
- **WHEN** 模型的 scale 由 1.0 改為 2.0 並重新生成支撐樹
- **THEN** 該點對應支撐柱的半徑 SHALL 仍為 0.6 mm

### Requirement: 新增欄位須納入序列化與相等比較

七個尺寸欄位 SHALL 全部納入 `SupportPoint` 的 cereal `serialize()` 與 `operator==`。任一欄位若未納入序列化 SHALL 被視為缺陷（資料靜默遺失）；若未納入相等比較 SHALL 被視為缺陷（變更偵測漏判）。

#### Scenario: 序列化往返後欄位完整
- **GIVEN** 一個七個尺寸欄位皆設為相異具體值的支撐點
- **WHEN** 經 cereal 序列化後再反序列化
- **THEN** 七個欄位的值 SHALL 與原始值逐一相等

#### Scenario: 單一欄位差異可被偵測
- **GIVEN** 兩個支撐點，除其中一個尺寸欄位外其餘完全相同
- **WHEN** 以 `operator!=` 比較
- **THEN** 結果 SHALL 為真
