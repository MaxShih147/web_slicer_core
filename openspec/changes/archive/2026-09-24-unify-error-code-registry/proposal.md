## Why

後端有 28 個 error code，但它們以**裸字面值**散在九份互相手抄的清單裡（`errors.py` 的 factory、`api_v2.py` 的 `_ERROR_CODE_FACTORIES`、`docs/err_code_spec.md`、`DS-Online/api/slicing_core.md`、前端 `BACKEND_ERROR_KEYS`、四語系文案、前端測試的手抄常數、兩支分類器各自的對照表）。**九份清單，零個檢查點。**

漂移已經發生：`PAD_CONFIG_INVALID`、`SUPPORT_POINTS_MODEL_MISMATCH`、`BOOLEAN_INVALID_MESH` 三個 code 後端有、前端完全沒有對應 i18n key，後端辛苦分類出的原因在最後一哩退化成「未預期的錯誤」，且無人發現。

支撐參數面板即將從 7 個欄位開放到 30 個，錯誤路徑會被大量踩到。後續兩個 change（合併分類器、支撐參數事前驗證）都需要一份可信的 code 清單當基準，所以這一單必須最先完成。

## What Changes

- 新增 `agent/error_codes.py`：28 個 error code 的**唯一真值**。每筆記錄含 `code`、`http_status`、`retryable`、`owner`（`engine` / `python`）、`note`（繁中說明）、`engine_needles`（僅 `owner=engine` 者）。
- 新增 `agent/tools/error_codes.py`：
  - `--write` 產生 `docs/err_code_spec.md` 與 `docs/error_codes.json`。
  - `--check` 只比對不寫檔，產出物與 commit 版本不一致即回非零，供本地 pipeline / pre-commit 使用。
- **BREAKING（文件層）**：`docs/err_code_spec.md` 改為自動產生，**不得手動編輯**。原本寫在 md 的中文說明搬進 `error_codes.py` 的 `note` 欄位。
- `api_v2.py` 的 `_ERROR_CODE_FACTORIES` 改由登錄檔於執行期推導，手抄的 dict 移除。
- 新增兩條契約測試：`errors.py` 每個 code 都有對應 factory（缺就紅）；`owner=engine` 的 code 其 `engine_needles` 字串仍存在於 `third_party/prusaslicer_fork` 原始碼（沿用 `test_support_string_contract.py` 的掃描手法）。

**本單刻意不做**：不產生 Python 程式碼（factory 仍手寫，只做「缺漏檢查」）；不改任何 runtime 行為；不動兩支分類器的判斷邏輯；不跨 repo 自動寫檔。

## Capabilities

### New Capabilities

- `error-code-registry`：error code 的單一真值來源、衍生文件的產生規則、以及「產出物過期即失敗」的檢查機制。

### Modified Capabilities

（無。本單為零行為變更的重構，`slicing-error-codes` 與 `support-generation-error-codes` 的 requirement 不變，只有實作來源改變。）

## Impact

| 對象 | 影響 |
|---|---|
| `agent/error_codes.py` | 新檔（真值） |
| `agent/tools/error_codes.py` | 新檔（產生器） |
| `agent/errors.py` | 不改實作，新增契約測試覆蓋 |
| `agent/api_v2.py` | 移除 `_ERROR_CODE_FACTORIES` 手抄 dict |
| `docs/err_code_spec.md` | 「Error Code Reference」表格區塊改為自動產生（唯讀）；其餘章節（Error Response Format、Endpoints）維持手動維護，不受 `--write` 管理（見 tasks.md 2.2 訂正） |
| `docs/error_codes.json` | 新檔（自動產生，供跨 repo 對帳） |
| `agent/tests/` | 新增 2 支契約測試 |
| DS-Online | 本單不動；下游由 `open-support-param-panel` 消費 `error_codes.json` |
| 本地 pipeline | 新增 `--check` 關卡 |

**API 相容性**：HTTP 回應格式、`code` 值、HTTP status、`retryable` 全部不變。前端零改動。
