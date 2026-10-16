# support-param-validation Specification

## Purpose
TBD - created by archiving change add-support-param-validation. Update Purpose after archive.
## Requirements
### Requirement: 事前參數驗證規則表

系統 SHALL 提供 `agent/param_rules.py`，以純算術判斷一組支撐／底墊參數送進引擎是否會被 `validate()` 擋下。規則 MUST 逐條對照引擎原始碼撰寫，MUST NOT 自行發明門檻。

每條規則 MUST 攜帶 `code`（取自 error code 登錄檔）、`scope`、`fields`（用到的參數欄位名）、判斷式與修正建議。

#### Scenario: 頭部直徑大於支柱直徑
- **WHEN** `support_head_front_diameter` 大於 `support_pillar_diameter`
- **THEN** 回報 `SUPPORT_HEAD_TOO_WIDE`
- **AND** `fields` 含這兩個欄位名

#### Scenario: 參數全部合法
- **WHEN** 一組參數不違反任何規則
- **THEN** 回傳 `ok` 為 true 且 `problems` 為空

#### Scenario: 規則不得比引擎嚴格
- **WHEN** 一組參數恰好落在引擎接受的邊界上
- **THEN** 規則表 MUST 放行

### Requirement: 驗證範圍以 scope 的聯集決定

規則 SHALL 標記 `scope` 為 `support_params` 或 `slice_only`。驗證 profile SHALL 為 scope 的**聯集**，MUST NOT 實作為多張平行的規則表。

| profile | 取用 scope |
|---|---|
| `support` | `support_params` |
| `slice` | `support_params` ＋ `slice_only` |
| `slice_imported` | `slice_only` |

#### Scenario: 切片驗證涵蓋支撐驗證
- **WHEN** 以 `slice` profile 驗證
- **THEN** 所有 `support_params` scope 的規則 MUST 全部被套用
- **AND** 額外套用 `slice_only` 的規則

#### Scenario: 新增一條支撐規則
- **WHEN** 開發者新增一條 `scope=support_params` 的規則
- **THEN** `support` 與 `slice` 兩個 profile 自動涵蓋，無需在第二處登記

### Requirement: 匯入支撐時不驗支撐參數

當切片流程偵測到 `input/support.stl` 存在時，系統 SHALL 使用 `slice_imported` profile，MUST NOT 套用任何 `support_params` scope 的規則。

理由：該模式下引擎忽略所有支撐與底墊參數，套用規則只會產生假失敗。

#### Scenario: 匯入支撐且底墊參數違規
- **WHEN** `input/support.stl` 存在，且底墊參數違反 `PAD_CONFIG_INVALID` 規則
- **THEN** 驗證 MUST 通過
- **AND** 切片 MUST NOT 被擋下

#### Scenario: 自生支撐且底墊參數違規
- **WHEN** 無 `input/support.stl`，且底墊參數違反同一條規則
- **THEN** 驗證 MUST 失敗並回報 `PAD_CONFIG_INVALID`

### Requirement: 無狀態參數驗證端點

系統 SHALL 提供 `POST /api/v2/support-params/validate`。該端點 MUST NOT 建立 job、MUST NOT 讀寫磁碟、MUST NOT 呼叫引擎。

Request MUST 接受整組參數（不做欄位白名單）、`flow`、以及選填的 `manual_point_count`、`per_point`、`printer_bounds`。

Response MUST 包含 `ok`、`problems[]`、`clamped[]`、`unknown[]`。

#### Scenario: 參數有問題
- **WHEN** 送出一組違反規則的參數
- **THEN** 回應 `ok` 為 false
- **AND** `problems[]` 每筆含 `code`、`fields[]`、`suggestion`

#### Scenario: 端點不留下副作用
- **WHEN** 連續呼叫端點 100 次
- **THEN** MUST NOT 產生任何 job 目錄或暫存檔

#### Scenario: 效能
- **WHEN** 以典型參數組呼叫 1000 次
- **THEN** 單次耗時 p95 MUST 小於 5 毫秒

### Requirement: 動態門檻須回報算出的數值

當規則的門檻由其他參數推導而得時，`problems[]` SHALL 攜帶當下算出的門檻值與實際值，MUST NOT 只回傳 code。

#### Scenario: 底墊側壁角度門檻
- **WHEN** `pad_wall_thickness / tan(pad_wall_slope) > pad_brim_size`
- **THEN** 回報 `PAD_CONFIG_INVALID`
- **AND** 攜帶當下算出的最小合法 `pad_wall_slope`
- **AND** 該門檻 MUST 隨 `pad_wall_thickness` 與 `pad_brim_size` 改變而改變，MUST NOT 為寫死常數

### Requirement: 靜默修改與未知欄位須回報

系統 SHALL 在 `clamped[]` 回報所有會被後端或引擎靜默修改的值（含原值與實際生效值），在 `unknown[]` 回報所有後端不認得的欄位名。

兩者 MUST NOT 使驗證失敗。`SLAConfig` 的 `extra` 行為 MUST 維持 `ignore`。

#### Scenario: 抬升高度被拉高
- **WHEN** 送出 `support_object_elevation` 為 3
- **THEN** `clamped[]` 含該欄位，原值 3、生效值 5
- **AND** `ok` 不因此變為 false

#### Scenario: 欄位名打錯
- **WHEN** 送出一個 `SLAConfig` 不存在的欄位名
- **THEN** `unknown[]` 含該欄位名
- **AND** 請求 MUST NOT 被拒絕

### Requirement: 參數錯誤須回 422 而非 500

當請求因參數驗證失敗時，v2 會拋錯的入口 SHALL 回傳 HTTP 422、`retryable: false`，訊息 MUST 指出出問題的欄位名。這些入口包括：

- `POST /api/v2/slices`（建立工作時帶入的初始 `config`）
- `PUT /api/v2/slices/{job_id}/config`
- `POST /api/v2/slices/{job_id}/execute`
- `POST /api/v2/slices/{job_id}/generate-supports`
- `POST /api/v2/slices/{job_id}/export-support-points`
- `POST /api/v2/slices/{job_id}/generate-hollow`

若失敗原因是 `SLAConfig` 欄位驗證（例如 `pad_wall_slope`、`support_points_density_relative`、`support_points_min_distance` 超出範圍），錯誤碼 SHALL 為 `CONFIG_VALIDATION_ERROR`。唯一的例外：只要失敗的欄位中有 `support_max_bridge_length` 或 `support_base_diameter`，錯誤碼 SHALL 為 `SUPPORT_PARAM_INVALID`（見「連接長度與底座直徑須為有限正數」）。

這些入口 MUST NOT 落入通用的 `except Exception` 兜底而回傳 `INTERNAL_ERROR`（HTTP 500、`retryable: true`）。

另有兩個入口的回應方式不同：

- `POST /api/v2/support-params/validate` MUST NOT 拋錯。它 SHALL 回傳 HTTP 200、`ok: false`，`problems[]` 含出問題欄位的項目，且其 `fields` 含出問題的欄位名。項目的 `code` 依上一段的規則決定：`support_max_bridge_length` 與 `support_base_diameter` 為 `SUPPORT_PARAM_INVALID`，其他 `SLAConfig` 欄位為 `CONFIG_VALIDATION_ERROR`。`SUPPORT_PARAM_INVALID` 的項目 SHALL 排在 `problems[]` 的最前面。
- v1 `POST /api/jobs` SHALL 維持既有行為，回傳 HTTP 400，訊息以 `Invalid config:` 開頭。這也適用於 `support_max_bridge_length` 與 `support_base_diameter` 的違規值。

#### Scenario: 側壁角度低於後端下限
- **WHEN** 直接呼叫 API 送出 `pad_wall_slope` 為 35
- **THEN** 回應 HTTP 422
- **AND** `retryable` 為 false
- **AND** 訊息含 `pad_wall_slope`

#### Scenario: 四個入口一致
- **WHEN** 分別對 `/execute`、`/generate-supports`、`/export-support-points`、`/generate-hollow` 送出違規參數
- **THEN** 四者 MUST 都回 422，MUST NOT 有任一處回 500

#### Scenario: 存設定時密度超出範圍
- **GIVEN** 一個待處理的切片工作
- **WHEN** 以 `support_points_density_relative` 為 -5 呼叫 `PUT /api/v2/slices/{job_id}/config`
- **THEN** 回應 HTTP 422，錯誤碼為 `CONFIG_VALIDATION_ERROR`
- **AND** `retryable` 為 false
- **AND** 訊息含 `support_points_density_relative`

#### Scenario: 執行端點遇到 min_distance 超出範圍
- **GIVEN** 一個待處理的切片工作，存下的設定裡 `support_points_min_distance` 為 150
- **WHEN** 分別呼叫 `/execute`、`/generate-supports`、`/export-support-points`、`/generate-hollow`
- **THEN** 四者都回應 HTTP 422，錯誤碼為 `CONFIG_VALIDATION_ERROR`
- **AND** 訊息含 `support_points_min_distance`
- **AND** MUST NOT 建立任何背景引擎工作

#### Scenario: 執行端點遇到連接長度為 0
- **GIVEN** 一個待處理的切片工作，存下的設定裡 `support_max_bridge_length` 為 0（例如繞過 `PUT /config` 直接寫入）
- **WHEN** 分別呼叫 `/execute`、`/generate-supports`、`/export-support-points`、`/generate-hollow`
- **THEN** 四者都回應 HTTP 422，錯誤碼為 `SUPPORT_PARAM_INVALID`
- **AND** `data.errors[]` 含 `loc` 為 `["support_max_bridge_length"]` 的項目
- **AND** MUST NOT 建立任何背景引擎工作，引擎佇列不受影響

#### Scenario: 驗證端點以 problems 回報
- **WHEN** 以 `support_points_density_relative` 為 10001 呼叫 `POST /api/v2/support-params/validate`
- **THEN** 回應 HTTP 200
- **AND** `ok` 為 false
- **AND** `problems[]` 含一筆 `code` 為 `CONFIG_VALIDATION_ERROR`、`fields` 含 `support_points_density_relative` 的項目

#### Scenario: 驗證端點回報支撐參數錯誤
- **WHEN** 以 `support_points_density_relative` 為 10001、`support_base_diameter` 為 0 呼叫 `POST /api/v2/support-params/validate`
- **THEN** 回應 HTTP 200，`ok` 為 false
- **AND** `problems[0]` 的 `code` 為 `SUPPORT_PARAM_INVALID`、`fields` 含 `support_base_diameter`
- **AND** `problems[]` 另含一筆 `code` 為 `CONFIG_VALIDATION_ERROR`、`fields` 含 `support_points_density_relative` 的項目

#### Scenario: v1 上傳端點維持 400
- **WHEN** 呼叫 `POST /api/jobs`，`config` 表單欄位的 JSON 裡 `support_points_density_relative` 為 -1
- **THEN** 回應 HTTP 400
- **AND** 訊息以 `Invalid config:` 開頭

#### Scenario: v1 上傳端點擋下連接長度為 0
- **WHEN** 呼叫 `POST /api/jobs`，`config` 表單欄位的 JSON 裡 `support_max_bridge_length` 為 0
- **THEN** 回應 HTTP 400，訊息以 `Invalid config:` 開頭
- **AND** MUST NOT 建立 job 或排入任何引擎工作

### Requirement: 匯入支撐時須重設支撐與底墊參數

`run_slicing()` 偵測到 `input/support.stl` 時，SHALL 將所有 `support_*` 與 `pad_*` 欄位明確重設為後端預設值，MUST NOT 只關閉 `supports_enable` 與 `pad_enable`。

#### Scenario: 匯入支撐的設定寫出
- **WHEN** `input/support.stl` 存在且使用者設定了非預設的底墊參數
- **THEN** 寫出的 `config.ini` 中所有 `pad_*` 與 `support_*` 為後端預設值

### Requirement: 相對密度範圍防護

`SLAConfig` SHALL 只接受 `0 <= support_points_density_relative <= 10000`。

- 密度為 0 時，`SLAConfig` 驗證 MUST 通過。這是為了保留「密度 0 加手動點」的合法路徑。密度 0 且沒有手動點的情況，仍由既有規則 `SUPPORT_POINTS_REQUIRED`（R5）判斷。
- 負數與大於 10000 的值 SHALL 被拒絕。錯誤訊息 MUST 含欄位名 `support_points_density_relative`。
- 系統 MUST NOT 把違規值自動改成邊界值。違規值也 MUST NOT 出現在 `clamped[]`。

#### Scenario: 密度 0 通過驗證
- **GIVEN** 一組其餘欄位皆合法的參數
- **WHEN** 以 `support_points_density_relative` 為 0 建立 `SLAConfig`
- **THEN** 建立成功，欄位值為 0

#### Scenario: 密度 0 搭配手動點不被擋下
- **GIVEN** `supports_enable` 為 true，`support_points_density_relative` 為 0
- **WHEN** 以 `manual_point_count` 為 5 呼叫 `POST /api/v2/support-params/validate`
- **THEN** `problems[]` MUST NOT 含任何 `fields` 包含 `support_points_density_relative` 的項目

#### Scenario: 上界 10000 通過驗證
- **WHEN** 以 `support_points_density_relative` 為 10000 建立 `SLAConfig`
- **THEN** 建立成功，欄位值為 10000

#### Scenario: 超過上界被拒絕
- **WHEN** 以 `support_points_density_relative` 為 10001 建立 `SLAConfig`
- **THEN** 拋出 `ValidationError`
- **AND** 錯誤訊息含 `support_points_density_relative`

#### Scenario: 負數被拒絕
- **WHEN** 以 `support_points_density_relative` 為 -1 建立 `SLAConfig`
- **THEN** 拋出 `ValidationError`
- **AND** 錯誤訊息含 `support_points_density_relative`

#### Scenario: 不自動夾限
- **GIVEN** 一個待處理的切片工作，其 `support_points_density_relative` 已存為 100
- **WHEN** 以 `support_points_density_relative` 為 20000 呼叫 `PUT /api/v2/slices/{job_id}/config`
- **THEN** 請求被拒絕
- **AND** 該工作存下的 `support_points_density_relative` MUST 仍為 100，MUST NOT 變成 10000

### Requirement: 最近點距範圍與 NaN 防護

`SLAConfig` SHALL 只接受 `0.0 <= support_points_min_distance <= 100.0`。

- 負數、大於 100.0、`NaN`、`+Infinity`、`-Infinity` SHALL 被拒絕。錯誤訊息 MUST 含欄位名 `support_points_min_distance`。
- 判斷 MUST 對 `NaN` 成立。也就是說，不能用「小於下界或大於上界」這種對 `NaN` 一律回傳 false 的寫法。
- 系統 MUST NOT 把違規值自動改成邊界值。違規值也 MUST NOT 出現在 `clamped[]`。

#### Scenario: 邊界值通過驗證
- **WHEN** 分別以 `support_points_min_distance` 為 0.0 與 100.0 建立 `SLAConfig`
- **THEN** 兩者都建立成功

#### Scenario: 負數被拒絕
- **WHEN** 以 `support_points_min_distance` 為 -0.1 建立 `SLAConfig`
- **THEN** 拋出 `ValidationError`
- **AND** 錯誤訊息含 `support_points_min_distance`

#### Scenario: 超過 100 mm 被拒絕
- **WHEN** 以 `support_points_min_distance` 為 100.01 建立 `SLAConfig`
- **THEN** 拋出 `ValidationError`
- **AND** 錯誤訊息含 `support_points_min_distance`

#### Scenario: NaN 被拒絕
- **WHEN** 以 `support_points_min_distance` 為 `float("nan")` 建立 `SLAConfig`
- **THEN** 拋出 `ValidationError`
- **AND** 錯誤訊息含 `support_points_min_distance`

#### Scenario: 正負無限大被拒絕
- **WHEN** 分別以 `support_points_min_distance` 為 `float("inf")` 與 `float("-inf")` 建立 `SLAConfig`
- **THEN** 兩者都拋出 `ValidationError`
- **AND** 錯誤訊息含 `support_points_min_distance`

#### Scenario: JSON 字面值 NaN 被拒絕
- **GIVEN** 一個待處理的切片工作
- **WHEN** 呼叫 `PUT /api/v2/slices/{job_id}/config`，請求本體的 JSON 寫著 `"support_points_min_distance": NaN`
- **THEN** 請求被拒絕，設定不被存下

#### Scenario: 不出現在 clamped
- **WHEN** 以 `support_points_min_distance` 為 150 呼叫 `POST /api/v2/support-params/validate`
- **THEN** `clamped[]` MUST NOT 含 `support_points_min_distance`

### Requirement: 連接長度與底座直徑須為有限正數

`SLAConfig` SHALL 只接受有限且不小於 `1e-4` 的 `support_max_bridge_length`（Max Connector Length），以及有限且不小於 `2e-4` 的 `support_base_diameter`（Base Diameter）。

底座直徑的下限 SHALL 是自訂支撐點 `base_radius_mm` 門檻（`1e-4`）的 2 倍。原因是引擎把底座直徑折半成半徑，寫進匯出的每個支撐點；下限取 2 倍，匯出的半徑才一定不小於單點門檻，`GET /support-points` 取回的清單原樣送回 `POST /support-points` 時才不會被拒絕。

- `0`、`-0.0`、負數、小於該欄位下限的正數（例如 `1e-9`、`0.00009`、`5e-324`；底座直徑另含 `0.0001`、`0.00015`）、`NaN`、`+Infinity`、`-Infinity` SHALL 被拒絕。可被轉成上述數值的字串（例如 `"0"`）也 SHALL 被拒絕。
- 判斷 MUST 對 `NaN` 成立。
- 系統 MUST NOT 把違規值自動改成合法值。違規值也 MUST NOT 出現在 `clamped[]`。
- 任何不小於該欄位下限的有限值（包括下限本身）SHALL 被接受。
- `support_max_pillar_link_distance`（Max Pillar Link Distance）MUST NOT 受本需求影響，`0` 仍是合法值。

API 回應時，只要驗證錯誤中有任何一筆的欄位是上述兩者之一，錯誤碼 SHALL 為 `SUPPORT_PARAM_INVALID`（HTTP 422、`retryable: false`），回應的 `data.errors[]` SHALL 列出每一筆驗證錯誤的 `loc`（欄位位置）與 `msg`（原因）。同一請求中其他欄位的驗證錯誤 MUST 一併列在 `data.errors[]`，MUST NOT 遺失。

#### Scenario: 零值被拒絕
- **GIVEN** 一個待處理的切片工作
- **WHEN** 以 `support_max_bridge_length` 為 0 呼叫 `PUT /api/v2/slices/{job_id}/config`
- **THEN** 回應 HTTP 422，錯誤碼為 `SUPPORT_PARAM_INVALID`
- **AND** `retryable` 為 false
- **AND** `data.errors[]` 含一筆 `loc` 為 `["support_max_bridge_length"]` 的項目
- **AND** 該設定 MUST NOT 被存下

#### Scenario: 負零被拒絕
- **WHEN** 以 `support_base_diameter` 為 `-0.0` 建立 `SLAConfig`
- **THEN** 拋出 `ValidationError`
- **AND** 錯誤位置為 `support_base_diameter`

#### Scenario: 負數被拒絕
- **WHEN** 分別以 `support_max_bridge_length` 為 -1 與 `support_base_diameter` 為 -0.5 建立 `SLAConfig`
- **THEN** 兩者都拋出 `ValidationError`

#### Scenario: NaN 被拒絕
- **WHEN** 分別以兩個欄位為 `float("nan")` 建立 `SLAConfig`
- **THEN** 兩者都拋出 `ValidationError`

#### Scenario: JSON 字面值 NaN 被拒絕
- **GIVEN** 一個待處理的切片工作
- **WHEN** 呼叫 `PUT /api/v2/slices/{job_id}/config`，請求本體的 JSON 寫著 `"support_base_diameter": NaN`
- **THEN** 回應 HTTP 422，錯誤碼為 `SUPPORT_PARAM_INVALID`
- **AND** 該設定 MUST NOT 被存下

#### Scenario: 正負無限大被拒絕
- **WHEN** 分別以兩個欄位為 `float("inf")` 與 `float("-inf")` 建立 `SLAConfig`
- **THEN** 四種組合都拋出 `ValidationError`

#### Scenario: 字串零被拒絕
- **WHEN** 以 `support_max_bridge_length` 為字串 `"0"` 建立 `SLAConfig`
- **THEN** 拋出 `ValidationError`

#### Scenario: 小於門檻的正數被拒絕
- **WHEN** 分別以兩個欄位為 `0.00009`、`1e-9`、`5e-324` 建立 `SLAConfig`
- **THEN** 每一種都拋出 `ValidationError`
- **AND** 錯誤位置為該欄位

#### Scenario: 底座直徑小於 2e-4 被拒絕
- **WHEN** 分別以 `support_base_diameter` 為 `0.0001`、`0.00015`、`0.00019` 建立 `SLAConfig`
- **THEN** 每一種都拋出 `ValidationError`
- **AND** 錯誤位置為 `support_base_diameter`

#### Scenario: 門檻值本身可通過
- **WHEN** 以 `support_max_bridge_length` 為 `0.0001`、`support_base_diameter` 為 `0.0002` 建立 `SLAConfig`
- **THEN** 建立成功

#### Scenario: 預設值不受影響
- **WHEN** 不帶任何參數建立 `SLAConfig`
- **THEN** 建立成功，`support_max_bridge_length` 為 15.0、`support_base_diameter` 為 4.0

#### Scenario: Link Distance 為 0 仍合法
- **GIVEN** 一個待處理的切片工作
- **WHEN** 以 `support_max_pillar_link_distance` 為 0、其他參數皆為預設值呼叫 `PUT /api/v2/slices/{job_id}/config`
- **THEN** 回應成功，設定被存下

#### Scenario: 與其他欄位錯誤同時發生
- **GIVEN** 一個待處理的切片工作
- **WHEN** 呼叫 `PUT /api/v2/slices/{job_id}/config`，同時送出 `pad_wall_slope` 為 35 與 `support_max_bridge_length` 為 0
- **THEN** 錯誤碼為 `SUPPORT_PARAM_INVALID`
- **AND** `data.errors[]` 同時含 `pad_wall_slope` 與 `support_max_bridge_length` 兩筆

#### Scenario: 不出現在 clamped
- **WHEN** 以 `support_base_diameter` 為 0 呼叫 `POST /api/v2/support-params/validate`
- **THEN** `clamped[]` MUST NOT 含 `support_base_diameter`

