## 程式碼審查：agent-origin-write-guard（effort：medium）

範圍：已 stage 之未提交變更（`git diff --cached` + 審查後小修）。

### 規格符合性
- ✅ 對齊 design／spec：`/api/` 寫入閘道、無 Origin 放行、白名單重用 `agent.cors`、Content-Length 於 `call_next` 前擋 500MiB、403／413 走 `APIError`、白名單 413 帶 CORS header。
- ✅ 與 local-library「無 Origin → 403」刻意分歧已在 middleware 註解與 spec 鎖定。

### 正確性（0 CONFIRMED / 上限 8）
- 正確性：未發現 CONFIRMED 問題。
- [REFUTED] 缺 `Content-Length` 可進 handler — design／spec 明文允許；非缺陷。
- [REFUTED] `CORSMiddleware` 於啟動時 snapshot allowlist — 與改前相同；閘道與 `_cors_headers` 讀 live `cors_origins`，413 ACAO 正確。

### 清理與最佳實踐
- 已移除測試檔未使用的 `api_v2` import。
- `test_error_code_registry.py` 的 `EXPECTED_TOTAL`／owner 計數隨新碼更新為 36／python:20（登錄檔擴充必要配套）。
- 建議（未改）：可另加 `ENABLE_CORS=false` 略過閘道的單元測試 — 非規格必測；實作已有 early-return。

### 測試覆蓋
- ✅ 規格六類案例皆有自動化測試；手動 curl／http.client 已記錄於 `manual-test-results.md`。
- 未採納建議：將「無 Origin」改為 403（會推翻 design D2）— **不採納**。

### 行動項目
- [x] 更新 error-code registry 計數斷言
- [x] 移除未用 import
- [ ] 複測 pytest + 關鍵 curl（下一步）
