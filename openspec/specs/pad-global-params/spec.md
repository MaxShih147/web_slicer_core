# Spec: Pad Global Params

## Purpose

定義後端 `SLAConfig` 對 11 個底墊（Pad）全域參數的宣告契約：欄位命名須與切片
引擎 `PrintConfig.cpp` 的 option key 一致、未提供時的預設值來源（`PrintConfig.cpp`
註冊值，非 `Pad.hpp` 的 `PadConfig` struct 預設）、`pad_wall_slope` 的合法範圍
與非法值拒絕規則、5 個 zero-elevation 專屬欄位的生效條件、以及引擎既有兩處
交叉驗證規則在契約文件的揭露義務。本規格僅涵蓋後端 API 契約，不含前端 UI
（見 `add-pad-global-params` change 的範圍收斂紀錄）。

---
## Requirements
### Requirement: 標準底墊全域參數可透過 API 設定

系統 SHALL 在 `SLAConfig` 新增以下 10 個底墊全域參數欄位，欄位名稱 SHALL 與
切片引擎 `PrintConfig.cpp` 註冊的 option key 完全一致：`pad_wall_thickness`、
`pad_wall_height`、`pad_brim_size`、`pad_max_merge_distance`、`pad_around_object`、
`pad_around_object_everywhere`、`pad_object_gap`、`pad_object_connector_stride`、
`pad_object_connector_width`、`pad_object_connector_penetration`。未於 request body
提供時 SHALL 使用與引擎 `PrintConfig.cpp` 註冊值一致的預設值。

#### Scenario: 設定值傳遞至切片引擎

- **WHEN** 使用者透過 API 送出上述任一參數的自訂值
- **THEN** `generate_config_ini` SHALL 將該值原樣寫入 `config.ini`
- **AND** 切片引擎 SHALL 讀到該值並套用於底墊生成

#### Scenario: 未提供參數時套用引擎註冊的預設值

- **WHEN** request body 未包含上述任一欄位
- **THEN** `SLAConfig` SHALL 套用 `PrintConfig.cpp` 的 `set_default_value`
  （例如 `pad_wall_thickness` 預設 `2.0`、`pad_wall_height` 預設 `0.0`、
  `pad_object_connector_penetration` 預設 `0.3`）
- **AND** 系統 SHALL NOT 採用 `Pad.hpp` 的 `PadConfig` struct 預設值
  （該來源在本後端的 `--load config.ini` 路徑不生效，且有 4 個欄位與註冊值不一致）

#### Scenario: 加入新欄位不改變既有輸出

- **WHEN** 既有 client 送出不含任何本批新欄位的 request
- **THEN** 生成結果 SHALL 與本次變更前完全一致

### Requirement: 底墊側壁斜度限制為引擎合法範圍

系統 SHALL 新增 `pad_wall_slope` 數值欄位（單位為度），合法範圍 SHALL 為
`45` 至 `90`（含兩端），預設值 SHALL 為 `90.0`。系統 SHALL 拒絕範圍外的值。

拒絕 MUST 以 HTTP 422 ＋ `retryable: false` 呈現，訊息 MUST 含欄位名 `pad_wall_slope`。
MUST NOT 落入通用兜底而回傳 HTTP 500 ＋ `retryable: true`。

此外，`45` 只是**靜態下限**。引擎的實際門檻由 `pad_wall_thickness / tan(pad_wall_slope) ≤ pad_brim_size` 推導，會隨其他兩個參數改變。系統 SHALL 在驗證回應中回報**當下算出的動態下限**，MUST NOT 以寫死常數表達。

#### Scenario: 合法值正常傳遞

- **WHEN** 使用者將 `pad_wall_slope` 設為 `45` 至 `90` 之間的值
- **THEN** 系統 SHALL 接受該值並原樣寫入 `config.ini`
- **AND** 引擎 SHALL 將其乘以 `PI/180` 轉為弧度後套用

#### Scenario: 範圍外的值遭到拒絕

- **WHEN** 使用者送出 `0`、`30`、`120` 或任何 `45–90` 範圍外的值
- **THEN** 系統 SHALL 回傳 HTTP 422 驗證錯誤，`retryable` 為 false，訊息含 `pad_wall_slope`
- **AND** 系統 SHALL NOT 將該值寫入 `config.ini`
- **AND** 系統 SHALL NOT 呼叫引擎 CLI

#### Scenario: 靜態範圍內但違反動態門檻

- **WHEN** 使用者送出 `pad_wall_slope` 為 `50`，而 `pad_wall_thickness` 為 `2.0`、`pad_brim_size` 為 `1.6`
- **THEN** 驗證 SHALL 失敗並回報 `PAD_CONFIG_INVALID`
- **AND** 回應 SHALL 攜帶算出的最小合法角度（此組參數下為 `51.4`）
- **AND** `fields` SHALL 含 `pad_wall_slope`、`pad_wall_thickness`、`pad_brim_size` 三者

#### Scenario: 動態門檻隨其他參數改變

- **WHEN** `pad_brim_size` 由 `1.6` 提高到 `2.5`，`pad_wall_slope` 維持 `50`
- **THEN** 同一組設定 SHALL 通過驗證
- **AND** 證明門檻為推導值而非寫死常數

#### Scenario: 此驗證不得被推廣為通用慣例

- **WHEN** 後續維護者為其他數值欄位評估是否加範圍驗證
- **THEN** 判準 SHALL 為「該值是否會造成除以零或產生 NaN」
- **AND** 引擎已定義語意的邊界值（例如 `support_max_pillar_link_distance` 的 `0`
  代表「完全不串接」）SHALL NOT 被加上範圍保護

### Requirement: zero-elevation 專屬欄位的生效條件

系統 SHALL 新增 `pad_around_object_everywhere`、`pad_object_gap`、
`pad_object_connector_stride`、`pad_object_connector_width`、
`pad_object_connector_penetration` 五個欄位，且 SHALL NOT 對這些欄位施加任何
條件驗證或連動邏輯。系統 SHALL 讓使用者可查閱到「這 5 個欄位僅在 `pad_enable`
與 `pad_around_object` 同時為 `true` 時才會被引擎讀取」這項條件。

#### Scenario: 條件成立時值被引擎讀取

- **WHEN** `pad_enable` 與 `pad_around_object` 皆為 `true`
- **THEN** 引擎 SHALL 讀取這 5 個欄位的值並套用於 zero-elevation 底墊生成

#### Scenario: 條件不成立時值被引擎忽略且不報錯

- **WHEN** `pad_enable` 或 `pad_around_object` 任一為 `false`
- **AND** 使用者仍送出這 5 個欄位的自訂值
- **THEN** 系統 SHALL 接受該值並正常送出切片請求
- **AND** 引擎 SHALL 忽略這些值
- **AND** 系統 SHALL NOT 回傳錯誤或中斷切片

#### Scenario: 連接柱參數設為 0 時靜默停用

- **WHEN** `pad_object_connector_stride`、`pad_object_connector_width` 或
  connector 相關的 padding 值設為 `0`
- **THEN** 引擎 SHALL 不產生任何連接柱（`Pad.cpp:66` 的 EPSILON 提前 return）
- **AND** 系統 SHALL NOT 回報錯誤
- **AND** 此靜默停用行為 SHALL 記載於 API 契約文件

### Requirement: 引擎既有交叉驗證規則須於契約文件揭露

系統 SHALL NOT 在 API 層複製引擎的跨欄位驗證邏輯。系統 SHALL 讓 API 使用者
可從契約文件查閱到引擎會拒絕的參數組合條件。

#### Scenario: 底墊外擴與斜度組合不合法

- **WHEN** 使用者送出的 `pad_brim_size`／`pad_wall_thickness`／`pad_wall_height`／
  `pad_wall_slope` 組合觸發引擎 `PadConfig::validate()` 的拒絕條件
- **THEN** 系統 SHALL 將該組合原樣送給引擎（不在 API 層預先攔截）
- **AND** 引擎的錯誤訊息原文 SHALL 可被 API 使用者取得（`/execute` 經
  `slicing_classifier` 回傳 `PAD_CONFIG_INVALID`；`/generate-supports` 回傳
  通用代碼並將原始 stderr 附於 `detail`）
- **AND** 本 change SHALL NOT 為此新增或修改任何錯誤分類邏輯——分類器的
  對照表補完屬獨立 change 範圍

#### Scenario: 底座安全距離小於底墊間隙

- **WHEN** zero-elevation 啟用且 `support_base_safety_distance` 小於 `pad_object_gap`
- **THEN** 系統 SHALL 將該組合原樣送給引擎
- **AND** 引擎 SHALL 回傳「'Support base safety distance' 必須大於 'Pad object gap'」
  類型的驗證錯誤

#### Scenario: 契約文件記載兩條交叉驗證規則

- **WHEN** 前端人員或 API 使用者查閱 `api/slicing_core.md`
- **THEN** 該文件 SHALL 記載上述兩條組合條件
- **AND** SHALL 說明這些條件由引擎在切片階段檢查，不在 API 驗證階段回報

---

## Behavioral Acceptance Table

| # | Condition | Expected Behavior | Pass/Fail Criteria |
|---|---|---|---|
| 1 | 送出 10 個標準欄位任一自訂值 | 值原樣寫入 config.ini 並影響底墊生成 | 生成的底墊幾何隨參數值變化 |
| 2 | 不送任何新欄位 | 全部使用 `PrintConfig.cpp` 預設值 | 生成結果與加欄位前完全一致（golden 比對） |
| 3 | `pad_wall_slope` 送 `45`／`67.5`／`90` | 接受並套用 | config.ini 內為對應數值；底墊側壁斜度隨之改變 |
| 4 | `pad_wall_slope` 送 `0` | 回傳驗證錯誤 | HTTP 4xx，不產生切片任務，不呼叫引擎 CLI |
| 5 | `pad_wall_slope` 送 `120` | 回傳驗證錯誤 | HTTP 4xx，不產生切片任務 |
| 6 | `pad_wall_height` 送 `0` | 接受，空腔關閉 | config.ini 內為 `0`；底墊無空腔 |
| 7 | zero-elevation 關閉時送 5 個專屬欄位 | 接受，引擎忽略 | 切片成功完成；生成結果與未送這 5 個欄位時一致 |
| 8 | zero-elevation 開啟時送 `pad_object_gap` 自訂值 | 接受並套用 | 模型底部與底墊之間的間隙隨值變化 |
| 9 | `pad_object_connector_stride` 送 `0` | 接受，不產生連接柱 | 切片成功完成，無連接柱幾何，無錯誤 |
| 10 | `pad_brim_size` 送 `0.05`（小於引擎 MIN_BRIM_SIZE_MM） | API 接受並透傳，引擎回傳驗證錯誤 | config.ini 內為 `0.05`；切片階段回報引擎錯誤訊息 |
| 11 | zero-elevation 開啟且 `support_base_safety_distance` < `pad_object_gap` | API 接受並透傳，引擎回傳驗證錯誤 | 切片階段回報引擎錯誤訊息 |

前端 UI 驗收（面板控件、tooltip、四語系文案）不在本規格範圍內，留給前端
另一個 change 制定。第 10、11 列的「引擎錯誤訊息可被取得」在全切片路徑上的
可靠性，屬於獨立追蹤項目，見 `add-pad-global-params` change 的 design.md
Open Questions。
