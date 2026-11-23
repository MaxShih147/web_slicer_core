# 手動測試結果（agent-origin-write-guard）

服務：`uvicorn agent.main:app` @ `http://127.0.0.1:15179`  
環境：`CORS_ALLOWED_ORIGINS=http://localhost:5173,https://localhost:5173`  
日期：2026-11-23

| # | 案例 | 結果 | 備註 |
|---|------|------|------|
| 4.2 | 白名單 Origin 寫入 `POST /api/v2/slices` | PASS HTTP 200 | `Origin: https://slicergo-dental.phrozen3d.info`，回 `jobId` |
| 4.3 | 偽造 Origin 寫入 | PASS HTTP 403 | `ORIGIN_FORBIDDEN`，無 jobId |
| 4.4 | 無 Origin 寫入 | PASS HTTP 200 | 回 `jobId` |
| 4.5 | GET `/api/health` + 偽造 Origin | PASS HTTP 200 | 未被閘道擋 |
| 4.5b | POST `/` + 偽造 Origin | PASS HTTP 405 | 非 403／非 `ORIGIN_FORBIDDEN` |
| 4.6 | 白名單 + `Content-Length: 524288001` | PASS HTTP 413 | `PAYLOAD_TOO_LARGE`；`access-control-allow-origin` 正確（raw http.client，避免 curl 覆寫 CL） |
| 4.7 | localhost Origin 寫入 | PASS HTTP 200 | `Origin: http://localhost:5173` |

自動化：`.venv\Scripts\python.exe -m pytest agent/tests/test_origin_write_guard.py -q` → **7 passed**
