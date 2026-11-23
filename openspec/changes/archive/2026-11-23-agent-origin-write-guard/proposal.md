## Why

切片服務（`web_slicer_core` agent）目前只靠 CORS 標頭，無法擋住瀏覽器以外、帶偽造 `Origin` 的寫入請求；未授權網站仍可能對本機 agent 建立 job、上傳檔案。需要在寫入路徑加上 Origin 白名單閘道，並在允許的跨站寫入上於進入 handler 前記下 500MB 上限，避免先落盤再拒絕。

## What Changes

- 新增 FastAPI／Starlette middleware：僅對路徑以 `/api/` 開頭且方法為 `POST`／`PUT`／`PATCH`／`DELETE` 的請求套用寫入 Origin 閘道。
- Origin 規則（**刻意與** `local-library-service` 的 `OriginValidationMiddleware` **不同**）：
  - 有 `Origin` 且不在白名單 → `403 Forbidden`；不建立 job、不寫入檔案。
  - 無 `Origin` → 放行（本機腳本／非瀏覽器客戶端；偽造 header 擋本機無意義）。
  - `Origin` 在白名單 → 再檢查請求大小；超過 500MB → `413 Payload Too Large`；否則放行。
- 白名單**重用**既有 CORS 名單（`main.py` 的 `_cors_origins`：硬編碼 SlicerGo Dental／正式 dsonline + `CORS_ALLOWED_ORIGINS`），不另維護第二份清單。
- `GET`、以及非 `/api/` 路徑，不套用此寫入 Origin 閘道。
- 403／413 回應對齊既有 `APIError` 結構化錯誤；白名單 Origin 被 413 擋下時仍須帶 CORS header，讓瀏覽器可讀錯誤。
- 登錄並產生 `ORIGIN_FORBIDDEN`（403）與 `PAYLOAD_TOO_LARGE`（413）錯誤碼（`error_codes.py` + factory + `--write`）。

## Capabilities

### New Capabilities

- `agent-origin-write-guard`：切片 agent 對 `/api/` 寫入請求的 Origin 白名單閘道，以及白名單 Origin 寫入的 500MB 上限（於 handler／落盤前拒絕）。

### Modified Capabilities

（無）— 既有 CORS 行為與 endpoint 契約不變；本能力為新增的寫入前閘道。錯誤碼登錄機制沿用 `error-code-registry`，不修改該能力的 REQUIREMENTS。

## Impact

- **程式碼**：`agent/main.py`（掛載 middleware、重用 `_cors_origins`／`_cors_headers`）、新建 middleware 模組（或同等位置）、`agent/errors.py`、`agent/error_codes.py`、衍生 `docs/err_code_spec.md`／`docs/error_codes.json`、`agent/tests/` 新增閘道測試。
- **API**：寫入行為對合法前端（白名單 Origin、localhost via env）與無 Origin 腳本應維持可用；偽造 Origin 的寫入改為 403；白名單 Origin 且 `Content-Length`＞500MB 改為 413。讀取（GET）與非 `/api/` 路徑不受影響。
- **相依／對照**：規則參考 `local-library-service` 的 Origin middleware，但「無 Origin → 放行」為本單硬性差異，不得照抄其 403。
- **非目標**：不實作完整 CSRF／認證；不擋「無 Origin」的本機腳本；不以另開白名單檔取代 CORS 名單；不在此變更改動前端。
