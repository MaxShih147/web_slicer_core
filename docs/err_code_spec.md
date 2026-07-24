## Error Response Format

```json
{
    "success": false,
    "code": "INTERNAL_ERROR",
    "message": "<thrown exception>",
    "data": {
        "retryable": true,
        "traceId": "<12-char hex>"
    }
}
```

---

## Error Code Reference

| Code | HTTP Status | retryable | 說明 |
|---|---|---|---|
| `INTERNAL_ERROR` | 500 | true | 非預期的伺服器錯誤 |
| `VALIDATION_ERROR` | 400 | false | 請求參數格式或值域錯誤（型別錯誤、非法 enum 值、content-type 不符等） |
| `MISSING_BODY` | 400 | false | 必要欄位或檔案缺失 |
| `JOB_NOT_FOUND` | 404 | false | 指定的 job_id 不存在 |
| `JOB_ALREADY_EXECUTED` | 409 | false | Job 已執行，不再接受修改 |
| `JOB_STILL_PROCESSING` | 200 | true | Job 尚未完成，無法下載結果 |
| `JOB_FAILED` | 409 | false | Job 執行失敗，無法下載結果 |
| `MODEL_NOT_FOUND` | 404 | false | Job 上沒有模型，或指定的 source 檔案不存在 |
| `INVALID_MODEL` | 422 | false | STL 內容損壞、格式無效、或幾何載入失敗 |
| `FILE_NOT_FOUND` | 404 | false | 輸出檔案不存在（job 完成但檔案遺失） |
| `BOOLEAN_FAILED` | 422 | false | Boolean 幾何計算失敗（non-manifold、self-intersecting 等） |
| `NO_DRAIN_HOLES` | 422 | false | 在目前幾何中找不到可放置 drain hole 的 wall edge |
| `NO_HEX_GRID_CELLS` | 422 | false | Hex grid 演算法未產生任何 cell，參數可能超出 hollow mesh 範圍 |
| `HOLLOW_GENERATION_FAILED` | 422 | false | PrusaSlicer 無法產生 hollow interior mesh（幾何太薄、太複雜等） |
| `SUPPORT_HEAD_TOO_WIDE` | 422 | false | 支撐 pinhead 直徑對此幾何無效（`Invalid pinhead diameter`） |
| `SUPPORT_HEAD_PENETRATION_INVALID` | 422 | false | 支撐 head penetration 值無效（`Invalid Head penetration`） |
| `SUPPORT_ELEVATION_TOO_LOW` | 422 | false | 物件抬升高度過低，無法產生支撐（`Elevation is too low for object`） |
| `SUPPORT_POINTS_REQUIRED` | 422 | false | 缺少必要支撐點（`Cannot proceed without support points`） |
| `SUPPORT_PAD_GAP_CONFLICT` | 422 | false | 支撐柱底部落於物件與 pad 的間隙（pillar/pad gap 衝突） |
| `MODEL_OUT_OF_BOUNDS` | 422 | false | 沒有物件完全落在成型體積內（`no object is fully inside the print volume`） |
| `SUPPORT_GENERATION_FAILED` | 422 | false | 支撐生成失敗且無法歸因至更具體代碼（fail-closed fallback，附原始 stdout/stderr） |

---

## Endpoints

### `POST /api/v2/slices`

建立新的 slice job（僅建立 ID，不執行）。

錯誤：

- INTERNAL_ERROR

---

### `PUT /api/v2/slices/{job_id}/config`

更新 job 的切片參數（只能在執行前呼叫）。

錯誤：

- JOB_NOT_FOUND
- JOB_ALREADY_EXECUTED // job 已執行，不在 pending 狀態
- MISSING_BODY // 沒有 config
- VALIDATION_ERROR // content-type 不是 JSON、JSON 格式錯誤、或欄位驗證失敗
- INTERNAL_ERROR

---

### `POST /api/v2/slices/{job_id}/models`

以 JSON 格式新增模型（目前僅支援 `stl_data`，`vertices` 尚未實作）。

錯誤：

- JOB_NOT_FOUND
- JOB_ALREADY_EXECUTED // job 已執行，不在 pending 狀態
- MISSING_BODY // 欄位空白
- VALIDATION_ERROR // content-type 不是 JSON、JSON 格式錯誤、或欄位驗證失敗
- INTERNAL_ERROR

---

### `POST /api/v2/slices/{job_id}/upload`

上傳 STL 檔案（推薦的模型新增方式）。

錯誤：

- JOB_NOT_FOUND
- JOB_ALREADY_EXECUTED // job 已執行，不在 pending 狀態
- MISSING_BODY // 欄位空白
- VALIDATION_ERROR // 檔案格式不符
- INVALID_MODEL // STL 內容損壞或格式無效
- INTERNAL_ERROR

---

### `POST /api/v2/slices/{job_id}/use-model-from/{source_job_id}`

從另一個 job 的輸出複製模型，避免重新上傳。

錯誤：

- JOB_NOT_FOUND
- MODEL_NOT_FOUND // source 檔案不存在
- INTERNAL_ERROR

---

### `POST /api/v2/slices/{job_id}/execute`

開始切片（背景執行）。呼叫後用 `GET /api/v2/slices/{job_id}` 輪詢狀態。

錯誤：

- JOB_NOT_FOUND
- JOB_ALREADY_EXECUTED // job 已執行，不在 pending 狀態
- MODEL_NOT_FOUND // 這個 job id 沒有模型
- INVALID_MODEL // 模型 data 無效
- INTERNAL_ERROR

---

### `POST /api/v2/slices/{job_id}/generate-supports`

僅產生支撐 mesh（背景執行），不切片。完成後可透過 `GET /api/jobs/{job_id}/support.stl` 下載。

結果分類完全依 CLI 的 stdout/stderr 文字標記判定，不依賴 exit code（見 openspec/changes/add-support-generation-error-codes）。

**建立/排程階段錯誤：**

- JOB_NOT_FOUND
- MODEL_NOT_FOUND // 這個 job id 沒有模型
- INVALID_MODEL // 模型 data 無效
- INTERNAL_ERROR

**支撐生成失敗（背景執行，透過 `GET /api/v2/slices/{job_id}` 以 HTTP 200 + `success:false` 回傳具體 code）：**

- SUPPORT_HEAD_TOO_WIDE // pinhead 直徑無效
- SUPPORT_HEAD_PENETRATION_INVALID // head penetration 值無效
- SUPPORT_ELEVATION_TOO_LOW // 抬升高度過低
- SUPPORT_POINTS_REQUIRED // 缺少必要支撐點
- SUPPORT_PAD_GAP_CONFLICT // 支撐柱底與 pad 間隙衝突
- MODEL_OUT_OF_BOUNDS // 沒有物件完全落在成型體積內
- SUPPORT_GENERATION_FAILED // 無法歸因的 fail-closed fallback（附原始 stdout/stderr）

**中性結果（非錯誤，job 狀態為 `COMPLETED`）：**

- 當 stdout 標記為 `(pad only)` 或 `No support/pad mesh generated` 時，代表模型實質零支撐柱。此時 job 以 `COMPLETED` 完成，`success:true`，並在狀態回應帶出 `supportOutcome: "SUPPORT_NOT_NEEDED"`、`hasSupportMesh: false`，不阻擋後續切片。
- 當 stdout 標記為 `(supports only)` 或 `(includes supports and pad)` 時為正式成功，`hasSupportMesh: true`。

> `supportOutcome` 欄位語意：`SUPPORT_NOT_NEEDED` 為目前唯一的中性值，僅出現在 `COMPLETED` 且無實際支撐柱的情況；屬 `success:true` 路徑，不進錯誤字典。缺此欄位時視為無中性提示（向後相容）。

---

### `POST /api/v2/slices/{job_id}/generate-hollow`

僅產生挖空 mesh（背景執行），不切片。完成後可透過 `GET /api/jobs/{job_id}/hollow.stl` 下載。

錯誤：

- JOB_NOT_FOUND
- MODEL_NOT_FOUND // 這個 job id 沒有模型
- INVALID_MODEL // 模型 data 無效
- INTERNAL_ERROR

---

### `POST /api/v2/slices/{job_id}/cut`

沿 Z 軸切割模型（背景執行）。

錯誤：

- JOB_NOT_FOUND
- MODEL_NOT_FOUND // 這個 job id 沒有模型
- INVALID_MODEL // 模型 data 無效
- MISSING_BODY // 欄位空白
- VALIDATION_ERROR // cut_height 高於模型高度或低於模型底部、keep_mode 不是 both/upper/lower
- INTERNAL_ERROR

---

### `POST /api/v2/slices/{job_id}/extend-bottom`

將 hollow mesh 底部頂點向下延伸（同步執行，直接覆寫 hollow.stl）。

錯誤：

- JOB_NOT_FOUND
- MODEL_NOT_FOUND // hollow mesh 不存在
- INVALID_MODEL // hollow mesh 無效
- MISSING_BODY // 欄位空白
- VALIDATION_ERROR // `bottom_z_threshold` 高於模型高度或低於 0、`extension_distance` 低於 0
- INTERNAL_ERROR

---

### `POST /api/v2/slices/{job_id}/generate-drain-holes`

在 hex grid wall edge 的中點產生排水孔圓柱 mesh（同步執行）。完成後可透過 `GET /api/jobs/{job_id}/drain_holes.stl` 下載。

錯誤：

- JOB_NOT_FOUND
- MODEL_NOT_FOUND // 這個 job id 沒有模型
- INVALID_MODEL // 模型 data 無效
- MISSING_BODY // 欄位空白
- VALIDATION_ERROR // 參數非數字、低於 0 等
- `NO_DRAIN_HOLES` // 在目前幾何中找不到可放置 drain hole 的 wall edge
- INTERNAL_ERROR

---

### `POST /api/v2/slices/{job_id}/generate-hex-grid`

對 hollow mesh 進行 raycast，產生蜂巢格填充 mesh（同步執行）。完成後可透過 `GET /api/jobs/{job_id}/hex_grid.stl` 下載。同時會產生並儲存 `hollow_aligned.stl`。

錯誤：

- JOB_NOT_FOUND
- MODEL_NOT_FOUND // hollow mesh 不存在
- INVALID_MODEL // hollow mesh 無效 或 load_trimesh 失敗
- MISSING_BODY // 欄位空白
- VALIDATION_ERROR // 參數非數字、低於 0 等
- NO_HEX_GRID_CELLS // Hex grid 演算法未產生任何 cell（參數可能超出 hollow mesh 範圍）
- INTERNAL_ERROR

---

### `POST /api/v2/boolean`

對兩個 mesh 執行 Boolean 運算。

錯誤：

- MISSING_BODY // 欄位空白
- VALIDATION_ERROR // mesh_a 或 mesh_b 不是 STL、或 operation 不是 union/difference/intersection
- INVALID_MODEL // STL 內容損壞或格式無效
- BOOLEAN_FAILED // 幾何計算失敗（non-manifold、self-intersecting 等），retryable: false
- INTERNAL_ERROR

---

### `GET /api/v2/slices/{job_id}`

取得 job 狀態。

**可能錯誤**：`JOB_NOT_FOUND`

失敗的 job 以 **HTTP 200 + `success: false`** 回傳，`code` 為具體原因（`JOB_FAILED`、`HOLLOW_GENERATION_FAILED` 等）。

---

### `GET /api/v2/slices/{job_id}/preview.zip`

**可能錯誤**：`JOB_NOT_FOUND`、`JOB_STILL_PROCESSING`、`JOB_FAILED`、`FILE_NOT_FOUND`

---

### `GET /api/v2/slices/{job_id}/layers.zip`

同 `GET /api/jobs/{job_id}/layers.zip`。

**可能錯誤**：`JOB_NOT_FOUND`、`JOB_STILL_PROCESSING`、`JOB_FAILED`、`FILE_NOT_FOUND`

---

### `POST /api/v2/slices/{job_id}/download.prz`

同 `POST /api/jobs/{job_id}/download.prz`。

**可能錯誤**：`JOB_NOT_FOUND`、`JOB_STILL_PROCESSING`、`JOB_FAILED`、`FILE_NOT_FOUND`

---

### `POST /api/v2/slices/{job_id}/ortho-process`

執行完整 ortho 處理 pipeline（背景執行）。包含 hollow → extend → align → hex grid → drain holes → 多次 boolean 共約 10 個步驟。

完成後可透過 `GET /api/jobs/{job_id}/ortho_result.stl` 下載。進度可透過 `GET /api/v2/slices/{job_id}` 的 `orthoProgress` 欄位追蹤。

錯誤：

- JOB_NOT_FOUND
- JOB_ALREADY_EXECUTED // job 已執行，不在 pending 狀態
- MODEL_NOT_FOUND // 沒有上傳模型
- 包含 `generate-hollow`、`extend-bottom`、`generate-hex-grid`、`generate-drain-holes`、`boolean` 的所有錯誤

---