## Why

手動支撐面板的底墊（pad）目前只開放 `pad_enable` 一個開關，其餘 11 個底墊全域
參數全部吃引擎內建預設值。切片引擎（`prusaslicer_fork`）的 `SLAPrintObjectConfig`
已經註冊並讀取這 11 個 option（`pad_wall_thickness`、`pad_brim_size` 等），全部
停在「引擎會讀、後端 `SLAConfig` 沒宣告、前端沒有控件」的狀態（B2）。這是
《SLA 支撐參數全表》／《手動支撐操作全表》盤點後排出的第二個梯次（F2），承接
已完工的 F1（`add-support-tree-global-params`），沿用同一套後端開放模式。

## What Changes

- `agent/models.py` 的 `SLAConfig` 新增 11 個底墊全域參數欄位，
  對應引擎 `PrintConfig.cpp:4716-4835` 已註冊的 option key（欄位名稱與引擎 key
  1:1，沿用 `generate_config_ini` 既有的通用欄位寫入機制，不需要新增後端轉譯
  邏輯，與 F1 相同）。
- 其中 1 個欄位有額外處理：
  - `pad_wall_slope`：新增 `field_validator` 限制合法值為 `45–90`（度）。這是
    本次唯一加驗證的欄位，理由是引擎 `Pad.hpp:75` 的 `bottom_offset()` 以
    `tan(wall_slope)` 為除數，送 `0` 會造成除以零，與 F1 的
    `support_max_pillar_link_distance`（`0` 是合法語意）性質不同。詳見 design.md D2。
- 5 個 zero-elevation 專屬欄位（`pad_around_object_everywhere`、`pad_object_gap`、
  `pad_object_connector_stride`／`_width`／`_penetration`）照常開放，**不在 API 層
  做條件驗證**。引擎的 `is_zero_elevation()`（`SLAPrint.cpp:48-51`）只有在
  `pad_enable` 與 `pad_around_object` 同時為 `true` 時才讀這 5 個值，其餘情況
  引擎自行忽略，不會報錯。條件關係寫進契約文件，供前端之後決定 UI 顯示條件。
- 預設值一律採 `PrintConfig.cpp` 的 `set_default_value`，**不採** `Pad.hpp:45-51`
  的 `PadConfig` struct 預設值——兩者有 3 個欄位不一致，是已知陷阱。詳見 design.md D3。
- `api/slicing_core.md` 同步新增這批參數的請求 body 欄位契約，並記錄引擎既有的
  兩處交叉驗證規則（`PadConfig::validate()`、`SLAPrint::validate()`），讓前端
  人員之後可依此契約自行開發串接。
- **本次不做前端**（`supportDefaults.js` / `SupportEditor.vue` / i18n 四語系文案）。
  範圍收斂為「後端 API 開放＋契約文件」，UI 串接留給前端人員之後另開 change 處理。
  前端 `sceneCoordinator.js:3888` 的 `PAD_WALL_THICKNESS_MM=2` 硬編碼常數，屬於
  前端範圍，本次不動。

## Capabilities

### New Capabilities

- `pad-global-params`：底墊全域參數（11 項）於後端 `SLAConfig` 的宣告、API 請求
  body 的欄位契約、`pad_wall_slope` 的範圍驗證規則、5 個 zero-elevation 專屬欄位
  的生效條件規格、以及引擎既有交叉驗證規則在契約文件的揭露義務。

### Modified Capabilities

（無。既有 `support-tree-global-params`（F1）與 `support-parameter-hints` 規格
描述的欄位行為不變；本次只新增欄位，不改動任何既有 spec 描述過的行為。）

## Impact

- **後端**（`agent/models.py`）：`SLAConfig` 新增 11 個欄位
  ＋1 個 Pydantic validator（`pad_wall_slope` 範圍 45–90）。`generate_config_ini`
  不須修改。
- **API 契約**：`api/slicing_core.md` 的 `SLAConfig` 表格新增 11 列，並補上兩處
  引擎交叉驗證規則的說明。
- **不影響**：C++ 引擎（`prusaslicer_fork`）本次不修改，僅讀取既有已註冊的 option。
- **不含前端**：`DS-Online` 的 `src/constants/supportDefaults.js`、
  `src/components/features/model_control/SupportEditor.vue`、
  `src/i18n/locales/{en,tw,cn,jp}.json` 本次不動。前端人員之後依
  `api/slicing_core.md` 契約自行開發串接，屬於未來另一個 change 的範圍。
- **不在本次範圍**：本次只做「後端把參數開出來」。錯誤分類邏輯一律不動——
  引擎的錯誤原文在兩條路徑都取得得到（`/execute` 回傳具體的
  `PAD_CONFIG_INVALID`，`/generate-supports` 回傳通用代碼但原始 stderr 附於
  `detail`），足以支撐本次的 API 開放目標。分類器對照表補完、引擎 exit code
  根因、`generate_hollow`／`cut_with_plane` 的罐頭訊息、死碼 `slice_model`，
  皆與底墊參數無關，獨立成 change，詳見 tasks 第 7 節。
