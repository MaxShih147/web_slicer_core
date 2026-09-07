## ADDED Requirements

### Requirement: 接受 PRZ 計時參數輸入

API 在接收切片工作建立請求時，SHALL 允許前端在 DS-Online 格式的 `"Print"` section 中傳入以下計時相關欄位：
`"Exposure Delay Mode"`、`"Light-off Delay"`、`"Rest Before Lift"`、`"Rest After Lift"`、`"Rest After Retract"`、`"Bottom Rest Before Lift"`、`"Bottom Rest After Lift"`、`"Bottom Rest After Retract"`。
所有欄位均為選填；若缺少任何欄位，後端 SHALL 使用對應的預設值，不得拒絕請求。

#### Scenario: 前端傳入完整計時參數
- **WHEN** 前端在 `"Print"` section 中傳入所有 8 個計時欄位，值均在合法範圍內
- **THEN** 後端 SHALL 將這些值解析為 `PrzPrintTimingConfig`，並在產生 `.prz` 檔案時使用這些值

#### Scenario: 前端未傳入任何計時參數
- **WHEN** 前端的 `"Print"` section 中不包含任何計時相關欄位
- **THEN** 後端 SHALL 以預設值產生 `.prz`（`exposure_delay_mode=1`、`light_off_delay=1.0s`、`rest_after_retract=1.0s`，其餘 rest 時間為 `0.0s`），不得回傳錯誤

#### Scenario: 前端傳入部分計時參數
- **WHEN** 前端只傳入部分計時欄位（例如只傳 `"Light-off Delay"`）
- **THEN** 後端 SHALL 使用傳入的值並對其餘欄位套用預設值

---

### Requirement: delay_mode 互斥邏輯

PRZ encoder 在寫入計時欄位時 SHALL 強制執行 `delay_mode` 的互斥規則，確保 binary 輸出不產生語意矛盾。

#### Scenario: lightOff 模式（delay_mode = 0）
- **WHEN** `"Exposure Delay Mode"` 為 `0`
- **THEN** `.prz` 中的 `light_off_time` SHALL 寫入 `"Light-off Delay"` 的值，且所有 `before_lift_time`、`after_lift_time`、`after_retract_time`（底層與一般層）SHALL 強制寫入 `0.0`，無論前端是否傳入這些欄位

#### Scenario: waitTime 模式（delay_mode = 1）
- **WHEN** `"Exposure Delay Mode"` 為 `1`
- **THEN** `.prz` 中的 `light_off_time` SHALL 強制寫入 `0.0`，且 `before_lift_time`、`after_lift_time`、`after_retract_time` SHALL 使用對應的 rest 參數值（底層使用底層值，一般層使用一般層值）

---

### Requirement: 底層計時參數 Fallback

底層（bottom layers）與一般層的 rest 計時參數 SHALL 各自獨立設定；若前端未傳入底層參數，後端 SHALL 自動複製一般層的對應值。

#### Scenario: 前端未傳入底層 rest 參數
- **WHEN** 前端傳入了 `"Rest After Retract"` 但未傳入 `"Bottom Rest After Retract"`（`null` 或省略）
- **THEN** 底層的 `after_retract_time` SHALL 使用與一般層相同的 `rest_after_retract` 值

#### Scenario: 前端明確傳入底層 rest 參數
- **WHEN** 前端同時傳入 `"Rest After Retract": 2.0` 與 `"Bottom Rest After Retract": 3.0`
- **THEN** 底層的 `after_retract_time` SHALL 寫入 `3.0`，一般層寫入 `2.0`，兩者各自獨立

---

### Requirement: 計時參數邊界值驗證

系統 SHALL 對計時參數施加上下限驗證，非法值 SHALL 在 API 層回傳 `422 Unprocessable Entity`，不得讓非法值流入 encoder。

#### Scenario: light_off_delay 超出上限
- **WHEN** 前端傳入 `"Light-off Delay": 150.0`（超過 120s 上限）
- **THEN** API SHALL 回傳 `422` 錯誤，訊息說明 `light_off_delay` 範圍為 0–120 秒

#### Scenario: rest 參數超出上限
- **WHEN** 前端傳入任一 rest 相關欄位的值超過 `60.0`（例如 `"Rest After Retract": 80.0`）
- **THEN** API SHALL 回傳 `422` 錯誤，訊息說明該欄位範圍為 0–60 秒

#### Scenario: exposure_delay_mode 為非法值
- **WHEN** 前端傳入 `"Exposure Delay Mode": 2`（非 0 或 1）
- **THEN** API SHALL 回傳 `422` 錯誤，訊息說明 `exposure_delay_mode` 必須為 0 或 1

#### Scenario: 所有參數合法
- **WHEN** 前端傳入的所有計時參數均在各自合法範圍內
- **THEN** API SHALL 接受請求並繼續切片流程，不得回傳驗證錯誤

---

### Requirement: 既有切片流程不受影響

新增 PRZ 計時參數的解析路徑 SHALL 完全獨立於 `SLAConfig` 與 `_convert_v2_config_to_sla()` 的映射邏輯；對 `SLAConfig` 不存在的計時欄位 SHALL 不造成任何影響。

#### Scenario: 未傳入計時參數的既有請求
- **WHEN** 前端使用現有格式發送切片請求（不含任何新計時欄位）
- **THEN** 切片流程 SHALL 與改動前完全一致，`.prz` 以預設計時值產生，不得出現任何錯誤或行為改變
