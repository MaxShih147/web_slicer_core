## Context

後端 28 個 error code 目前沒有任何一處是「清單」。`errors.py:1` 的 docstring 寫著 `matching err_code_spec.md`，但那是一句宣告，沒有測試在驗。全庫掃過 `.py` / `.sh` / `.yml` / `.js`，找不到任何產生器。

九份手抄清單的實際位置：

| # | 位置 | 形式 |
|---|---|---|
| 1 | `agent/errors.py` | 28 個 factory 函式（事實上的真值） |
| 2 | `agent/api_v2.py:253` `_ERROR_CODE_FACTORIES` | 手抄 dict |
| 3 | `docs/err_code_spec.md` | 手寫表格 |
| 4 | `DS-Online/api/slicing_core.md:331` | 跨 repo 手抄表格 |
| 5 | `DS-Online/src/services/errors.js` `BACKEND_ERROR_KEYS` | 手寫 |
| 6 | `DS-Online/src/i18n/locales/*.json` × 4 | 手寫 |
| 7 | `DS-Online/src/services/__tests__/backendErrorKeys.spec.js:8` | 手抄 6 個常數 |
| 8-9 | 兩支 classifier 的 needle→code 表 | 手抄 |

## Goals / Non-Goals

**Goals**

- 把 28 個 code 收斂成**一份人寫的真值**。
- 衍生文件（`err_code_spec.md`、`error_codes.json`）改為自動產生，且產出物過期即失敗。
- 建立跨 repo 對帳的機器可讀介面。

**Non-Goals**

- 不產生 Python 程式碼。factory 有時需要客製訊息，生成程式碼會讓除錯困難。
- 不改任何 runtime 行為。HTTP 回應格式、code 值、status、`retryable` 全部不變。
- 不跨 repo 自動寫檔。DS-Online 是另一個 repo、跨帳號，後端腳本不得寫入。
- 不動兩支分類器（那是 `merge-engine-result-classifiers` 的範圍）。

## Decisions

### D1：真值放 Python，不放 Markdown

**決定**：`agent/error_codes.py` 是真值，`err_code_spec.md` 由它產生。

**理由**：md 無法被 import，無法被型別檢查，也無法在執行期推導 `_ERROR_CODE_FACTORIES`。反過來（md 為真值、Python 從 md 讀）會讓 runtime 依賴文件檔案存在。

**代價**：以後改中文說明要編 Python 檔，不能直接編 md。**這是本單唯一變麻煩的地方，已與使用者確認接受。**

### D2：每個 code 標 `owner`（`engine` / `python`）

**決定**：登錄檔每筆記錄標明這個 code 由誰產生。

分群結果：

| owner | 數量 | 內容 |
|---|---|---|
| `engine` | 13 | 引擎在自己的 process 裡就能判斷的，且有專屬的 needle 字串可比對。含 `SUPPORT_HEAD_TOO_WIDE`、`PAD_CONFIG_INVALID`、`MODEL_OUT_OF_BOUNDS`、`INVALID_MODEL` 等 |
| `python` | 15 | 需要知道 job、檔案系統、HTTP 才能判斷的，或雖然源頭是引擎執行結果、但判斷點在 Python（如檢查 exit code / 輸出檔是否存在）。含 `JOB_NOT_FOUND`、`NO_DRAIN_HOLES`、`BOOLEAN_FAILED`、`JOB_FAILED`、`HOLLOW_GENERATION_FAILED`、`SUPPORT_GENERATION_FAILED` 等 |

**理由**：後續 `engine-error-code-table`（C++ 出 code）只實作 `owner=engine` 那 13 個。B 群的概念（job 目錄、HTTP status、pydantic，或需綜合 exit code／檔案是否產生等多重條件）不該進引擎。現在先標好，屆時直接篩選即可。

**訂正記錄（2026-09-17）**：本節原寫 `engine=14 / python=14`，並把 `HOLLOW_GENERATION_FAILED` 列為 engine 群範例。實作前對照實際程式碼（`agent/sla_operations.py` 的 `generate_hollow`、`agent/api_v2.py` 的 boolean/hex-grid/drain-hole 呼叫點）發現這四個（`HOLLOW_GENERATION_FAILED`、`BOOLEAN_FAILED`、`BOOLEAN_INVALID_MESH`、`NO_DRAIN_HOLES`、`NO_HEX_GRID_CELLS`）皆由 Python 檢查 exit code 或輸出檔是否存在來判斷，並無專屬 engine needle 字串；`SUPPORT_GENERATION_FAILED` 同理是「兩支 classifier 皆比對不到」時的 fallback，沒有專屬 needle。依 `error-code-registry` spec 「owner=engine 但 engine_needles 為空 MUST 拋錯」的規則，以上五者只能歸為 `python`，故正確分群為 `engine=13 / python=15`。

**判準**：引擎在自己的 process 裡就能判斷的 → `engine`。需要 job、檔案系統、HTTP、或需綜合多次執行結果的 → `python`。

### D3：只做「檢查」，不做「程式碼生成」

**決定**：產生器對 `errors.py` 的 factory **只檢查缺漏**，不自動補寫。

**理由**：factory 簽名不一致（有的吃 `detail`，有的吃 `job_id`），生成的程式碼會比手寫更難維護。缺漏檢查已經能擋住 100% 的漏補。

### D4：`--check` 是本單的核心，不是附屬品

**決定**：同一支腳本提供 `--write` 與 `--check`。`--check` 不寫檔，只比對產出物與 commit 版本；不一致回非零，並印出「請執行 `--write`」。

**理由**：只有手動觸發不夠，人會忘記。`--check` 掛在本地 pipeline / pre-commit，才讓這套自動化真正生效。**沒有 `--check`，這一單只是把一個手動步驟換成另一個手動步驟。**

### D5：跨 repo 用「產出 ＋ 測試擋」，不用「自動同步」

**決定**：後端腳本產生 `docs/error_codes.json` 就停。DS-Online 自己拉一份到 `api/`，由前端測試把關。

**理由**：兩個 repo 跨帳號、SSH submodule 佈局。後端腳本偷寫別的 repo 再 commit 是壞習慣。且 `DS-Online/api/README.md` 已有「後端 API 變更必須同步此資料夾」的既有規則，沿用即可，不新增制度。

**失敗模式覆蓋**：後端改了、前端沒拉 → 前端 `backendErrorKeys.spec.js` 紅。

## Risks

| 風險 | 影響 | 緩解 |
|---|---|---|
| `err_code_spec.md` 被手改後又被 `--write` 覆蓋，改動遺失 | 中 | 產生的檔案頂端加醒目標頭：「本檔自動產生，請勿手動編輯；改說明請編 `agent/error_codes.py`」 |
| `_ERROR_CODE_FACTORIES` 改執行期推導後，某個 factory 名稱對不上 | 高 | 契約測試逐一驗證 28 個 code 都推導得到 factory；推導失敗即測試紅，不進 runtime |
| 中文說明搬家時抄漏或抄錯 | 中 | `--write` 首次執行後，用 `git diff docs/err_code_spec.md` 逐行比對，差異必須為零（除新增標頭） |

## Migration

1. 先寫 `error_codes.py`，`note` 欄位**逐字**抄自現有 `err_code_spec.md`。
2. 跑 `--write`，`git diff` 應只有新增的「自動產生」標頭。這是搬家無損的證明。
3. 再改 `_ERROR_CODE_FACTORIES`。
4. 最後掛 `--check`。

**順序不可顛倒**：先改 `_ERROR_CODE_FACTORIES` 會讓步驟 2 的 diff 混入無關改動，失去驗證力。
