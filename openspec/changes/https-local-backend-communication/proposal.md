## 緣由

雲端託管的 SPA 透過 **HTTPS** 載入（例如在 Render），而 Bundle **本機 agent** 卻以純 **HTTP** 監聽（例如 `http://127.0.0.1:5179`）。瀏覽器將「HTTPS 網頁再去請求 HTTP 資源」視為 **混合內容（mixed content）**；**Safari** 會直接封鎖這類請求，也不像 Chrome 提供類似 Local Network Access 的提示。此失敗是由**瀏覽器安全策略**強制執行，並非後端 CORS 設定錯誤。在本機 agent 上啟用 **HTTPS（以及適用時的 WSS）**，可使頁面安全情境與 agent 端點一致，讓 **Safari** 與其他瀏覽器皆能允許 API 與 WebSocket 流量。

## 短期主線決策（已定調）

以下為產品／技術之**短中期預設路徑**，本 change 之規格與任務皆對齊此決策；對內說明補充見 `safari-support/https-mixed-content-communication-and-trust.md`。

| 項目 | 決策 |
|------|------|
| **本機 agent** | 以 **TLS** 提供 **HTTPS**（若有 WebSocket 則 **WSS**），例如 `https://127.0.0.1:<port>`／`wss://127.0.0.1:<port>`。 |
| **雲端 SPA** | 在 **HTTPS** 頁面內，以 **`https://`／`wss://`** 呼叫本機 agent（**不得**在支援情境下對本機使用 `http://`／`ws://` 以免 mixed content）。 |
| **信任** | 透過 **自簽**或**私有 CA**，由 **Launcher** 與／或**文件**引導使用者在**首次安裝**完成**一次性**本機信任（根憑證或同等流程）；**根 CA 不變**之版本升級**無須**重複該流程。公開 CA **不**作為 `127.0.0.1` 之預設解法。 |

**長期方向（上下文）：** 後端與 API 預期收斂至**雲端公開 HTTPS** 後，瀏覽器僅需呼叫雲端 API，與本 change 之過渡主線銜接；本 change **不排除**後續獨立之「全雲端 API」變更。

## 變更內容

- 將本機 agent 的 HTTP API 改為透過 **TLS** 提供，呼叫端可自 HTTPS 網頁使用 `https://127.0.0.1:<port>`（或同等主機）。
- 若 agent 目前已暴露 **WebSocket**，或於同一變更組合內新增，則應在相同 TLS 設定下以 **WSS**（`wss://...`）提供，避免被視為混合內容而遭封鎖。
- 本 change 直接採用 **HTTPS/WSS only**：不提供「開發例外 HTTP」或雙堆疊作為支援路徑；`http://`／`ws://` 對 HTTPS 頁面情境視為不支援。
- 為本機 TLS 提供**開發／本機環境等級的信任機制**（例如自簽憑證或由 Launcher 管理的 CA），並記載使用者**首次安裝時一次性**信任路徑；材料為**內嵌單一組**（全用戶相同、預期長期沿用，見 `design.md` **D5**）。
- **破壞性變更（BREAKING）**：對 agent 寫死 `http://` 或 `ws://` 的用戶端必須改為 `https://`／`wss://`（或透過可解析正確 scheme 的設定）。
- **執行型態一致性：** 後端在「程式碼直接運行（dev/runtime）」與「打包後運行（packaged）」兩種型態下，皆必須可由前端以 `https://`（及若適用之 `wss://`）正常通訊。
- 記載運維上的限制（除非日後明確納入，否則憑證釘選不在範圍內）。
- **雙瀏覽器：** 所交付之 TLS／WSS 與信任流程**須**同時涵蓋 **Safari** 與 **Google Chrome（Chromium）** 情境（見 `specs/local-agent-https/spec.md`）。
- **非迴歸：** 導入 HTTPS／TLS **不得**無解釋地破壞既有行為，例如 splash、連線偵測、連接埠啟動、與 agent 之 API 溝通等（見規格）。

## 能力範圍

### 新增能力

- `local-agent-https`：本機 agent 的 TLS 終止與安全 URL 約定，使 HTTPS 雲端前端能在**不因混合內容被封鎖**的前提下與本機後端通訊；若使用 WebSocket 則包含 WSS。

### 修改之既有能力

- _（無——此版本庫中尚無 `openspec/specs/` 既有能力。）_

## 影響面

- **本機 agent（Python）**：HTTP 伺服器堆疊（改為 HTTPS-only）、credential 載入、設定介面（路徑、啟用旗標、連接埠）、dev/runtime 與 packaged 兩種執行型態的一致行為。
- **Bundle Launcher／打包**：發布或產生憑證資產、安裝程式或首次啟動時信任本機 CA（若適用）、應用程式或文件內寫死的 `http://127.0.0.1:5179` 等參照。
- **雲端／網頁前端**：當頁面以 HTTPS 提供時，agent 的基礎 URL 或環境變數必須使用 `https`／`wss`（實際前端版本庫可能在本 monorepo 之外，但仍須更新才能端到端生效）。
- **開發者體驗**：本機測試說明、Safari 與 Chrome 信任步驟、釐清混合內容與憑證錯誤的排解方式。
- **迴歸風險**：須驗證 splash、連線偵測、連接埠與 API 等與變更前一致（規格化於 `specs/local-agent-https/spec.md`）。
