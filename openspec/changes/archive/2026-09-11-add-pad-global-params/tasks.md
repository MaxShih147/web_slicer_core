## 1. 後端：標準底墊全域參數（10 項）

- [x] 1.1 `agent/tests/test_sla_config.py`（此檔**已存在**，內容含
      `fix-prz-output-correctness` 與 `add-support-tree-global-params` 的既有測試，
      **在既有檔案裡新增測試類別，不得整檔覆寫**）新增 10 個標準欄位的測試
      （`pad_wall_thickness`、`pad_wall_height`、`pad_brim_size`、
      `pad_max_merge_distance`、`pad_around_object`、`pad_around_object_everywhere`、
      `pad_object_gap`、`pad_object_connector_stride`、`pad_object_connector_width`、
      `pad_object_connector_penetration`）——正常值案例、未提供時的預設值案例、
      `generate_config_ini` 寫出 ini 內容正確的案例
- [x] 1.2 `agent/models.py` 的 `SLAConfig` 在既有 `pad_enable`
      欄位下方新增上述 10 個欄位，預設值對齊 `PrintConfig.cpp:4716-4835` 的
      `set_default_value`（`pad_wall_thickness=2.0`、`pad_wall_height=0.0`、
      `pad_brim_size=1.6`、`pad_max_merge_distance=50.0`、`pad_around_object=False`、
      `pad_around_object_everywhere=False`、`pad_object_gap=1.0`、
      `pad_object_connector_stride=10.0`、`pad_object_connector_width=0.5`、
      `pad_object_connector_penetration=0.3`）
- [x] 1.3 在欄位區塊上方加程式碼註解，記錄 D3 的預設值陷阱：`Pad.hpp:45-51` 的
      `PadConfig` struct 另有一套預設值，其中 `pad_wall_thickness`、
      `pad_wall_height`、`pad_wall_slope`、`pad_object_connector_penetration`
      四項與 `PrintConfig.cpp` 不一致；本後端走 `--load config.ini` 路徑，
      SHALL 以 `PrintConfig.cpp` 為準，不得「參考 Pad.hpp 修正」。
      註解開頭 SHALL 標明本 change 名稱 `add-pad-global-params`，讓
      `git log --grep` 與 `openspec` 查得到決策紀錄。**本 change 的文件與程式碼
      同在本 repo**，因此只需寫 change 名稱，不必像 F1 那樣加註 repo 名
      （F1 的文件在 DS-Online，其註解已於本次補上 repo 指標）
- [x] 1.4 **撰寫預設值合約測試**（本節最重要的一項，見 design.md D3）。
      背景：`generate_config_ini`（`sla_operations.py:294`）會把
      `SLAConfig.model_dump()` 的**每一個欄位**寫進 ini，不論使用者有沒有提供。
      因此本次填的 Python 預設值是**取代**引擎預設值，填錯會讓所有未調整的
      使用者底墊幾何靜默改變，且不會報錯。
      作法：新增 `agent/tests/test_pad_defaults_contract.py`，
      直接讀取 `third_party/prusaslicer_fork/src/libslic3r/PrintConfig.cpp`，
      解析 11 個 `pad_*` option 的 `set_default_value(new ConfigOptionFloat/Bool(...))`，
      與 `SLAConfig` 的對應欄位預設值逐一比對，不一致即失敗。
      須包含一個負向檢查（刻意改錯一個期望值，證明斷言真的有效），
      比照既有的 `agent/tests/test_support_string_contract.py` 的寫法
      （該檔即以同樣方式把分類器字串釘死在 fork 原始碼上）。
      **不採用 golden ini 字串比對**——加欄位後 ini 必然多 11 行，字串比對無法成立

## 2. 後端：底墊側壁斜度（範圍驗證）

- [x] 2.1 撰寫測試：`pad_wall_slope` 送 `45`／`67.5`／`90` 皆可正常設定；
      送 `0`／`44.9`／`90.1`／`120`／負值皆觸發驗證錯誤且不寫入 ini
- [x] 2.2 `models.py` 新增 `pad_wall_slope: float = 90.0`，加 `field_validator`
      限制合法範圍為 `45 <= v <= 90`，錯誤訊息須明確指出合法範圍
- [x] 2.3 在該 validator 旁加程式碼註解，記錄 D2 的判準：擋這個欄位是因為
      `Pad.hpp:75` 的 `bottom_offset()` 以 `tan(wall_slope)` 為除數，送 `0` 會
      除以零並產生 `NaN`；並註明反例——F1 的 `support_max_pillar_link_distance`
      的 `0` 是引擎定義的合法語意，SHALL NOT 加範圍保護。判準是「有無除法／NaN
      風險」，不是「一律加驗證」

## 3. 後端：zero-elevation 專屬欄位（生效條件，不做條件驗證）

- [x] 3.1 撰寫測試：`pad_enable=False` 或 `pad_around_object=False` 時，送出
      5 個 zero-elevation 專屬欄位的自訂值仍可正常設定並寫入 ini，不觸發任何
      驗證錯誤
- [x] 3.2 確認 `models.py` 的這 5 個欄位（已於 1.2 新增）SHALL NOT 套用任何
      `model_validator` 或條件式連動邏輯
- [x] 3.3 在這 5 個欄位旁加程式碼註解，記錄 D4：引擎
      `SLAPrint.cpp:48-51` 的 `is_zero_elevation()` 為
      `pad_enable && pad_around_object`，兩者同時為 `true` 才讀這 5 個值；
      並註明 `Pad.cpp:66` 的 EPSILON 提前 return（connector 參數設 `0` 會靜默
      不產生連接柱）

## 4.（移出本次範圍）前端：UI 控件與文案

本次不做前端。本節不建立任何 task，內容保留備查，待未來另開 change 由前端
接手時參考：

- `src/constants/supportDefaults.js` 的 `SUPPORT_CONFIG_BASE` 新增全部 11 個
  欄位鍵與預設值。
- `src/components/features/model_control/SupportEditor.vue` 的 `backendFields`
  新增對應控件：`pad_wall_thickness`／`pad_wall_height`／`pad_brim_size`／
  `pad_max_merge_distance`（滑桿或輸入）、`pad_wall_slope`（滑桿，下限 45 不是 0）、
  `pad_around_object`／`pad_around_object_everywhere`（開關）、
  `pad_object_gap`／connector 三項（滑桿或輸入）。
- 5 個 zero-elevation 專屬控件的顯示條件：`pad_enable && pad_around_object`
  同時為 `true` 才有意義，隱藏或 disabled 由前端決定。
- `pad_wall_height` 的 tooltip 須帶引擎自附的脫模警告（空腔內樹脂吸附效應）。
- `pad_around_object` 的 tooltip 須註明「開啟後引擎會忽略
  `support_object_elevation`」。
- 前端 `sceneCoordinator.js:3888` 的 `PAD_WALL_THICKNESS_MM=2` 硬編碼常數，
  改讀 `pad_wall_thickness` 真值。
- `src/i18n/locales/{en,tw,cn,jp}.json` 補齊上述控件的 label／tooltip 四語系
  文案（先讀 `i18n-key-conventions` skill）。

## 5. 契約文件與驗收

> **跨 repo 警告**：5.1 與 5.2 動到的 `api/slicing_core.md` **不在本 repo**，
> 它在 **`DS-Online` repo** 的 `api/slicing_core.md`（前端視角的後端契約文件，
> 見 `DS-Online/api/README.md` 的維護規則）。本 change 的程式碼與測試在
> `web_slicer_core`，契約文件在 `DS-Online`，**兩者無法放進同一個 commit**。
>
> 因此本 change 需要 **兩個 repo、各一個 commit**：
>
> | Repo | 內容 | 對應 task |
> |---|---|---|
> | `web_slicer_core` | `agent/models.py`、`agent/tests/*`、本 change 文件 | 第 1–3 節、5.3、5.4 |
> | `DS-Online` | `api/slicing_core.md` | 5.1、5.2 |
>
> **關單前務必確認 `DS-Online` 那個 commit 真的做了。** 前車之鑑：F1
> （`add-support-tree-global-params`）的後端 commit `826786b` 只帶了
> `agent/models.py` 與測試，沒有任何 openspec 文件，決策紀錄全留在另一個 repo，
> 後端維護者在本 repo 的 git history 裡看不到。

- [x] 5.1 **【DS-Online repo】** `api/slicing_core.md` 的 `SLAConfig` 表格
      （現於 `pad_enable` 該列附近）
      新增本批 11 個參數的請求 body 欄位說明，須含：
      (a) 各欄位的型別、預設值、引擎範圍；
      (b) `pad_wall_slope` 的合法範圍 `45–90`（度）與非法值回傳驗證錯誤；
      (c) 5 個 zero-elevation 專屬欄位的精確生效條件
      （`pad_enable` **與** `pad_around_object` 同時為 `true`）；
      (d) connector 三項設 `0` 會靜默不產生連接柱；
      (e) `pad_around_object` 開啟後引擎忽略 `support_object_elevation`；
      (f) `pad_wall_height` 的脫模警告文案
- [x] 5.2 **【DS-Online repo】** `api/slicing_core.md` 新增引擎交叉驗證規則區塊，記載兩條規則：
      `PadConfig::validate()` 的 brim／斜度／厚度組合條件，以及
      `support_base_safety_distance` 必須大於 `pad_object_gap`（zero-elevation 時）。
      須明確說明這兩條由引擎在切片階段檢查，不在 API 驗證階段回報
- [x] 5.3 **【本 repo】** `pytest agent/tests/` 全綠，且既有測試無回歸
      （含 `test_sla_config.py` 新增的測試類別、新建的
      `test_pad_defaults_contract.py`）。
      **執行紀錄**：752 passed / 2 failed（`test_prz_print_time.py::test_6_11_single_normal_layer_full_params`、
      `test_subprocess_boundary_5_11.py::test_engine_runs_as_separate_process`），
      另有 4 個檔案因缺 `httpx2` 套件無法 collect。以上皆用 `git stash` 驗證為
      本次改動前即存在的既有問題，與 pad 參數無關，非本次回歸。本次新增/修改的
      測試（`TestStandardPadGlobalParams`、`TestPadWallSlope`、
      `TestZeroElevationPadFields`、`test_pad_defaults_contract.py`、
      `test_pad_api_v2_intake.py`）全數通過。
- [x] 5.4 直接呼叫後端 API 驗證（不透過 UI）：驗證 `api_v2.py` 兩條資料流——
      `_convert_v2_config_to_sla`（`/generate-supports`、`/export-support-points` 用）
      與 `_build_sla_config`（`/execute` 用）——都能正確接住本次 11 個新欄位並
      傳進 `SLAConfig`，`generate_config_ini` 產生的 `config.ini` 內容與送出值一致；
      `pad_wall_slope` 送 `0` 時在兩條路徑下皆回傳驗證錯誤。
      （F1 已確認這兩個轉換函式對 `SLAConfig` 新欄位是動態接住、無白名單限制，
      本次只需複驗結論仍成立）

## 6. 完工發布（追蹤用 Artifact）

- [x] 6.1 用 Artifact 工具發布一份「工作結果說明」頁面，內容須包含：
      (a) 本次做了什麼——11 個 `pad_*` 參數的後端 API 開放，以及各欄位的
      型別／預設值／範圍；
      (b) 本次沒做什麼——前端 UI 串接（第 4 節）、引擎修改，以及為什麼；
      (c) 連結本次 openspec change 的 proposal／design／specs，方便日後回溯
- [x] 6.2 **上述 Artifact SHALL 完整收錄 design.md 的「D2 白話說明」、
      「D3 白話說明」、「D4 白話說明」三個小節**。這三段是使用者指定保留的
      說明版本，SHALL 以白話敘述呈現（含 D2 的除以零推導、D3 的四列預設值
      對照表與「F2 之前／之後」的 ini 行為對比、D4 不擋的四個理由），
      SHALL NOT 壓縮成條列摘要或改寫成純技術描述。目的：讓沒有讀過原始碼的人，
      光看 Artifact 就能理解這三個決策的風險與理由
- [x] 6.3 **Artifact SHALL 另立一段醒目提醒：D4 的 5 個參數帶有生效條件。**
      內容須包含：
      (a) 這 5 個參數（`pad_around_object_everywhere`、`pad_object_gap`、
      `pad_object_connector_stride`／`_width`／`_penetration`）只有在
      `pad_enable` **與** `pad_around_object` **同時為 `true`** 時才會被引擎讀取；
      (b) 條件不成立時，API 照收、引擎忽略、不報錯，因此**從 API 回應看不出
      這些值有沒有生效**；
      (c) **給未來的明確指示**：日後再整理參數清單、製作參數對照表、或規劃
      前端控件時，這 5 個參數 SHALL 被特別標記為「條件生效」，不可與無條件
      生效的參數混在同一組呈現。同類需要標記的還有 F1 的
      `branchingsupport_*` 系列（僅 `support_tree_type="branching"` 時生效）
      與 `support_enforcers_only`（需 enforcer/blocker 標記體積才生效）

## 7. 獨立追蹤（不屬於本次範圍，僅記錄）

本節不建立任何 task，不影響本 change 的關單條件。

**已查核並排除的疑慮**：`/execute` 對引擎 `validate()` 失敗的偵測**已經是可靠的**。
它走 `jobs.py:433` 的 `run_slicing`，使用 `agent/slicing_classifier.py` 的七步
分類器，同時處理 exit≠0 與 exit=0 兩條路徑（`slicing_classifier.py:180-186`
的 Step 6.x 明文針對引擎的 exit code 問題做了繞道），且已含
`PAD_CONFIG_INVALID` 對照。這條路不需要本次或後續處理。
**注意**：`sla_operations.py:560` 的 `slice_model` 只信任 returncode，但它
**沒有任何生產端呼叫者**（只有 `test_preview_scale_contract.py` 引用），是死碼，
不是 `/execute` 的實作。

**已知限制，不擋本次**：`/generate-supports` 路徑的 `support_classifier` 缺
`Pad brim size is too small` 的對照條目，該路徑遇到底墊參數組合錯誤時會回傳
通用的 `SUPPORT_GENERATION_FAILED`。**原始 stderr 全文仍完整附在 `detail` 欄位，
資訊不遺失**，只是呼叫端分不出錯誤種類。本次不處理。

**仍待處理，另開 change**：

1. `support_classifier` 補上 `Pad brim size` 對照（代碼沿用 `slicing_classifier`
   已登錄的 `PAD_CONFIG_INVALID`），並加防漂移測試斷言兩份分類器對照表一致。
2. 引擎 `ProcessActions.cpp` 有 15 個錯誤出口寫成 `return 1`，但函式宣告是
   `bool`，C++ 轉成 `true`，導致 process exit code 為 0。這是根因。目前已被
   兩個分類器各自繞過，但每個新增的 CLI 呼叫端都得重新記得這件事。需重建引擎
   與完整回歸。
3. `generate_hollow`（`sla_operations.py:697`）與 `cut_with_plane`（`:929`）
   仍用 naive `returncode != 0` ＋ 罐頭訊息，失敗時丟掉引擎給的原因。
4. 死碼 `slice_model` 的刪除或標註。
