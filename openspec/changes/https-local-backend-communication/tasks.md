## 1. TLS 憑證與設定

- 1.1 實作**內嵌單一組** cert／key（與／或 PKCS#12，全安裝相同），隨 agent 安裝包發布；SAN 須涵蓋 `127.0.0.1` 與 `localhost`（**不**採每裝產生；細部見 `design.md` **D5**）。
- 1.2 新增 agent 設定旗標／環境變數：啟用 HTTPS、憑證／金鑰路徑（或 PKCS#12）、監聽繫結位址與連接埠。
- 1.3 依所選憑證模型，撰寫 macOS Safari 與至少一款 Chromium 引擎瀏覽器之首次信任說明。

## 2. Agent 執行期

- 2.1 於 agent HTTP 堆疊啟用 TLS（HTTPS 監聽），並以外部 TLS 用戶端驗證交握（例如 `curl -k` 或已信任憑證之 `curl`）。
- 2.2 若使用 WebSocket，於啟用 TLS 時以 **WSS** 暴露相同邏輯服務；自 `https:` 測試頁或自動化用戶端確認升級成功。
- 2.3 移除或停用任何預設／可選純 HTTP 對外監聽路徑；開發與打包情境皆以 HTTPS（及 WSS）為唯一支援路徑。
- 2.4 新增並驗證「程式碼直接運行（dev/runtime）」模式之啟動參數與憑證載入，確保可與 HTTPS 前端正常溝通。

## 3. Launcher、打包與整合方

- 3.1 在打包後的 agent 版面配置中附帶**既定內嵌**憑證材料（見 1.1）；將任何寫死之 `http://127.0.0.1:5179` 改為可設定之 `https://` 基礎 URL（若適用）。
- 3.2 當 UI 以 HTTPS 提供時，更新 SPA／雲端前端設定與文件，使 agent 使用 `https://`（及 `wss://`）；於 release note 標明 **BREAKING** 之 URL 變更。
- 3.3 於支援 runbook 新增章節：區分混合內容（scheme 錯誤）、TLS 信任錯誤與 CORS。
- 3.4 於對外／對內敘述**一致聲明**：**短期主線**為本機 TLS + **`https://`／`wss://`** + **首次安裝**時 Launcher／文件**一次性信任**（根 CA 不變之升級不重複）；憑證為內嵌單一組（與 `proposal.md`、`design.md` **D5**、`safari-support/https-mixed-content-communication-and-trust.md` 對齊）。
- 3.5 Launcher：實作「**僅首次安裝**觸發引導式升權並寫入 CA」；**升級安裝**在偵測根 CA 已受信任或未更換時**不**再提示密碼、**不**重複寫入（與 `design.md` **D5** 一致；若未來更換根 CA 則另訂行為）。
- 3.6 在打包後（packaged）交付型態中，驗證憑證與設定路徑可被正確載入，並確保前端可透過 `https://`／`wss://` 與後端正常溝通。

## 4. 驗證

- 4.1 手動驗證 Safari：完成信任步驟後，HTTPS 雲端應用程式可呼叫 `https://127.0.0.1:<port>`，主控台無混合內容錯誤。
- 4.2 若適用，於 Safari 與 Chrome 驗證自 HTTPS 網頁連線之 WSS。
- 4.3 **執行型態驗證：** 分別在「程式碼直接運行（dev/runtime）」與「打包後運行（packaged）」兩種模式下，驗證 HTTPS API（與若適用之 WSS）均可正常連通。
- 4.4 驗證：首次安裝後完成 CA 信任；覆蓋安裝／升級至新版（根 CA 不變）時**不**應再次要求信任流程。
- 4.5 **雙瀏覽器：** 在 Safari **與** Google Chrome（或產品指定之 Chromium 瀏覽器）各跑一輪：HTTPS API 與（若適用）WSS；確認完成相同信任步驟後兩者均可連通（對齊 `specs/local-agent-https/spec.md`）。
- 4.6 **非迴歸：** 驗證 splash、連線偵測、連接埠啟動／監聽、與 agent 之 API 溝通與既有預期一致；刻意行為變更須有 release note／規格說明（對齊 `specs/local-agent-https/spec.md`）。

