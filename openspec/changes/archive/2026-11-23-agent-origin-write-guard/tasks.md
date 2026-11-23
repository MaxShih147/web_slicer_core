## 1. 錯誤碼與共用白名單前置

- [x] 1.1 在 `agent/error_codes.py` 登錄 `ORIGIN_FORBIDDEN`（403，`retryable=false`，`owner=python`）與 `PAYLOAD_TOO_LARGE`（413，`retryable=false`，`owner=python`）
- [x] 1.2 在 `agent/errors.py` 新增對應 factory（`origin_forbidden`、`payload_too_large`），執行 `python -m agent.tools.error_codes --write` 更新衍生文件
- [x] 1.3 確認 CORS allowlist（`_cors_origins`／`CORS_ALLOWED_ORIGINS`／`_cors_headers`）可供 middleware 重用，必要時抽出共用符號但**不**另開第二份名單

## 2. TDD：先寫會失敗的測試

- [x] 2.1 載入並遵守專案 tdd skill；新增 `agent/tests/test_origin_write_guard.py`（或同等路徑），使用 pytest + `TestClient`，對真實 `app` 或同等掛載方式測試
- [x] 2.2 案例：白名單 Origin + `/api/` 寫入 → 非 403／非 413（成功進入 handler）
- [x] 2.3 案例：偽造 Origin + `/api/` 寫入 → 403 `ORIGIN_FORBIDDEN`，且無新 job／無落盤副作用
- [x] 2.4 案例：無 Origin + `/api/` 寫入 → 非 403（放行）
- [x] 2.5 案例：`GET /api/...` 或非 `/api/` 寫入 + 偽造 Origin → 不被本閘道以 403 拒絕
- [x] 2.6 案例：白名單 Origin + `Content-Length` > 500MiB → 413 `PAYLOAD_TOO_LARGE`（只設 header，不真傳 body）；允許 Origin 時回應帶 CORS header
- [x] 2.7 案例：`CORS_ALLOWED_ORIGINS` 含 localhost Origin 時，該 Origin 寫入成功
- [x] 2.8 在實作前執行測試，確認上述案例失敗（紅燈）；測試指令使用專案既有 pytest 方式（例如 `.venv312/Scripts/python.exe -m pytest agent/tests/test_origin_write_guard.py -q`），卡住時遵守本 repo hang 慣例

## 3. 實作 middleware 並掛載

- [x] 3.1 實作 Origin 寫入閘道 middleware（適用 `/api/` + POST/PUT/PATCH/DELETE；無 Origin 放行；非白名單 403；白名單再查 `Content-Length`；超量 413；量測點在 `call_next`／建 job／寫檔之前）
- [x] 3.2 於 `agent/main.py` 掛載：順序對齊 design（CORS 之後加閘道）；短路回應使用 `APIError.to_response` + `_cors_headers` 語意
- [x] 3.3 `ENABLE_CORS=false` 時略過閘道（與 design D3 一致）
- [x] 3.4 重跑 2.x 測試至全綠；必要時微調實作，不放寬「無 Origin 放行」與「不另維護白名單」

## 4. 手動測試（未過不得進 review／關單）

- [x] 4.1 以 `run_agent`（或專案慣用啟動方式）起服務
- [x] 4.2 curl：白名單 Origin 寫入 → 成功（或非 403／413）
- [x] 4.3 curl：偽造 Origin 寫入 → 403，確認無新 job／檔案
- [x] 4.4 curl：無 Origin 寫入 → 成功
- [x] 4.5 curl：GET 或非 `/api/` → 不因閘道 403
- [x] 4.6 curl：白名單 Origin + 過大 `Content-Length` → 413
- [x] 4.7 確認前端 localhost／slicergo 正常寫入仍可用（`CORS_ALLOWED_ORIGINS` 已含 localhost 時）
- [x] 4.8 將手動測結果記在本 change 或回報清單（通過才繼續）

## 5. Stage、code-review、複測

- [x] 5.1 僅 stage 本 change 相關檔（openspec、agent middleware／errors／error_codes、tests、衍生 docs）；勿夾帶 `__third_party`、secrets、無關未追蹤檔
- [x] 5.2 載入 code-review skill 跑 review；完整閱讀報告
- [x] 5.3 修復與 design／spec 一致的問題；若建議推翻 design 刻意決策（例如無 Origin 放行）→ 不盲修，對齊 design 或詢問使用者
- [x] 5.4 review 修復後重跑 pytest 關鍵檔與 4.x curl／關鍵路徑；未過不得關單

## 6. 關單與 commit（僅在授權後）

- [x] 6.1 tasks 全勾、測試與手動測通過後，依本 repo openspec close／archive 流程歸檔（`openspec-close-change`／`opsx-close` 或同等）；delta sync、pre-flight 全過
- [x] 6.2 僅在關單完成且流程／使用者要求 commit 時，以 conventional commit 提交；**不** push、**不**合進 `dev`，除非使用者明確要求
