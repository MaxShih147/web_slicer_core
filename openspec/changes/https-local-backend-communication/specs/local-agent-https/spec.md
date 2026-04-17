## ADDED Requirements

### Requirement: 本機 agent 暴露 HTTPS API

當本機 agent 啟用 TLS 時，系統**必須**於設定的主機與連接埠上，使用適用於 loopback 的 TLS 憑證接受 HTTPS 請求（例如憑證主旨或 SAN 含 `127.0.0.1` 及／或 `localhost`）。

#### Scenario: HTTPS 網頁呼叫 agent

- **WHEN** 網頁應用程式自 `https:` 來源載入，並對 `https://127.0.0.1:<agent-port>/`（或設定的 HTTPS 基礎 URL）執行 `fetch` 或 `XMLHttpRequest`
- **THEN** 使用者代理**不得**僅因混合內容政策而封鎖該請求；且當連線成功時，agent **必須**透過 TLS 回應該請求。

### Requirement: 啟用 TLS 時 WebSocket 升級須使用 WSS

若產品對瀏覽器用戶端暴露 WebSocket 端點，且 agent 已啟用 TLS，則系統**必須**對來自 HTTPS 網頁的該端點僅宣導並接受 **WSS**（`wss:`）URL，或**必須**在與 HTTPS 相同之 TLS 設定上終止 WSS。

#### Scenario: 自 HTTPS 網頁建立即時通道

- **WHEN** 自 `https:` 來源載入的網頁應用程式對 `wss://127.0.0.1:<agent-port>/<path>`（或設定的 WSS URL）開啟 WebSocket
- **THEN** 使用者代理**不得**僅因混合內容政策而封鎖該連線；且 agent **必須**透過 TLS 完成 WebSocket 交握。

### Requirement: 本機 TLS 憑證之信任路徑須文件化

系統**必須**文件化維運人員或終端使用者如何建立對 agent TLS 憑證的信任（例如信任所提供的根 CA，或依瀏覽器／作業系統說明接受自簽憑證），使 Safari 與其他瀏覽器在完成所述步驟後能完成 TLS 交握，且不持續出現阻擋畫面。

#### Scenario: 首次以 Safari 使用

- **WHEN** 使用者依所發行之憑證模型遵循文件化信任步驟
- **THEN** Safari **必須**能與 agent 建立 TLS，且**不得**因「自 HTTPS 頁面載入 HTTP」之混合內容而封鎖（若仍有失敗，**不得**僅歸因於 HTTP 對 HTTPS 之混合內容）。

### Requirement: 針對 HTTPS 網頁之用戶端設定須使用安全 URL

自 `https:` 來源載入 SPA 之整合**必須**以 `https:` scheme 設定 agent 基礎 URL（WebSocket 則用 `wss:`）。系統**必須**將在 `https:` 網頁情境下使用 `http:` 或 `ws:` 視為**不支援**，以維持跨瀏覽器相容性。

#### Scenario: 誤設 HTTP 基礎 URL

- **WHEN** 文件或設定將 UI 以 HTTPS 託管之部署的 agent URL 列為 `http://127.0.0.1:<port>`
- **THEN** 文件**必須**說明此設定將導致 Safari（及其他瀏覽器亦很可能）因混合內容而失敗，並**必須**指向 **HTTPS/WSS** 基礎 URL 作為支援作法。

### Requirement: TLS 失敗須能與混合內容區分

支援用之運維文件**必須**說明如何區分**混合內容**（自 `https:` 網頁請求 `http:` 遭封鎖）與 **TLS 信任／憑證錯誤**（交握或名稱不符），以避免將設定錯誤誤判為 CORS 問題。

#### Scenario: 支援分流排查

- **WHEN** 使用者回報自 HTTPS 雲端應用程式連線 localhost 出現「request blocked」或「access control」等錯誤
- **THEN** 支援材料**必須**指示在追蹤 CORS 或應用程式記錄**之前**，先檢查請求 scheme（`https`／`wss` 對 `http`／`ws`）。

### Requirement: 須同時支援 Safari 與 Google Chrome（Chromium）

本機 HTTPS（與適用之 WSS）與所文件化之**信任路徑**在**同一組**產品行為下，**必須**適用於以 **Safari** 與 **Google Chrome**（或以 Chromium 為引擎、面向一般使用者之同家族瀏覽器）自 `https:` 來源存取雲端 SPA 之情境。不得僅以單一引擎可通過即視為完成本 change。

#### Scenario: Safari 與 Chrome 皆能完成 TLS 並呼叫 agent

- **WHEN** 使用者已依文件完成一次性本機 CA／憑證信任，並分別以 Safari 與 Google Chrome 開啟同一 HTTPS 託管之應用程式
- **THEN** 兩者**皆須**能對 `https://127.0.0.1:<agent-port>`（或設定之 HTTPS 基礎 URL）成功完成 TLS 交握並進行預期之 HTTP API 流量；若有 WSS，兩者**皆須**能依產品設定建立 `wss:` 連線（在應用程式與 CORS 等設定正確之前提下）。

### Requirement: 導入 TLS／HTTPS 不得破壞既有產品行為

導入或開啟本機 **HTTPS**（與適用之 **WSS**）、憑證載入及 Launcher 信任相關變更時，系統**必須**維持既有、變更前已存在之**使用者可見流程與整合行為**，僅允許與 **scheme**（`https`／`wss`）或 **TLS 設定**直接相關且已文件化之調整。下列類型功能**不得**因本 change 而失效或行為未說明地退化（與下列同名或可對應之實作皆屬之）：

- 啟動／**splash**（或同等啟動畫面）流程  
- **連線偵測**（或 agent／本機服務可達性檢查）  
- **連接埠**之綁定、監聽與啟動（agent 可接受連線）  
- 與 agent 之 **API** 溝通（請求／回應語意與整合契約一致；僅端點 scheme 或 TLS 層可預期變更）

#### Scenario: 變更後迴歸煙霧測試

- **WHEN** 於整合測試或發行前驗證中，在啟用本機 HTTPS 與所選信任模型下啟動完整產品流程
- **THEN** splash、連線偵測、連接埠啟動與 API 溝通**必須**仍符合產品預期；若某行為刻意改變，**必須**於變更說明或 release note 中明列，且**不得**與本 requirement 之上列約束無解釋地衝突。

### Requirement: 所有支援執行型態必須以 HTTPS/WSS 與前端連通

後端專案在系統所支援的執行型態（至少包含「程式碼直接運行（dev/runtime）」與「打包後運行（packaged）」）下，**必須**使用相容於 loopback 的 TLS 設定對外提供 `https:` API（及若適用之 `wss:`），並與 HTTPS 前端完成正常通訊。對 HTTPS 前端情境下之 `http:`／`ws:` 端點，系統**必須**視為不支援。

#### Scenario: 程式碼直接運行可與 HTTPS 前端通訊

- **WHEN** 後端以程式碼直接運行（dev/runtime）啟動，且前端自 `https:` 來源載入並使用文件化的 `https://127.0.0.1:<agent-port>`（及若適用之 `wss://...`）
- **THEN** 前後端**必須**可完成 TLS 交握與預期 API（及若適用之 WebSocket）通訊，且不得要求改回 `http:`／`ws:`。

#### Scenario: 打包後運行可與 HTTPS 前端通訊

- **WHEN** 後端以打包後（packaged）型態啟動，且前端自 `https:` 來源載入並使用文件化的 `https://127.0.0.1:<agent-port>`（及若適用之 `wss://...`）
- **THEN** 前後端**必須**可完成 TLS 交握與預期 API（及若適用之 WebSocket）通訊，且行為與 dev/runtime 模式在整合契約上保持一致。
