## 1. Error code 字典與文件

- [x] 1.1 於 `agent/errors.py` 新增 factory：`support_head_too_wide`、`support_head_penetration_invalid`、`support_elevation_too_low`、`support_points_required`、`support_pad_gap_conflict`、`model_out_of_bounds`、`support_generation_failed`（HTTP/retryable 依 design D6，`MODEL_OUT_OF_BOUNDS` 暫定 422/false）
- [x] 1.2 於 `agent/api_v2.py` 的 `_ERROR_CODE_FACTORIES` 註冊上述代碼，使 `_error_from_status` 能回傳具體 code
- [x] 1.3 更新 `docs/err_code_spec.md`：新增代碼列與 `generate-supports` 端點的錯誤/中性結果清單，並記錄 `supportOutcome` 欄位語意
- [x] 1.4 **驗證**：撰寫並執行單元測試，斷言每個新 factory 產出的 `code` / `http_status` / `retryable` 正確，且 `_ERROR_CODE_FACTORIES` 對每個 code 都能查得對應 factory

## 2. 雙串流捕捉（run_prusa_cli）

- [x] 2.1 調整 `agent/sla_operations.py` 的 `run_prusa_cli`，將 `stdout` 一併落 log（新增 stdout log 檔或合併輸出），保留回傳 `(returncode, stdout, stderr)`
- [x] 2.2 確認呼叫端能取得 `stdout` 完整原文供分類器使用（不因既有 log 行為而遺失）
- [x] 2.3 **驗證**：以 fake/stub subprocess 執行單元測試，斷言 `stdout` 與 `stderr` 皆被完整捕捉並寫入 log

## 3. 分類器核心（五步決策樹 parser）

- [x] 3.1 新增純函式 `classify_support_result(stdout, stderr, support_stl_exists)`，回傳結構化結果（`status` / `error_code` / `support_outcome` / `has_support_mesh`），**不接受 returncode 作為分類條件**（design D1）
- [x] 3.2 實作 Step 1：`stderr` 命中已知 validate 錯誤 → 依對照表回傳具體 code（比對採訊息特徵子字串）
- [x] 3.3 實作 Step 2：`stdout`/`stderr` 命中 `no object is fully inside the print volume` → `MODEL_OUT_OF_BOUNDS`
- [x] 3.4 實作 Step 3：`stdout` 命中 `(pad only)` 或 `No support/pad mesh generated` → `COMPLETED` + `SUPPORT_NOT_NEEDED` + `has_support_mesh=false`
- [x] 3.5 實作 Step 4：`stdout` 命中 `(supports only)` 或 `(includes supports and pad)` → `COMPLETED` + `has_support_mesh=true`
- [x] 3.6 實作 Step 5 fail-closed：未命中任何標記、或同時命中互斥標記 → `FAILED` + `SUPPORT_GENERATION_FAILED`（附原始 stdout/stderr）
- [x] 3.7 **驗證**：對每一 Step 與每一 validate 對照條目撰寫 parser 單元測試（含「validate 失敗 exit 0」「pad only 不得回報 has_support_mesh=true」「寫檔失敗須 fail-closed」「互斥標記須 fail-closed」等 spec 場景），並全數通過

## 4. 狀態持久化（write_job_status）

- [x] 4.1 擴充 `agent/jobs.py` 的 `write_job_status`，支援寫入 `error_code`（失敗時）與 `support_outcome`（中性時）欄位至 `status.json`
- [x] 4.2 確認讀取端對缺欄位的舊 `status.json` 向後相容（缺 `error_code` → `JOB_FAILED`；缺 `support_outcome` → 無中性提示）
- [x] 4.3 **驗證**：單元測試斷言寫入後可正確讀回新欄位，且缺欄位的舊格式讀取不報錯並回退至既有行為

## 5. Job 層接線（run_support_generation）

- [x] 5.1 修改 `agent/jobs.py` 的 `run_support_generation` / `generate_supports`：以 `classify_support_result` 取代現行 `returncode!=0` 與 `support_stl.exists()` 兩段判斷
- [x] 5.2 依分類結果呼叫 `write_job_status`：失敗帶 `error_code`、中性帶 `support_outcome` 且狀態為 `COMPLETED`、成功設 `has_support_mesh=true`
- [x] 5.3 確認 `notify_launcher_if_prusa_crashed` 依 returncode 的既有行為不受影響（與分類器解耦）
- [x] 5.4 **驗證**：以 stub CLI 輸出跑整條 `run_support_generation`，斷言各情境寫出的 `status.json` 欄位符合預期

## 6. API 狀態端點

- [x] 6.1 於 `agent/models.py` 的狀態回應模型新增 `supportOutcome`（Optional）欄位
- [x] 6.2 調整 `agent/api_v2.py` GET 狀態端點：`COMPLETED` 回應帶出 `supportOutcome`；`FAILED` 經 `_error_from_status` 回傳具體 `error_code`；中性結果 MUST 走 `success:true` 而非錯誤路徑
- [x] 6.3 **驗證**：以 FastAPI TestClient 對 API 回應斷言——`SUPPORT_HEAD_TOO_WIDE` 失敗回 `success:false`+具體 code；`SUPPORT_NOT_NEEDED` 回 `COMPLETED`+`supportOutcome`+`hasSupportMesh:false`

## 7. 語系鎖定與契約測試

- [x] 7.1 確保支撐生成的引擎執行環境固定英文語系（design D5），使 Step 1 的 validate 子字串比對可靠
- [x] 7.2 新增契約/golden 測試，直接對 CLI 實際輸出的 validate 訊息與 stdout 標記字串斷言，字串變動即讓測試失敗
- [x] 7.3 **驗證**：執行契約測試通過；刻意改動一個標記字串以確認測試會如預期失敗（negative check）

## 8. 端到端驗證與收尾

- [x] 8.1 以真實模型跑端到端：自支撐模型（期望 `SUPPORT_NOT_NEEDED`）、`pad_enable=True` 零支撐模型（期望 `SUPPORT_NOT_NEEDED`、非 has_support）、pinhead 直徑過大（期望 `SUPPORT_HEAD_TOO_WIDE`）、需支撐模型（期望成功、has_support_mesh=true）
- [x] 8.2 對整個 `agent/` 執行 lint 與既有測試套件，確認無回歸
- [x] 8.3 執行 `openspec validate add-support-generation-error-codes` 通過
- [x] 8.4 解決或明確記錄 design.md 的 Open Questions（曝光時間歸類、是否修 C++ `return 1`、`MODEL_OUT_OF_BOUNDS` 語意、`supportOutcome` 值域）