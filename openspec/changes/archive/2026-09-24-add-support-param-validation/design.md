## Context

引擎的 validate 規則是唯一的裁判，但它只在**跑完一輪之後**才發言。參數住在前端，後端在按下按鈕之前完全看不到。

面板即將從 7 個欄位開放到 30 個。三個已驗證的現況：

1. `api_v2.py` 的 `:351`、`:575`、`:618` 都是 `except Exception: raise internal_error(str(exc))` → HTTP 500 ＋ `retryable: true`。
2. `SupportEditor.vue:109-113` 的 `pad_wall_slope` `min: 30`，`models.py:183-187` 在 45 以下直接 `raise ValueError`。**30～44 是死區。**
3. `jobs.py:449-457`：偵測到 `input/support.stl` 時強制 `supports_enable=False`、`pad_enable=False`，引擎忽略所有支撐與底墊參數。

第 3 點決定了本單最重要的設計取捨。

## Goals / Non-Goals

**Goals**

- 引擎的 7 條純算術規則，在不跑引擎的情況下事先算出來。
- 規則只寫一份、放後端。前端不得重寫任何公式。
- 使用者填錯得到 422 ＋ 欄位名，不是 500 ＋「請重試」。

**Non-Goals**

- 不搬需要模型幾何的規則（模型出界、底墊長不出來、有不可列印層）——那三條搬不動，留給引擎回報。
- 不把 `SLAConfig` 的 `extra` 從 `ignore` 改成 `forbid`（會打壞既有呼叫端）。
- 不改前端（companion change 承接）。
- 不動引擎。

## Decisions

### D1：profile 是 scope 的**子集關係**，不是兩張平行表

**決定**：

```
SLICE_RULES = SUPPORT_PARAM_RULES + SLICE_ONLY_RULES
```

規則上標 `scope`（`support_params` / `slice_only`），profile 取其聯集。

| profile | 取哪些 scope |
|---|---|
| `support` | `support_params` |
| `slice` | `support_params` ＋ `slice_only` |
| `slice_imported` | `slice_only` |

**理由**：子集關係由程式碼保證，不靠人記得同步。兩份分類器各漏一列，成因就是它們是兩張平行表。**不得在此重犯。**

### D2：匯入模式不驗支撐參數

**決定**：`import_support == True` 時使用 `slice_imported` profile。

**理由**：引擎在該模式下忽略所有支撐與底墊參數。去驗它們只會製造**假失敗**——一個對成品毫無影響的底墊規則，把一個本來會成功的切片擋下來。

**判斷因子**：`run_slicing()` 已經算好的 `import_support`（`jobs.py:446`），不需要新的狀態。

**代價**：匯入模式下無人檢查「support.stl 是用哪組參數做的」。此風險由 companion change 的參數指紋（R6）承接。

### D3：整組參數全部送，不做白名單

**決定**：`/validate` 的 request 送整組 30 個參數。

**理由**：7 條規則用到的欄位聯集是 14 個，但新增一條規則就要同步改白名單，改漏了就是靜默放行。30 個數字約 600 位元組，成本是零。**白名單一定會漏，這已經發生過兩次。**

### D4：動態門檻要算出來回報，不寫死

**決定**：`pad_wall_slope` 的下限**不是固定的 51.4 度**，而是由 `pad_wall_thickness / tan(slope) ≤ pad_brim_size` 反算。`problems[]` MUST 回報**當下算出的下限值**。

**理由**：門檻隨厚度與外擴一起動。寫死一個數字永遠會錯。使用者需要看到的是「目前需要 ≥ 51.4°」，不是「底墊參數不正確」。

**這決定了 `problems[]` 必須攜帶數值欄位，不能只有 code。**

### D5：`clamped[]` 與 `unknown[]` 是回報，不是錯誤

**決定**：

- `clamped[]`：後端會靜默改掉的值（`enforce_min_elevation` 把低於 5 的抬升拉到 5；引擎把 0 的底座安全距離改成 0.5）。回報實際生效值，不擋。
- `unknown[]`：`SLAConfig` 對未知欄位的處理是忽略。打錯欄位名沒有任何錯誤，直接吃引擎預設值。回報清單，不擋。

**理由**：兩者都不是「錯」，但使用者有權知道「我輸入的和實際生效的不一樣」。改成 `forbid` 會打壞既有呼叫端，不可行。

### D6：`/validate` 是無狀態端點

**決定**：不建 job、不讀檔、不寫檔、不碰磁碟、不跑引擎。就是一個函式加一個路由。

**理由**：它要能被每次拖滑桿呼叫。任何磁碟或 job 操作都會讓它不夠快，且會留下垃圾 job 目錄。

**效能目標**：單次 p95 < 5 毫秒。

## Risks

| 風險 | 影響 | 緩解 |
|---|---|---|
| 規則公式抄錯，事前放行但引擎擋下 | 高（使用者更困惑） | `test_param_rules_contract.py` 把公式與常數釘在 C++ 原始碼上；邊界值直接取自引擎常數 |
| 規則比引擎嚴格，擋下本來會成功的參數 | 高（假失敗） | 每條規則配一組「剛好通過」與「剛好失敗」的邊界測試；`slice_imported` profile 完全不驗支撐參數 |
| `PUT /config` 開始驗證後，既有呼叫端被擋 | 中 | 先跑既有 API 測試確認無回歸；`unknown[]` 只回報不擋 |
| 三處 `except ValidationError` 分支漏改一處 | 中 | 測試逐一打三個入口，斷言回 422 而非 500 |

## Migration

1. 先寫 `param_rules.py` 與其測試（純函式，不接任何路由）。
2. 再開 `/validate` 端點。
3. 再補三處 `ValidationError` 分支。
4. 最後才讓 `PUT /config` 接規則表。

**順序理由**：步驟 4 會改變既有端點行為，風險最高，放最後；前三步都是純新增。
