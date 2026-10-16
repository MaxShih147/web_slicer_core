## ADDED Requirements

### Requirement: 建立工作時即驗證初始設定

`POST /api/v2/slices` 若帶有 `config`，系統 SHALL 在建立工作之前，以與其他 v2 入口相同的轉換流程（DS-Online 欄位名對應到 `SLAConfig` 欄位）建立一次 `SLAConfig` 來驗證它。驗證失敗時：

- 系統 SHALL 回傳 HTTP 422、`retryable: false`，錯誤碼依「參數錯誤須回 422 而非 500」的規則決定（支撐連接長度或底座直徑違規為 `SUPPORT_PARAM_INVALID`，其他欄位為 `CONFIG_VALIDATION_ERROR`）。
- 系統 MUST NOT 建立工作。回應 MUST NOT 含 `jobId`，待處理工作清單 MUST NOT 留下任何項目。

`config` 的結構若讓轉換流程無法處理（例如 `"Print": null`、`"Print"` 是字串、`center` 含非數值），系統 SHALL 同樣回傳 HTTP 422 `CONFIG_VALIDATION_ERROR`，訊息指明設定結構不合法，且 MUST NOT 建立工作。系統 MUST NOT 因此回傳 HTTP 500，也 MUST NOT 略過驗證而建立工作（否則藏在其中的違規值會進入待處理工作）。

此處 SHALL 只做 `SLAConfig` 欄位驗證，MUST NOT 套用 `param_rules.py` 的參數規則表。原因是部分規則（例如相對密度為 0 時須有手動支撐點）需要建立工作之後才會送來的資料，建立當下判斷會誤擋。

驗證 MUST NOT 改動要存下的 `config` 內容；驗證通過時存下的 `config` SHALL 與請求送來的完全相同。

`config` 缺省或為空物件時，行為 SHALL 與本變更前相同。`prz_config` 與 `center` 不在本需求的驗證範圍內。

#### Scenario: 初始設定的連接長度為 0
- **WHEN** 呼叫 `POST /api/v2/slices`，`config` 為 `{"support_max_bridge_length": 0}`
- **THEN** 回應 HTTP 422，錯誤碼為 `SUPPORT_PARAM_INVALID`
- **AND** `data.errors[]` 含 `loc` 為 `["support_max_bridge_length"]` 的項目
- **AND** 回應 MUST NOT 含 `jobId`
- **AND** 待處理工作數量與呼叫前相同

#### Scenario: 初始設定的底座直徑為 NaN
- **WHEN** 呼叫 `POST /api/v2/slices`，請求本體的 JSON 寫著 `"config": {"support_base_diameter": NaN}`
- **THEN** 回應 HTTP 422，錯誤碼為 `SUPPORT_PARAM_INVALID`
- **AND** MUST NOT 建立工作

#### Scenario: 初始設定的其他欄位違規
- **WHEN** 呼叫 `POST /api/v2/slices`，`config` 為 `{"pad_wall_slope": 35}`
- **THEN** 回應 HTTP 422，錯誤碼為 `CONFIG_VALIDATION_ERROR`
- **AND** MUST NOT 建立工作

#### Scenario: DS-Online 欄位名一樣會被轉換後驗證
- **WHEN** 呼叫 `POST /api/v2/slices`，`config` 為 `{"Layer Height": "abc"}`（DS-Online 欄位名，轉換後對應 `layer_height`，值無法轉成數字）
- **THEN** 回應 HTTP 422，錯誤碼為 `CONFIG_VALIDATION_ERROR`
- **AND** 訊息含 `layer_height`
- **AND** MUST NOT 建立工作

#### Scenario: 設定結構不合法
- **WHEN** 呼叫 `POST /api/v2/slices`，`config` 為 `{"Print": null}`
- **THEN** 回應 HTTP 422，錯誤碼為 `CONFIG_VALIDATION_ERROR`，MUST NOT 為 HTTP 500
- **AND** 訊息說明設定結構不合法
- **AND** MUST NOT 建立工作

#### Scenario: 不套用參數規則表
- **WHEN** 呼叫 `POST /api/v2/slices`，`config` 為 `{"supports_enable": true, "support_points_density_relative": 0}`
- **THEN** 工作建立成功，回應含 `jobId`

#### Scenario: Link Distance 為 0 可建立工作
- **WHEN** 呼叫 `POST /api/v2/slices`，`config` 為 `{"support_max_pillar_link_distance": 0}`
- **THEN** 工作建立成功

#### Scenario: 合法設定原樣存下
- **WHEN** 呼叫 `POST /api/v2/slices`，`config` 含合法的支撐參數與 DS-Online 欄位名
- **THEN** 工作建立成功
- **AND** 待處理工作存下的 `config` 與請求送來的內容完全相同

#### Scenario: 不帶設定
- **WHEN** 呼叫 `POST /api/v2/slices`，不帶 `config`（或 `config` 為空物件）
- **THEN** 行為與本變更前完全相同
