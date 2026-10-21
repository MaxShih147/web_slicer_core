# sla-bracing-topology Specification

## Purpose
定義 SLA 預設支撐樹（`DefaultSupportTree`）柱與柱之間斜撐（bracing）的平面拓撲規則：候選如何全域排序與判定、斜撐之間與斜撐對其他桿件的俯視與立體間距、穿柱與緊貼柱叢集、孤立高柱的救援與保底連接、桿件型態與配對計數的交換格式，以及 C++ 引擎與 DS-online 前端共用的幾何測試向量與驗收門檻。由變更 sla-bracing-planar-topology 建立。

## Requirements
### Requirement: 斜撐候選須全域由短到長建立

預設支撐樹（`DefaultSupportTree`）於連接柱子階段 SHALL 先收集全部候選連線，再依序嘗試建立，MUST NOT 沿用逐柱 cascade 的走訪順序。

候選連線 SHALL 由每一根非凍結柱與其俯視距離 ≤ `max_pillar_link_distance_mm` 的其他柱組成；超出此距離的柱對不是候選，不回報原因。柱的俯視位置 SHALL 取其軸心（`endpt` 的 X、Y）。兩端皆為凍結柱的候選 MUST NOT 列入。系統 MUST NOT 因候選柱的 `r_start` 小於自身而略過它。

候選 SHALL 依排序鍵 `(俯視距離, 兩端較小編號, 兩端較大編號)` 升序排序；距離 SHALL 以未經捨入的浮點值比較。

每個候選 SHALL 依下列順序檢查，第一個不通過的項目即為其拒絕原因：

1. `too_close`：俯視距離 < `2 × head_back_radius_mm`
2. `pair_cap`
3. `obstacle_pillar`
4. `shared_angle`
5. `cross_truss`
6. 逐桿判定（模型碰撞與 `z_clear_fail`）：至少一根桿建立即視為該組建立；全部未建立時，若任何一根是因 `z_clear_fail` 被擋，原因 SHALL 為 `z_clear_fail`，否則為模型碰撞。兩柱的可用長度連一根桿都放不下時（鋸齒桿產生結果為空），原因 SHALL 為 `no_room`

#### Scenario: 近鄰先成網，遠距連線不越過近鄰
- **GIVEN** 三根等高、等粗的柱 A(0,0)、B(4,0)、C(8,0)，`max_pillar_link_distance_mm` 為 10
- **WHEN** 執行連接柱子階段
- **THEN** 嘗試順序 SHALL 為 A–B、B–C、A–C
- **AND** A–B 與 B–C SHALL 建立
- **AND** A–C SHALL 因穿過 B 而被拒絕

#### Scenario: 等距候選以編號決定先後
- **GIVEN** 柱 0–1 與柱 2–3 的俯視距離完全相同
- **WHEN** 排序候選
- **THEN** 0–1 SHALL 排在 2–3 之前

#### Scenario: 粗柱不略過旁邊的細柱
- **GIVEN** 粗柱 A（`r_start` 1.0）的最近鄰居為細柱 M（`r_start` 0.5），更遠處另有粗柱 H
- **WHEN** 執行連接柱子階段
- **THEN** A–M SHALL 先於 A–H 被嘗試
- **AND** A–M MUST NOT 因 M 較細而被略過

#### Scenario: 凍結柱之間不產生候選
- **GIVEN** 兩根凍結柱彼此相距 5 mm
- **WHEN** 收集候選
- **THEN** 兩者之間 MUST NOT 產生候選連線

### Requirement: 計數須拆分為結構計數與配對計數

每根柱 SHALL 攜帶兩個計數。

`links`（結構計數）SHALL 維持既有語意：一組斜撐建立後，對其中一端，僅在「該端高度 < 15 mm」或「另一端高度 ÷ 該端高度 > 0.5」時加 1。`links` SHALL 只用於決定輔助柱數量與孤立救援，MUST NOT 用於決定是否停止配對。

`pairs`（配對計數）SHALL 在每建立一組斜撐時，對兩端各加 1，不論高度比。任一端 `pairs` 已達 3 時，該候選 SHALL 被拒絕（原因 `pair_cap`）。例外只有兩個：輔助柱的斜撐不看配對上限（見「輔助柱斜撐」需求），保底連接改看 `links`（見「孤立高柱須經保底連接」需求）。

一組候選的所有斜撐桿都未能建立時，該組 SHALL 視為未建立，兩個計數 MUST NOT 增加。

#### Scenario: 高度比不足時仍計入配對數
- **GIVEN** 柱 A 高 30 mm、柱 B 高 10 mm，兩者之間的斜撐成功建立
- **THEN** A 與 B 的 `pairs` SHALL 各加 1
- **AND** A 的 `links` MUST NOT 增加（10 ÷ 30 不大於 0.5 且 A 不低於 15 mm）
- **AND** B 的 `links` SHALL 加 1（B 低於 15 mm）

#### Scenario: 配對數達上限即停止配對
- **GIVEN** 柱 A 的 `pairs` 為 3、`links` 為 1
- **WHEN** 候選 A–E 輪到嘗試
- **THEN** A–E SHALL 被拒絕，原因為 `pair_cap`

#### Scenario: 全部斜撐桿被擋下不計數
- **GIVEN** 候選 A–B 通過所有俯視規則，但每一根斜撐桿都撞到模型
- **WHEN** 嘗試建立 A–B
- **THEN** A 與 B 的 `pairs` 與 `links` MUST NOT 改變

### Requirement: 已滿柱須成為障礙物

`pairs` 已達 3 的柱 SHALL 不再被連，但 SHALL 以俯視圓形障礙物身分參與後續候選的穿柱判定。

#### Scenario: 已滿柱擋下越過它的遠距連線
- **GIVEN** 柱 B(4,0) 的 `pairs` 為 3，柱 A(0,0) 與柱 C(8,0.5) 皆未滿，各柱半徑 0.5
- **WHEN** 候選 A–C 輪到嘗試
- **THEN** A–C SHALL 被拒絕，原因為 `obstacle_pillar`

#### Scenario: 不經過已滿柱的連線不受影響
- **GIVEN** 同上，另有柱 D(4,6) 未滿
- **WHEN** 候選 A–D 輪到嘗試
- **THEN** A–D MUST NOT 因 B 已滿而被拒絕

### Requirement: 緊貼柱須視為同一叢集

兩根柱的軸心俯視距離 < `r1 + r2 + safety_clearance`（`r` 為各自的 `r_start`）時，兩者 SHALL 視為緊貼。緊貼關係 SHALL 依連通性合併成叢集：A 緊貼 B、B 緊貼 C，則 A、B、C 同屬一個叢集。叢集 SHALL 以全部柱計算，包含凍結柱、已滿柱與不參與配對的短柱；輔助柱加入時 SHALL 一併併入。

在斜撐的位置規則中，同一叢集的柱 SHALL 視為同一根柱：

- 穿柱：候選任一端所屬叢集內的其他柱 MUST NOT 觸發 `obstacle_pillar`。
- 斜撐對斜撐：兩組斜撐若各有一端落在同一個叢集，SHALL 視為共用柱，只做同柱夾角判定，MUST NOT 做 `cross_truss` 距離判定。夾角 SHALL 以兩組各自端柱的軸心為起點量測。
- 逐桿判定：非斜撐桿的端柱與斜撐組的端柱同屬一個叢集時，SHALL 比照共用柱豁免；救援與保底比對斜撐桿時亦同。

叢集 MUST NOT 改變 `too_close`、配對上限、計數與候選收集；同一叢集的兩柱之間仍可成為候選。

#### Scenario: 緊貼柱互不擋路
- **GIVEN** 柱 A(0,0) 與柱 A'(0.9,0) 半徑皆為 0.5（距離 0.9 < 1.2，同一叢集），柱 X(0,6)
- **WHEN** 候選 A'–X 輪到嘗試
- **THEN** A'–X MUST NOT 因 A 而被拒絕為 `obstacle_pillar`

#### Scenario: 叢集以連通性合併
- **GIVEN** 柱 A(0,0)、B(1.1,0)、C(2.2,0)，半徑皆為 0.5
- **WHEN** 計算叢集
- **THEN** A、B、C SHALL 屬於同一個叢集（A 與 C 距離 2.2，但都緊貼 B）

#### Scenario: 恰等於門檻不算緊貼
- **GIVEN** 兩柱半徑皆為 0.5，軸心距離恰為 1.2
- **WHEN** 計算叢集
- **THEN** 兩者 MUST NOT 屬於同一個叢集

#### Scenario: 叢集出發的斜撐以夾角判定
- **GIVEN** 柱 A(0,0) 與 A'(0.9,0) 同一叢集，已建立斜撐 A–X，X 在 A 的 0° 方向 6 mm 處
- **WHEN** 候選 A'–Y 輪到嘗試，Y 在 A' 的 45° 方向
- **THEN** A'–Y MUST NOT 被拒絕為 `cross_truss`
- **AND** 若 Y 改在 A' 的 10° 方向，A'–Y SHALL 被拒絕，原因為 `shared_angle`

### Requirement: 斜撐對斜撐須俯視無交錯

兩組不共用柱的斜撐，其俯視線段（兩柱軸心連線）之間的最短距離 SHALL ≥ `r1 + r2 + safety_clearance`，其中 `r1`、`r2` 為兩組斜撐的桿半徑。不滿足時，較晚嘗試的候選 SHALL 被拒絕（原因 `cross_truss`）。

是否共用柱 SHALL 以柱編號判定，MUST NOT 以端點距離推斷；同一叢集的柱比照共用柱（見「緊貼柱須視為同一叢集」）。共用柱的兩組斜撐 SHALL 豁免上述距離規則，但兩者自共用柱出發的俯視方向夾角 SHALL ≥ 20°；不滿足時，較晚嘗試的候選 SHALL 被拒絕（原因 `shared_angle`）。

斜撐的桿半徑 SHALL 取兩端柱 `r_start` 的較小者。

#### Scenario: X 形交叉被拒絕
- **GIVEN** 已建立斜撐 A(0,0)–B(6,6)
- **WHEN** 候選 C(0,6)–D(6,0) 輪到嘗試
- **THEN** C–D SHALL 被拒絕，原因為 `cross_truss`

#### Scenario: T 形接觸被拒絕
- **GIVEN** 已建立斜撐 A(0,0)–B(8,0)
- **WHEN** 候選 C(4,5)–D(4,0.1) 輪到嘗試，且 D 不是 A 或 B
- **THEN** C–D SHALL 被拒絕，原因為 `cross_truss`

#### Scenario: 共用柱且夾角足夠
- **GIVEN** 已建立斜撐 A–B，方向 0°
- **WHEN** 候選 A–C 方向 45° 輪到嘗試
- **THEN** A–C MUST NOT 因與 A–B 相交於 A 而被拒絕

#### Scenario: 共用柱但夾角過小
- **GIVEN** 已建立斜撐 A–B，方向 0°
- **WHEN** 候選 A–C 方向 19° 輪到嘗試
- **THEN** A–C SHALL 被拒絕，原因為 `shared_angle`
- **AND** 方向 21° 的候選 MUST NOT 因夾角被拒絕

#### Scenario: 平行斜撐的距離門檻
- **GIVEN** 兩組平行、不共用柱的斜撐，桿半徑皆為 0.5，`safety_clearance` 為 0.2
- **WHEN** 兩者俯視距離為 1.2 − 1e-6
- **THEN** 較晚者 SHALL 被拒絕，原因為 `cross_truss`
- **AND** 距離為 1.2 + 1e-6 時 MUST NOT 被拒絕

#### Scenario: 共線且重疊被拒絕
- **GIVEN** 已建立斜撐 A(0,0)–B(10,0)
- **WHEN** 候選 C(3,0)–D(7,0) 輪到嘗試，四柱互不相同
- **THEN** C–D SHALL 被拒絕，原因為 `cross_truss`

#### Scenario: 部分重疊時端柱先擋下
- **GIVEN** 已建立斜撐 A(0,0)–B(6,0)
- **WHEN** 候選 C(3,0)–D(9,0) 輪到嘗試，四柱互不相同
- **THEN** C–D SHALL 被拒絕，原因為 `obstacle_pillar`（柱 B 位於 C–D 上，穿柱檢查先於交錯檢查）

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

### Requirement: 斜撐不得穿過第三根柱

一組斜撐的俯視線段，到任何非其兩端的柱軸心的距離 SHALL ≥ `r_bar + r_pillar + safety_clearance`。不滿足時該候選 SHALL 被拒絕（原因 `obstacle_pillar`）。此規則 SHALL 適用於所有柱，包含凍結柱與已滿柱，且 MUST NOT 考慮柱的高度範圍。唯一的例外是與任一端同叢集的柱（見「緊貼柱須視為同一叢集」）。

#### Scenario: 中間柱擋路
- **GIVEN** 柱 A(0,0)、B(4,0.3)、C(8,0)，半徑皆為 0.5，B 未滿
- **WHEN** 候選 A–C 輪到嘗試
- **THEN** A–C SHALL 被拒絕，原因為 `obstacle_pillar`

#### Scenario: 腳站在模型上的柱仍為障礙物
- **GIVEN** 柱 B 的底端位於模型上、高於地面 20 mm，且 B 的軸心位於候選 A–C 的俯視線段上
- **WHEN** 候選 A–C 輪到嘗試
- **THEN** A–C SHALL 被拒絕，原因為 `obstacle_pillar`

### Requirement: 孤立高柱須經一次救援

全域貪婪結束後，對每一根非凍結、`links` 為 0 且高度 > 15 mm 的柱，系統 SHALL 依原排序鍵重新嘗試其候選一次。救援時，「斜撐對斜撐俯視無交錯」中的距離規則 SHALL 改為逐桿判定：新斜撐組的每一根桿，與俯視相近的每一根既有斜撐桿之間，套用「斜撐桿對非斜撐桿」的立體間距規則；穿柱規則、同柱夾角規則、配對上限與距離範圍 SHALL 照常適用。

救援 SHALL 在輔助柱階段之前執行。救援成功的柱 SHALL 依一般規則更新 `links` 與 `pairs`。

#### Scenario: 救援成功
- **GIVEN** 柱 P 高 30 mm，貪婪結束後 `links` 為 0；其唯一候選 P–Q 因與已建立的 X–Y 俯視交叉而被拒絕，但相近的斜撐桿之間 3D 最短距離皆 ≥ 1.2 mm
- **WHEN** 執行救援
- **THEN** P–Q SHALL 建立
- **AND** P 的 `links` SHALL 依高度比規則更新

#### Scenario: 救援失敗則交給輔助柱階段
- **GIVEN** 同上，但所有 P–Q 斜撐桿與相近既有斜撐桿的 3D 最短距離皆 < 1.2 mm
- **WHEN** 執行救援
- **THEN** P–Q MUST NOT 建立
- **AND** 若輔助柱開啟，P SHALL 照既有規則進入輔助柱階段

#### Scenario: 救援不放寬穿柱規則
- **GIVEN** 孤立高柱 P 的候選 P–Q 穿過第三根柱 R
- **WHEN** 執行救援
- **THEN** P–Q SHALL 仍被拒絕，原因為 `obstacle_pillar`

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

### Requirement: 孤立高柱須經保底連接

全域貪婪、救援與輔助柱階段全部結束後，對每一根非凍結、可配對、`links` 為 0 且高度 > 15 mm 的柱，系統 SHALL 執行保底連接。輔助柱關閉時，保底連接 SHALL 照常執行。

保底連接的候選 SHALL 為該柱與俯視距離 ≤ `max_pillar_link_distance_mm` 的其他可配對柱（含凍結柱），且只收能讓該柱得到 `links` 的對象（對方高度 ÷ 該柱高度 > 0.5）。候選 SHALL 依原排序鍵 `(距離, 小編號, 大編號)` 嘗試，資格於走訪中即時重算；該柱一得到 `links` 即停止。

保底連接的判定與救援相同（`cross_truss` 改為逐桿 3D 判定：新斜撐桿與俯視相近的既有斜撐桿之間 `seg_seg_dist3d ≥ r1 + r2 + safety_clearance`；非斜撐桿照常判定），差別只有配對上限：保底連接 SHALL 改以兩端的 `links` 判定，`links` 已達 3 的一端 SHALL 拒絕（原因 `pair_cap`），`pairs` 達 3 MUST NOT 阻擋。穿柱、同柱夾角、`too_close`、模型碰撞 SHALL 照常適用。

保底連接建立的斜撐 SHALL 與救援斜撐一樣，不計入俯視違規數的門檻，但 SHALL 被記錄。

#### Scenario: 鄰居配對已滿仍可保底
- **GIVEN** 柱 P 高 30 mm，三個階段後 `links` 為 0；最近的等高鄰居 Q 的 `pairs` 為 3、`links` 為 2
- **WHEN** 執行保底連接
- **THEN** P–Q SHALL 建立
- **AND** P 的 `links` SHALL 變為 1，Q 的 `pairs` SHALL 變為 4

#### Scenario: 結構計數已滿的鄰居不被連
- **GIVEN** 同上，但 Q 的 `links` 為 3
- **WHEN** 執行保底連接
- **THEN** P–Q SHALL 被拒絕，原因為 `pair_cap`，系統 SHALL 嘗試下一個候選

#### Scenario: 矮鄰居不是保底對象
- **GIVEN** 柱 P 高 30 mm，範圍內只有高 10 mm 的鄰居
- **WHEN** 執行保底連接
- **THEN** 系統 MUST NOT 建立任何斜撐（建了也不會讓 P 得到 `links`）

#### Scenario: 保底仍不穿柱
- **GIVEN** 孤立高柱 P 的唯一保底候選穿過第三根不同叢集的柱
- **WHEN** 執行保底連接
- **THEN** 該候選 SHALL 被拒絕，原因為 `obstacle_pillar`

### Requirement: 桿件須帶型態

每一根桿件 SHALL 帶 `kind`，於建立當下由建立點寫入，MUST NOT 事後以幾何推斷：

- `truss`：`interconnect()` 建立的斜撐，包含主柱與輔助柱之間的斜撐。
- `head`：支撐頭掛到鄰柱的橋，包含先長一段自身短柱再掛過去的情況。
- `prop`：主柱頂端連到輔助柱頂端的橋。
- `route`：繞過模型尋找地面的折線段，包含 `DiffBridge`。

support-tree 匯出的每一筆 `bridges` 記錄 SHALL 帶 `kind`，且 SHALL 一律寫出，MUST NOT 比照其他欄位省略。

#### Scenario: 匯出的每根桿皆有型態
- **WHEN** 以 `--export-support-tree` 匯出一棵含斜撐、掛橋與輔助柱的支撐樹
- **THEN** 每一筆 `bridges` 記錄 SHALL 帶 `kind`，值 SHALL 為 `truss`、`head`、`prop`、`route` 之一

#### Scenario: 型態與建立來源一致
- **GIVEN** 一棵同時含 `interconnect()` 斜撐與 `connect_to_nearpillar()` 掛橋的支撐樹
- **WHEN** 匯出
- **THEN** 前者 SHALL 為 `truss`，後者 SHALL 為 `head`

### Requirement: 交換格式擴充須向後相容

support-tree 格式 SHALL 維持 `version: 2`，新增 `bridges[].kind` 與 `pillars[].pairs`。prior-pillar 格式（`--prior-supports` 輸入與 support-pillars 輸出）SHALL 維持 `version: 1`，新增選填的 `pillars[].pairs` 與 `attached_to[].pairs`。

讀取端遇到缺 `pairs` 的柱，SHALL 以該柱的 `links` 代替。遇到缺 `kind` 的桿，SHALL 視為 legacy 並以立體間距規則判定。

#### Scenario: 舊版 prior-pillar 清單可被讀取
- **GIVEN** 一份不含 `pairs` 的 prior-pillar 清單，某柱 `links` 為 2
- **WHEN** 以 `--prior-supports` 載入
- **THEN** 載入 SHALL 成功
- **AND** 該柱的 `pairs` SHALL 視為 2

#### Scenario: 版本號不變
- **WHEN** 匯出 support-tree 與 support-pillars
- **THEN** 前者 `version` SHALL 為 2，後者 SHALL 為 1

#### Scenario: 回報附著對象的配對數
- **GIVEN** 本次生成連到一根凍結柱
- **WHEN** 匯出 support-pillars
- **THEN** `attached_to` 中該柱的記錄 SHALL 帶 `pairs`，值為本次生成後的配對數

### Requirement: 凍結柱不得成為配對的發起端

凍結柱（prior pillar）SHALL 只作為候選的一端與障礙物，MUST NOT 發起配對，也 MUST NOT 被輔助柱。輔助柱階段結束後，若需處理新加入的輔助柱，系統 MUST NOT 對凍結柱重新發起配對。

#### Scenario: 輔助柱階段不重新處理凍結柱
- **GIVEN** 一次生成帶有凍結柱，且長出了輔助柱
- **WHEN** 輔助柱階段結束
- **THEN** 凍結柱之間 MUST NOT 新增任何斜撐
- **AND** 凍結柱的計數只能因與新柱之間的斜撐而增加

### Requirement: 判定門檻與常數

所有俯視距離、3D 距離與夾角判定 SHALL 採「嚴格小於門檻才拒絕」，恰等於門檻 SHALL 接受。

下列值 SHALL 為引擎內常數，MUST NOT 經由設定檔或 API 開放：`safety_clearance = 0.2 mm`、同柱夾角下限 20°、配對上限 3、救援高度門檻 15 mm。

#### Scenario: 恰等於門檻時接受
- **GIVEN** 兩組平行斜撐的俯視距離恰等於 `r1 + r2 + safety_clearance`
- **WHEN** 判定
- **THEN** 較晚者 MUST NOT 被拒絕

#### Scenario: 常數不受設定影響
- **WHEN** 於切片設定中加入任何名為 `safety_clearance` 的鍵
- **THEN** 斜撐判定所用的間隙 SHALL 仍為 0.2 mm

### Requirement: 共通幾何測試向量

`third_party/prusaslicer_fork/tests/data/sla_bracing_vectors/` SHALL 為斜撐規則的測試向量正本，每個案例為一個 JSON 檔，內容 SHALL 包含：

- `cfg`：`safety_clearance`、`min_shared_angle_deg`、`pair_cap`、`max_link_distance`、`min_pillar_distance`、`rescue_height`，以及產生鋸齒桿所需的 `bridge_slope_deg`、`ground_z`、`base_height`、`connection_mode`
- `pillars`：`{id, endpoint, height, r, links, pairs, frozen}`
- `bars`：既有桿件 `{startp, endp, r, kind, a, b}`
- `expect`：`accepted`（依建立順序列出的 `{pair, bars_built}`）與 `rejected`（`{pair, reason}`）；`bars_built` 為該組實際建立的桿數。向量依序執行全域貪婪、救援與保底連接（向量不含輔助柱）

原因代碼 SHALL 為 `too_close`、`pair_cap`、`obstacle_pillar`、`shared_angle`、`cross_truss`、`z_clear_fail`、`no_room` 之一。向量 MUST NOT 依賴模型網格；模型碰撞 SHALL 於執行向量時視為全數通過。

目錄 SHALL 含 `MANIFEST.sha256`，逐行列出每個向量檔的 SHA-256。引擎測試 SHALL 執行全部向量，並驗證 `MANIFEST.sha256` 與實際檔案一致。

案例 SHALL 至少涵蓋：X 交叉、T 字、共用端點、同柱夾角 19° 與 21°、共線重疊、共線不重疊、平行距離門檻 ±1e-6、中間柱擋路、已滿柱擋路、head 桿高度錯開與未錯開、腳站在模型上的柱、等距平手、長度為 0 的候選、救援成功、救援失敗、配對上限、「單一非凍結新柱對全凍結板」、緊貼柱叢集（互不擋路、連通合併、恰等於門檻、叢集夾角）、保底連接（鄰居配對已滿、鄰居結構計數已滿、矮鄰居），以及一個 `ground_z` 不為 0、座標系混用（Z 偏移一個模型底面高度）時決策必定不同的案例。

#### Scenario: 引擎通過全部向量
- **WHEN** 執行引擎的斜撐向量測試
- **THEN** 每個向量的實際接受順序與拒絕原因 SHALL 與 `expect` 完全相同

#### Scenario: 清單不一致即失敗
- **GIVEN** 某個向量檔被修改但 `MANIFEST.sha256` 未更新
- **WHEN** 執行引擎的斜撐向量測試
- **THEN** 測試 SHALL 失敗

#### Scenario: 單一新柱情境
- **GIVEN** 一個向量中只有一根非凍結柱，其餘皆為凍結柱且附帶既有桿件
- **WHEN** 執行向量
- **THEN** 只有包含該新柱的候選 SHALL 被嘗試
- **AND** 結果 SHALL 與 `expect` 相同

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

### Requirement: 同一對柱只能有一組斜撐

斜撐 SHALL 以無序柱對（canonical pair，`(min(a,b), max(a,b))`）為唯一鍵。任何建立斜撐的路徑，包含全域貪婪、救援、保底、`attach()` 與 `run_greedy_for()`，MUST NOT 對已有斜撐的柱對建立任何桿。全域貪婪、救援、保底與 `run_greedy_for()` 在產生候選時 SHALL 排除已有斜撐的柱對，因此不會產生該柱對的決策；`attach()` 由呼叫者直接指定柱對，遇到已有斜撐的柱對 SHALL 拒絕，原因為 `duplicate_pair`。`duplicate_pair` SHALL 加入原因代碼與向量格式，既有原因代碼的意義不變。

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

