## Why

自動支撐的斜撐（pillar 之間的鋸齒桁架）會越過旁邊的柱子連到遠處，也會彼此交叉、穿過第三根柱，畫面雜亂且多出不必要的桿件；手動支撐疊在自動支撐上時，同樣的規則（前端照抄引擎）也讓兩者互相交錯。根因全在 `DefaultSupportTree::interconnect_pillars()`：

1. **鄰柱滿了就跳過**（`DefaultSupportTree.cpp:1055`）：最近的柱已連滿 3 根，就改連 10 mm 內更遠的柱，桿子越過近鄰。自動樹完成後多數柱已滿，新柱幾乎必然跨接。
2. **比我細就跳過**（`:1056`）：每點尺寸上線後，粗柱會略過旁邊的細柱去連遠處的粗柱。
3. **連了不算數**（`:1068-1074`）：高度比 < 0.5 時橋照建、計數不加，迴圈持續找下一個，多出額外桿件。
4. **沒有任何桿對桿、桿對柱檢查**：`interconnect()` 只檢查模型碰撞。

前端 DS-online 即將以同一套規則重寫手動支撐的橋接預覽，引擎必須先成為可驗證的標準，否則兩份實作會各自漂移。

## What Changes

- 斜撐改為「全域由短到長」的貪婪建立：先收集全部候選連線，按俯視距離排序後依序嘗試，近距連線優先成網，遠距連線不能搶先佔位。
- 斜撐對斜撐採**嚴格俯視無交錯**：不共用柱的兩組斜撐，俯視距離須 ≥ `r1 + r2 + safety_clearance`；共用同一柱的兩組斜撐，俯視夾角須 ≥ 20°，避免樹脂殘留與溢光沾黏。
- 斜撐不得穿過第三根柱（俯視軸心距離 ≥ `r_bar + r_pillar + safety_clearance`）。
- 計數拆分：`links` 維持原義（結構剛性，保留 0.5 高度比規則，只用於決定輔助柱與救援）；新增 `pairs`（配對數，上限 3，達上限即停止配對）。
- 已滿柱不再被連，改為俯視圓形障礙物，阻擋越過它的遠距連線。
- 每根桿件帶 `kind`：`truss`（斜撐）、`head`（頭部掛橋）、`prop`（輔助柱橋）、`route`（繞路段），於建立當下標記，禁止以幾何推斷。斜撐對 `head` / `prop` / `route` / 缺 `kind` 的 legacy 桿，改用立體間距判定（俯視相近時算兩桿的 3D 最短距離，即「Z 高度差判定」的精確形式）。
- 孤立救援：貪婪結束後 `links = 0` 且高度 > 15 mm 的柱，於輔助柱階段之前，以立體間距規則取代嚴格俯視規則重試一次。
- 移除「比我細就跳過」。
- 修正輔助柱階段重跑 cascade 時未排除凍結柱的問題（`DefaultSupportTree.cpp:1238`，與 `:1088` 的註解矛盾）。
- 匯出格式新增選填欄位：support-tree 的 `bridges[].kind`、`pillars[].pairs`；prior-pillar 的 `pillars[].pairs`、`attached_to[].pairs`。**不升版號**。
- 建立共通幾何測試向量正本 `third_party/prusaslicer_fork/tests/data/sla_bracing_vectors/` 與 `MANIFEST.sha256`，作為 DS-online 移植的唯一標準。
- 預設輸出的斜撐幾何會改變（刻意的行為變更）；既有以「改動前逐位元相同」為基準的支撐網格黃金檔需重建。

## 架構取捨

**為什麼不用通用 3D 線段距離或 BVH。** 每一根桿都是直線，必定落在「其俯視投影線正上方的垂直面」內，因此兩根桿要相碰，俯視投影必定相近。俯視檢查是不會漏判的必要條件，可作為粗篩；只有俯視相近的少數桿對，才需要算 3D 線段最短距離，每對計算量為 O(1)。（只比較交叉點高度差並不足夠：兩根傾斜桿的真實間距等於高度差乘上不大於 1 的方向係數，只看高度差會高估間距。）同一對柱之間的所有鋸齒桿共用同一條俯視線段，因此斜撐對斜撐的嚴格判定以「一對柱」為單位，不必逐桿比較。候選數約為柱數的 1.5 倍，以既有的 `BoxIndex`（`SLA/SpatIndex.hpp:66`，2D R* 樹）做外擴包圍盒查詢即可，不需引入 3D BVH。

**為什麼不是全部嚴格擋下。** 頭部掛橋、輔助柱橋與繞路段都位於柱頂附近或繞模型而行，與下方的鋸齒斜撐高度通常錯開。若一律以俯視交叉擋下，每根主柱最多 3 根往外放射的掛橋會封鎖大量斜撐，孤立柱激增。因此只有斜撐對斜撐採嚴格俯視規則（這是使用者看到「交錯、多餘」的主體），其餘一律用立體間距判定。孤立救援則是嚴格規則的安全網，只在柱子會因此變成孤立高柱時才放寬。

**為什麼是全域由短到長，而不是沿用逐柱 cascade。** 逐柱 cascade 的結果取決於空間索引的走訪順序，先被處理的柱可以搶走遠距連線，封鎖後來的近距連線。全域排序讓結果與走訪順序無關，並以 `(距離, 小編號, 大編號)` 打破平手，確保決定性。

**為什麼拆兩個計數而不是修掉 0.5 規則。** 0.5 規則是刻意設計：矮柱撐不住高柱，不應算作結構支撐，且這個計數決定是否長輔助柱。若全部計入，高柱會被矮柱「填滿」而失去輔助柱，自動支撐變弱。真正的缺陷是「不算數」讓搜尋停不下來，因此另立 `pairs` 控制搜尋終止。

## 相容性策略

- support-tree 維持 `version: 2`、prior-pillar 維持 `version: 1`，只新增選填欄位；舊讀取端忽略未知欄位即可。
- 讀到缺 `pairs` 的柱：以 `links` 代替。
- 讀到缺 `kind` 的桿：視為 legacy，一律以立體間距規則判定，MUST NOT 以幾何推斷型態。
- `kind` 一律寫出（缺值代表 legacy，不能比照其他欄位省略預設值）。每根桿約增加十餘位元組，數千根桿的自動樹約增加數十 KB。
- `safety_clearance = 0.2 mm`、同柱夾角下限 20°、配對上限 3、救援高度門檻 15 mm 皆為引擎內常數，不開放 API。

## 非目標

- branching 樹（`BranchingTreeSLA`）不在範圍內。
- 模型碰撞檢查（`bridge_mesh_distance`）的方式不變。
- 頭部掛橋、繞路段的生成邏輯不變，只作為障礙物參與判定。
- 引擎的疊加路徑（`--prior-supports`）只收到凍結柱，沒有舊桿資料，因此無法檢查新斜撐與舊桿的交叉，列為已知限制。前端目前未使用此路徑。
- 「按下自動產生會清除該模型手動支撐」的前端行為不變。
- DS-online 的 JS 移植另立變更（建議名稱 `port-bracing-planar-topology`），待本變更驗收後進行。

## 風險與指標

- **孤立柱增加**：嚴格規則會減少斜撐。指標：`links = 0` 且高度 > 15 mm 的柱數 MUST NOT 多於基準線；輔助柱數與桿件總數記錄趨勢。
- **站在模型上的柱造成誤擋**：嚴格俯視的穿柱規則不看柱的 Z 範圍，腳在半空的柱仍會擋下從其下方通過的斜撐。救援不放寬穿柱規則。以同一指標監看，必要時另立變更。
- **效能**：連接階段耗時增量 MUST NOT 超過 max(10%, 50 ms)。
- **決定性**：`routing_to_model` 本來就是平行執行，可能已有不穩定。先量現況作為基準，避免把既有不確定性算到本變更頭上。
- **常數未經實測**：0.2 mm 與 20° 尚無列印實驗依據，先寫死為常數，後續以實驗校正。

## Capabilities

### New Capabilities
- `sla-bracing-topology`：SLA 預設支撐樹中，柱與柱之間斜撐的建立順序、配對上限與結構計數、障礙物與交錯規則、桿件型態、孤立救援，以及相關匯出欄位與共通幾何測試向量的契約。

### Modified Capabilities
（無。`per-point-support-geometry` 的「全為哨兵時逐位元不變」以該變更之前為基準，本變更不修改其需求文字，但依該不變式產生的黃金檔需重建。）

## Impact

- **引擎（`third_party/prusaslicer_fork/src/libslic3r/SLA/`）**：`DefaultSupportTree.cpp`（`interconnect_pillars`、`interconnect`、`connect_to_nearpillar` 的 kind 標記、輔助柱階段）、`SupportTreeBuilder.hpp`（`Bridge`、`Pillar`）、`SupportTree.hpp`（`TreeBridge`、`TreePillar`、`PriorPillar`、`PriorAttachment`）、`SupportTree.cpp`（匯出）、`SupportTreeIO.hpp`、`PriorPillarIO.hpp`、`SupportTreeUtils.hpp` / `SupportTreeUtilsLegacy.hpp`（route 標記）；新增 `BracingPlanner.{hpp,cpp}`。
- **測試**：`tests/sla_print/` 新增向量與量測測試；新增 `tests/data/sla_bracing_vectors/`。
- **後端 API**：`GET /slices/{id}/support-tree`、`GET /slices/{id}/support-pillars` 的回應多出選填欄位；`agent/` 原樣轉送，不需改程式。
- **下游**：DS-online 的 `supportInterconnect.js`、`supportGraph.js`、`supportTreeDrag.js`、`supportTreeFromPreview.js`、`sceneCoordinator.js` 需在後續變更中移植規則並承接 `pairs` / `kind`。
