## ADDED Requirements

### Requirement: 幾何元件須以 3D 膠囊體表示

本能力判定的每個幾何元件 SHALL 以「軸線段 + 半徑」的膠囊體表示，對應如下：

- 掛橋（`head`，包含自身短柱上方那根）、繞路段（`route` 的 `Bridge`）、輔助柱橋（`prop`）：`startp → endp`，半徑 `r`。
- 繞路段 `DiffBridge`：`startp → endp`，半徑 `max(r, end_r)`。
- 柱（包含中心柱、自立柱、錨柱、凍結柱、輔助柱）：柱腳 `endpt` → 柱頂 `endpt + height·ẑ`，半徑 `max(r_start, r_end)`。
- 支撐頭：`pos → junction_point()`，半徑 `r_back`。

柱底座（pedestal）與斜撐（`truss`）MUST NOT 列為本能力的障礙物；斜撐由 `sla-bracing-topology` 規範。

#### Scenario: 錐形柱取較大半徑
- **GIVEN** 一根柱 `r_start = 0.5`、`r_end = 0.75`
- **WHEN** 將它列為障礙物
- **THEN** 其膠囊體半徑 SHALL 為 0.75

#### Scenario: 支撐頭以 r_back 膠囊體表示
- **GIVEN** 一個支撐頭 `r_back = 0.4`
- **WHEN** 將它列為障礙物
- **THEN** 其膠囊體 SHALL 為 `pos` 到 `junction_point()` 的線段，半徑 0.4

### Requirement: 間距判定須以 3D 軸線段最短距離為準

兩個膠囊體 x、y 的間距判定 SHALL 以兩條軸線段的 3D 最短歐氏距離 `d` 為準：`d ≥ x.r + y.r + c` 時通過，`d` 恰等於門檻時 SHALL 通過。`c` 在 L0 為 0.2 mm、在 L1 為 0（見「降級狀態機」）。

判定結論 MUST NOT 以 2D 俯視投影或高度差得出。空間索引的粗篩 SHALL 只作為「可能違規者」的超集合過濾，MUST NOT 漏掉任何 `d` 小於門檻的元件。長度為 0 的軸線段 SHALL 視為點。

#### Scenario: 高度錯開的交叉掛橋合法
- **GIVEN** 兩根水平掛橋俯視垂直交叉，半徑皆為 0.5，交叉點處高度差 1.5 mm
- **WHEN** 在 L0 判定
- **THEN** `d = 1.5 ≥ 1.2`，SHALL 通過

#### Scenario: 高度未錯開的交叉掛橋違規
- **GIVEN** 同上，但高度差 1.0 mm
- **WHEN** 在 L0 判定
- **THEN** `d = 1.0 < 1.2`，SHALL 判定為違規

#### Scenario: 傾斜桿不以高度差計
- **GIVEN** 一根沿 X 軸的水平掛橋，與一根在 YZ 平面內傾斜 45° 的掛橋俯視交叉，半徑皆為 0.5，交叉點處高度差 1.5 mm
- **WHEN** 在 L0 判定
- **THEN** `d ≈ 1.06 < 1.2`，SHALL 判定為違規

#### Scenario: 恰等於門檻時通過
- **GIVEN** 兩根掛橋半徑皆為 0.5，`d` 恰為 1.2
- **WHEN** 在 L0 判定
- **THEN** SHALL 通過

### Requirement: 共用柱接點須以動態半徑 R 豁免

元件是否共用柱 SHALL 以 ID 判定，MUST NOT 以幾何推斷。各元件的柱集合為：桿取其 `owner_a`、`owner_b`（排除未設定者）；柱取自身 ID；支撐頭取其承載柱（坐在其上的柱，或其掛橋的終點柱）。兩元件柱集合的交集為 S。

下列情況 SHALL 完全豁免判定：同一支撐頭路徑內的元件彼此之間、桿對其端柱本身、支撐頭對其承載柱本身。

S 非空的其餘情況，對每根 P ∈ S，SHALL 計算：

`R_P = r_P + x.r + y.r + 0.2 mm`，其中 `r_P = max(P.r_start, P.r_end)`

並 SHALL 先剪除 x、y 落在「以 P 軸心為中心、半徑 `R_P` 的鉛直圓柱」內的部分，再以剩餘部分做 3D 間距判定。任一方被完全剪除時 SHALL 視為通過。`R_P` SHALL 依實際半徑逐對計算，MUST NOT 使用固定值。

#### Scenario: 預設尺寸下 R 為 1.7 mm
- **GIVEN** 柱 P 與兩根掛橋的半徑皆為 0.5
- **WHEN** 計算 `R_P`
- **THEN** `R_P` SHALL 為 1.7 mm

#### Scenario: 每點尺寸下 R 隨半徑變化
- **GIVEN** 柱 P 半徑 0.75，兩根掛橋半徑皆為 0.75
- **WHEN** 計算 `R_P`
- **THEN** `R_P` SHALL 為 2.45 mm

#### Scenario: 接點附近的接觸豁免
- **GIVEN** 兩根掛橋都終止於柱 P 軸心上的同一點，俯視夾角 90°，半徑皆為 0.5
- **WHEN** 判定兩者
- **THEN** 剪除半徑 1.7 mm 圓柱內的部分後，剩餘部分距離 ≥ 1.2，SHALL 通過

#### Scenario: 接點外的貼合違規
- **GIVEN** 兩根長 5 mm 的掛橋終止於柱 P 軸心上的同一點，3D 夾角 10°，半徑皆為 0.5
- **WHEN** 判定兩者
- **THEN** 剪除後剩餘部分的最近距離約 0.30 mm，小於 1.2，SHALL 判定為違規

#### Scenario: 共用柱以 ID 判定
- **GIVEN** 兩根掛橋的終點幾何上都落在柱 P 軸心附近，但其中一根的 `owner_b` 是柱 Q
- **WHEN** 判定兩者
- **THEN** 系統 MUST NOT 把 P 視為共用柱

### Requirement: 掛橋與繞路段不得互相交錯

一個支撐頭待提交路徑中的每根掛橋、繞路段與自身短柱，對所有已提交的掛橋、繞路段與輔助柱橋，SHALL 通過間距判定（含共用柱的 R 豁免）。

#### Scenario: 兩群掛橋實體貫穿
- **GIVEN** 已提交一根掛到柱 P 的掛橋；一個待提交的掛橋掛到柱 Q，兩者軸心最近距離 0.358 mm，半徑皆為 0.5
- **WHEN** 驗證該待提交路徑
- **THEN** 該路徑 SHALL 判定為違規

### Requirement: 掛橋與繞路段不得穿過第三根柱或其他支撐頭

待提交路徑中的每根掛橋、繞路段，對所有非其端柱的柱，以及所有其他支撐頭，SHALL 通過間距判定。柱的膠囊體只涵蓋柱腳到柱頂，所以從半空柱腳下方通過、且 3D 距離足夠的桿 SHALL 視為合法。

#### Scenario: 掛橋穿過中間的柱
- **GIVEN** 柱 B 位於掛橋 h→P 的俯視路徑上，B 的柱身涵蓋該處高度，軸心到掛橋距離 0.79 mm，半徑皆為 0.5
- **WHEN** 驗證該路徑
- **THEN** SHALL 判定為違規

#### Scenario: 從半空柱腳下方通過
- **GIVEN** 柱 B 站在模型上，柱腳高 20 mm；掛橋以 z = 15 mm 從 B 軸心正下方通過
- **WHEN** 驗證該路徑
- **THEN** 3D 距離 5 mm，SHALL 通過

#### Scenario: 掛橋穿過別人的支撐頭
- **GIVEN** 支撐頭 k 不是本路徑的支撐頭，也不坐在本路徑的端柱上；本路徑的掛橋與 k 的膠囊體距離 0.5 mm，兩者半徑皆為 0.5
- **WHEN** 驗證該路徑
- **THEN** SHALL 判定為違規

### Requirement: 新柱不得刺穿已提交的桿與支撐頭

任何新長出的柱，包含第 3 步的自立柱、第 4 步繞路後的柱與錨柱、第 6 步的輔助柱，其膠囊體 SHALL 對所有已提交的掛橋、繞路段、輔助柱橋與支撐頭通過間距判定。柱對柱的重疊不在本需求範圍。輔助柱的放置規則見 `sla-bracing-topology`。

#### Scenario: 自立柱會刺穿先前的掛橋
- **GIVEN** 支撐頭 h 的唯一候選是自立柱，其柱身與一根已提交掛橋的距離 0.6 mm，半徑皆為 0.5
- **WHEN** 在 L0 驗證該候選
- **THEN** SHALL 判定為違規，並依降級狀態機繼續處理

### Requirement: 硬規則須在間距判定前過濾且不得放寬

驗證任何候選時，系統 SHALL 先檢查下列硬規則；不滿足者 SHALL 視為該候選失敗，MUST NOT 進入間距判定。硬規則在 L0、L1、L2 任一層級 MUST NOT 放寬：

1. 一個支撐頭 SHALL 只提交一條路徑，提交 SHALL 是原子的：整條寫入，或完全不寫。任何被拒絕的候選 MUST NOT 在 builder 中留下桿、短柱或接合點。
2. 掛柱候選的目標柱 SHALL 滿足 `r_start ≥` 支撐頭的 `r_back`。此規則 SHALL 適用於所有掛柱路徑，包含掛到群中心柱。
3. 目標柱的掛橋數 SHALL 以提交當下的狀態判定，`bridgecount < max_bridges_on_pillar` 才可掛上。系統 MUST NOT 在不同位置使用不一致的上限比較。
4. 既有的模型碰撞、橋端離地下限與最大橋長條件照舊適用。

#### Scenario: 先遇到細柱不會留下殘橋
- **GIVEN** 支撐頭 h 的 `r_back = 0.75`；最近的柱 `r_start = 0.3` 且模型碰撞可行；次近的柱 `r_start = 0.75` 且可行
- **WHEN** 處理 h
- **THEN** h SHALL 恰有一根掛橋，終點為次近的柱
- **AND** 系統 MUST NOT 建立 h 到最近那根柱的任何桿

#### Scenario: 粗頭不掛細的中心柱
- **GIVEN** 群中心柱 `r_start = 0.3`，同群支撐頭 h 的 `r_back = 0.75`
- **WHEN** 處理 h
- **THEN** h MUST NOT 掛到中心柱，SHALL 改走下一個候選

#### Scenario: 自立柱的支撐頭沒有掛橋
- **GIVEN** 支撐頭 h 所有掛柱候選都失敗，最後提交的是自立柱
- **WHEN** 匯出支撐樹
- **THEN** 從 h 的接合點出發的掛橋數 SHALL 為 0

#### Scenario: 掛橋上限
- **GIVEN** 柱 P 的掛橋數已等於 `max_bridges_on_pillar`
- **WHEN** 驗證掛到 P 的候選
- **THEN** 該候選 SHALL 失敗

#### Scenario: L2 也不放寬粗細
- **GIVEN** 支撐頭 h 進入 L2，唯一模型可行的掛柱候選是比 h 細的柱
- **WHEN** 選取保底候選
- **THEN** 該候選 MUST NOT 被選為保底候選

### Requirement: 候選須依固定退路順序排列

每個支撐頭的候選 SHALL 依下列順序排列。同類候選依距離排序，距離相同者 SHALL 以柱 ID 由小到大排序：

- 朝地面的支撐頭（第 3 步）：群中心柱 → 其他柱 → 自立柱。
- 朝模型的支撐頭（第 4 步）：柱 → 繞路到地面 → 錨在模型上。

群中心柱 SHALL 以建立時記錄的柱 ID 指定，MUST NOT 以「離中心頭最近的柱」查詢代替。中心柱建立失敗的群，其他頭的候選 MUST NOT 含中心柱。

#### Scenario: 次佳柱優先於繞路
- **GIVEN** 朝模型的支撐頭 h，最近的柱在 L0 違規，次近的柱在 L0 通過，繞路也可行
- **WHEN** 處理 h
- **THEN** h SHALL 掛到次近的柱

#### Scenario: 中心柱建立失敗
- **GIVEN** 某群的中心柱建立失敗
- **WHEN** 處理同群的其他支撐頭
- **THEN** 它們的候選 MUST NOT 含任何被當作中心柱的柱

#### Scenario: 等距候選以柱 ID 決定
- **GIVEN** 兩根候選柱與支撐頭 h 的距離完全相同，ID 分別為 12 與 7
- **WHEN** 排列 h 的候選
- **THEN** 柱 7 SHALL 排在柱 12 之前

### Requirement: 降級狀態機

每個支撐頭 SHALL 依下列順序處理，直到提交為止：

1. **L0**（c = 0.2 mm）：依序驗證候選，提交第一個通過硬規則與間距判定者。
2. L0 全部失敗且尚未重算時，SHALL 以當下最新狀態重算一次候選清單，再回到 L0。每個支撐頭至多重算一次。
3. **L1**（c = 0）：依序驗證候選，提交第一個通過者，並 SHALL 寫一筆 info 等級的 log。
4. **L2**（保留）：提交「保底候選」，也就是重算後的候選清單中第一個通過所有硬規則者，不論其間距，並 SHALL 依「L2 保留須記錄警告」記錄。
5. 沒有任何保底候選時，SHALL 維持既有的失敗處理。

斜撐 MUST NOT 參與此狀態機。

#### Scenario: L0 成功
- **GIVEN** 支撐頭 h 的第一個候選在 L0 違規，第二個候選通過
- **WHEN** 處理 h
- **THEN** SHALL 在 L0 提交第二個候選，且不寫任何降級紀錄

#### Scenario: 重算後看見新柱
- **GIVEN** 支撐頭 h 的階段一候選在 L0 全部違規；一個 ID 較小的支撐頭剛提交的自立柱，對 h 而言在 L0 可行
- **WHEN** 處理 h
- **THEN** 系統 SHALL 重算一次，並在 L0 提交掛到該自立柱的路徑

#### Scenario: 降到 L1
- **GIVEN** 支撐頭 h 重算後在 L0 仍全部違規；某候選與障礙物的 `d = 1.1`，半徑和為 1.0
- **WHEN** 處理 h
- **THEN** SHALL 在 L1 提交該候選，並寫一筆 info log
- **AND** 匯出的 `warnings` MUST NOT 含 h

#### Scenario: 降到 L2
- **GIVEN** 支撐頭 h 在 L0、L1 都沒有任何候選通過間距判定，但有通過硬規則的候選
- **WHEN** 處理 h
- **THEN** SHALL 在 L2 提交第一個通過硬規則的候選，並記錄警告

### Requirement: L2 保留須記錄警告

每次 L2 提交，系統 SHALL：

- 以 warning 等級寫一行 log，內容 SHALL 以 `WARNING: fallback_intersection_retained` 起頭，並含支撐頭 ID、路徑類型、違規接觸數與每個接觸的座標。
- 在 support-tree 匯出的頂層 `warnings` 陣列加入一筆紀錄：`code` 為 `"fallback_intersection_retained"`；`head` 為匯出 `heads[]` 中的索引；`route` 為 `to_pillar`、`own_pillar`、`ground_route`、`model_anchor` 之一；`contacts` 中每筆含 `pos`（`[x, y, z]`）、`with`（`head_bar`、`route_bar`、`prop_bar`、`pillar`、`pinhead` 之一）、`dist` 與 `required`（兩者半徑和）。

support-tree 的 `version` SHALL 維持 2。沒有任何 L2 提交時，匯出 MUST NOT 含 `warnings` 鍵。

#### Scenario: 有保留交錯時的匯出
- **GIVEN** 一次生成中有一個支撐頭在 L2 提交，與一根掛橋的接觸距離 0.41 mm，半徑和 1.0
- **WHEN** 以 `--export-support-tree` 匯出
- **THEN** `warnings` SHALL 恰有一筆，`code` 為 `fallback_intersection_retained`，其 `contacts` 含一筆 `with` 為 `head_bar`、`dist` 為 0.41、`required` 為 1.0 的紀錄
- **AND** log SHALL 含一行以 `WARNING: fallback_intersection_retained` 起頭、含該座標的訊息

#### Scenario: 沒有保留交錯時的匯出
- **WHEN** 一次生成中沒有任何 L2 提交
- **THEN** 匯出 MUST NOT 含 `warnings` 鍵，且 `version` SHALL 為 2

### Requirement: 本變更的規則不得導致支撐頭被刪除

本能力引入的間距與避讓規則，在任何情況下 MUST NOT 導致任何支撐頭被刪除。若支撐頭因模型幾何在所有方向的物理阻擋（既有的模型干涉）而完全沒有可行路徑，SHALL 維持既有行為。

#### Scenario: 間距全滿仍保住支撐頭
- **GIVEN** 支撐頭 h 的所有候選都違反間距，但至少一個通過硬規則
- **WHEN** 處理 h
- **THEN** h MUST NOT 被刪除，SHALL 在 L2 提交

#### Scenario: 模型全向阻擋
- **GIVEN** 支撐頭 h 在所有方向都被模型阻擋，沒有任何模型可行的候選
- **WHEN** 處理 h
- **THEN** 系統 SHALL 依既有行為處理 h，且此結果與本能力的間距規則無關

### Requirement: 兩階段排程須保證確定性

第 3 步（同群其他支撐頭）與第 4 步（朝模型的支撐頭）SHALL 分兩階段執行：

- **階段一**：可多執行緒。每個支撐頭只讀取本步開始時的不可變快照，計算其候選清單，MUST NOT 寫入 builder、空間索引或任何共享狀態。
- **階段二**：單執行緒。依支撐頭 ID 由小到大，執行降級狀態機並提交；builder 的 ID 與陣列順序 SHALL 依提交順序產生。

同一模型、同一參數，這兩步產生的掛橋、繞路段、自立柱、錨柱與 `warnings` 紀錄 SHALL 逐位元相同，與執行緒數及排程無關。此要求 MUST NOT 以「基準線本身不一致」為由放寬。

#### Scenario: 多次執行結果相同
- **GIVEN** China-dragon1 與 Pikachu，以同一組參數
- **WHEN** 以預設執行緒數連續生成 4 次
- **THEN** 4 次第 3、4 步的記錄 SHALL 逐位元相同

#### Scenario: 與執行緒數無關
- **WHEN** 同一輸入分別以預設執行緒數與 `--threads 1` 生成
- **THEN** 兩者第 3、4 步的記錄 SHALL 逐位元相同

#### Scenario: 階段一看不到同輪的新柱
- **GIVEN** ID 較小的支撐頭在階段二提交了一根自立柱
- **WHEN** ID 較大的支撐頭的階段一候選被使用
- **THEN** 該候選清單 MUST NOT 含這根自立柱，除非該支撐頭依降級狀態機重算

### Requirement: 掛橋優先於斜撐

掛橋、繞路段、自立柱與錨柱 SHALL 在斜撐規劃之前提交完畢。斜撐規劃 MUST NOT 移除或改變它們；違規時 SHALL 由斜撐避讓（見 `sla-bracing-topology`）。

#### Scenario: 斜撐不改變掛橋
- **GIVEN** 一根已提交的掛橋與一根候選斜撐桿違規
- **WHEN** 規劃斜撐
- **THEN** 該掛橋 SHALL 原樣保留，該斜撐桿 MUST NOT 被建立

### Requirement: 常數不開放設定

安全間隙 0.2 mm SHALL 是與 `sla-bracing-topology` 共用的同一個引擎內常數。每個支撐頭保留的掛柱候選數上限 K 為引擎內常數，定案為 4（初值 8，依效能量測校正）。兩者 MUST NOT 經由設定檔或 API 開放。

#### Scenario: 設定不影響間隙
- **WHEN** 於切片設定中加入任何名為 `safety_clearance` 的鍵
- **THEN** 掛橋判定所用的間隙 SHALL 仍為 0.2 mm

### Requirement: 回歸與效能門檻

在驗收素材上，本能力 SHALL 滿足：

- 驗收素材為：02.stl（墊高 10 mm，密度 100 與 400）、02.stl 搭配每點隨機尺寸（支撐頭半徑 0.25 / 0.4 / 0.75，至少 5 個亂數種子）、China-dragon1、Pikachu。
- 同一支撐頭多條掛橋數、粗頭掛細柱數、重複斜撐柱對數 SHALL 為 0。
- 所有門檻 SHALL 以基準線匯出的固定支撐點清單（`evidence/baseline-*/inputs/`）為輸入判定，以隔離支撐點生成與支撐頭放置本身的不確定性。
- A、C、反向 C 的每一處剩餘違規（以 L0 間隙判定），SHALL 都對應到一筆 L1 log 或 L2 `warnings` 紀錄；沒有紀錄的違規數 SHALL 為 0。
- 柱與支撐頭的接觸中，若該柱由某支撐頭長出，而該支撐頭與被碰支撐頭兩者的膠囊體（不做共用柱剪除）間距本身即 < `r1 + r2 + 0.2 mm`，屬支撐點原生過密，不在本能力範圍內：這類接觸 SHALL 不列入上述「沒有紀錄的違規」，但其數量 SHALL 被記錄。第 3(a) 步的中心柱 MUST NOT 進入降級狀態機。
- 第 3(a) 步的中心柱 SHALL 維持原位建立，MUST NOT 因間距而移位、改道或降級。中心柱的柱身與非原生過密的支撐頭間距 < `r1 + r2 + 0.2 mm` 時，系統 SHALL 以 info 等級寫一行 log，內容以 `centroid_pillar_clearance_recorded` 起頭，並含柱 ID、支撐頭 ID、距離、門檻與接觸座標；這類接觸視為已記錄的邊界，SHALL 不列入「沒有紀錄的違規」，其數量 SHALL 計入生成結束的摘要 log。
- 被刪除的支撐頭數 MUST NOT 多於改動前的引擎。
- 第 3、4 步的合計耗時 SHALL ≤ T + max(0.1 × T, 50 ms)，T 為改動前（`release/v1.0.6` 合入 planar 後）於同一台機器、同一編譯設定下的量測值。
- L1 次數、L2 次數、柱數與桿數 SHALL 被記錄，供人判讀趨勢，不作為通過門檻。

#### Scenario: 驗收素材無未記錄的違規
- **WHEN** 以本變更的引擎為所有驗收素材生成支撐
- **THEN** D、粗頭掛細柱與重複斜撐柱對 SHALL 皆為 0
- **AND** 沒有紀錄的 A、C、反向 C 違規 SHALL 為 0

#### Scenario: 原生過密的支撐頭不列入未記錄違規
- **GIVEN** 中心柱 P 由支撐頭 h1 長出，支撐頭 h1 與 h2 的膠囊體間距 0.9 mm，兩者 `r_back` 皆為 0.5（門檻 1.2 mm）
- **WHEN** P 的柱身與 h2 的間距不足門檻
- **THEN** 這一處 MUST NOT 計入沒有紀錄的反向 C 違規，且 SHALL 計入原生過密的數量
- **AND** P MUST NOT 因此改走降級狀態機

#### Scenario: 中心柱貼近非原生過密的支撐頭
- **GIVEN** 中心柱 P 的柱身與支撐頭 h2 的間距 1.16 mm，門檻 1.2 mm；長出 P 的支撐頭與 h2 的膠囊體間距 ≥ 門檻（不是原生過密）
- **WHEN** 第 3(a) 步建立 P
- **THEN** P SHALL 照原位建立，且 MUST NOT 進入降級狀態機
- **AND** log SHALL 含一行以 `centroid_pillar_clearance_recorded` 起頭、含 P、h2 與接觸座標的訊息
- **AND** 這一處 SHALL 視為已記錄，MUST NOT 計入沒有紀錄的反向 C 違規

#### Scenario: 支撐頭不因本變更減少
- **WHEN** 以改動前與改動後的引擎為同一驗收素材生成支撐
- **THEN** 改動後被刪除的支撐頭數 MUST NOT 多於改動前

#### Scenario: 效能門檻
- **GIVEN** 改動前第 3、4 步合計耗時 T
- **WHEN** 以本變更的引擎在同一台機器、同一編譯設定下量測
- **THEN** 耗時 SHALL ≤ T + max(0.1 × T, 50 ms)
