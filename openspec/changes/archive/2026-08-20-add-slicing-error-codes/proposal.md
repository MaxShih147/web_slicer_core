## Why

目前 `POST /api/v2/slices/{job_id}/execute` 的背景切片流程，失敗時一律將 job 標為 `FAILED` 並回傳籠統的 `JOB_FAILED`（見 `agent/jobs.py` 的 `run_slicing()`）。這造成兩個實際問題：

1. **無法分辨失敗原因**：參數非法（如 pad brim 過小、曝光時間超出範圍）、幾何破損（non-manifold mesh 無法切片）、模型超出成型體積，前端都只收到同一個 `JOB_FAILED`，無從給使用者可行動的提示。
2. **兩條 exit-0 失敗路徑無法歸因**：
   - F-17（模型超出成型體積）：`ProcessActions.cpp` 在 `print->empty()` 時寫 stdout 後繼續執行（未 `return false`），exit code 維持 0、無輸出檔，原本只被報為 `"Output file not created"`。
   - F-06（空模型）：`LoadPrintData.cpp` 的 empty model 路徑對 `model.objects` 逐元素 `continue`（非 `return false`），同樣造成 exit 0、無輸出，與 F-17 無從區分。

本變更以 `agent/slicing_classifier.py` 分類器取代上述兩段判斷，引入**可歸因的切片 error code 集合**，讓前端與使用者能取得具體的失敗原因。

## What Changes

- **新增切片結果分類器**：`agent/slicing_classifier.py`，以純函式 `classify_slice_result(exit_code, stdout, stderr, input_filename, output_file_exists)` 取代 `run_slicing()` 中的兩段判斷（`returncode != 0` / `output_file.exists()`），回傳結構化的 `Optional[SliceClassification]`，架構與 `support_classifier.py` 對稱。
- **七步決策樹（兩條 exit 路徑）**：

  ```
  Path A（exit_code ≠ 0）：
    Step 1  stderr 命中已知 validate() 訊息     → FAILED + 具體 code
    Step 2  stderr 命中 process() 例外訊息     → FAILED + 具體 code
    Step 3  stderr 含 "{model_filename}:" 前綴  → FAILED + INVALID_MODEL（STL parse error）
    Step 4  未命中任何標記（unclassified）       → FAILED, no code（JOB_FAILED fallback）

  Path B（exit_code = 0，輸出檔不存在）：
    Step 5  stdout/stderr 含模型出界標記         → FAILED + MODEL_OUT_OF_BOUNDS
    Step 6  stderr 含空模型標記                  → FAILED + INVALID_MODEL
    Step 7  其餘 zero-exit / no-output           → FAILED, no code（JOB_FAILED fallback）

  成功：exit 0 + 輸出檔存在                     → 回傳 None（呼叫端走正常完成路徑）
  ```

- **新增 5 個 error factory**：於 `agent/errors.py` 新增 `pad_config_invalid`、`exposure_time_out_of_range`、`model_mesh_unsliceable`、`unprintable_object`、`pad_generation_failed`（HTTP 422 / retryable=false）。
- **擴充 `_ERROR_CODE_FACTORIES`**：於 `agent/api_v2.py` 補入 `INVALID_MODEL`（原有 factory 但未被 `_error_from_status` 查找到）並新增上述 5 個 slicing 代碼，使 `_error_from_status` 能回傳具體 `APIError`。
- **更新 `docs/err_code_spec.md`**：新增 5 個代碼表格列與 `execute` 端點的切片失敗清單。

### validate() → error code 對照（Path A Step 1）

| 偵測訊息（C++ 來源） | error code | retryable |
|---|---|---|
| `Elevation is too low for object`（[SLAPrint.cpp:734](../../../third_party/prusaslicer_fork/src/libslic3r/SLAPrint.cpp#L734)） | `SUPPORT_ELEVATION_TOO_LOW` | false |
| `The endings of the support pillars`（[:740](../../../third_party/prusaslicer_fork/src/libslic3r/SLAPrint.cpp#L740)） | `SUPPORT_PAD_GAP_CONFLICT` | false |
| `Pad brim size is too small`（SLA/Pad.cpp PadConfig::validate()） | `PAD_CONFIG_INVALID` | false |
| `xposition time is out of printer profile bounds`（[:756](../../../third_party/prusaslicer_fork/src/libslic3r/SLAPrint.cpp#L756)、[:763](../../../third_party/prusaslicer_fork/src/libslic3r/SLAPrint.cpp#L763)） | `EXPOSURE_TIME_OUT_OF_RANGE` | false |
| `Invalid Head penetration`（[:771](../../../third_party/prusaslicer_fork/src/libslic3r/SLAPrint.cpp#L771)） | `SUPPORT_HEAD_PENETRATION_INVALID` | false |
| `Invalid pinhead diameter`（[:780](../../../third_party/prusaslicer_fork/src/libslic3r/SLAPrint.cpp#L780)） | `SUPPORT_HEAD_TOO_WIDE` | false |
| 其餘無法歸因 | JOB_FAILED（Step 4 fallback） | — |

### process() 例外 → error code 對照（Path A Step 2）

| 偵測訊息（C++ 來源） | error code | retryable |
|---|---|---|
| `can not be sliced`（[SLAPrintSteps.cpp:693](../../../third_party/prusaslicer_fork/src/libslic3r/SLAPrintSteps.cpp#L693)） | `MODEL_MESH_UNSLICEABLE` | false |
| `There are unprintable objects`（[:1165](../../../third_party/prusaslicer_fork/src/libslic3r/SLAPrintSteps.cpp#L1165)） | `UNPRINTABLE_OBJECT` | false |
| `No pad can be generated`（[:1030](../../../third_party/prusaslicer_fork/src/libslic3r/SLAPrintSteps.cpp#L1030)） | `PAD_GENERATION_FAILED` | false |

## Capabilities

### New Capabilities

- `slicing-error-codes`：定義 SLA 切片（`execute`）的結果分類契約——七步決策樹、兩條 exit 路徑的判定規則、完整的 error code 集合與對照表。

### Modified Capabilities

（無。`docs/err_code_spec.md` 屬文件而非 OpenSpec spec；`openspec/specs/` 下亦無既有切片 capability，故不需 delta spec。）

## Impact

- **後端程式**：[agent/slicing_classifier.py](../../../agent/slicing_classifier.py)（新增）、[agent/jobs.py](../../../agent/jobs.py)（`run_slicing()`）、[agent/api_v2.py](../../../agent/api_v2.py)（`_ERROR_CODE_FACTORIES`）、[agent/errors.py](../../../agent/errors.py)（新 factory）。
- **文件**：[docs/err_code_spec.md](../../../docs/err_code_spec.md) 新增代碼列與 `execute` 端點切片失敗清單。
- **API 契約（對前端）**：`execute` 輪詢結果新增數個具體 error code，屬**新增**代碼，不移除既有欄位；前端需更新以顯示具體錯誤訊息。
- **無資料庫 schema 變更**；`error_code` 欄位為 `status.json` 的向後相容擴充（缺欄位時回退 `JOB_FAILED`）。
