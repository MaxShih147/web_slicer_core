## ADDED Requirements

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

## MODIFIED Requirements

### Requirement: 參數錯誤須回 422 而非 500

當請求因參數驗證失敗時，v2 會拋錯的入口 SHALL 回傳 HTTP 422、`retryable: false`，訊息 MUST 指出出問題的欄位名。這些入口包括：

- `PUT /api/v2/slices/{job_id}/config`
- `POST /api/v2/slices/{job_id}/execute`
- `POST /api/v2/slices/{job_id}/generate-supports`
- `POST /api/v2/slices/{job_id}/export-support-points`
- `POST /api/v2/slices/{job_id}/generate-hollow`

若失敗原因是 `SLAConfig` 欄位驗證（例如 `pad_wall_slope`、`support_points_density_relative`、`support_points_min_distance` 超出範圍），錯誤碼 SHALL 為 `CONFIG_VALIDATION_ERROR`。

這些入口 MUST NOT 落入通用的 `except Exception` 兜底而回傳 `INTERNAL_ERROR`（HTTP 500、`retryable: true`）。

另有兩個入口的回應方式不同：

- `POST /api/v2/support-params/validate` MUST NOT 拋錯。它 SHALL 回傳 HTTP 200、`ok: false`，`problems[]` 含一筆 `code` 為 `CONFIG_VALIDATION_ERROR` 的項目，且其 `fields` 含出問題的欄位名。
- v1 `POST /api/jobs` SHALL 維持既有行為，回傳 HTTP 400，訊息以 `Invalid config:` 開頭。

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

#### Scenario: 驗證端點以 problems 回報
- **WHEN** 以 `support_points_density_relative` 為 10001 呼叫 `POST /api/v2/support-params/validate`
- **THEN** 回應 HTTP 200
- **AND** `ok` 為 false
- **AND** `problems[]` 含一筆 `code` 為 `CONFIG_VALIDATION_ERROR`、`fields` 含 `support_points_density_relative` 的項目

#### Scenario: v1 上傳端點維持 400
- **WHEN** 呼叫 `POST /api/jobs`，`config` 表單欄位的 JSON 裡 `support_points_density_relative` 為 -1
- **THEN** 回應 HTTP 400
- **AND** 訊息以 `Invalid config:` 開頭
