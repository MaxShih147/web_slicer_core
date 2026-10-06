# 斜撐拓撲最終驗收（任務組 7）

量測時間：2026-10-05 07:45 UTC。本目錄是 tasks.md 7.1 至 7.6 的驗收紀錄，比較基準是 `../baseline-20261005T051227Z/`（改動前）。

## 結論

| 項目 | 門檻 | 結果 |
|---|---|---|
| 7.1 非救援、非保底斜撐的俯視違規與穿柱違規 | 0 | 四個模型皆為 0（改動前：小 81、中 71、滿版 137，高柱 0） |
| 7.1 孤立高柱 | 0 | 四個模型皆為 0 |
| 7.1 輔助柱 | 正常運作 | 高柱模型 4 根輔助柱、4 根輔助柱橋，與改動前相同 |
| 7.2 連接階段耗時增量 | ≤ max(10%, 50 ms) | 最大增量 2.84 ms（滿版，1 執行緒） |
| 7.3 決定性 | 一致 | 每個模型的 8 與 1 執行緒執行，雜湊全部相同 |
| 7.4 agent API 端到端 | 每根桿有合法 `kind`，柱有 `pairs` | 111 根桿全有 `kind`，114 根柱全有 `pairs` |
| 7.5 黃金檔 | 受影響者重建 | 沒有依賴舊斜撐幾何的黃金檔，不需重建（見下） |

## 引擎建置身分

- fork commit：`e0be76c570a59614284db063d230267e73d2c333`（web_slicer_core `0fc176d181b9531d048d9f9d4e7e392fd95bd164`）。工作區另含本變更任務組 2 至 6 的全部修改（尚未提交）。
- 量測專用的小修改：`Bridge` 新增 `fallback` 旗標（與既有的 `relaxed` 一樣只供量測，不匯出），讓量測可以把保底斜撐和救援斜撐分開計數。`bracing_metrics()` 新增 `fallback_groups` 與 `obstacle_pillar_relaxed`；`obstacle_pillar` 改為只計非救援、非保底的組（四個模型都沒有救援或保底組，所以這項改動不影響本次數字）。
- 編譯：Visual Studio 17 2022，MSVC 19.44.35225.0，Release（`/MD /O2 /Ob2 /DNDEBUG`），與基準線相同。
- 量測程式 `sla_print_tests.exe`：SHA-256 `70b61fe0cce4ba49f4205db9df2b645251d601166255eb78180a7c2928de8952`
- 正式引擎 `slicer_core.dll`：SHA-256 `02b1c3c8174f9a62694df2c12fd07ec14cc9bbde51c881e75bab1e51ea77c328`
- 機器：Intel i7-11370H（4 核心 8 執行緒），15.7 GB 記憶體，Windows 11 Pro 10.0.26200，與基準線相同。
- 單元測試：`sla_print_tests.exe` 全套 245 個測試案例、198178 個檢查點全部通過。

## 7.1 斜撐指標

模型、切片參數與量測方法都和基準線相同（`plan.json` 只改了輸出路徑）。下表為「改動前 → 改動後」。

| 指標 | 小 | 中 | 滿版 | 高柱 |
|---|---|---|---|---|
| 支撐點 / 有效頭 | 169 / 169 | 216 / 216 | 576 / 576 | 37 / 37 |
| 柱 / 輔助柱 | 114 / 0 | 120 / 0 | 315 / 0 | 36 / 4 |
| 斜撐桿 | 76 → 56 | 436 → 393 | 1079 → 1043 | 423 → 383 |
| 斜撐組 | 69 → 49 | 140 → 128 | 345 → 337 | 35 → 35 |
| 頭部掛橋 / 輔助柱橋 / 繞路段 | 55 / 0 / 0 | 96 / 0 / 0 | 261 / 0 / 0 | 5 / 4 / 0 |
| **俯視違規 `cross_truss`** | 22 → **0** | 28 → **0** | 49 → **0** | 0 → **0** |
| **同柱夾角違規 `shared_angle`** | 6 → **0** | 19 → **0** | 38 → **0** | 0 → **0** |
| **穿柱違規 `obstacle_pillar`** | 53 → **0** | 24 → **0** | 50 → **0** | 0 → **0** |
| 救援斜撐組 / 保底斜撐組 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 |
| 救援與保底組的違規（另計） | 0 | 0 | 0 | 0 |
| 高度 > 15 mm 的柱 | 0 | 27 | 71 | 34 |
| **孤立高柱** | **0** | **0** | **0** | **0** |
| 緊貼柱叢集（最大叢集柱數） | 10（4） | 3（2） | 5（2） | 0（1） |
| 每柱配對夥伴數 0/1/2/3/4/5+ | 54/29/24/7/0/0 | 15/20/19/66/0/0 | 40/60/31/184/0/0 | 2/3/26/5/0/0 |
| 桿件 `kind` 缺漏 / 與來源不符 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 |
| 合併網格面數 | 87872 → 86592 | 132352 → 129600 | 347264 → 344960 | 48256 → 45696 |

說明：

- 改動前的量測函式還沒有「緊貼柱叢集」的規則；改動後依規格把緊貼柱視為同一叢集。叢集只豁免同一叢集內的柱，不豁免叢集外的違規。
- 四個模型都沒有用到救援或保底斜撐，所以這兩條路徑在模型上沒有被執行到。它們由任務 6 的共通向量覆蓋（`rescue_*`、`fallback_*`，其中 `fallback_past_plan_crossing` 是 Level 3 保底連接）。
- 高柱模型的斜撐組數不變，桿數少了 40 根：部分組的桿件因 3D 間距不足，只建到被擋住之前的那一段。

## 7.2 連接階段耗時

取狀態回呼中 `Interconnecting pillars` 到 `Merging support mesh` 這段時間的中位數，單位 ms。

| 模型 | 8 執行緒 | 1 執行緒 | 最大增量 | 整棵支撐樹（8 執行緒） |
|---|---|---|---|---|
| 小 | 0.46 → 1.27（n=7） | 0.55 → 1.23（n=5） | +0.81 | 19.8 → 20.4 |
| 中 | 1.06 → 1.79（n=5） | 1.20 → 1.82（n=3） | +0.74 | 18.2 → 15.9 |
| 滿版 | 2.82 → 5.35（n=5） | 3.28 → 6.12（n=3） | +2.84 | 58.9 → 60.4 |
| 高柱 | 2.56 → 3.32（n=7） | 2.77 → 3.44（n=5） | +0.76 | 7.1 → 7.4 |

門檻是 max(10%, 50 ms)。連接階段本身只有幾毫秒，10% 遠小於 50 ms，所以門檻是 50 ms。最大增量 2.84 ms，通過。相對比例雖然上升（最多約 2.8 倍），但整棵支撐樹的耗時幾乎不變。

## 7.3 決定性

| 模型 | 支撐樹執行（8 + 1 執行緒） | 不同的結果數 | 斜撐雜湊 | 合併網格雜湊（頂點 / 面） |
|---|---|---|---|---|
| 小 | 7 + 5 | 1 | `0fc40e8cd5da5480` | `2d0fb871665b22e2`（44149 / 86592） |
| 中 | 5 + 3 | 1 | `06aff6feb44e3f7e` | `ded74445b741eabd`（66498 / 129600） |
| 滿版 | 5 + 3 | 1 | `a59f4e6603653e9a` | `83fb6e181f1c20c0`（176998 / 344960） |
| 高柱 | 7 + 5 | 1 | `8d65c853c4d49b8a` | `b45342a4ed2895e9`（23667 / 45696） |

每次執行的頭、柱、掛橋、斜撐、繞路段、合併網格雜湊（FNV-1a 64）與全部指標都相同。支撐點雜湊與基準線相同。頭、掛橋、繞路段的雜湊也與基準線相同，代表改變只發生在斜撐與柱（柱的 `links`、`pairs` 計數）。

### 正式引擎匯出的支撐 STL

以基準線目錄的 `config-<角色>.ini` 執行 `slicer-engine --export-support-stl`。面數與上表的合併網格完全相同。

| 模型 | SHA-256 | 面數 |
|---|---|---|
| 小 | `2b65033d606ed275eadac14ffc93060f617d85d6c7fbf61d2556b650c39af10d` | 86592 |
| 中 | `a7a9f17d508f90d06d956d9fb5954b717bded8ce9dcc89fedcd357bc54525e02` | 129600 |
| 滿版 | `ab4e2a7077797ed71b417f50b38ef3234104c29a214ddffaf85774631775f5f3` | 344960 |

## 7.4 agent API 端到端

- 在本機以 `uvicorn agent.main:app --port 5199` 啟動 agent，`SLICER_ENGINE_BIN` 指向本次編譯的 `slicer-engine.exe`，工作目錄放在暫存區。
- 流程：`POST /api/v2/slices` → `POST /slices/{id}/upload`（`tests/data/frog_legs.obj` 轉成的 STL）→ `POST /slices/{id}/generate-supports` → 輪詢 `GET /slices/{id}` 到 `completed` → `GET /slices/{id}/support-tree` 與 `GET /slices/{id}/support-pillars`。
- 結果（修正前的第一次執行；`e2e.json` 現在存的是審查修正後的重跑，見下文）：
  - `support-tree`：version 2，111 根桿，全部帶合法 `kind`（head 55、truss 56），不合法 0；114 根柱全部帶 `pairs`，沒有 `pairs < links` 的柱。
  - `support-pillars`：version 1，114 根柱全部帶 `pairs`。
- agent 產生的 `model_support.stl` 與上表小模型的 CLI 匯出位元相同（SHA-256 `2b65033d…af10d`），確認 agent 用的是本次的引擎。
- 另以隱藏測試 `[.bracing_io]` 對四個模型檢查兩種匯出格式（`io.stdout.log`）：小 111 根桿（head 55、truss 56）、中 489（head 96、truss 393）、滿版 1304（head 261、truss 1043）、高柱 392（head 5、prop 4、truss 383），全部通過。

## 7.5 黃金檔

- fork 的單元測試全部通過，沒有任何測試以改動前的支撐網格為準。
- web_slicer_core 中唯一記錄支撐雜湊的是 `scripts/raster_bench/manifest.json` 的凍結支撐。它是光柵量測的固定輸入：每次量測都匯入同一份 `support.stl`，不重新產生，也不和引擎新產生的支撐比對。重建它會讓光柵量測失去前後可比性，所以刻意不重建。
- 因此沒有黃金檔需要重建。支撐網格的改變（本文件 7.1 與 7.3 的面數與雜湊）是本變更刻意的幾何拓撲優化：移除交錯與穿柱的斜撐，而不是迴歸錯誤。提交時請在提交說明中註明這一點。

## 7.6 交接給 DS-online 移植

- 向量目錄：`third_party/prusaslicer_fork/tests/data/sla_bracing_vectors/`（42 個向量 JSON、`MANIFEST.sha256`、`.gitattributes`）
- `MANIFEST.sha256` 本身的 SHA-256：`84ddaa198e8be41cecfab2c5f2c3eb8cbd98522dc48538b3305e295c64b7fa6c`
- 驗證：在該目錄執行 `sha256sum -c MANIFEST.sha256`，本次結果全部 OK。
- 換行：目錄內的 `.gitattributes`（`* text eol=lf`）讓向量與清單在任何環境取出時都維持 LF。`git check-attr` 已確認 `near_first.json` 與 `MANIFEST.sha256` 都是 `text: set`、`eol: lf`。

## 程式碼審查後的修正與重跑

審查（2026-10-05）後修正了三項，並補上一個編譯期檢查。修正後重新編譯，再跑一次全部測試與量測。

- 資料競爭：`SupportTreeBuilder` 加桿時，`owner_a`、`owner_b`、`relaxed`、`fallback` 與 `kind` 改在同一段鎖內寫入（`_add_bridge` 的 `BridgeTags`）。加桿函式改為回傳鎖內取得的複本，不再回傳指向可能被其他執行緒擴容之陣列的參考。
- 繞路桿：`create_ground_pillar` 在柱建立後，把柱 id 寫到終點落在柱頂的那一根桿（繞路修正桿或漸變桿）；`connect_to_ground` 只在柱頂就是自己終點時寫入。終點不在柱頂的桿維持不登錄。
- `pairs` 讀取：缺值、null、負數、小數、字串、布林、陣列或超過 unsigned 範圍時，一律回退為 `links`，不丟例外、不溢位。
- `static_assert(PAIR_CAP == SupportTreeConfig::pillar_cascade_neighbors)`，放在 `DefaultSupportTree.cpp`（planner 標頭是純幾何，不引入 `SupportTreeConfig`）。
- 量測：繞路桿現在可能帶柱 id。`bracing_metrics()` 對「帶柱 id、柱不是輔助柱」的桿，改以記錄的 `kind` 區分頭部掛橋與繞路桿；沒有柱 id 的桿仍必須是繞路桿。

重跑結果：

- 單元測試：249 個測試案例、258258 個檢查點全部通過。新增 4 個：owner 與桿一起寫入、多執行緒加桿 owner 不錯置、繞路最後一根桿登錄柱 id（3 種情況）、`pairs` 異常值回退。
- 四個模型：每次執行的全部雜湊與上文 7.1、7.3 完全相同，違規數與孤立高柱仍為 0，8 與 1 執行緒結果一致。這四個模型都沒有繞路桿，所以幾何不變。原始數據是 `runs-after-review.jsonl` 與 `run-after-review.stdout.log`。
- agent API 端到端（7.4 重跑，2026-10-06，修正後的引擎，`e2e.json`）：
  - `frog_legs`：111 根桿全帶合法 `kind`，114 根柱全帶 `pairs`；support-tree 的 SHA-256 與修正前的執行相同（`e52b1aa7…0f892142`）。
  - `extruder_idler`（tests/data 中會長出繞路桿與輔助柱的模型）：42 根桿全帶合法 `kind`（head 4、route 1、prop 1、truss 36），17 根柱在兩種匯出中都帶 `pairs`；那根繞路桿帶 `b`，終點落在 `b` 那根柱的柱頂（`route_owned_off_top` 為 0）。
- 匯出上的連帶變化：支撐頭若先接一根繞路修正桿再落地，support-tree 的 `heads[].pillar`（承重柱）以前因那根桿沒有柱而是 -1，現在指向它落地的柱。這與 `SupportTreeUtils.hpp` 的新繞路流程（`own_diffbridges_from`）原本的記錄方式一致。
- 連接階段中位數（8 / 1 執行緒，ms）：小 1.26 / 1.24、中 1.97 / 1.92、滿版 5.29 / 6.15、高柱 2.98 / 3.27。相對基準線的最大增量 2.87 ms，仍遠低於 50 ms。
- 正式引擎匯出的三個支撐 STL，SHA-256 與上文相同。
- 修正後的 `sla_print_tests.exe`：SHA-256 `37953517403754fe7f184da3618f864ce0555eda7198baca37b29a1071a3424e`；`slicer_core.dll`：`62e51dae5ec22b7da514b369f0a42a91abc808acb3a28f0ed7cb7f24571f3864`。
- `MANIFEST.sha256` 未變動，`sha256sum -c` 全部 OK。

## 檔案

- `plan.json`：執行計畫，與基準線相同，只有輸出路徑不同。
- `runs.jsonl`：每一次執行的完整雜湊、指標與耗時（審查修正前的引擎）。
- `runs-after-review.jsonl`：審查修正後的同一組量測，格式相同。
- `run.stdout.log`、`run-after-review.stdout.log`、`io.stdout.log`：`[.bracing_baseline]`（修正前、後）與 `[.bracing_io]` 的原始輸出。
- `e2e.json`：7.4 的檢查結果，審查修正後重跑的 `frog_legs` 與 `extruder_idler` 兩筆。

重新量測（`runs.jsonl` 以附加方式寫入，重跑前請先移走舊檔）：

```
BRACING_BASELINE_PLAN=<本目錄>/plan.json build/tests/sla_print/Release/sla_print_tests.exe "[.bracing_baseline]"
BRACING_BASELINE_PLAN=<本目錄>/plan.json build/tests/sla_print/Release/sla_print_tests.exe "[.bracing_io]"
```
