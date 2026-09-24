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

當請求因參數驗證失敗時，系統 SHALL 回傳 HTTP 422、`retryable: false`，訊息 MUST 指出出問題的欄位名。

MUST NOT 落入通用的 `except Exception` 兜底而回傳 `INTERNAL_ERROR`（HTTP 500、`retryable: true`）。

#### Scenario: 側壁角度低於後端下限
- **WHEN** 直接呼叫 API 送出 `pad_wall_slope` 為 35
- **THEN** 回應 HTTP 422
- **AND** `retryable` 為 false
- **AND** 訊息含 `pad_wall_slope`

#### Scenario: 三個入口一致
- **WHEN** 分別對三個既有入口送出違規參數
- **THEN** 三者 MUST 都回 422，MUST NOT 有任一處回 500

### Requirement: 匯入支撐時須重設支撐與底墊參數

`run_slicing()` 偵測到 `input/support.stl` 時，SHALL 將所有 `support_*` 與 `pad_*` 欄位明確重設為後端預設值，MUST NOT 只關閉 `supports_enable` 與 `pad_enable`。

#### Scenario: 匯入支撐的設定寫出
- **WHEN** `input/support.stl` 存在且使用者設定了非預設的底墊參數
- **THEN** 寫出的 `config.ini` 中所有 `pad_*` 與 `support_*` 為後端預設值

