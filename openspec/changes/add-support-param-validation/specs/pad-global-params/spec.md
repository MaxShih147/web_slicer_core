## MODIFIED Requirements

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
