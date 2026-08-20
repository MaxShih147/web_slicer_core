## 1. Error code 字典與文件

- [x] 1.1 於 `agent/errors.py` 新增 factory：`pad_config_invalid`、`exposure_time_out_of_range`、`model_mesh_unsliceable`、`unprintable_object`、`pad_generation_failed`（HTTP 422 / retryable=false，與幾何失敗家族一致）
- [x] 1.2 於 `agent/api_v2.py` 的 `_ERROR_CODE_FACTORIES` 補入 `INVALID_MODEL` 並新增上述 5 個 slicing 代碼，使 `_error_from_status` 能回傳具體 code
- [x] 1.3 更新 `docs/err_code_spec.md`：新增 5 個代碼列與 `execute` 端點的切片失敗清單（9 個目前 Web API 可達 code + JOB_FAILED fallback，另標注 2 個分類器支援但目前不可達的 code）

## 2. 切片結果分類器

- [x] 2.1 新增純函式 `classify_slice_result(exit_code, stdout, stderr, input_filename, output_file_exists)` 於 `agent/slicing_classifier.py`，回傳 `Optional[SliceClassification]`
- [x] 2.2 實作 Path A（exit ≠ 0）：Step 1 validate() 對照表、Step 2 process() 例外對照表、Step 3 STL parse error 偵測（`"{filename}:"` 前綴）、Step 4 unclassified fallback
- [x] 2.3 實作 Path B（exit = 0 + 輸出檔不存在）：Step 5 MODEL_OUT_OF_BOUNDS（stdout/stderr）、Step 6 INVALID_MODEL（stderr 空模型）、Step 7 fallback
- [x] 2.4 實作成功路徑：exit 0 + 輸出檔存在 → 回傳 `None`，`run_slicing()` 走正常完成路徑

## 3. Job 層接線（run_slicing）

- [x] 3.1 修改 `agent/jobs.py` 的 `run_slicing()`：以 `classify_slice_result` 取代原有的兩段 `returncode != 0` / `output_file.exists()` 判斷
- [x] 3.2 依 `SliceClassification.error_code` 呼叫 `write_job_status(FAILED, error=failure.error, error_code=failure.error_code)`，成功則繼續既有的 `parse_sl1_metadata` + `write_job_status(COMPLETED)` 流程

## 4. 驗證

- [x] 4.1 撰寫 `slicing_classifier.py` 的單元測試：對每個 Step 與每個對照條目斷言，含 F-06 exit-0 / INVALID_MODEL、F-17 exit-0 / MODEL_OUT_OF_BOUNDS、validate 先於 process 的排序、unclassified fallback、成功回傳 None 等情境
- [x] 4.2 建立契約 / golden 測試，直接對 CLI 實際輸出的 validate 訊息與 stderr/stdout 標記字串進行斷言，使引擎改版或去識別化改寫時能被測試擋下
- [x] 4.3 對整個 `agent/` 執行 lint 與既有測試套件，確認無回歸（302 passed；2 pre-existing failures 與本次無關）
- [ ] 4.4 以真實模型跑端到端：幾何破損 mesh（期望 `MODEL_MESH_UNSLICEABLE`）、成型體積外的模型（期望 `MODEL_OUT_OF_BOUNDS`）、曝光時間超出預設範圍（期望 `EXPOSURE_TIME_OUT_OF_RANGE`）、正常模型（期望成功）
