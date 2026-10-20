**共通約定（適用於每個 Task）**

- C++ 一律由使用者以 Visual Studio 2022 手動建置。方案檔：`third_party\prusaslicer_fork\build\PrusaSlicer.sln`，組態 `Release`、平台 `x64`。
- 建置產物：引擎 `third_party\prusaslicer_fork\build\src\Release\slicer-engine.exe`；測試 `third_party\prusaslicer_fork\build\tests\sla_print\Release\sla_print_tests.exe`。
- Python 一律使用專案的 `.venv\Scripts\python`。量測腳本放在本變更的 `evidence/tools/`。
- 驗收素材：`D:\tool\stl\02.stl`（墊高 10 mm，密度 100 與 400；另加墊高 5 mm、密度 100、柱徑 1.0 的預設組，用來檢查重複斜撐）、02.stl 搭配每點隨機尺寸（支撐頭半徑 0.25 / 0.4 / 0.75，種子 1～5）、`D:\tool\stl\China-dragon1.stl`、`D:\tool\stl\Pikachu.stl`。
- 每個 Task 都要建置成功、驗證通過、`/code-review` 審查完並修正確認的問題之後，才進入下一個 Task。

## 1. 分支合併與基準線

- [x] 1.1 主專案自 `release/v1.0.6` 建立分支 `fix/sla-head-bridge-clearance`；fork 自其 `release/v1.0.6`（`7764188f1`）建立同名分支
- [x] 1.2 fork 合入 `feat/sla-bracing-planar-topology`（`b43f3cd70`）。`DefaultSupportTree.cpp` 的 `interconnect_pillars()` 衝突採 planar 版本；其餘衝突逐一檢查，確認 `02f19db4e`、`cd971bc2d`、`a114d13bd` 中與斜撐無關的改動（例如島嶼取樣修正、版本號）都保留
- [x] 1.3 主專案合入 `feat/sla-bracing-planar-topology`（`2bd7ce1`、`74bf40b`），確認 `openspec/specs/sla-bracing-topology/spec.md` 已出現；子模組指標指向 1.2 的合併 commit
- [x] 1.4 執行 `openspec validate sla-head-bridge-clearance`，確認通過，且 `specs/sla-bracing-topology/spec.md` 中 MODIFIED 的三條需求標題都與基底規格完全一致
- [x] 1.5 把探索期的分析腳本整理進 `evidence/tools/`：`analyze_tree.py`（改用匯出的 `kind` 欄位分類，不再依匯出順序推斷；計算 A、B、C、反向 C、D、重複柱對、粗頭掛細柱，以及共用柱的 R 過濾）、`bench_steps.py`（從引擎 log 時間戳記取出第 3、4 步耗時）、`determinism.py`（同一輸入跑 N 次與 `--threads 1`，比對雜湊）
- [x] 1.6 **VS 2022 建置**：開啟 `PrusaSlicer.sln` → 組態選 `Release`、平台選 `x64` → 在方案總管對 `slicer-engine` 按右鍵選「建置」→ 展開 `tests` 資料夾，對 `sla_print_tests` 按右鍵選「建置」→ 確認兩個 exe 的修改時間已更新
- [x] 1.7 **驗證**：執行 `sla_print_tests.exe "[bracing_planner],[bracing_vectors],[bracing_metrics],[sla_io]"`，全部通過；`sla_print_tests.exe` 不帶參數全跑一次，記錄合併前就已失敗的測試（若有）
- [x] 1.8 **基準線量測**：以 1.6 的引擎對所有驗收素材執行 1.5 的三支腳本，記錄以下數據：第 3、4 步合計耗時 T（每組 3 次取中位數）；A、B、C、反向 C、D、重複柱對、粗頭掛細柱的計數；被刪除的支撐頭數（log 中 `Failed to route model facing support point` 的行數）；4 次執行與 `--threads 1` 的雜湊。連同 fork commit 與編譯設定寫入 `evidence/baseline-<UTC 時間>/`
- [x] 1.9 **`/code-review` 檢核點**：審查合併 diff。重點：衝突解法是否誤刪 v1.0.6 的修正；planar 的 `BridgeKind` 標記在所有 `add_bridge*` 呼叫點都有寫出；子模組指標正確
- [x] 1.10 提交本 Task（fork 與主專案各一個合併 commit）

## 2. 幾何模組與單元測試

- [x] 2.1 新增 `src/libslic3r/SLA/BridgeClearance.{hpp,cpp}`（命名空間 `Slic3r::sla::clearance`），加入 `src/libslic3r/CMakeLists.txt`
- [x] 2.2 定義 `SAFETY_CLEARANCE = 0.2`、`PrimKind`、`Capsule`、`Prim`、`Contact`；`capsule_dist()` 直接呼叫 `bracing::geom::seg_seg_dist3d`，不另寫第二份
- [x] 2.3 實作元件轉膠囊體的對應（design 決策 2 的表格）：掛橋 / 繞路 / prop 取 `r`，`DiffBridge` 取 `max(r, end_r)`，柱取柱腳到柱頂與 `max(r_start, r_end)`，支撐頭取 `pos → junction_point()` 與 `r_back`
- [x] 2.4 實作 `ClearanceIndex`：boost 3D R* 樹（`rstar<16, 4>`，`double` 座標），存入外擴 `r` 的 AABB，查詢框外擴 `r + c`；只插入不刪除
- [x] 2.5 實作共用柱判定（以 ID 取柱集合並求交集）與完全豁免規則（同一支撐頭路徑內、桿對其端柱、支撐頭對其承載柱）
- [x] 2.6 實作 R 接點過濾：`R_P = r_P + r1 + r2 + 0.2`（依 spec 固定用 `SAFETY_CLEARANCE`，L1 也不縮小）；以俯視二次式解出圓柱內的參數區間；多根共用柱時做區間差集（至多 3 段）；幾乎鉛直的桿以端點判定；任一方被剪光即通過；提供 `joint_clipped_dist()`
- [x] 2.7 實作 `ClearanceIndex::violations(cands, c, axis_of)`，回傳全部違規 `Contact`（含座標、距離、門檻、對象種類）；恰等於門檻視為通過
- [x] 2.8 `bracing::PlannerConfig::safety_clearance` 的預設值改為引用 `clearance::SAFETY_CLEARANCE`（數值不變）
- [x] 2.9 新增 `tests/sla_print/sla_bridge_clearance_tests.cpp`（標籤 `[bridge_clearance]`），加入 `tests/sla_print/CMakeLists.txt`。涵蓋 spec 的情境：高度差 1.5 通過、1.0 違規、45° 傾斜 1.06 違規、恰為 1.2 通過、錐形柱取 0.75、支撐頭膠囊體、半空柱腳下方 5 mm 通過、R = 1.7 / 2.45、同點 90° 通過、同點 10° 違規、共用柱以 ID 判定。另加一個隨機性質測試：比較索引查詢與暴力全比對，結果須完全一致（粗篩不得漏判）
- [x] 2.10 **VS 2022 建置**：開啟 `PrusaSlicer.sln`。CMakeLists 有改動，建置時 VS 會先自動重跑 CMake（`ZERO_CHECK`）；若跳出「重新載入方案」，請按「全部重新載入」。組態 `Release`、平台 `x64` → 建置 `libslic3r` → 建置 `sla_print_tests` → 建置 `slicer-engine`
- [x] 2.11 **驗證**：`sla_print_tests.exe "[bridge_clearance]"` 全部通過；`sla_print_tests.exe "[bracing_planner],[bracing_vectors],[bracing_metrics],[sla_io]"` 仍全部通過。以 `--threads 1` 對 02.stl 預設組生成，`tree.json` 雜湊與 1.8 基準線相同（本 Task 不改變任何引擎輸出）
- [x] 2.12 **`/code-review` 檢核點**：重點：粗篩外擴量是否保證超集合；區間差集的邊界（端點恰在圓上、整段在內、相切）；浮點退化（零長度線段、平行線段）；常數只有一處定義
- [x] 2.13 提交本 Task

## 3. 排程拆分重構

- [x] 3.1 定義 `RoutePlan`（`to_pillar`、`own_pillar`、`ground_route`、`model_anchor`）與 `BuildRecipe`（提交時要重放的 builder 呼叫，含 `BridgeKind`、owner、底座、接合點），放在 SLA 目錄的內部標頭
- [x] 3.2 把 `create_ground_pillar()`（含 `search_widening_path`、零墊高修正橋）拆成 `plan_ground_pillar()`（只讀）與提交函式。保留原函式作為「規劃 + 提交」的包裝，讓第 3(a) 步與其他呼叫者行為不變
- [x] 3.3 把 `connect_to_ground()`、`search_ground_route()` 拆成 `plan_ground_route()` 與提交；確認優化器仍為 `seed(0)`
- [x] 3.4 把 `connect_to_nearpillar()` 拆成 `plan_to_pillar()` 與提交，包含「先長自身短柱再掛過去」的情況
- [x] 3.5 把 `connect_to_model_body()` 拆成 `plan_model_anchor()` 與提交。階段一不得寫入共享的 `m_penetration_stats`：統計值隨 plan 攜帶，提交時再累加
- [x] 3.6 實作候選清單：第 3(b) 步為中心柱 → 其他柱 → 自立柱；第 4 步為柱 → 繞路 → 錨在模型上。柱依（柱腳距離, 柱 ID）排序，最多保留 K = 4 個模型可行的掛柱候選（初值 8，於 3.13 依效能量測校正）；只有在沒有任何可行掛柱候選時，才計算繞路 / 自立柱 / 錨柱
- [x] 3.7 第 3(a) 步直接記錄每群中心柱的 ID，取代 `m_pillar_index.query(..., 1)`；中心柱建立失敗的群，其候選不含中心柱（中心柱的間距紀錄在 4.1 加入，本 Task 不改中心柱的建立結果）
- [x] 3.8 實作兩階段驅動（第 3(b)、4 步）：階段一用 `execution::for_each` 讀不可變快照（builder 唯讀、柱索引複本），結果寫入以支撐頭 ID 為索引的陣列；階段二單執行緒依支撐頭 ID 由小到大提交；候選全滅時以最新狀態重算一次
- [x] 3.9 在階段二實作硬規則：一頭一路徑且原子提交；`r_start ≥ r_back`（含掛中心柱）；以提交當下的 `bridgecount < max_bridges_on_pillar` 判定，移除 `:310` / `:374` 的不一致寫法；既有的模型碰撞、`minz`、最大橋長留在階段一
- [x] 3.10 沒有任何候選時維持既有行為：第 4 步照舊 `head.invalidate()` 並寫既有警告；第 3(b) 步照舊（自立柱失敗時不另做處理）。兩者都要計數
- [x] 3.11 新增引擎層測試（標籤 `[head_routing]`），使用程式內產生的小型合成網格（例如蘑菇形，讓支撐頭朝向模型）：(a) 以 `tbb::global_control` 限制 1 個執行緒與不限制，各生成一次，第 3、4 步的 head / pillar / bridge 記錄完全相同；(b) 每點尺寸混合時，從同一接合點出發的掛橋數皆 ≤ 1，且沒有支撐頭同時有自立柱與掛橋；(c) 沒有粗頭掛細柱
- [x] 3.12 **VS 2022 建置**：組態 `Release`、平台 `x64` → 建置 `slicer-engine` → 建置 `sla_print_tests`。若新增了標頭或測試檔，VS 會先自動重跑 CMake，跳出提示時按「全部重新載入」
- [x] 3.13 **驗證**：`sla_print_tests.exe "[head_routing],[bridge_clearance],[bracing_planner],[bracing_vectors],[bracing_metrics],[sla_io]"` 全部通過。對驗收素材執行 `evidence/tools/`（一律加 `--inputs evidence/baseline-20261019T060139Z/inputs`）：D = 0、粗頭掛細柱 = 0；China-dragon1 與 Pikachu 各跑 4 次再加 `--threads 1`，第 3、4 步記錄的雜湊全部相同；第 3、4 步耗時 ≤ T + max(0.1T, 50 ms)；被刪除的支撐頭數不多於基準線。A、B、C 本 Task 尚未處理，只記錄
- [x] 3.14 **`/code-review` 檢核點**：重點：階段一是否有任何共享狀態寫入（builder、索引、統計、`head().bridge_id`）；提交重放與原函式的 builder 呼叫是否逐一對應（owner、`BridgeKind`、`own_*`、底座）；排序的平手規則；重算是否確實只發生一次
- [x] 3.15 提交本 Task

## 4. 間距規則與降級狀態機

- [ ] 4.1 在 `DefaultSupportTree` 加入 `ClearanceIndex` 成員：分類後插入所有有效支撐頭的膠囊體；`adopt_prior_pillars()` 插入凍結柱；第 3(a) 步插入中心柱；每次提交插入該 plan 的全部元件。第 3(a) 步中心柱照原位建立、不進降級；建立後以 c = 0.2 查它對支撐頭的違規，排除原生過密（長出它的支撐頭與被碰支撐頭的膠囊體本身 < 門檻，只計數），其餘每一處寫 info log `centroid_pillar_clearance_recorded pillar=<id> head=<id> dist=<d> required=<r> at (x,y,z)`
- [ ] 4.2 由 `RoutePlan` 產生待判元件清單（掛橋、自身短柱、繞路段、`DiffBridge`、新柱、錨頭），並帶上 head_id 與柱 ID，供豁免與 R 過濾使用
- [ ] 4.3 實作純函式的路徑選擇器 `select_route(cands, index, hard_ok, recompute)`：L0（c = 0.2）→ 重算一次 → L1（c = 0）→ L2（重算後第一個通過硬規則者）→ NONE；回傳選中的候選、層級與違規 `Contact`
- [ ] 4.4 在階段二以 `select_route` 取代 Task 3 的直接提交；硬規則在任何層級都不放寬；斜撐不參與
- [ ] 4.5 L1 提交寫 info log；L2 提交寫 `WARNING: fallback_intersection_retained head=<id> kind=<route> contacts=<n> at (x,y,z)...`，並把 L2 紀錄（支撐頭、路徑類型、接觸清單）存進 `DefaultSupportTree`，供 Task 6 匯出
- [ ] 4.6 生成結束時寫一行摘要 log：L1、L2、NONE 次數，以及中心柱已記錄接觸數、原生過密數（寫法比照 `report_penetration_failsafes`）
- [ ] 4.7 單元測試（標籤 `[head_route_select]`）：以假的候選與手動建立的索引驅動 `select_route`，涵蓋 spec 的情境：L0 選第二候選、重算後看見新柱、L1（d = 1.1 對 1.0）、L2、NONE、L2 不放寬粗細與掛橋上限、等距候選以柱 ID 決定
- [ ] 4.8 引擎層測試（`[head_routing]` 擴充）：在合成網格上刻意製造交叉，結果須沒有未記錄的 A、C、反向 C（每一處都有 L1、L2 或 `centroid_pillar_clearance_recorded` 紀錄）；另造一個中心柱貼近非原生過密支撐頭的案例，確認中心柱位置不變且有該行 log；1 個執行緒與不限制的輸出仍完全相同
- [ ] 4.9 **VS 2022 建置**：組態 `Release`、平台 `x64` → 建置 `slicer-engine` → 建置 `sla_print_tests`
- [ ] 4.10 **驗證**：`sla_print_tests.exe "[head_route_select],[head_routing],[bridge_clearance],[bracing_planner],[bracing_vectors],[bracing_metrics],[sla_io]"` 全部通過。對驗收素材：L0 判定下的 A、C、反向 C 剩餘違規（柱碰支撐頭以 `revC_head_net` 計，原生過密的 `revC_head_native` 只記錄），每一處都能在 log 的 L1 / L2 紀錄中找到，中心柱碰支撐頭則在 `centroid_pillar_clearance_recorded` 紀錄中找到（基準線的 mixed_s1、mixed_s2、China-dragon1 三處屬此類）；D、粗頭掛細柱 = 0；被刪除的支撐頭數不多於基準線；確定性與第 3、4 步耗時門檻同 3.13；記錄 L1、L2 次數，以及柱數、桿數相對基準線的變化
- [ ] 4.11 **`/code-review` 檢核點**：重點：狀態轉移是否完全照 spec 的順序；重算後的保底候選是否取自重算後的清單；豁免與 R 過濾是否只依 ID；違規座標是否正確寫入 log；摘要計數與實際次數一致
- [ ] 4.12 提交本 Task

## 5. planar 整合與向量

- [ ] 5.1 修改 `BracingPlanner::evaluate` 第 6 步：障礙桿與斜撐組端柱（含叢集成員）的柱集合有交集時，以 `clearance::joint_clipped_dist` 判定（叢集成員以自身軸心與半徑計算 `R_P`）；沒有交集時維持原判定；救援 / 保底模式的逐桿 3D 判定不變
- [ ] 5.2 `BracingPlanner::attach()` 開頭檢查 `built_pair(a, b)`，命中回傳新原因 `Reason::duplicate_pair`；`reason_name()` 加入 `"duplicate_pair"`；`accept()` 加 debug assert，禁止對已有斜撐的柱對再接受
- [ ] 5.3 輔助柱階段：在 `try_attach()` 之前，由 `DefaultSupportTree` 檢查候選輔助柱的柱身與 prop 桿對 `ClearanceIndex`（c = 0.2）。不通過的角度視為不可放置；放置後把新柱與 prop 桿插入索引
- [ ] 5.4 新增共通向量至 `tests/data/sla_bracing_vectors/`：共用柱且接觸在 R 內（接受）、共用柱但接觸在 R 外（`z_clear_fail`）、同一柱對嘗試兩次（`duplicate_pair`）；必要時擴充向量格式以表達 `attach` 操作；以 LF 重建 `MANIFEST.sha256`
- [ ] 5.5 確認既有 42 組向量的期望值全部不變，特別是 `head_bar_owner_exempt.json` 須落在 R 內而仍被接受。若有任何既有向量因本變更而改變結果，停下並回報，不得自行修改期望值
- [ ] 5.6 planner 單元測試（`[bracing_planner]` 擴充）：B 收窄的接受與拒絕、叢集成員的 R、`attach` 重複柱對、`run_greedy_for` 不產生已建柱對
- [ ] 5.7 **VS 2022 建置**：組態 `Release`、平台 `x64` → 建置 `slicer-engine` → 建置 `sla_print_tests`
- [ ] 5.8 **驗證**：`sla_print_tests.exe "[bracing_planner],[bracing_vectors],[bracing_metrics],[sla_io],[bridge_clearance],[head_route_select],[head_routing]"` 全部通過。02.stl 預設組的重複柱對 = 0；所有驗收素材中「共用柱、接觸在 R 外」的 B = 0；planar 的三個參考模型仍符合 planar 的回歸門檻（俯視違規 0、穿柱 0、孤立高柱 0、連接階段耗時門檻）；記錄輔助柱數的變化
- [ ] 5.9 **`/code-review` 檢核點**：重點：planner 是否仍不依賴網格與 builder；叢集成員的軸心與半徑是否用對；新原因代碼是否在 C++ 與向量格式中名稱一致；MANIFEST 是否為 LF 且雜湊正確
- [ ] 5.10 提交本 Task

## 6. 警告匯出與驗收工具

- [ ] 6.1 在 `SupportTree.hpp` 新增 `TreeWarning`（code、head 索引、route、contacts），由 `DefaultSupportTree` 的 L2 紀錄轉入；head 索引需換算成匯出 `heads[]` 的索引
- [ ] 6.2 `SupportTreeIO.hpp`：只有在有 L2 紀錄時才寫出頂層 `warnings` 陣列，欄位依 spec；`version` 維持 2
- [ ] 6.3 IO 測試（`[sla_io]` 擴充）：沒有警告時沒有 `warnings` 鍵且 `version` 為 2；有一筆警告時，`code`、`head`、`route`、`contacts[].pos/with/dist/required` 都正確
- [ ] 6.4 新增 C++ 量測 `tests/sla_print/sla_head_bridge_metrics.{hpp,cpp}`，直接讀 builder：A、B、C、反向 C、D、重複柱對、粗頭掛細柱、L1、L2、NONE、中心柱已記錄接觸數、原生過密數、未記錄的違規數（L1、L2、中心柱紀錄與原生過密都不算未記錄）；附單元測試（標籤 `[head_bridge_metrics]`），以小型手造支撐樹驗證每一種計數
- [ ] 6.5 確認 agent 對 `warnings` 只做原樣轉送：執行 `.venv\Scripts\python -m pytest agent/tests/test_support_points_wiring.py agent/tests/test_support_e2e.py`，結果與合併前相同
- [ ] 6.6 **最終驗收**：以最終引擎對所有驗收素材執行 6.4 的量測與 `evidence/tools/` 腳本。逐條核對 spec「回歸與效能門檻」（輸入為基準線的固定支撐點清單）：D / 粗頭掛細柱 / 重複柱對（`dup_truss_pairs` 與 `pairs_excess`）= 0；未記錄的違規 = 0（原生過密只記錄；中心柱碰支撐頭以 `centroid_pillar_clearance_recorded` 計為已記錄）；被刪除的支撐頭數不多於基準線；確定性（4 次 + `--threads 1`）；第 3、4 步耗時門檻；planar 參考模型的回歸門檻。把結果與基準線的對照寫入 `evidence/final-<UTC 時間>/FINAL.md`，L1、L2、柱數、桿數只記錄趨勢
- [ ] 6.7 重建受影響的支撐網格黃金檔（若有既有測試以改動前的支撐輸出為準）；提交說明註明這是刻意的幾何變更
- [ ] 6.8 **VS 2022 建置**：組態 `Release`、平台 `x64` → 建置 `slicer-engine` → 建置 `sla_print_tests`；最後對整個方案按「建置方案」一次，確認沒有其他目標因本變更而無法編譯
- [ ] 6.9 **驗證**：`sla_print_tests.exe` 不帶參數全跑，除了 1.7 記錄的既有失敗之外全部通過；`openspec validate sla-head-bridge-clearance` 通過
- [ ] 6.10 **`/code-review` 檢核點**：審查整個分支相對 `release/v1.0.6` 的 diff。重點：匯出欄位名稱與 spec 完全一致；`warnings` 不存在時不寫鍵；量測工具與 spec 的計數定義一致；沒有遺留除錯輸出
- [ ] 6.11 提交本 Task，並把主專案的子模組指標更新到 fork 的最終 commit
