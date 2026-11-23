# 改動說明：切片服務寫入 Origin 閘道 + 500MB 上限

## 本次更新

- 原行為：切片 agent 不擋帶偽造／未授權 `Origin` 的寫入，未授權網站仍可能對本機建 job、上傳檔。
- 新行為：對路徑以 `/api/` 開頭的寫入（POST／PUT／PATCH／DELETE）做 Origin 檢查：
  - `Origin` 不在白名單 → **403**，不建 job、不存檔。
  - **沒有 Origin → 放行**（本機腳本；與 local-library「無 Origin 也 403」不同）。
  - Origin 在白名單 → 再看大小；`Content-Length` 超過 **500MB** → **413**，且在進 handler／落盤前就擋。
- 白名單重用既有 CORS 名單（SlicerGo Dental 三環境 + 正式 dsonline，其餘含 localhost 靠 `CORS_ALLOWED_ORIGINS`），不另維護一份。
- GET、非 `/api/` 路徑不受此寫入閘道影響。

## 工作計畫

以 FastAPI middleware 做寫入前閘道；錯誤走既有結構化 `APIError`（`ORIGIN_FORBIDDEN`／`PAYLOAD_TOO_LARGE`）。先 TDD（pytest）再實作，curl 手動驗收後 code-review、複測、OpenSpec 關單。

## 參數表（Parameter Table）

| 參數名稱 | 說明 | 預設值 | 範圍/選項 | 影響 |
|---|---|---|---|---|
| CORS 硬編碼 Origin | 出貨白名單 | slicergo 三環境 + `https://dsonline.phrozen3d.info` | 固定四個 HTTPS host | 這些站的寫入可過閘道 |
| `CORS_ALLOWED_ORIGINS` | 額外 Origin（逗號分隔） | 空（本機常加 localhost） | 合法 Origin URL | localhost／過渡站寫入 |
| `ENABLE_CORS` | 是否啟用 CORS（關則略過閘道） | true | true／false | 開發用關閉 |
| 寫入大小上限 | 白名單 Origin 的 `Content-Length` 上限 | 500 MiB | `500 * 1024 * 1024` | 超過回 413 |

## 新增/修改的 API

- 無新 endpoint。行為變更僅限 `/api/` 寫入前置檢查。
- 新錯誤碼：`ORIGIN_FORBIDDEN`（403）、`PAYLOAD_TOO_LARGE`（413）。

## 驗收方式（Acceptance）

1. 白名單 Origin 對 `/api/` 寫入 → 成功（非 403／413）。
2. 偽造 Origin 對 `/api/` 寫入 → 403，無新 job／無落盤。
3. 無 Origin 對 `/api/` 寫入 → 成功。
4. GET `/api/...` 或非 `/api/` 寫入 + 偽造 Origin → 不因本閘道 403。
5. 白名單 Origin + `Content-Length` > 500MB（只設 header）→ 413；瀏覽器可讀錯誤（有 CORS header）。
6. `CORS_ALLOWED_ORIGINS` 含 localhost 時，該 Origin 寫入成功；slicergo 前端正常寫入仍可用。
