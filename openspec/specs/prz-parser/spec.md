# prz-parser Specification

## Purpose
TBD - created by archiving change add-prz-parser. Update Purpose after archive.
## Requirements
### Requirement: PRZ 格式驗證
解碼器 SHALL 在解析前驗證檔案為合法的 PRZ V3.0 格式。

#### Scenario: 合法 PRZ 檔案通過驗證
- **WHEN** 輸入檔案前 4 bytes 為 `V3.0`，且 bytes 4–11 為 `\x07\x00\x00\x00DLP\x00`
- **THEN** 解析繼續執行，不拋出例外

#### Scenario: magic bytes 不符
- **WHEN** 輸入檔案前 12 bytes 不符合 PRZ V3.0 magic
- **THEN** 拋出 `ValueError`，訊息包含 "Invalid PRZ file"

#### Scenario: 檔案過短
- **WHEN** 輸入資料長度小於 `LAYER_CONTENT_OFFSET`（195,477 bytes）
- **THEN** 拋出 `ValueError`，訊息包含 "File too short"

---

### Requirement: Header 欄位解析
解碼器 SHALL 從 PRZ header（195,477 bytes）解析所有欄位，對映至 `PrzHeader` dataclass。

#### Scenario: 機器與列印設定正確還原
- **WHEN** 解析由 `prz_encoder.py` 產生的合法 .prz 檔案
- **THEN** `PrzHeader` 中的 `printer_name`、`x_res`、`y_res`、`layer_height`、`exposure_time`、`bottom_exposure_time`、`bottom_layers`、`total_layers` 等欄位與編碼時的輸入值一致（浮點數誤差 ≤ 1e-4）

#### Scenario: 時間字串格式
- **WHEN** 解析 header 中的 file_time 欄位（24 bytes 字串）
- **THEN** `PrzHeader.file_time` 為 `str`，格式為 `YYYY-MM-DD HH:MM:SS`（或空字串若全為 null bytes）

---

### Requirement: Per-Layer 定義解析
解碼器 SHALL 解析每一層的 64 bytes 定義區塊，填入 `PrzLayerDef` dataclass 列表。

#### Scenario: 層數與設定對應
- **WHEN** 解析一個有 N 層的 .prz 檔案
- **THEN** `PrzFile.layers` 長度等於 `PrzHeader.total_layers`（= N），且每層 `z_position`、`exposure_time`、`light_pwm` 欄位有正確數值

#### Scenario: 底層 exposure 時間區分
- **WHEN** 解析前 `bottom_layers` 層
- **THEN** 這些層的 `exposure_time` 等於 header 的 `bottom_exposure_time`

#### Scenario: 過渡層 exposure 時間插值
- **WHEN** 解析第 `bottom_layers` 到 `bottom_layers + transition_layers - 1` 層（過渡層）
- **THEN** 這些層的 `exposure_time` 介於 `bottom_exposure_time` 與 `exposure_time` 之間（插值值）

---

### Requirement: RLE 圖層影像解碼
解碼器 SHALL 提供 `PrzFile.decode_layer_image(index)` 方法，將指定層的 RLE 資料還原為灰度 numpy array。

#### Scenario: 純黑層解碼
- **WHEN** 呼叫 `decode_layer_image(i)`，該層 RLE 僅含黑色像素 run
- **THEN** 回傳 shape 為 `(height, width)` 的 `uint8` ndarray，所有值為 `0`

#### Scenario: 純白層解碼
- **WHEN** 呼叫 `decode_layer_image(i)`，該層 RLE 僅含白色像素 run
- **THEN** 回傳 shape 為 `(height, width)` 的 `uint8` ndarray，所有值為 `255`

#### Scenario: 灰階 round-trip
- **WHEN** 任意灰度圖像先用 `_rle_encode_layer()` 編碼後再用 `decode_layer_image()` 解碼
- **THEN** 解碼結果與原始像素陣列完全相同（逐像素比對）

#### Scenario: RLE checksum 驗證
- **WHEN** 層 RLE 資料末尾 checksum 與前述所有 RLE bytes 之加和不符
- **THEN** 拋出 `ValueError`，訊息包含 "RLE checksum mismatch"

#### Scenario: 索引越界
- **WHEN** 呼叫 `decode_layer_image(index)`，index 超出 `[0, total_layers)` 範圍
- **THEN** 拋出 `IndexError`

---

### Requirement: 預覽圖解碼
解碼器 SHALL 從 header 中解碼兩張 RGB565 big-endian 預覽圖，還原為 RGB numpy array。

#### Scenario: 小預覽圖尺寸
- **WHEN** 解析 .prz 檔案
- **THEN** `PrzFile.preview_small` 為 shape `(116, 116, 3)` 的 `uint8` ndarray

#### Scenario: 大預覽圖尺寸
- **WHEN** 解析 .prz 檔案
- **THEN** `PrzFile.preview_large` 為 shape `(290, 290, 3)` 的 `uint8` ndarray

#### Scenario: RGB565 色彩還原
- **WHEN** 預覽圖是由純紅色（R=248, G=0, B=0）編碼為 RGB565 再解碼
- **THEN** 解碼像素 R 分量 ≥ 240（RGB565 的 5-bit 精度損失可接受）

---

### Requirement: `parse_prz()` 公開 API
`agent/prz_decoder.py` SHALL 提供 `parse_prz(data: bytes) -> PrzFile` 函式作為主要進入點。

#### Scenario: 接受 bytes 輸入
- **WHEN** 傳入合法 .prz 檔案的完整 bytes
- **THEN** 回傳 `PrzFile` 實例，不拋出例外

#### Scenario: layer 圖像採延遲解碼
- **WHEN** 呼叫 `parse_prz()` 解析一個大型 .prz 檔案（例如 500 層）
- **THEN** 函式返回前不解碼任何圖層影像（layers 僅含定義欄位與原始 RLE bytes 的 offset/size 資訊）

---

### Requirement: REST API 端點 `POST /prz/parse`
`agent/api_v2.py` SHALL 提供 `POST /prz/parse` 端點，接受 .prz 上傳並回傳解析結果。成功解析後 SHALL 同時建立 PRZ session 並在回應中包含 `session_id`。

#### Scenario: 成功解析回傳 JSON
- **WHEN** 上傳合法 .prz 檔案（`multipart/form-data`，欄位名稱 `file`）
- **THEN** 回傳 HTTP 200，body 為 JSON，包含 `header`（物件）、`preview_small_b64`（PNG base64 字串）、`preview_large_b64`（PNG base64 字串）、`layer_count`（整數）、**`session_id`（UUID v4 字串）**

#### Scenario: 無效檔案回傳 400
- **WHEN** 上傳不是合法 PRZ V3.0 的二進位資料
- **THEN** 回傳 HTTP 400，body JSON 包含 `detail` 欄位說明錯誤原因

#### Scenario: 上傳超過大小限制
- **WHEN** 上傳檔案大小超過 500 MB
- **THEN** 回傳 HTTP 413

---

### Requirement: PRZ 體積 / 重量 / 價格欄位單位

PRZ header 的 `volume`、`weight`、`price` 三個欄位 SHALL 以**立方公釐（mm³）**為單位寫入與解析。

三個欄位 SHALL 保持相同數值（鏡像 Mechado C++ 原作行為：encoder 將 volume 同時寫入 weight 與 price 欄位）。

`prz_decoder.py` 的 `PrzHeader.volume`、`PrzHeader.weight`、`PrzHeader.price` 欄位語意 SHALL 為 mm³。下游若需 mL，可自行 ÷ 1000 換算。

#### Scenario: 切片產出的 PRZ volume 為 mm³
- **WHEN** 編碼一個 1000 mm³ 樹脂消耗的物體（如 10×10×10mm 實心 cube）
- **THEN** PRZ header 的 `volume` 欄位 SHALL ≈ 1000.0（容許 ±10 為樹脂支撐 / 切片精度誤差）

#### Scenario: weight 與 price 同步為 mm³
- **WHEN** 解碼任一 PRZ 檔案
- **THEN** `PrzHeader.weight == PrzHeader.volume`
- **AND** `PrzHeader.price == PrzHeader.volume`
- **AND** 三者單位均為 mm³

#### Scenario: 對比 change 前版本數值放大 1000×
- **WHEN** 同一份切片資料分別用 change 前 / change 後版本編碼
- **THEN** change 後的 `volume` / `weight` / `price` 三欄數值 SHALL 為 change 前的 ~1000 倍

---

### Requirement: PRZ print_time 欄位由 encoder 內部物理推導

PRZ header 的 `print_time` 欄位（4 byte unsigned int 秒）SHALL 由 [`prz_encoder.py`](agent/prz_encoder.py) 內部呼叫 `_compute_print_time(config, total_layers, timing)` 計算。**SHALL NOT** 直接使用 fork（PrusaSlicer）的 `estimated_print_time` 估值。

計算公式定義詳見 `prz-motion-time` capability。

#### Scenario: print_time 不再來自 fork 估值
- **WHEN** 編碼任一 PRZ 檔案
- **THEN** PRZ `print_time` SHALL 等於 `_compute_print_time(config, total_layers, timing)` 的回傳值（int 截斷）
- **AND** SHALL NOT 等於 caller 傳入的 `estimated_print_time` 參數值

#### Scenario: 不同 motion 參數產生不同 print_time
- **WHEN** 同一物體分別用兩組不同 lift_speed 編碼（例如 50 vs 100）
- **THEN** 兩份 PRZ 的 `print_time` 欄位數值 SHALL 不同（反映 motion 公式的速度依賴）

---

### Requirement: PRZ Retract Distance 4 欄位採 4-case override

PRZ header 與 per-layer 的 `Retract Distance`、`Bottom Retract Distance`、`Retract Second Distance`、`Bottom Retract Second Distance` 4 欄位 SHALL 依「4-case override 邏輯」計算，詳見 `prz-motion-time` capability 的 Requirement。

舊行為（永遠執行 `max(0, lift + lift2 - drop2)`）SHALL 被取代。

#### Scenario: 既有未傳 retract 參數的 config 行為改變（breaking change）
- **WHEN** 既有 config 未傳 `"Print.Retract Distance"` 與 `"Print.Retract Second Distance"`（change 前走「永遠公式」路徑）
- **THEN** change 後 PRZ 寫入 `retract = 0.0`、`drop2 = lift + lift2`（Case 4 新版行為）
- **AND** 此行為改變 SHALL 在 release notes 中明確標示

---

### Requirement: encoder 接受 `Print.Retract Distance` 與 `Print.Bottom Retract Distance` config key

[`prz_encoder.py`](agent/prz_encoder.py) SHALL 從 config dict 讀取以下兩個新 key（既有 `_get_float()` 機制即可）：
- `"Print.Retract Distance"`
- `"Print.Bottom Retract Distance"`

未傳入時（falsy）走 4-case override 的 Case 1 或 Case 4 路徑。

#### Scenario: 前端傳入 Retract Distance
- **WHEN** API 請求的 `config` 含 `"Print": {"Retract Distance": 2.0}`
- **THEN** PRZ header 的 normal retract = 2.0
- **AND** PRZ header 的 normal drop2 = `max(0, lift + lift2 - 2.0)`（Case 2 路徑）

#### Scenario: 前端傳入 Bottom Retract Distance
- **WHEN** API 請求的 `config` 含 `"Print": {"Bottom Retract Distance": 1.5}`
- **THEN** PRZ header 的 bottom retract = 1.5
- **AND** PRZ header 的 bottom drop2 = `max(0, bottom_lift + bottom_lift2 - 1.5)`

#### Scenario: 既有 API 請求向後相容
- **WHEN** API 請求不含這兩個新 key（change 前的請求格式）
- **THEN** SHALL NOT 回傳 422 錯誤
- **AND** 走 4-case override 的 Case 1（若 drop2 仍有傳）或 Case 4（drop2 也未傳）路徑

