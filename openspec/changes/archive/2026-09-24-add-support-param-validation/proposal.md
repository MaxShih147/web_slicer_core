## Why

支撐參數面板即將從 7 個欄位開放到 30 個。今天踩不到的引擎規則，開放之後每一條都會被踩到。

三個具體問題：

1. **使用者填錯，後端回「伺服器錯誤，請重試」。** `api_v2.py` 的三個入口（`:351`、`:575`、`:618`）都用 `except Exception` 兜底並回 `internal_error`（HTTP 500 + `retryable: true`）。參數填錯是永遠不會因為重試而好的錯。
2. **面板與後端的範圍對不上。** `pad_wall_slope` 面板下限 30 度，後端 `models.py` 的 validator 在 45 度以下直接 `raise ValueError`。30～44 是死區，今天就存在，開放後天天踩。
3. **參數住在前端，後端平常看不到。** 要等到按下「產生支撐」或「切片」才會同步過去，使用者得等一輪引擎（數秒到數十秒）才知道自己填錯。

引擎的 9 條 validate 規則裡，**有 7 條是純算術**，可以在不跑引擎的情況下事先算出來。

## What Changes

- 新增 `agent/param_rules.py`：一張參數規則表。每列含 `code`、`scope`、`fields`（用到的欄位）、`predicate`（判斷式）、`suggestion`。判斷式**逐條對照 C++ 原始碼寫出來，不自行發明**。
  - `scope` 只有兩種：`support_params`（支撐頭／柱／底座／連接柱／佈點／底墊）與 `slice_only`（曝光時間等）。
  - profile 是 scope 的**聯集**，不是平行的兩張表：
    | profile | 取哪些 scope | 使用時機 |
    |---|---|---|
    | `support` | `support_params` | 產生支撐 |
    | `slice` | `support_params` + `slice_only` | 切片且**自生支撐** |
    | `slice_imported` | `slice_only` | 切片且**已匯入 `support.stl`** |
  - `slice_imported` 刻意不驗支撐參數：`jobs.py:449-457` 在偵測到 `input/support.stl` 時強制 `supports_enable=False`、`pad_enable=False`，引擎會忽略所有支撐與底墊參數。此時去驗它們只會製造**假失敗**。
- 新增 `POST /api/v2/support-params/validate`：無狀態、不建 job、不碰磁碟、不跑引擎。回傳 `ok`、`problems[]`（含 `code` / `fields` / `suggestion`）、`clamped[]`（後端會靜默改掉的值）、`unknown[]`（後端不認得的欄位名）。
  - Request 送**整組參數**，不做白名單。白名單一定會漏——兩支分類器已經各漏一次。
- 三個入口新增 `except ValidationError` 分支：回 HTTP 422、`retryable: false`、訊息帶欄位名。不再落到 500。
- `PUT /config` 接上規則表：存設定當下就擋，不等到 execute。
- `run_slicing()` 在偵測到 `support.stl` 時，將所有 `pad_*` 與 `support_*` **明確重設回後端預設值**，不只關 `pad_enable` 與 `supports_enable`。

**本單刻意不做**：不改 `SLAConfig` 的 `extra='ignore'` 為 `forbid`（會打壞既有呼叫端），未知欄位改由 `unknown[]` 回報；不動引擎；不改前端（由 companion change `open-support-param-panel` 承接）。

## Capabilities

### New Capabilities

- `support-param-validation`：事前參數驗證的規則表結構、三種 profile 的取用規則、`/validate` 端點契約、以及「規則只寫一份、放後端、前端用問的」這個不變量。

### Modified Capabilities

- `slice-config-intake`：`PUT /config` 從「原封不動收下」改為「當下驗證，違規回 422」。
- `pad-global-params`：底墊參數的合法範圍改由 `param_rules.py` 統一定義，並回報算出來的動態下限（`pad_wall_thickness / tan(slope) ≤ pad_brim_size`）。

## Impact

| 對象 | 影響 |
|---|---|
| `agent/param_rules.py` | 新檔 |
| `agent/api_v2.py` | 新端點；三處兜底新增 `ValidationError` 分支；`PUT /config` 接規則表 |
| `agent/jobs.py` | `run_slicing()` 匯入模式明確重設支撐／底墊參數 |
| `agent/models.py` | 不改欄位定義；`enforce_min_elevation` 等 clamp 行為改為同時回報 `clamped[]` |
| `agent/tests/` | 新增 `test_param_rules.py`、`test_param_rules_contract.py`、`test_support_params_validate.py` |
| DS-Online | **跨 repo**：本單為權威 spec，前端實作見 `open-support-param-panel` |

**前置條件**：`unify-error-code-registry` 必須先完成——`/validate` 回傳的 `code` 必須取自登錄檔。

**跨 repo**：見同目錄 `CROSS-REPO.md`。
