# agent-origin-write-guard Specification

## Purpose

切片 agent 對 `/api/` 寫入請求的 Origin 白名單閘道，以及白名單 Origin 寫入的 500MB 上限（於 handler／落盤前拒絕）。

## Requirements

### Requirement: 寫入路徑 Origin 閘道

系統 SHALL 以 middleware（或同等請求前置層）對同時滿足下列條件的 HTTP 請求套用 Origin 寫入閘道：

1. URL path 以 `/api/` 開頭；且
2. 方法為 `POST`、`PUT`、`PATCH` 或 `DELETE`。

閘道使用的允許 Origin 集合 MUST 與 CORS allowlist 為同一真值（含硬編碼之 SlicerGo Dental／正式 dsonline host，以及環境變數 `CORS_ALLOWED_ORIGINS` 合併後的項目）。MUST NOT 維護第二份獨立白名單。

當 `ENABLE_CORS` 為關閉時，系統 MAY 略過本 Origin 閘道（與開發用關閉 CORS 一致）。

#### Scenario: 白名單 Origin 寫入放行

- **WHEN** 客戶端對 `/api/` 寫入路徑發出寫入方法，且 `Origin` 屬於 CORS allowlist，且請求大小未超過上限（見「白名單寫入 500MB 上限」）
- **THEN** 系統 MUST NOT 僅因 Origin 檢查而回傳 403
- **AND** 請求 MUST 進入既有 handler 處理

#### Scenario: 偽造 Origin 寫入拒絕且無副作用

- **WHEN** 客戶端對 `/api/` 寫入路徑發出寫入方法，且帶有不在 CORS allowlist 的 `Origin`
- **THEN** 系統 MUST 回傳 HTTP 403
- **AND** 回應 MUST 為結構化錯誤，`code` 為 `ORIGIN_FORBIDDEN`，`retryable` 為 false
- **AND** 系統 MUST NOT 建立新 job、MUST NOT 將上傳內容寫入 job／工作目錄

#### Scenario: 無 Origin 寫入放行

- **WHEN** 客戶端對 `/api/` 寫入路徑發出寫入方法，且請求未帶 `Origin` header（或缺席／空）
- **THEN** 系統 MUST NOT 因 Origin 閘道回傳 403
- **AND** 請求 MUST 進入既有 handler（本機腳本路徑）

#### Scenario: GET 不受寫入 Origin 閘道限制

- **WHEN** 客戶端對 `/api/` 路徑發出 `GET`，即使 `Origin` 不在白名單
- **THEN** 系統 MUST NOT 因本寫入 Origin 閘道回傳 403

#### Scenario: 非 /api/ 路徑不受寫入 Origin 閘道限制

- **WHEN** 客戶端對非 `/api/` 前綴路徑發出寫入方法，即使 `Origin` 不在白名單
- **THEN** 系統 MUST NOT 因本寫入 Origin 閘道回傳 403

#### Scenario: CORS_ALLOWED_ORIGINS 內的 localhost 寫入放行

- **WHEN** 環境已將 `http://localhost:5173`（或同等 localhost Origin）併入 CORS allowlist，且客戶端以此 `Origin` 對 `/api/` 發出寫入且未超 500MB
- **THEN** 系統 MUST NOT 因 Origin 閘道回傳 403
- **AND** 請求 MUST 進入既有 handler

### Requirement: 白名單寫入 500MB 上限

當寫入請求已通過 Origin 閘道（`Origin` 存在且屬於 CORS allowlist）時，系統 SHALL 在呼叫下游 handler、建立 job、或將請求 body 寫入磁碟之前，檢查請求宣告大小。

大小量測 MUST 以 `Content-Length` header 為準（可解析之整數位元組數）。上限為 `500 * 1024 * 1024`（500 MiB）。超過上限 MUST 回傳 HTTP 413，`code` 為 `PAYLOAD_TOO_LARGE`，`retryable` 為 false，且 MUST NOT 建立 job 或落盤。

若缺少 `Content-Length` 或無法解析，本閘道 MUST NOT 僅因此回傳 413（放行至 handler；既有 endpoint 級上限仍可適用）。

無 `Origin` 而放行的請求，不受本 middleware 500MB 規則約束（產品將大小檢查置於白名單 Origin 分支）。

#### Scenario: Content-Length 超過 500MB 回 413

- **WHEN** 白名單 `Origin` 對 `/api/` 發出寫入，且 `Content-Length` 大於 `500 * 1024 * 1024`
- **THEN** 系統 MUST 回傳 HTTP 413，`code` 為 `PAYLOAD_TOO_LARGE`
- **AND** 系統 MUST NOT 呼叫會建立 job 或寫入上傳檔的下游邏輯
- **AND** 測試 MUST 僅設定 `Content-Length`（或同等可控方式），MUST NOT 真傳 500MB body

#### Scenario: 允許 Origin 的 413 仍帶 CORS header

- **WHEN** 白名單 `Origin` 的寫入因超過 500MB 被閘道拒絕
- **THEN** 回應 MUST 包含對應該 Origin 的 CORS 允許標頭（與既有 `_cors_headers` 語意一致），使瀏覽器可讀取錯誤本體

### Requirement: 與 local-library Origin 規則之差異

本能力對「無 Origin」的行為 MUST 為放行。實作與文件 MUST NOT 將 `local-library-service` 的「無 Origin → 403」行為套用到本切片 agent。

#### Scenario: 文件與測試鎖定無 Origin 放行

- **WHEN** 審查本能力之規格、設計或測試
- **THEN** MUST 存在明確案例：無 `Origin` 的 `/api/` 寫入不被本閘道以 403 拒絕
