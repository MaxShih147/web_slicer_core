## Why

`POST /api/v2/prz/parse` 已能回傳 PRZ 的 header 參數與預覽圖，但沒有提供各層像素圖的存取方式。前端（DS-Online）需要在匯入 PRZ 後，能透過滑動 bar 逐層瀏覽每一列印層的灰階圖，讓使用者在列印前確認切層結果。

## What Changes

- **修改** `POST /api/v2/prz/parse`：新增回傳 `session_id`（UUID），後端同步將 `PrzFile` 物件快取在記憶體中，供後續層圖請求使用
- **新增** `GET /api/v2/prz/{session_id}/layer/{index}`：從快取的 `PrzFile` lazy decode 指定層並以 PNG 回傳
- **新增** `DELETE /api/v2/prz/{session_id}`：釋放快取（前端頁面卸載時呼叫）
- **新增** 後端 TTL 自動清理：30 分鐘未存取的 session 自動回收記憶體

## Capabilities

### New Capabilities
- `prz-layer-session`: 伺服器端 PRZ session 管理與逐層圖 API — 上傳一次、按需取得各層 PNG

### Modified Capabilities
- `prz-parser`: `POST /api/v2/prz/parse` 回應新增 `session_id` 欄位（向下相容，現有欄位不變）

## Impact

**後端**
- `d:\repos\web_slicer_core\agent\api_v2.py`：新增全域 `_prz_sessions` dict、修改 parse endpoint、新增兩個 endpoint、新增背景清理 task

**記憶體**：每個活躍 session 持有整個 PRZ 檔案的 memoryview（最大 ~500MB），本地單人使用場景可接受；TTL 機制確保不無限累積
