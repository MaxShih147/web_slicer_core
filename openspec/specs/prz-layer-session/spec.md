# prz-layer-session Specification

## Purpose
後端 PRZ session 管理與逐層圖 API — 上傳一次、按需取得各層 PNG，支援 TTL 自動清理與前端主動釋放。

## Requirements

### Requirement: PRZ Session 建立
`POST /api/v2/prz/parse` SHALL 在成功解析後將 `PrzFile` 物件快取於伺服器記憶體，並回傳唯一的 `session_id`，供後續層圖請求使用。

#### Scenario: 成功建立 session
- **WHEN** 上傳合法的 .prz 檔案至 `POST /api/v2/prz/parse`
- **THEN** 回傳 JSON 包含 `session_id` 欄位（非空字串），且後端記憶體中已存有對應的 `PrzFile` 物件

#### Scenario: session_id 格式
- **WHEN** 成功解析 .prz 後取得 `session_id`
- **THEN** `session_id` 為符合 UUID v4 格式的字串（例如 `"550e8400-e29b-41d4-a716-446655440000"`）

#### Scenario: 解析失敗不建立 session
- **WHEN** 上傳非合法 PRZ 格式的檔案
- **THEN** 回傳 HTTP 400，後端不建立任何 session

---

### Requirement: 逐層圖 API
`agent/api_v2.py` SHALL 提供 `GET /api/v2/prz/{session_id}/layer/{index}` 端點，從快取的 `PrzFile` lazy decode 指定層並以 PNG 回傳。

#### Scenario: 成功取得層圖
- **WHEN** 以有效的 `session_id` 和合法的 `index`（0-based）請求層圖
- **THEN** 回傳 HTTP 200，`Content-Type: image/png`，body 為合法 PNG，解析後尺寸為 `(header.x_res, header.y_res)`，色彩模式為 8-bit 灰階

#### Scenario: session 不存在回傳 404
- **WHEN** 使用不存在或已過期的 `session_id` 請求層圖
- **THEN** 回傳 HTTP 404，JSON body 包含 `detail` 欄位

#### Scenario: index 超出範圍回傳 422
- **WHEN** 以有效 `session_id` 但 `index >= layer_count` 或 `index < 0` 請求層圖
- **THEN** 回傳 HTTP 422，JSON body 包含 `detail` 欄位說明索引超出範圍

#### Scenario: 存取層圖更新 last_access 時間
- **WHEN** 成功取得任一層圖
- **THEN** 該 session 的 last_access 時間戳更新為當下，TTL 計時重置

---

### Requirement: Session 主動釋放
`agent/api_v2.py` SHALL 提供 `DELETE /api/v2/prz/{session_id}` 端點，讓前端在頁面卸載時主動釋放伺服器記憶體。

#### Scenario: 成功刪除 session
- **WHEN** 以有效的 `session_id` 呼叫 DELETE
- **THEN** 回傳 HTTP 204，後端記憶體中對應的 `PrzFile` 物件被移除；後續以同一 `session_id` 請求層圖將回傳 404

#### Scenario: 刪除不存在的 session
- **WHEN** 以不存在或已過期的 `session_id` 呼叫 DELETE
- **THEN** 回傳 HTTP 404，JSON body 包含 `detail` 欄位

---

### Requirement: TTL 自動清理
後端 SHALL 自動清理超過 30 分鐘未存取的 PRZ session，以防止記憶體無限累積。

#### Scenario: 30 分鐘後 session 失效
- **WHEN** 一個 session 的 last_access 時間距今超過 1800 秒，且後台清理 task 已執行
- **THEN** 該 session 的 `PrzFile` 物件從記憶體移除；後續請求該 session 回傳 404

#### Scenario: 清理不影響活躍 session
- **WHEN** 後台清理 task 執行時，某 session 的 last_access 距今不足 1800 秒
- **THEN** 該 session 不被清理，後續層圖請求仍能正常回傳
