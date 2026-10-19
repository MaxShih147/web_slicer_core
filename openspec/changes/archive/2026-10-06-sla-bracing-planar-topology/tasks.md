## 1. 基準線量測（改動前）

- [x] 1.1 在 `tests/sla_print/` 新增量測輔助函式 `bracing_metrics(const SupportTreeBuilder&)`，直接讀取 builder 內部的 `crossbridges()`、`bridges()`、`pillars()`（不依賴匯出格式，因為改動前沒有 `kind`），輸出：斜撐俯視違規數（依兩端柱分組成「組」，以 `r1 + r2 + 0.2` 判定，共用柱者另以 20° 夾角判定）、斜撐穿柱違規數、`links = 0` 且高度 > 15 mm 的非凍結柱數、各來源桿件數、輔助柱數
- [x] 1.2 選定小、中、滿版三個參考模型（另補高柱模型 `builtin:tall_fixture` 覆蓋輔助柱路徑）（小模型可取 `tests/data/` 既有檔，中與滿版可沿用 `scripts/raster_bench/make_fixtures.py` 的排版），記錄檔名、SHA-256 與切片參數
- [x] 1.3 以狀態回呼的步驟切換時間點（`Interconnecting pillars` 到 `Merging support mesh`）量測連接柱子階段耗時，每個模型取多次執行的中位數
- [x] 1.4 量測決定性：同一輸入執行兩次，並以不同執行緒數各執行一次，比對斜撐集合與合併網格；記錄任何既有的不一致與其可能來源（例如 `routing_to_model` 的平行執行）
- [x] 1.5 將 1.1 至 1.4 的數據與引擎建置身分（fork commit、編譯設定）寫入 `openspec/changes/sla-bracing-planar-topology/evidence/baseline-<UTC 時間>/`

## 2. 資料層

- [x] 2.1 新增 `enum class BridgeKind { unset, truss, head, prop, route }`（定義於 `SupportTree.hpp`，見 design.md 決策 8），`SupportTreeBuilder.hpp` 的 `Bridge` 加 `kind` 欄位（`DiffBridge` 繼承）
- [x] 2.2 於每個建立點標記型態：`add_crossbridge_between` → `truss`；`add_bridge_to_pillar` 與 `DefaultSupportTree.cpp:384` 的短柱 `add_bridge_between` → `head`；`DefaultSupportTree.cpp:1212` 的輔助柱 `add_bridge_between` → `prop`；`SupportTreeUtilsLegacy.hpp:177/237/297` 與 `SupportTreeUtils.hpp:625` → `route`
- [x] 2.3 `TreeBridge` 加 `kind`，並在 `SupportTree.cpp:196-208` 的匯出組裝處帶入
- [x] 2.4 `Pillar`、`TreePillar`、`PriorPillar`、`PriorAttachment` 加 `pairs`；`add_frozen_pillar` 與 `adopt_prior_pillars()` 帶入凍結柱的 `pairs`
- [x] 2.5 驗證：完成 2.1 至 2.4 後，三個參考模型的合併支撐網格須與基準線逐位元相同（此階段只加欄位，不改幾何）

## 3. BracingPlanner 幾何核心

- [x] 3.1 新增 `SLA/BracingPlanner.{hpp,cpp}`，定義常數 `SAFETY_CLEARANCE_MM = 0.2`、`MIN_SHARED_ANGLE_DEG = 20`、`PAIR_CAP = 3`、`RESCUE_HEIGHT_MM = 15`，並加入 `CMakeLists.txt`
- [x] 3.2 實作俯視線段對線段最短距離、點到線段最短距離，涵蓋平行、共線、長度為 0 的退化情況；單元測試覆蓋門檻 ±1e-6
- [x] 3.3 實作 3D 線段最短距離（`z_clear` 判定的依據，含平行與退化情況）、俯視最近點的高度線性內插（供診斷與向量說明）、共用柱夾角的餘弦比較；單元測試須含「水平桿對 45° 斜桿，高度差 1.5 mm 時 3D 距離約 1.06 mm」案例
- [x] 3.4 實作候選收集（排除凍結對凍結、距離 ≤ `max_pillar_link_distance_mm`、不看 `r_start` 大小）與排序鍵 `(距離, 小編號, 大編號)`
- [x] 3.5 實作貪婪接受：依規格的檢查順序回傳原因代碼；已接受的斜撐組、柱與非斜撐桿各以一個 `BoxIndex`（`SpatIndex.hpp:66`，2D R* 樹，整數縮放座標）索引，查詢時將俯視包圍盒外擴 `r_bar + r_max + safety_clearance` 並向外取整；逐桿判定以回呼注入（模型碰撞與非斜撐桿的 `z_clear`），使向量測試可不帶網格
- [x] 3.6 實作救援：對 `links = 0` 且高度 > 15 mm 的非凍結柱重試，以逐桿 `z_clear` 取代 `cross_truss`，其餘檢查不變

## 4. interconnect 改寫

- [x] 4.1 `interconnect()` 改為接受逐桿判定回呼，桿半徑取兩端 `r_start` 較小者，回傳實際建立的桿數，並將建立的桿標為 `truss`
- [x] 4.2 以 BracingPlanner 取代 `interconnect_pillars()` 的 `cascadefn`：配對上限看 `pairs`，`links` 維持 0.5 高度比規則；移除 `neighborpillar.r_start < pillar.r_start` 的略過條件
- [x] 4.3 非斜撐桿（`head` / `prop` / `route`）在連接階段開始前登錄為 `z_clear` 障礙物
- [x] 4.4 在輔助柱階段之前呼叫救援
- [x] 4.5 輔助柱階段改走 BracingPlanner：輔助柱與主柱、輔助柱彼此的斜撐都須通過規則；刪除 `DefaultSupportTree.cpp:1238` 對全部柱（含凍結柱）的重跑，凍結柱不得發起配對或被輔助
- [x] 4.6 `note_prior_attachment()` 與 `prior_attachments()` 回報凍結柱更新後的 `pairs`
- [x] 4.7 緊貼柱叢集（design.md 決策 11）：planner 以並查集維護叢集（`add_pillar` 時合併，含輔助柱）；穿柱、共用柱夾角（以各自軸心起算的 `dir_angle_ok`）、`cross_truss`、逐桿判定與救援的共用柱豁免都改用 `same_place`；單元測試涵蓋規格的四個叢集情境
- [x] 4.8 輔助柱解耦：`try_attach` / `attach` 不檢查配對上限；位置搜尋的每個角度須同時通過 `try_attach` 才算可放置；單元測試涵蓋「主柱配對已滿仍可長輔助柱」
- [x] 4.9 保底連接（design.md 決策 12）：`run_fallback()` 於輔助柱階段之後執行（輔助柱關閉時也執行），候選只收能給 `links` 的對象，配對上限改看 `links`，其餘同救援；`Bridge::relaxed` 與 `add_crossbridge_between` 的 `relaxed` 參數；單元測試涵蓋規格的四個保底情境
- [x] 4.10 量測工具同步：叢集規則、排除 `relaxed` 斜撐的俯視違規門檻（另計 `relaxed` 斜撐的違規數與組數）、最大叢集大小
- [x] 4.11 診斷中模型在 4.7、4.8 之後殘留的孤立柱：印出它每個候選的鄰居、距離、鄰居的 `pairs`／`links`／高度與被拒原因（臨時追蹤，驗證後移除），確認保底連接覆蓋其成因
- [x] 4.12 驗證：4 個參考模型的非救援俯視違規數與穿柱數為 0、孤立高柱數為 0；`sla_print_tests` 全數通過（含先前失敗的 4 個支撐樹完整性測試）

## 5. IO 序列化

- [x] 5.1 `SupportTreeIO.hpp`：`bridges[].kind` 一律寫出、`pillars[].pairs` 寫出；`version` 維持 2；更新檔頭的格式說明註解
- [x] 5.2 `PriorPillarIO.hpp`：讀取 `pairs`（缺值時以 `links` 代替）、寫出 `pairs`、`attached_to[]` 加 `pairs`；`version` 維持 1；更新格式說明註解
- [x] 5.3 IO 測試：缺 `pairs` 的舊清單可讀且以 `links` 代替；匯出的每根桿都有 `kind` 且值合法；版本號不變（`tests/sla_print/sla_supporttree_io_tests.cpp` 的 `[sla_io]`；四個參考模型以隱藏的 `[.bracing_io]` 執行，共用 `BRACING_BASELINE_PLAN`）

## 6. 共通測試向量

- [x] 6.1 建立 `tests/data/sla_bracing_vectors/`，依規格的 JSON 結構撰寫全部必要案例（X 交叉、T 字、共用端點、19°/21°、共線包含/部分重疊/不重疊、平行門檻 ±1e-6、中間柱擋路、已滿柱擋路、head 桿高度錯開/未錯開、腳站在模型上的柱、等距平手、長度為 0、救援成功/失敗、配對上限、單一新柱對全凍結板、緊貼柱叢集（互不擋路／連通合併／恰等於門檻／叢集夾角）、保底連接（鄰居配對已滿／結構計數已滿／矮鄰居）、`ground_z` 不為 0 的座標系混用偵測案例）
- [x] 6.2 產生 `MANIFEST.sha256`（逐行 `<sha256>  <檔名>`），並提供重新產生的腳本或指令說明（指令寫在 `sla_bracing_vectors_tests.cpp` 檔頭：`sha256sum -t *.json > MANIFEST.sha256`，驗證用 `sha256sum -c MANIFEST.sha256`；向量與清單皆為 LF）
- [x] 6.3 新增 `tests/sla_print/sla_bracing_vectors_tests.cpp`：載入每個向量，以 BracingPlanner 執行（模型碰撞回呼一律通過），比對 `accepted` 順序、`bars_built` 與 `rejected` 原因；另驗證 `MANIFEST.sha256` 與實際檔案一致；加入 `tests/sla_print/CMakeLists.txt`
- [x] 6.4 執行向量測試全數通過（42 個向量；另驗證斜率 ±1e-9 rad 決策不變、座標系混用時決策必不同）
- [x] 6.5 引擎層測試：搜尋輔助柱位置時，能站但無法建斜撐的角度須被跳過，改用下一個可站且可建斜撐的角度（任務 4.8 的 `try_attach` 篩選，至今只有 planner 單元測試；`[bracing_engine]` 以凍結柱擋在第一個角度的斜撐路徑上驗證）

## 7. 模型驗收

- [x] 7.1 以本變更的引擎對四個參考模型重跑 1.1 的量測：非救援、非保底斜撐的俯視違規數與穿柱違規數皆為 0；孤立高柱數為 0；記錄桿件總數、輔助柱數、救援與保底斜撐數（見 `evidence/final-20261005T074524Z/FINAL.md`：四個模型三項違規皆 0，孤立高柱 0，輔助柱 4 根與改動前相同，救援與保底組皆 0；量測另以 `Bridge::fallback` 分開保底組）
- [x] 7.2 在與基準線相同的機器與編譯設定下重跑 1.3：耗時增量 ≤ max(10%, 50 ms)（最大增量 2.84 ms，門檻 50 ms）
- [x] 7.3 重跑 1.4：結果一致，或不一致範圍不大於基準線，並記錄原因（每個模型 8 與 1 執行緒的雜湊全部相同）
- [x] 7.4 以 agent API 端到端執行一次 generate-supports，確認 `GET /slices/{id}/support-tree` 每根桿帶 `kind`、柱帶 `pairs`，`GET /slices/{id}/support-pillars` 帶 `pairs`（本機 agent 以 frog_legs 執行：111 根桿全有 `kind`，114 根柱全有 `pairs`；支撐 STL 與 CLI 匯出位元相同）
- [x] 7.5 重建受影響的支撐網格黃金檔（若有既有測試以改動前的輸出為準），並在提交說明中註明為刻意的行為變更（沒有依賴舊斜撐幾何的黃金檔；raster_bench 凍結支撐是固定輸入，刻意不重建；提交說明需註明為刻意的拓撲變更）
- [x] 7.6 將 7.1 至 7.4 的結果寫入 `evidence/final-<UTC 時間>/`，並記錄向量目錄路徑與 `MANIFEST.sha256` 本身的 SHA-256，作為 DS-online 移植變更的交接依據（`MANIFEST.sha256` 的 SHA-256 為 `84ddaa198e8be41cecfab2c5f2c3eb8cbd98522dc48538b3305e295c64b7fa6c`）
