## Context

切片 agent（`agent/main.py`）已有 CORS allowlist：硬編碼四個正式／預發 host，其餘（含 localhost）靠 `CORS_ALLOWED_ORIGINS`。CORS 只影響瀏覽器是否暴露回應，**無法**阻止帶偽造 `Origin` 的寫入。`local-library-service` 已有 `OriginValidationMiddleware`，但對「無 Origin」回 403；本產品需求明確要求無 Origin 放行（本機腳本）。既有上傳路徑（例如 `POST /api/jobs`）會先 `create_job` 再 `file.read()` 寫檔；`POST /api/v2/prz/parse` 則在讀完整 body 後才以 `_PRZ_MAX_UPLOAD_BYTES`（500MB）回 413。閘道必須在 handler／落盤前擋下未授權 Origin 與過大白名單寫入。

## Goals / Non-Goals

**Goals:**

- 以單一 middleware 對 `/api/` 寫入套用 Origin 閘道與（白名單 Origin 下的）500MB 上限。
- 白名單與 CORS 共用 `_cors_origins`，避免雙份漂移。
- 403／413 使用既有 `APIError` JSON 形狀；白名單 Origin 的 413 仍帶 CORS header。
- 大小檢查以請求進入 handler **之前**為準，避免「先建 job／先寫檔再 413」。
- 測試覆蓋產品列舉的六類案例；agent 測試沿用 pytest／TestClient 慣例（本 repo 非 Vitest）。

**Non-Goals:**

- 不實作 token／API key／完整 CSRF 防護。
- 不對「無 Origin」客戶端套用 middleware 層 500MB 上限（產品條文將大小檢查掛在「Origin 在白名單」之後；無 Origin 端點若另有上限則維持既有行為）。
- 不另維護獨立 Origin 白名單檔或環境變數。
- 不改前端、Launcher 契約欄位（僅重用既有 `CORS_ALLOWED_ORIGINS`）。
- 不把路徑縮成僅 `/api/v2/`（產品要求 `/api/` 前綴，以涵蓋 v1 `POST /api/jobs` 等）。

## Decisions

### D1 — Middleware 掛載與適用範圍

- **決策**：新增 `OriginWriteGuardMiddleware`（名稱可微調），以 `BaseHTTPMiddleware`（或同等 ASGI middleware）掛在 `app` 上；僅當 `path.startswith("/api/")` 且 `method ∈ {POST,PUT,PATCH,DELETE}` 時檢查。
- **理由**：對齊產品路徑前綴；GET／靜態頁／非 API 不受影響。
- **替代方案**：在各寫入 endpoint 重複檢查 → 易漏（尤其 v1／v2 多入口）。拒絕。

### D2 — 無 Origin 放行（與 local-library 刻意分歧）

- **決策**：`Origin` header 缺席或空字串 → 直接 `call_next`，不做白名單比對、不做本 middleware 的 500MB 檢查。
- **理由**：產品明確要求本機腳本可寫入；瀏覽器跨站請求幾乎總會帶 Origin，偽造「無 Origin」對瀏覽器攻擊面無意義。
- **替代方案**：照抄 local-library 對無 Origin 回 403 → **禁止**，與本單衝突。

### D3 — 白名單單一真值

- **決策**：middleware 讀取與 CORS 相同的 `_cors_origins` 集合（含啟動時已 merge 的 `CORS_ALLOWED_ORIGINS`），或抽成共用模組／函式供 CORS 與閘道引用；**禁止**複製一份硬編碼 list。
- **理由**：產品要求「不要另維護」。
- **`ENABLE_CORS=false`**：與 local-library 一致，關閉 CORS 時略過 Origin 閘道（本機除錯）；500MB 閘道一併略過（無白名單語意）。於 design／tasks 註明，避免與正式路徑混淆。

### D4 — 大小量測點（避免先寫檔）

- **決策**：僅在「Origin 存在且 ∈ 白名單」時，讀取 `Content-Length`；若可解析為整數且 `> 500 * 1024 * 1024`，立即回 413，**不**呼叫 `call_next`。
- **量測點**：middleware `dispatch` 內、任何 job 建立／`UploadFile` 讀取／磁碟寫入之前。
- **缺 `Content-Length` 或無法解析**：本 middleware **不**因此拒絕（放行至 handler）。理由：chunked／部分客戶端可能省略；產品驗收以 Content-Length 可控測試為準。既有 endpoint 級上限（如 PRZ 讀完再比）仍可作為後備，但閘道目標是「有 Content-Length 的過大請求絕不進 handler」。
- **替代方案**：在 middleware 緩衝讀完整 body → 記憶體壓力大、實作複雜；拒絕作為預設。

### D5 — 錯誤碼與 CORS header

- **決策**：
  - 403 → `ORIGIN_FORBIDDEN`（`retryable: false`），factory 如 `origin_forbidden()`。
  - 413 → `PAYLOAD_TOO_LARGE`（`retryable: false`），factory 如 `payload_too_large()`。
  - 兩者登錄 `agent/error_codes.py`（`owner: python`），執行 `python -m agent.tools.error_codes --write`。
  - 回傳使用 `APIError.to_response(headers=...)`；headers 重用 `_cors_headers(request)` 語意：僅當 Origin ∈ 白名單時附加 ACAO／credentials（413 必需要，讓前端讀得到；403 偽造 Origin 通常不在名單， naturally 不帶）。
- **理由**：對齊 local-library 錯誤碼命名與本 repo 結構化錯誤；滿足「允許 Origin 時錯誤仍應帶 CORS header」。
- **替代方案**：裸 `HTTPException(403/413)` → 與 `APIError`／前端錯誤處理不一致。

### D6 — Middleware 與 CORSMiddleware 順序

- **決策**：比照 local-library：先加 `CORSMiddleware`，再加 Origin 閘道（後加者為外層）。閘道短路回應時**自行**附上 CORS headers（見 D5），不依賴 CORSMiddleware 再包一層。
- **理由**：短路時內層 CORS middleware 不會處理該 Response；手動 headers 最穩。

### D7 — 測試策略

- **決策**：pytest + `fastapi.testclient.TestClient`，對真實 `app`（或掛上同一 middleware／同源白名單的精簡 app）發請求。
- **案例**：
  1. 白名單 Origin + 寫入 → 非 403／非 413（成功路徑可 mock handler 或打輕量 endpoint）。
  2. 偽造 Origin + 寫入 → 403，且無新 job 目錄／無副作用（可對 `POST /api/jobs` 或可觀察的寫入點 assert）。
  3. 無 Origin + 寫入 → 成功（非 403）。
  4. GET 或非 `/api/` → 即使偽造 Origin 也不被此閘道擋。
  5. 白名單 Origin + `Content-Length` > 500MB → 413（只設 header，不真傳 body）。
  6. `CORS_ALLOWED_ORIGINS` 含 localhost Origin 的寫入 → 成功。
- ** vitest**：不適用本 repo agent；卡住時遵守既有 pytest／hang 慣例（明確路徑、避免整包卡住的測試指令）。

## Risks / Trade-offs

- [無 Origin 可寫入] → 產品接受的本機腳本路徑；瀏覽器跨站幾乎必帶 Origin。文件與 Notion 摘要須寫清。
- [缺 Content-Length 可繞過 middleware 500MB] → 以 endpoint 既有檢查為後備；驗收以 Content-Length 為主。若未來要強制，另開 change。
- [偽造 Origin 成白名單字串] → 本閘道不驗證 TLS／簽名；僅擋「非白名單 Origin」與過大 payload。完整認證非本單範圍。
- [BaseHTTPMiddleware 已知限制] → 若實作中遇 request body 消費問題，改純 ASGI middleware；測試須覆蓋「403／413 後無落盤」。

## Migration Plan

1. 合併後隨 agent 重啟即生效；無需資料遷移。
2. 本機前端須確保 `CORS_ALLOWED_ORIGINS` 含其 Origin（既有 CORS 需求，無新變數）。
3. 回滾：移除 middleware 掛載或設 `ENABLE_CORS=false`（後者同時關 CORS，僅適開發）。

## Open Questions

（無阻擋實作的未決項。若實作時發現 v1 `HTTPException` 與 `APIError` 混用導致 403／413 形狀不一致，優先讓閘道本身走 `APIError`；不強制本單改寫所有 v1 handler。）
