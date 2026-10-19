## MODIFIED Requirements

### Requirement: 斜撐桿對非斜撐桿須通過立體間距判定

本需求即討論中所稱的「Z 高度差判定」。兩根桿俯視交叉時，其 3D 最短距離等於交叉點高度差乘上一個由兩桿方向決定、不大於 1 的係數；只比較高度差會高估間距，因此本需求以 3D 最短距離為準，MUST NOT 只比較高度差。

每一根斜撐桿與每一根 `kind` 為 `head`、`prop`、`route` 或缺 `kind`（legacy）的桿，若兩者軸線段的俯視最短距離 < `r1 + r2 + safety_clearance`，SHALL 計算兩者軸線段的 3D 最短距離，該距離 SHALL ≥ `r1 + r2 + safety_clearance`。

非斜撐桿的任一端柱（`a` 或 `b`，以編號判定）與該斜撐組的任一端柱相同或同屬一個叢集時，這些共用柱的集合為 S。系統 MUST NOT 因此整根豁免，而 SHALL 依 `sla-head-bridge-clearance` 的「共用柱接點須以動態半徑 R 豁免」處理：對每根 P ∈ S 計算 `R_P = r_P + r1 + r2 + safety_clearance`，剪除兩桿落在以 P 軸心為中心、半徑 `R_P` 的鉛直圓柱內的部分，再以剩餘部分做上述 3D 判定。S 中屬於叢集成員的柱，以該成員自身的軸心與半徑計算。

不滿足的斜撐桿 SHALL 不被建立（原因 `z_clear_fail`）；同組其餘通過的桿 SHALL 照常建立。此判定 SHALL 以單根桿為單位，與既有的模型碰撞檢查並列。非斜撐桿本身 MUST NOT 因此被移除或改變。

#### Scenario: 高度錯開的水平桿不阻擋斜撐
- **GIVEN** 一根水平的 `prop` 桿與一根水平的斜撐桿俯視垂直交叉，桿半徑皆為 0.5，交叉點處兩者高度差為 1.5 mm
- **WHEN** 建立該斜撐桿
- **THEN** 兩者 3D 最短距離為 1.5 mm，該斜撐桿 SHALL 被建立

#### Scenario: 高度未錯開的斜撐桿不被建立
- **GIVEN** 同上，但交叉點處高度差為 1.0 mm
- **WHEN** 建立該斜撐桿
- **THEN** 該斜撐桿 MUST NOT 被建立，原因為 `z_clear_fail`
- **AND** 同組其他通過判定的斜撐桿 SHALL 照常建立

#### Scenario: 傾斜桿的間距不以高度差計
- **GIVEN** 一根沿 X 軸的水平 `head` 桿，與一根在 YZ 平面內傾斜 45° 的斜撐桿俯視交叉，桿半徑皆為 0.5，交叉點處高度差為 1.5 mm
- **WHEN** 建立該斜撐桿
- **THEN** 兩者 3D 最短距離約為 1.06 mm（1.5 × cos 45°），小於 1.2 mm
- **AND** 該斜撐桿 MUST NOT 被建立，原因為 `z_clear_fail`

#### Scenario: 共用柱的掛橋在接點內豁免
- **GIVEN** 一根 `head` 桿的 `b` 為柱 P；斜撐組 P–Q 的某根斜撐桿，與該 `head` 桿的接觸只發生在 P 軸心周圍 `R_P` 以內；柱與桿半徑皆為 0.5（`R_P` = 1.7 mm）
- **WHEN** 建立該斜撐桿
- **THEN** 該斜撐桿 MUST NOT 因這根 `head` 桿而被拒絕

#### Scenario: 共用柱的掛橋在接點外仍須判定
- **GIVEN** 同上，但剪除 `R_P` 圓柱內的部分後，兩者剩餘部分的 3D 最短距離為 0.6 mm，接觸點距 P 軸心 3 mm
- **WHEN** 建立該斜撐桿
- **THEN** 該斜撐桿 MUST NOT 被建立，原因為 `z_clear_fail`

#### Scenario: 缺型態的桿以立體間距判定
- **GIVEN** 一根缺 `kind` 的桿
- **WHEN** 斜撐桿與它俯視相近
- **THEN** 系統 SHALL 以本需求的立體間距規則判定
- **AND** MUST NOT 以端點位置推斷其型態

### Requirement: 輔助柱斜撐不受配對上限限制

輔助柱階段中，主柱與輔助柱之間、輔助柱彼此之間的斜撐 SHALL 依一般規則判定，但 MUST NOT 檢查配對上限（`pair_cap`）；建立後兩端計數照常增加。

搜尋輔助柱位置時，一個位置 SHALL 同時滿足以下三項才算可放置：既有的垂直路徑與柱底條件；「主柱與該位置的輔助柱之間可建立斜撐」；以及該輔助柱的柱身與其輔助柱橋，對所有已提交的掛橋、繞路段、輔助柱橋與支撐頭，依 `sla-head-bridge-clearance` 的 3D 間距判定（間隙 0.2 mm）通過。只符合部分條件的位置 MUST NOT 被選用。輔助柱 MUST NOT 參與降級：沒有可放置的位置時，就不放置。

#### Scenario: 主柱配對已滿仍可長輔助柱
- **GIVEN** 柱 P 高 30 mm，`pairs` 為 3（都是矮柱），`links` 為 0，輔助柱開啟
- **WHEN** 輔助柱階段處理 P
- **THEN** P 與輔助柱之間的斜撐 MUST NOT 因 `pair_cap` 被拒絕

#### Scenario: 位置搜尋跳過無法建斜撐的角度
- **GIVEN** 第一個垂直路徑暢通的角度上，主柱到輔助柱的斜撐會穿過第三根柱；下一個角度不會
- **WHEN** 搜尋輔助柱位置
- **THEN** 系統 SHALL 選用下一個角度

#### Scenario: 位置搜尋跳過會刺穿掛橋的角度
- **GIVEN** 第一個可建斜撐的角度上，輔助柱柱身與一根已提交掛橋的 3D 距離為 0.6 mm，半徑皆為 0.5；下一個角度的距離為 2.0 mm
- **WHEN** 搜尋輔助柱位置
- **THEN** 系統 SHALL 選用下一個角度

### Requirement: 回歸與效能門檻

於三個參考模型（小、中、滿版，以檔名與 SHA-256 記錄）上，本變更 SHALL 滿足：

- 非救援、非保底斜撐之間的俯視違規數（違反 `cross_truss` 或 `shared_angle`，依叢集規則判定）SHALL 為 0。
- 斜撐穿柱違規數（依叢集規則判定）SHALL 為 0。
- `links` 為 0 且高度 > 15 mm 的非凍結柱數 SHALL 為 0。
- 同一對柱的斜撐組數 SHALL 至多為 1。
- 連接柱子階段的耗時增量 MUST NOT 超過 max(基準線的 10%, 50 ms)。
- 同一輸入執行兩次，斜撐集合 SHALL 相同；若基準線本身在相同條件下已不一致，SHALL 以基準線的不一致範圍為準，並記錄原因。此例外 MUST NOT 適用於 `sla-head-bridge-clearance` 所規範的掛橋、繞路段、自立柱、錨柱與 `warnings` 紀錄，它們 SHALL 無條件逐位元相同。

桿件總數與輔助柱數 SHALL 被記錄，供人判讀趨勢，不作為通過門檻。

#### Scenario: 參考模型無交錯
- **WHEN** 以本變更的引擎為三個參考模型生成支撐
- **THEN** 非救援、非保底斜撐的俯視違規數與穿柱違規數 SHALL 皆為 0

#### Scenario: 沒有孤立高柱
- **WHEN** 以本變更的引擎為參考模型生成支撐
- **THEN** `links` 為 0 且高度 > 15 mm 的非凍結柱數 SHALL 為 0

#### Scenario: 沒有重複的柱對
- **WHEN** 以本變更的引擎為參考模型與 02.stl（墊高 5 mm、密度 100、柱徑 1.0）生成支撐
- **THEN** 任兩筆 `truss` 記錄的無序端點對 MUST NOT 完全相同，且同一對柱的斜撐組數 SHALL 至多為 1

#### Scenario: 效能門檻
- **GIVEN** 改動前連接柱子階段耗時 T
- **WHEN** 以本變更的引擎在同一台機器、同一編譯設定下量測
- **THEN** 耗時 SHALL ≤ T + max(0.1 × T, 50 ms)

## ADDED Requirements

### Requirement: 同一對柱只能有一組斜撐

斜撐 SHALL 以無序柱對（canonical pair，`(min(a,b), max(a,b))`）為唯一鍵。任何建立斜撐的路徑，包含全域貪婪、救援、保底、`attach()` 與 `run_greedy_for()`，遇到已有斜撐的柱對 SHALL 拒絕，原因為 `duplicate_pair`，且 MUST NOT 建立任何桿。`duplicate_pair` SHALL 加入原因代碼與向量格式，既有原因代碼的意義不變。

#### Scenario: 重複呼叫 attach
- **GIVEN** 主柱 35 與輔助柱 94 已由 `attach(35, 94)` 建立一組斜撐
- **WHEN** 再次以 `attach(94, 35)` 或 `attach(35, 94)` 嘗試
- **THEN** 回傳原因 SHALL 為 `duplicate_pair`，且 MUST NOT 建立任何桿

#### Scenario: 輔助柱後的補連不重複
- **GIVEN** 輔助柱階段已以 `attach` 連接主柱與輔助柱
- **WHEN** 對新輔助柱執行 `run_greedy_for`
- **THEN** 該對柱 MUST NOT 再出現在候選中

#### Scenario: 共通向量
- **WHEN** 以共通幾何測試向量執行「同一柱對嘗試兩次」的案例
- **THEN** 第二次的決策 SHALL 為 `duplicate_pair`
