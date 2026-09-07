## 1. 建立模組骨架與資料結構

- [x] 1.1 新增 `agent/prz_decoder.py`，定義 `PrzHeader` dataclass（對映 header 所有欄位：版本、機器名稱、解析度、列印參數、PWM、過渡層數等）
- [x] 1.2 定義 `PrzLayerDef` dataclass（對映 per-layer 64 bytes 定義：z_position、exposure_time、light_off_time、lift/retract 參數、light_pwm）
- [x] 1.3 定義 `PrzFile` dataclass（含 `header: PrzHeader`、`preview_small: np.ndarray`、`preview_large: np.ndarray`、`layers: list[PrzLayerDef]`，以及儲存各層 RLE offset/size 的內部欄位）

## 2. Header 解析

- [x] 2.1 實作 magic bytes 與版本驗證（檢查前 4 bytes = `V3.0`、bytes 4–11 = `\x07\x00\x00\x00DLP\x00`；不符合或檔案過短時拋出 `ValueError`）
- [x] 2.2 實作 `_parse_header(data: bytes) -> PrzHeader`，依照 `prz_encoder.py` 中的位元組偏移表依序讀取所有欄位（使用 `struct.unpack_from` + 大端序格式字元）
- [x] 2.3 實作 RGB565 big-endian → RGB numpy array 的預覽圖解碼（`_rgb565_be_to_rgb(data: bytes, w: int, h: int) -> np.ndarray`），向量化處理

## 3. Layer 定義解析與索引建立

- [x] 3.1 實作 `_scan_layers(data: bytes, total_layers: int) -> list[dict]`，從 `LAYER_CONTENT_OFFSET`（195,477）開始依序掃描每層：讀取 64 bytes 定義 + CRLF + 4 bytes RLE size，記錄 RLE data 的起始偏移與長度
- [x] 3.2 在 `_scan_layers` 中解析每層 64 bytes 定義欄位，填入 `PrzLayerDef`（z_position、exposure_time、light_off_time、lift distance/speed、retract distance/speed、second-stage 參數、light_pwm）

## 4. RLE 解碼

- [x] 4.1 實作 `_rle_decode_layer(rle_bytes: bytes, width: int, height: int) -> np.ndarray`，使用 `memoryview` 索引掃描：讀 first byte → 解析 color type（bits 5-4）與 byte_count_bits（bits 7-6）→ 讀 extra bytes → 若灰階再讀 1 byte 灰度值 → 填像素 buffer
- [x] 4.2 在解碼函式末尾驗證 RLE checksum（`(~sum(rle_bytes[1:-1])) & 0xFF` 應等於最後 1 byte）；不符合時拋出 `ValueError("RLE checksum mismatch")`
- [x] 4.3 在 `PrzFile` 上實作 `decode_layer_image(index: int) -> np.ndarray` 方法，根據 layer 索引從原始 bytes 取出對應的 RLE 資料再呼叫 `_rle_decode_layer`；索引越界時拋出 `IndexError`

## 5. 公開 `parse_prz()` 函式

- [x] 5.1 實作 `parse_prz(data: bytes) -> PrzFile`：依序呼叫驗證 → `_parse_header` → 預覽圖解碼 → `_scan_layers`，組裝並回傳 `PrzFile`；`data` 以 `memoryview` 持有避免不必要複製

## 6. 單元測試（round-trip 驗證）

- [x] 6.1 新增 `agent/tests/test_prz_decoder.py`（或對應測試目錄），使用 `prz_encoder.py` 的 `_rle_encode_layer` 產生合成 RLE 資料，驗證 `_rle_decode_layer` 還原結果與原始像素陣列完全相同
- [x] 6.2 新增測試：建立最小合法 .prz header bytes（可直接 hardcode 195,477 bytes 的 mock，或用 `encode_prz` 產生），呼叫 `parse_prz()` 驗證 `PrzHeader` 欄位值正確

## 7. API 端點

- [x] 7.1 在 `agent/api_v2.py` 新增 `POST /prz/parse` 路由，接受 `multipart/form-data`（`file` 欄位），呼叫 `parse_prz()`，回傳 JSON（`header` dict、`preview_small_b64` PNG base64、`preview_large_b64` PNG base64、`layer_count`）
- [x] 7.2 在端點中加入格式錯誤的例外處理：`ValueError` → HTTP 400（含 `detail` 訊息）
- [x] 7.3 在端點中加入上傳大小限制（500 MB），超過時回傳 HTTP 413

## 8. 前端文件（DS-Online 整合說明）

- [x] 8.1 在 `D:\repos\DS-Online\docs\backend_API.md` 新增 `POST /prz/parse` 端點文件，包含：請求格式（`multipart/form-data`，`file` 欄位）、完整 JSON response 結構（`header` 所有欄位說明、`preview_small_b64`/`preview_large_b64` 型別與尺寸、`layer_count`）、錯誤碼（400/413）
- [x] 8.2 在 API 文件中補充 `header` 物件的完整欄位表（欄位名稱、型別、單位、說明），對應 `PrzHeader` 的所有屬性（機器設定、列印參數、PWM 等）
- [x] 8.3 在 API 文件中加入前端使用範例（JavaScript/fetch），示範：上傳 .prz 檔案、解析回傳的 base64 預覽圖（轉為 `<img>` src）、讀取 `header.layer_count` 與 `header.layer_height` 等常用欄位
