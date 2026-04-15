## 1. 後端：Session 管理基礎設施

- [x] 1.1 在 `agent/api_v2.py` 頂部新增全域 `_prz_sessions: dict[str, tuple[PrzFile, float]] = {}`，並確認 `import uuid, time` 已存在（或補上）
- [x] 1.2 在 FastAPI app 的 `startup` 事件中啟動 asyncio 背景 task，每 300 秒掃描一次 `_prz_sessions`，清除 last_access 距今超過 1800 秒的 session

## 2. 後端：修改 POST /prz/parse

- [x] 2.1 在 `parse_prz_endpoint` 中，成功解析後產生 `session_id = str(uuid.uuid4())`，並將 `(prz, time.time())` 存入 `_prz_sessions[session_id]`
- [x] 2.2 在回傳的 JSON response 中新增 `session_id` 欄位

## 3. 後端：新增層圖與 Session 管理端點

- [x] 3.1 新增 `GET /api/v2/prz/{session_id}/layer/{index}` 端點：查無 session 回傳 404；index 越界回傳 422；成功時呼叫 `prz.decode_layer_image(index)` 並以 Pillow 轉為 PNG bytes 回傳（`Response(content=..., media_type="image/png")`），同時更新 last_access 時間
- [x] 3.2 新增 `DELETE /api/v2/prz/{session_id}` 端點：session 存在時移除並回傳 204；不存在時回傳 404
- [x] 3.3 確認現有 `_ndarray_to_png_b64()` 的 Pillow encode 邏輯可被 3.1 複用（或提取成 `_ndarray_to_png_bytes()` 返回 raw bytes 而非 base64）

