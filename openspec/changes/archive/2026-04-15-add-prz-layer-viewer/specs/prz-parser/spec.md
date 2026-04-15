## MODIFIED Requirements

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
