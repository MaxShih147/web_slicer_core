## MODIFIED Requirements

### Requirement: 系統須提供載入自訂支撐點的 CLI 介面

切片核心 SHALL 提供 `--import-support-points <path>` 參數。載入的點 SHALL 填入 `ModelObject::sla_support_points`，且 `sla_points_status` SHALL 設為 `UserModified`，使引擎採用傳入的點而不執行自動偵測。此處理 SHALL 發生在 `print->apply()` 之前。

載入的點 SHALL 完整豁免懸空角度門檻。因 `sla_points_status` 為 `UserModified`，管線 SHALL 於 `slaposSupportPoints` 提前返回而不執行自動產點階段的角度過濾；`slaposSupportTree` 亦 MUST NOT 對其套用懸空角度門檻。

因此，`support_critical_angle` 與 `branchingsupport_critical_angle` 的變動 MUST NOT 改變一份既有匯入清單所產生的支撐點集。角度設定 SHALL 僅在自動產點階段生效。

`normal_cutoff_angle` 的幾何合理性檢查與碰撞干涉檢查 SHALL 無條件適用於所有載入的點，不受本豁免影響。

#### Scenario: 傳入的點被完整採用
- **GIVEN** 一份含 N 個支撐點的 JSON
- **WHEN** 以 `--import-support-points` 載入並生成支撐
- **THEN** 引擎使用的支撐點數量 SHALL 為 N

#### Scenario: 不執行自動偵測
- **GIVEN** 一份僅含 1 個支撐點的 JSON，而該模型自動偵測會產生數百個點
- **WHEN** 以 `--import-support-points` 載入並生成支撐
- **THEN** 引擎使用的支撐點數量 SHALL 為 1

#### Scenario: 調整角度不影響匯入的點集
- **GIVEN** 一份含 N 個支撐點的 JSON，其中部分點位於陡峭表面
- **WHEN** 分別以 `support_critical_angle` 為 0、45、90 度載入同一份 JSON 並生成支撐
- **THEN** 三次執行中引擎使用的支撐點數量 SHALL 皆為 N

#### Scenario: 陡峭表面上的匯入點進入幾何計算
- **GIVEN** 一份 JSON 含一個位於斜度 80 度表面上的點，且 `support_critical_angle` 設為 45 度
- **WHEN** 以 `--import-support-points` 載入並生成支撐
- **THEN** 該點 SHALL 進入支撐頭的幾何計算，MUST NOT 因懸空角度而被剔除

---

### Requirement: 支撐點類型須以字串編碼

支撐點的 `type` 欄位 SHALL 以字串編碼，取值為 `manual_add`、`island`、`slope` 之一。MUST NOT 沿用 3MF 那套以浮點數範圍比對（約等於 1.0 即為 island）的編碼。

`type` SHALL 為純資訊性標記，用途限於記錄該點的來源，供呼叫端顯示與編輯使用。支撐樹建構（`slaposSupportTree`）MUST NOT 依 `type` 分派任何行為差異，包含但不限於懸空角度門檻的套用與否。

匯入時缺少 `type` 鍵 SHALL 解讀為 `manual_add`；匯出時 SHALL 一律寫入解析後的實值。無法辨識的 `type` 字串 SHALL 使載入失敗並回報錯誤，MUST NOT 猜測其語意。

`SupportPoint::is_island()` 於支撐點產生器內的既有用途不受本規則影響。

#### Scenario: 三種類型往返不變
- **GIVEN** 三個支撐點分別為 `manual_add`、`island`、`slope`
- **WHEN** 匯出後再匯入
- **THEN** 三個點的類型 SHALL 與原始值逐一相同

#### Scenario: 類型不影響支撐生成結果
- **GIVEN** 兩份 JSON，點的座標與尺寸完全相同，僅 `type` 分別為 `manual_add` 與 `slope`
- **WHEN** 以相同組態分別載入並生成支撐
- **THEN** 兩次產生的支撐網格 SHALL 逐位元相同

#### Scenario: 缺少類型鍵視為手動點
- **GIVEN** 一份 JSON，其中某個點只寫了 `pos` 而未寫 `type`
- **WHEN** 以 `--import-support-points` 載入
- **THEN** 該點的類型 SHALL 為 `manual_add`

#### Scenario: 無法辨識的類型被拒絕
- **GIVEN** 一份 JSON，其中某個點的 `type` 為引擎不認得的字串
- **WHEN** 以 `--import-support-points` 載入
- **THEN** 系統 SHALL 拒絕載入並回報錯誤
- **AND** MUST NOT 繼續執行切片

## ADDED Requirements

### Requirement: 匯入點的物理極限行為

匯入的支撐點雖豁免懸空角度門檻，但 SHALL 仍受既有的幾何與物理檢查約束。

法線落在正上方 `180 度 − normal_cutoff_angle`（現值 30 度）錐內的點 SHALL 被 `normal_cutoff_angle` 剔除，不生成支撐柱。此行為 SHALL 無條件適用於所有點類型，且 SHALL 被視為預期的物理結果而非缺陷。

通過角度豁免的點若在支撐頭放置時無足夠空間，SHALL 由既有的碰撞干涉檢查剔除。此剔除同樣 SHALL 被視為預期行為。

位於近垂直表面的匯入點通過豁免後，其支撐頭方向 SHALL 由 `bridge_slope` 飽和運算夾住，因而可能生成斜向插出的支撐柱。此結果 SHALL 被視為使用者主動放置的預期結果，MUST NOT 被額外的過濾機制抑制。

#### Scenario: 法線朝正上方的匯入點不生成支撐柱
- **GIVEN** 一份 JSON 含一個位於朝上平面的點，其法線偏離正上方不足 30 度
- **WHEN** 以 `--import-support-points` 載入並生成支撐
- **THEN** 該點 SHALL 被 `normal_cutoff_angle` 剔除
- **AND** MUST NOT 生成支撐柱

#### Scenario: 法線偏離正上方 30 度以外的匯入點進入計算
- **GIVEN** 一份 JSON 含一個位於斜上 45 度表面的點（法線偏離正上方 45 度）
- **WHEN** 以 `--import-support-points` 載入並生成支撐
- **THEN** 該點 SHALL 通過 `normal_cutoff_angle`
- **AND** 其去留 SHALL 由碰撞干涉檢查決定

#### Scenario: 垂直牆面上的匯入點生成斜向支撐柱
- **GIVEN** 一份 JSON 含一個位於垂直牆面的點，且該點下方空間足以容納支撐頭
- **WHEN** 以 `--import-support-points` 載入並生成支撐
- **THEN** 該點 SHALL 生成支撐柱
- **AND** 該支撐頭的方向 SHALL 被 `bridge_slope` 夾住而呈斜向插出

#### Scenario: 空間不足的匯入點靜默失敗
- **GIVEN** 一份 JSON 含一個位於狹縫內、無足夠空間放置支撐頭的點
- **WHEN** 以 `--import-support-points` 載入並生成支撐
- **THEN** 該點 MUST NOT 生成支撐柱
- **AND** 此結果 SHALL 不被視為錯誤，切片 SHALL 正常完成

---

### Requirement: 匯出的點清單須已通過角度過濾

`--export-support-points` 匯出的自動產生點 SHALL 已通過懸空角度過濾。匯出清單中 MUST NOT 包含「僅因懸空角度不足」而不會生成支撐柱的點。

此保證僅涵蓋懸空角度一項。其餘成因（座標去重、`normal_cutoff_angle`、支撐頭空間不足、低於底板、`ground_facing_only`、支撐柱路徑搜尋失敗）造成的落單點 SHALL 不在本保證範圍內。

#### Scenario: 匯出清單不含角度不足的點
- **GIVEN** 一個模型含斜度超過通過上限的朝下表面，`support_critical_angle` 設為 45 度
- **WHEN** 以 `--export-support-points` 匯出
- **THEN** 匯出的 JSON 中 MUST NOT 出現位於該表面上的點

#### Scenario: 匯出後直接匯入不改變點集
- **GIVEN** 以某組態匯出的一份支撐點 JSON
- **WHEN** 以同一組態將該 JSON 以 `--import-support-points` 載回並生成支撐
- **THEN** 引擎使用的支撐點集 SHALL 與匯出清單逐點相同
