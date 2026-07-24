## Why

目前 `POST /api/v2/slices/{job_id}/generate-supports` 在支撐生成失敗時，一律把 job 標成 `FAILED` 並回傳籠統的 `JOB_FAILED`（見 [run_support_generation](../../../agent/jobs.py#L358-L387) 與 [generate_supports](../../../agent/sla_operations.py#L234-L249)）。這造成三個實際問題：

1. **無法分辨失敗原因**：參數非法（如 pinhead 直徑過大）、模型擺出成型體積外、引擎崩潰，前端都只收到同一個 `JOB_FAILED`，無從給使用者可行動的提示。
2. **把「不需支撐」誤判為失敗**：模型自身完全自支撐時，引擎正常結束卻沒有產出支撐 STL，現行碼把它當成失敗——這其實是合法的中性成功，不應阻擋後續切片。
3. **把「只有底座」誤判為有支撐**：當 `pad_enable=True` 且模型零支撐時，CLI 仍會輸出一個「只含 pad」的 STL；現行以「STL 檔案是否存在」為判準的邏輯，會把這塊底座誤報成有支撐。

本變更引入一套**明確、可歸因的支撐生成 error code**，並把「成功／中性／失敗」的判準從「exit code + 檔案是否存在」改為「解析 CLI 的 stdout/stderr 文字標記」這個唯一真相來源。

## What Changes

- **雙串流捕捉**：調整 [run_prusa_cli](../../../agent/sla_operations.py#L151-L173)，同時捕捉並落 log `stdout` 與 `stderr`（目前僅落 stderr，且 stdout 未用於歸因）。
- **以五步決策樹取代現行兩段判斷**：支撐生成結果的分類改為固定順序的五步流程（見下），**判定不依賴 exit code 的實際數值**，規避 CLI `return 1` 在 bool 函式中等於 `true`、導致 validate 錯誤回傳 exit 0 的既有行為。
- **成功判準改看 stdout 括號標記，不看 STL 檔案存在與否**：以 `(supports only)` / `(includes supports and pad)` / `(pad only)` / `No support/pad mesh generated` 這些標記作為權威判準，讓「只有底座」不再被誤報為有支撐。
- **新增支撐相關 error code**：於 [errors.py](../../../agent/errors.py)、[err_code_spec.md](../../../docs/err_code_spec.md) 與 [_ERROR_CODE_FACTORIES](../../../agent/api_v2.py#L211-L217) 註冊新代碼（`SUPPORT_HEAD_TOO_WIDE`、`SUPPORT_HEAD_PENETRATION_INVALID`、`SUPPORT_ELEVATION_TOO_LOW`、`MODEL_OUT_OF_BOUNDS`、`SUPPORT_GENERATION_FAILED` 等）。
- **中性狀態走「完成」而非「錯誤」路徑**：`SUPPORT_NOT_NEEDED` 屬於 `COMPLETED` 上的中性標記，而非 error。GET 狀態端點（[api_v2.py:1402-1416](../../../agent/api_v2.py#L1402-L1416)）需新增 **`supportOutcome`** 欄位承載它，並讓 `hasSupportMesh` 如實反映「是否真的有支撐柱」。
- **狀態持久化擴充**：[write_job_status](../../../agent/jobs.py#L60-L83) 需能存 `error_code`（供 [_error_from_status](../../../agent/api_v2.py#L211-L217) 回傳具體代碼），並能存中性的 `supportOutcome`。

### 五步決策樹（權威版）

```
Step 1  stderr 命中已知 validate 錯誤   → FAILED + 具體 code（SUPPORT_HEAD_TOO_WIDE …）
Step 2  stdout/stderr 命中模型出界      → FAILED + MODEL_OUT_OF_BOUNDS
Step 3  stdout 命中 "(pad only)" 或
        "No support/pad mesh generated" → COMPLETED + SUPPORT_NOT_NEEDED，hasSupportMesh=false
Step 4  stdout 命中 "(supports only)" 或
        "(includes supports and pad)"   → COMPLETED + 正式成功，hasSupportMesh=true
Step 5  以上皆不中（無法歸因）           → FAILED + SUPPORT_GENERATION_FAILED（附原始 stdout+stderr）
```

### 已知 validate 錯誤 → error code 對照（初版，最終於 specs/design 定稿）

| CLI validate 訊息（來源） | error code | retryable |
|---|---|---|
| `Invalid pinhead diameter…`（[SLAPrint.cpp:780](../../../third_party/prusaslicer_fork/src/libslic3r/SLAPrint.cpp#L780)） | `SUPPORT_HEAD_TOO_WIDE` | false |
| `Invalid Head penetration…`（[:771](../../../third_party/prusaslicer_fork/src/libslic3r/SLAPrint.cpp#L771)） | `SUPPORT_HEAD_PENETRATION_INVALID` | false |
| `Elevation is too low for object…`（[:734](../../../third_party/prusaslicer_fork/src/libslic3r/SLAPrint.cpp#L734)） | `SUPPORT_ELEVATION_TOO_LOW` | false |
| `Cannot proceed without support points!…`（[:723](../../../third_party/prusaslicer_fork/src/libslic3r/SLAPrint.cpp#L723)） | `SUPPORT_POINTS_REQUIRED` | false |
| `The endings of the support pillars…`（[:740](../../../third_party/prusaslicer_fork/src/libslic3r/SLAPrint.cpp#L740)） | `SUPPORT_PAD_GAP_CONFLICT` | false |
| `Exposition time…` / `Initial exposition time…`（[:756](../../../third_party/prusaslicer_fork/src/libslic3r/SLAPrint.cpp#L756)、[:763](../../../third_party/prusaslicer_fork/src/libslic3r/SLAPrint.cpp#L763)） | 待定（非支撐專屬；候選 fallback） | false |
| 其餘無法歸因 | `SUPPORT_GENERATION_FAILED` | false |

### 三個實作前必須釘死的前提假設

1. **locale 鎖定**：Step 1 的 validate 字串包在 `_u8L()`＝`I18N::translate()` 內、**會隨語系變動**；而 Step 3/4 的 stdout 標記是**裸字面量、不翻譯**。⟹ 支撐生成時必須固定引擎語系，否則 Step 1 比對會靜默退化為 Step 5。
2. **validate 對照表一次列全**：`validate()` 至少 8 條訊息（見上表），須明確定義哪幾條給專屬 code、其餘一律落 `SUPPORT_GENERATION_FAILED`。
3. **單一物件假設**：stdout 標記印在 per-object 迴圈內（[ProcessActions.cpp:527](../../../third_party/prusaslicer_fork/src/CLI/ProcessActions.cpp#L527)）；本設計假設每個 job 僅一個物件（現行 `generate_supports` 只餵單一 `model.stl`）。若未來支援多物件，標記掃描的 precedence 須改為 per-object 聚合。

## Capabilities

### New Capabilities

- `support-generation-error-codes`: 定義 `generate-supports` 的結果分類契約——五步決策樹、成功／中性／失敗的權威判準（stdout/stderr 標記）、完整的 error code 集合與對照表，以及 `supportOutcome` API 欄位與 `hasSupportMesh` 的語意。

### Modified Capabilities

（無。目前 `docs/err_code_spec.md` 屬文件而非 OpenSpec spec，`openspec/specs/` 下亦無既有的 API 錯誤碼 capability，故不需 delta spec。）

## Impact

- **後端程式**：[agent/sla_operations.py](../../../agent/sla_operations.py)（`run_prusa_cli`、`generate_supports`）、[agent/jobs.py](../../../agent/jobs.py)（`run_support_generation`、`write_job_status`）、[agent/api_v2.py](../../../agent/api_v2.py)（`generate-supports` 端點、GET 狀態端點、`_ERROR_CODE_FACTORIES`）、[agent/errors.py](../../../agent/errors.py)（新 factory）、[agent/models.py](../../../agent/models.py)（狀態回應欄位）。
- **文件**：[docs/err_code_spec.md](../../../docs/err_code_spec.md) 需新增代碼與端點錯誤清單。
- **API 契約（對前端）**：`generate-supports` 輪詢結果新增 `supportOutcome` 欄位、新增數個具體 error code。屬**新增**欄位與代碼，不移除既有欄位；前端需更新以顯示中性提示與具體錯誤訊息。
- **引擎相依**：依賴 PrusaSlicer fork CLI 目前的 stdout/stderr 文字輸出格式；與去識別化工程並存時須確認這些標記字串未被改寫（見前提假設 1、2）。
- **無資料庫 schema 變更**；job 狀態以 `status.json` 落地，新增 `error_code`／`supportOutcome` 欄位為向後相容的擴充。