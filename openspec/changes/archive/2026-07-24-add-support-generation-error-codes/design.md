## Context

`POST /api/v2/slices/{job_id}/generate-supports` 走背景執行：[run_support_generation](../../../agent/jobs.py#L358-L387) → [generate_supports](../../../agent/sla_operations.py#L176-L258) → 呼叫 PrusaSlicer fork CLI（support-only fast path），結果以 `status.json` 落地，前端輪詢 GET 狀態端點取得。

現行分類邏輯只有兩段判斷（[sla_operations.py:234-249](../../../agent/sla_operations.py#L234-L249)）：
1. `returncode != 0` → 失敗（籠統訊息）；
2. `returncode == 0` 但 `support_stl` 不存在 → 失敗、訊息「Model may not need supports」。

探索過程確立了三項關鍵事實，構成本設計的約束：

- **CLI 的 exit code 不可信**：`validate()` 失敗時走 [ProcessActions.cpp:470](../../../third_party/prusaslicer_fork/src/CLI/ProcessActions.cpp#L470) 的 `return 1`，但該函式回傳型別是 `bool`，`1`＝`true`，經 [Run.cpp:37](../../../third_party/prusaslicer_fork/src/CLI/Run.cpp#L37) 反相後行程 **exit code = 0**；而 `process()` 例外走 `return false` → exit code = 1。同一類「失敗」對映到不同 exit code，且與直覺相反。
- **關鍵訊號分散在 stdout 與 stderr**：validate 錯誤在 stderr；「模型出界」（[:476](../../../third_party/prusaslicer_fork/src/CLI/ProcessActions.cpp#L476)）與「不需支撐 / 只有底座」的標記（[:555-567](../../../third_party/prusaslicer_fork/src/CLI/ProcessActions.cpp#L555-L567)）都在 stdout。現行管線只落 stderr、丟棄 stdout。
- **「STL 存在」不等於「有支撐柱」**：support-only fast path 一定跑到 `slaposPad`，`pad_enable=True` 時零支撐仍會輸出「只含 pad」的 STL 並印 `(pad only)`。

本專案與去識別化工程並存，該工程會改寫引擎的識別字串，使「以字串比對判定結果」這條路徑天生脆弱，必須在設計上正面處理。

## Goals / Non-Goals

**Goals:**
- 讓 `generate-supports` 的每一種結果都能被**明確歸因**成一個穩定的 `error_code` 或中性結果。
- 建立**不依賴 exit code** 的分類器：以 stdout/stderr 文字為唯一真相來源。
- 以**正向偵測**認定「不需支撐」與「有支撐」，杜絕「STL 存在＝有支撐」與「看不懂＝當成功」兩種誤判。
- 對前端提供向後相容的契約擴充（新增 `supportOutcome` 欄位與數個 error code）。

**Non-Goals:**
- **不**修改 PrusaSlicer fork 的 C++（尤其不在本變更修 `return 1`／exit code 語意）。分類器設計成無論 exit code 如何都正確，因此 C++ 修復非必要；若日後修復，本設計也不受影響。
- **不**支援單一 job 多物件的支撐生成（維持現行單一 `model.stl` 假設）。
- **不**改動切片、hollow、cut、boolean 等其他 operation 的錯誤處理。
- **不**引入資料庫或新的外部相依。

## Decisions

### D1. 分類權威 = stdout/stderr 文字標記，且完全不看 exit code

以固定順序的五步決策樹判定（見 proposal）。不將 `returncode` 納入任何分支條件。

- **理由**：exit code 對 validate 失敗回傳 0 是既有 bug 的副作用；任何一次 C++ 正常化都會翻轉它。把判定綁在文字標記上，讓行為不隨 exit code 漂移。
- **替代方案**：(a) 修 C++ 讓 exit code 正確、Python 只看 exit code——被否決，因為它把後端正確性押在一個尚未修復、且跨 submodule 的 C++ 變更上；(b) 只看 stderr——被否決，因為「不需支撐」「模型出界」的訊號在 stdout。

### D2. 雙串流捕捉

調整 [run_prusa_cli](../../../agent/sla_operations.py#L151-L173)：完整捕捉並落 log `stdout` 與 `stderr`，兩者都交給分類器。

- **理由**：D1 需要 stdout 才能運作；同時保留兩者的完整原文供 `SUPPORT_GENERATION_FAILED` 的除錯附錄。
- **相容性**：`run_prusa_cli` 已回傳 `(returncode, stdout, stderr)`，僅需擴充 log 落地與呼叫端使用方式，介面變動小。

### D3. 正向偵測，未知一律失敗（fail-closed）

「不需支撐」只由 stdout 正向 marker（`(pad only)` 或 `No support/pad mesh generated`）認定；「有支撐」只由 `(supports only)` / `(includes supports and pad)` 認定。凡無法命中任何已知 marker 且無 STL 者，一律 `FAILED` + `SUPPORT_GENERATION_FAILED`。

- **理由**：在會改寫字串的環境裡，「看不懂就當成功」會把寫檔失敗、出界、去識別化改寫過的訊息靜默吞成「不需支撐、可直接切」。fail-closed 讓未知情況浮出檯面而非被掩蓋。
- **marker 與 STL 一致性**：`(supports only)` 等 marker 印在寫檔成功分支（[:554](../../../third_party/prusaslicer_fork/src/CLI/ProcessActions.cpp#L554)）內，故 marker 出現即代表檔案已成功寫出，「以 marker 為權威、不看檔案」在單物件下自洽。

### D4. `hasSupportMesh` 反映「真的有支撐柱」；中性結果走 COMPLETED + `supportOutcome`

- `(pad only)` 與 `No support/pad mesh generated` 一律 `hasSupportMesh=false`，且 job 狀態為 `COMPLETED`（非 `FAILED`），以新的 `supportOutcome` 欄位（如 `SUPPORT_NOT_NEEDED`）承載中性提示。
- **理由**：中性結果不是錯誤，不應走 `_error_from_status`／`success:false` 路徑，否則會阻擋前端後續切片。`hasSupportMesh` 需與「是否真的長出支撐」一致，避免把底座當支撐。
- **持久化**：[write_job_status](../../../agent/jobs.py#L60-L83) 擴充 `error_code`（失敗時）與 `supportOutcome`（中性時）兩欄；GET 狀態端點（[api_v2.py:1402-1416](../../../agent/api_v2.py#L1402-L1416)）在 COMPLETED 回應中帶出 `supportOutcome`。

### D5. error code 對照以字串比對，並鎖定引擎語系

Step 1 的 validate 訊息包在 `_u8L()`＝`I18N::translate()`；headless CLI 無載入翻譯 catalog 時回落英文，但不可默契依賴。分類器與引擎執行環境須**明確固定語系為英文**（例如不載入 catalog／設定對應環境），使 Step 1 的英文子字串比對可靠。Step 3/4 的 stdout marker 為裸字面量、不翻譯，不受此影響。

- **替代方案**：改以非文字訊號（結構化 exit code／機器可讀輸出）判定——理想但需改 C++，列為 Non-Goal，改由字串比對＋契約測試守住。

### D6. error code 集合與註冊點

新增 factory 於 [errors.py](../../../agent/errors.py)，並在 [_ERROR_CODE_FACTORIES](../../../agent/api_v2.py#L211-L217) 註冊，同步更新 [err_code_spec.md](../../../docs/err_code_spec.md)。集合：`SUPPORT_HEAD_TOO_WIDE`、`SUPPORT_HEAD_PENETRATION_INVALID`、`SUPPORT_ELEVATION_TOO_LOW`、`SUPPORT_POINTS_REQUIRED`、`SUPPORT_PAD_GAP_CONFLICT`、`MODEL_OUT_OF_BOUNDS`、`SUPPORT_GENERATION_FAILED`（fallback）。中性 `SUPPORT_NOT_NEEDED` 屬 `supportOutcome`，不進錯誤字典。

## Risks / Trade-offs

- **字串比對對語系／版本／去識別化改寫脆弱** → 鎖定英文語系（D5）；validate 與 marker 字串建立 golden/contract 測試，直接對 CLI 實際輸出斷言，改版即會被測試擋下；比對採「訊息特徵子字串」而非全字串，降低次要文案變動的影響。
- **去識別化工程可能改寫 marker 字串** → 明訂 marker 為契約的一部分並納入 contract 測試；於 proposal 前提假設 2 追蹤；若改寫不可避免，退而要求引擎輸出穩定的結構化標記（升級為 C++ 變更，另案處理）。
- **多物件會破壞 marker 掃描 precedence**（同一 stdout 同時含成功與 not-needed marker） → 明示單物件假設（Non-Goal），並在分類器對「同時偵測到多個互斥 marker」時走 fail-closed（`SUPPORT_GENERATION_FAILED`）而非任選其一。
- **曝光時間等非支撐專屬的 validate 訊息** 仍會擋下 support-only 請求 → 見 Open Questions，暫落 `SUPPORT_GENERATION_FAILED` 並保留原文。
- **exit code 與文字判定脫鉤，可能遮蔽真正的引擎崩潰**（segfault 無任何 marker、stderr 可能為空） → 崩潰情境本就落 Step 5 fail-closed；另 `notify_launcher_if_prusa_crashed`（[sla_operations.py:36](../../../agent/sla_operations.py#L36)）仍依 returncode 運作，與分類互不干擾，予以保留。

## Migration Plan

1. **後端優先、純新增**：`error_code`／`supportOutcome` 為 `status.json` 與 API 回應的新增欄位，舊前端忽略即可，無破壞性。
2. **部署順序**：先上後端（分類器＋新欄位＋新 code），再更新前端顯示中性提示與具體錯誤。
3. **語系前置**：部署時確認 support 生成的引擎執行環境語系為英文（D5），否則 Step 1 退化為 fallback（功能不壞，只是失去細分）。
4. **回滾**：還原後端即可；新前端遇不到新欄位時須維持既有 `JOB_FAILED` 相容處理。
5. **既有 job**：舊 `status.json` 無新欄位，讀取端以缺省值（無 `error_code` → `JOB_FAILED`；無 `supportOutcome` → 不顯示中性提示）向後相容。

## Open Questions

1. **曝光時間 / 初始曝光時間 out-of-bounds**（含 `Use tilt` 等非支撐專屬 validate 錯誤）對 support-only 路徑是否應視為支撐失敗？
   - **已定案（2026-07-24）**：於 Step 1 **優先判定**（在 stdout marker 掃描之前），歸類為 `SUPPORT_GENERATION_FAILED`（fallback）並**保留原始 log**。在 Step 1 判定可確保 validate 失敗永遠勝過任何殘留的 stdout marker，符合「Step 1 first」順序。
   - 實作：分類器 `NONSPECIFIC_VALIDATE_MARKERS`（`agent/support_classifier.py`）涵蓋 `xposition time is out of printer profile bounds` 與 `Disabling the 'Use tilt' function`；未列舉的其餘 validate 訊息亦會在無 marker 時自然落 Step 5 fallback，結果一致。
   - 後續：若產品要求對曝光時間給專屬 code 或在 support-only 路徑忽略此檢查，屬另案調整，不影響本分類架構。
2. 是否**一併修 C++ 的 `return 1` → `return false`** 讓 exit code 正確化？本設計不依賴它，但修復可讓行為更直覺——列為獨立後續事項。
3. `MODEL_OUT_OF_BOUNDS` 的 HTTP 語意與 retryable 值（傾向 422 / false）最終確認。
   - **已定案（2026-07-24）**：採 `422 / retryable=false`，與其餘幾何類支撐失敗一致（同一份輸入重試不會改變出界事實，故不可重試）。實作於 [errors.py](../../../agent/errors.py) `model_out_of_bounds` factory 並註冊於 [_ERROR_CODE_FACTORIES](../../../agent/api_v2.py#L213-L222)，[err_code_spec.md](../../../docs/err_code_spec.md) 同步登錄。
   - 後續：若前端需區分「模型可平移回範圍內」的可重試語意，屬另案調整。
4. `supportOutcome` 欄位的值域與命名（是否未來擴充 `SUPPORT_ONLY_PAD` 等更細狀態）於 spec 定稿。
   - **已定案（2026-07-24）**：本變更值域僅 `SUPPORT_NOT_NEEDED` 一種中性結果（涵蓋 `(pad only)` 與 `No support/pad mesh generated` 兩種 stdout marker），承載於 `COMPLETED` 回應而非錯誤字典。欄位為 `Optional`，缺省即「無中性提示」，向後相容。
   - 後續：若日後要細分 `SUPPORT_ONLY_PAD`／`SUPPORT_NONE` 等更細狀態，因其為新增列舉值且欄位本就 Optional，屬純擴充、不破壞既有契約。