## Context

`POST /api/v2/slices/{job_id}/execute` 走背景執行：`run_slicing()`（`agent/jobs.py`）→ `asyncio.create_subprocess_exec` → PrusaSlicer fork CLI → `Run()` → `process_actions()` → `SLAPrint::validate()` + `SLAPrint::process()` → 結果以 `status.json` 落地，前端輪詢 `GET /api/v2/slices/{job_id}` 取得。

現行失敗處理只有兩段判斷：
1. `returncode != 0` → `write_job_status(FAILED, error="Exit code N: <stderr>")` — 任何非零退出一律籠統報錯。
2. `output_file` 不存在 → `write_job_status(FAILED, error="Output file not created")` — 兩條 exit-0 特殊路徑（F-17、F-06）被歸為同一訊息，無具體 code。

探索確立了以下設計約束：

- **exit code 對切片路徑基本可信，但有兩個 exit-0 例外**：`ProcessActions.cpp` 在 validate() 回傳非空字串時呼叫 `return false`（而非支撐生成路徑的 `return 1` in bool function），經 `Run.cpp` 反相後 exit code 為 1；process() 的例外由 `catch(std::exception& ex)` 捕獲後寫 cerr 並 `return false` → exit 1。兩者皆可靠地對映至非零退出。
- **兩個 exit-0 特殊路徑需在 Path B 各自識別**：
  - F-17：`ProcessActions.cpp` 在 `print->empty()` 時寫 stdout（`"no object is fully inside the print volume"`）後繼續執行（未 return false）→ exit 0 + 無輸出檔。
  - F-06：`LoadPrintData.cpp` 的空 model 路徑寫 stderr（`"Error: file is empty:"`）後 `continue`（非 return false）→ exit 0 + 無輸出檔。
- **validate() 訊息為可翻譯字串**（包在 `_u8L()`），需固定引擎語系為英文才能可靠比對（與支撐生成相同約束，見 `2026-07-24-add-support-generation-error-codes` D5）。
- **F-08（SUPPORT_POINTS_REQUIRED）在切片路徑不可達**：「Cannot proceed without support points」只在 `UserModified` 狀態的支撐點全部存在時觸發；Web 後端上傳原始 STL 不設 support point，此條件不成立。

## Goals / Non-Goals

**Goals:**
- 讓 `run_slicing()` 的每一種已知失敗都能被歸因為穩定的 `error_code`。
- 建立雙路徑（exit ≠ 0 / exit = 0 + 無輸出）分類器，覆蓋所有已知失敗情境，未知情境 fail-closed（JOB_FAILED）。
- 以新增 code 向後相容的方式擴充前端契約。

**Non-Goals:**
- **不**修改 PrusaSlicer fork 的 C++。
- **不**改動支撐生成、hollow、cut、boolean 等其他 operation 的錯誤處理。
- **不**對 v1 API（`/api/jobs/{id}`）新增 error code 支援（v1 `JobStatusResponse` 模型無 `error_code` 欄位，屬另案）。
- **不**引入資料庫或新的外部相依。

## Decisions

### D1. exit code 用於 Path A / Path B 分流

不像 `support_classifier.py` 完全不看 exit code，切片路徑的 validate() 與 process() 失敗均可靠地回傳 exit 1，故以 `exit_code != 0` 作為 Path A 的分流門檻——非零進 Path A（依 stderr 細分具體 code），零退出 + 無輸出進 Path B（依 stdout/stderr 文字識別兩個特殊路徑）。

- **理由**：此判別在切片路徑上是可信的；在 Path B 仍以文字標記為判定依據，確保 exit-0 特殊路徑的歸因不依賴 exit code 的具體數值。

> **【事後修正 2026-08-24】** D1 原文「均可靠地回傳 exit 1」對 validate() 路徑有誤。實際上 `ProcessActions.cpp::process_actions()` 宣告為 `bool`，其 validate 失敗分支執行 `return 1`——在 C++ bool 函式中等同 `return true`；`Run.cpp` 的 `if (!process_actions(...)) return 1` 條件因此不觸發，**process 以 exit 0 退出**，但 stderr 仍留有 validate() 寫入的錯誤訊息。以 `exposure_time=200` 直接測試既有 `slicer-engine.exe`（Aug 3 build）確認：exit_code=0，stderr="Exposition time is out of printer profile bounds."，無輸出檔。Non-Goals 已列明不修改 C++ fork；Python 端 workaround 為在 Path B 新增 **Step 6.x**，對 stderr 重跑 `_VALIDATE_CODE_MAP` 掃描（`agent/slicing_classifier.py`），確保 validate 失敗即使 exit 0 也能歸因到正確 error code。

### D2. Path A 分類順序：validate → process → STL parse → unclassified

validate() 在程式執行順序上先於 process()，訊息更具體（參數非法）；process() 例外次之（幾何操作失敗）；STL parse error 以 `"{filename}:"` 前綴作為指紋（`LoadPrintData.cpp` 使用 `cerr << file << ": " << e.what()` 格式）。三者互斥；依此序列「first match wins」可保證確定性。

### D3. Path B F-17 與 F-06 各有獨立 marker，防禦性掃描兩個串流

F-17 marker（`"no object is fully inside the print volume"`）出現在 stdout，防禦性地也掃 stderr；F-06 marker（`"Error: file is empty:"`）出現在 stderr。兩者格式不同，可可靠分辨；掃描策略與 `support_classifier.py` 的 `OUT_OF_BOUNDS_MARKER` 對稱。

### D4. F-08 明確排除於切片分類器之外

「Cannot proceed without support points」僅在 `UserModified` 支撐點存在時觸發，Web 後端原始 STL 上傳流程不設 support point，此路徑不可達，刻意不納入，避免誤判其他含類似文字的訊息。

### D5. 語系固定為英文

validate() 訊息包在 `_u8L()` 內，validate 比對須在英文語系下才可靠（與支撐生成相同）。process() 例外訊息雖來自裸字面量，亦於固定語系下執行，保持一致。

### D6. error code 集合與註冊點

**新增 factory**（`agent/errors.py`）：`pad_config_invalid`、`exposure_time_out_of_range`、`model_mesh_unsliceable`、`unprintable_object`、`pad_generation_failed`（HTTP 422 / retryable=false，與幾何失敗家族一致）。

**首次補入 `_ERROR_CODE_FACTORIES`**（`agent/api_v2.py`）：`INVALID_MODEL` 原已有 factory 但未被 `_error_from_status` 查找到，此次補入，使 STL parse / 空模型失敗能回傳具體訊息而非 `JOB_FAILED`。

**重用既有 factory**（無新增）：`SUPPORT_ELEVATION_TOO_LOW`、`SUPPORT_PAD_GAP_CONFLICT`、`SUPPORT_HEAD_PENETRATION_INVALID`、`SUPPORT_HEAD_TOO_WIDE`、`MODEL_OUT_OF_BOUNDS`。

**分類器覆蓋範圍與 Web API 可達性不完全相同**：分類器對照表涵蓋 11 個 Prusa CLI 訊息模式，但其中 `PAD_CONFIG_INVALID`（依賴 `pad_brim_size` 等 pad 幾何參數）與 `SUPPORT_PAD_GAP_CONFLICT`（依賴 `pad_around_object`，Prusa 預設 false）因 `SLAConfig` 目前未暴露對應欄位而對 Web API 不可達。分類器邏輯本身正確，一旦 SLAConfig 補齊相關欄位即自動生效，無需改動分類器。

## Risks / Trade-offs

- **字串比對對版本／去識別化改寫脆弱** → 語系鎖定英文；需補齊契約 / golden 測試守住標記字串（見 tasks.md 4.2）。
- **F-05 STL parse error 以 `"{filename}:"` 前綴偵測**：若 LoadPrintData.cpp 改變 cerr 格式，偵測靜默退化為 Step 4 unclassified（JOB_FAILED），不會誤判——可接受的降級。
- **v1 API 不受益**：`/api/jobs/{id}` 仍回傳籠統訊息，屬已知限制，另案處理。

## Migration Plan

1. **純新增欄位**：`error_code` 為 `status.json` 的新增欄位，舊前端忽略即可；缺欄位時讀取端回退 `JOB_FAILED`。
2. **部署**：後端直接替換 `run_slicing()` 失敗分支，無資料遷移。
3. **語系前置**：確認切片引擎執行環境語系為英文，否則 validate() 比對退化為 JOB_FAILED（功能不壞，只失去細分）。

## Open Questions

1. **v1 API 的 error code 支援**：`/api/jobs/{id}` 的 `JobStatusResponse` 模型缺少 `error_code` 欄位，slicing 失敗的具體代碼對 v1 消費者不可見。若有需要，屬另案調整。
2. **切片分類器的契約 / golden 測試**：類比 `2026-07-24-add-support-generation-error-codes` Task 7 的要求，目前尚未建立；應補齊以在引擎改版或去識別化改寫時提早偵測字串變動（見 tasks.md 4.2）。
