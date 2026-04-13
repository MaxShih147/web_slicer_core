## Why

目前 `prz_encoder.py` 只支援 .prz 的**單向輸出**（從 .sl1 → .prz），缺乏對應的解碼能力。`prz_pwm_patcher.py` 有部分層解析邏輯，但僅限於讀取 PWM 偏移量，不能還原完整的列印參數或圖層影像。需要一個完整的 parser，讓後端能從現有 .prz 檔案讀回所有設定與圖層資料，用於驗證、重新編碼、預覽顯示等用途。

## What Changes

- 新增 `agent/prz_decoder.py` 模組，實作 PRZ V3.0 格式的完整解碼
- 解碼能力涵蓋：header 所有欄位、per-layer 定義、RLE 圖像解碼、預覽圖解碼
- 新增後端 API 端點，允許上傳 .prz 並回傳解析結果（列印設定 JSON + 預覽圖）

## Capabilities

### New Capabilities
- `prz-parser`: 解碼 PRZ V3.0 二進位格式，提取 header 參數（機器設定、列印參數）、各層定義（exposure/lift/retract 值、PWM）、RLE 圖層影像（還原為灰度 numpy array）、兩組預覽圖（RGB565 → RGB）

### Modified Capabilities

（無現有 spec 需修改）

## Impact

- **新增檔案**: `agent/prz_decoder.py`
- **可能修改**: `agent/main.py` 或 `agent/api_v2.py`（新增解析 API 端點）
- **相依**: 僅標準函式庫 + `numpy`（現有依賴）
- **與現有程式碼關係**: 可與 `prz_pwm_patcher.py` 共用部分層解析邏輯（重構或調用）
