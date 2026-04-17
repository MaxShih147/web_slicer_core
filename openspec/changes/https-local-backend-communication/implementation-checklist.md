# Implementation Checklist（by Repo Modules）

本文件將 `https-local-backend-communication` 的 OpenSpec 需求，拆成可直接執行的 implementation tickets。  
目標：全面 **HTTPS/WSS only**，並確保後端在 **dev/runtime** 與 **packaged** 兩種型態皆可與前端正常通訊。

## Repo 邊界與責任

- `DS-Online`：前端專案（HTTPS 頁面；呼叫本機 agent 的 API/WSS client）。
- `Bundle-Launcher`：後端打包與後端程式總入口（Electron `main.cjs`、安裝信任流程、打包腳本）。
- `web_slicer_core`：後端切片專案（Python/FastAPI/核心 API；TLS/WSS server 行為）。
- `WebSlicer_PrinterControl`：機台控制監控專案（與 Launcher 一起打包；若有 WS 或 API 互通需對齊 HTTPS/WSS 契約）。

---

## 開發前必填參數表（Production-like Readiness Gate）

此表已採用建議值作為本次預設基線，可直接開工。  
若後續調整，請以 PR 形式更新本表，避免跨 repo 漂移。

### 1) 通訊與端點契約（跨 repo）


| 參數                       | 建議值（實務預設）                                    | 最終值                                                                                           | Owner Repo                      | Owner                    | Freeze By |
| ------------------------ | -------------------------------------------- | --------------------------------------------------------------------------------------------- | ------------------------------- | ------------------------ | --------- |
| Agent API Base URL       | `https://127.0.0.1:5179`                     | `https://127.0.0.1:5179`                                                                      | `web_slicer_core` + `DS-Online` | Backend TL + Frontend TL | M1 start  |
| Agent WS Base URL（若適用）   | `wss://127.0.0.1:5179`                       | `wss://127.0.0.1:5179`                                                                        | `web_slicer_core` + `DS-Online` | Backend TL + Frontend TL | M1 start  |
| Health Endpoint          | `/health`                                    | `/health`                                                                                     | `web_slicer_core`               | Backend TL               | M1 start  |
| API Version Prefix       | `/api/v1`（若現況有 versioning）                   | `/api/v1`（新端點）/ 既有端點維持原狀直到完成遷移                                                                | `web_slicer_core`               | Backend TL               | M1 start  |
| Allowed Origin（HTTPS 前端） | `https://<DS-Online-domain>`（含 staging/prod） | `https://app.ds-online.com`, `https://staging.ds-online.com`（本機開發可加 `https://localhost:5173`） | `web_slicer_core` + `DS-Online` | Backend TL + Frontend TL | M1 start  |


### 2) TLS 憑證與信任模型（安全與安裝）


| 參數                   | 建議值（實務預設）                              | 最終值                      | Owner Repo                            | Owner                    | Freeze By |
| -------------------- | -------------------------------------- | ------------------------ | ------------------------------------- | ------------------------ | --------- |
| 憑證封裝型式               | `cert.pem + key.pem`（若既有工具鏈偏好可改 `p12`） | `cert.pem + key.pem`     | `Bundle-Launcher` + `web_slicer_core` | Launcher TL + Backend TL | M1 start  |
| SAN                  | 必含 `127.0.0.1`, `localhost`            | `127.0.0.1`, `localhost` | `web_slicer_core`                     | Backend TL               | M1 start  |
| 憑證材料策略               | 單一組內嵌材料（依 OpenSpec D5）                 | 單一組內嵌材料（根 CA 不變）         | `Bundle-Launcher`                     | Launcher TL              | M1 start  |
| 根 CA 信任觸發            | 僅首次安裝觸發（升級且根 CA 不變不重複）                 | 僅首次安裝觸發；升級不重複（根 CA 不變）   | `Bundle-Launcher`                     | Launcher TL              | M2 start  |
| 信任失敗 handling policy | 顯示可操作錯誤訊息 + 引導重試/聯繫支援                  | 顯示錯誤碼 + 重試按鈕 + 支援文件連結    | `Bundle-Launcher`                     | Launcher TL + Support TL | M2 start  |


### 3) 執行型態與打包佈局（dev/runtime + packaged）


| 參數                             | 建議值（實務預設）                                             | 最終值                                                              | Owner Repo                            | Owner                    | Freeze By |
| ------------------------------ | ----------------------------------------------------- | ---------------------------------------------------------------- | ------------------------------------- | ------------------------ | --------- |
| Dev/runtime 憑證讀取路徑             | 明確環境變數注入（不寫死絕對路徑）                                     | `TLS_CERT_PATH`, `TLS_KEY_PATH` 由 Launcher 注入；CI 可用 `.env.local` | `Bundle-Launcher` + `web_slicer_core` | Launcher TL + Backend TL | M1 start  |
| Packaged 憑證讀取路徑                | 透過 bundle 內固定相對路徑                                     | `<bundleRoot>/certs/cert.pem`, `<bundleRoot>/certs/key.pem`      | `Bundle-Launcher`                     | Launcher TL              | M1 start  |
| Launcher health check protocol | HTTPS only                                            | HTTPS only（`https://127.0.0.1:5179/health`）                      | `Bundle-Launcher`                     | Launcher TL              | M1 start  |
| HTTP fallback policy           | Disabled（不支援 `http/ws`）                               | Disabled（全 repo 一致）                                              | All repos                             | Tech Lead                | M1 start  |
| Error telemetry key fields     | `scheme`, `host`, `port`, `cert_source`, `error_code` | `scheme`, `host`, `port`, `cert_source`, `error_code`, `phase`   | `Bundle-Launcher` + `web_slicer_core` | Launcher TL + Backend TL | M1 start  |


### 4) 前端整合與設定管理（DS-Online）


| 參數                    | 建議值（實務預設）                          | 最終值                         | Owner Repo  | Owner            | Freeze By |
| --------------------- | ---------------------------------- | --------------------------- | ----------- | ---------------- | --------- |
| Frontend env key（API） | `VITE_AGENT_API_BASE_URL`（依前端框架調整） | `VITE_AGENT_API_BASE_URL`   | `DS-Online` | Frontend TL      | M1 start  |
| Frontend env key（WSS） | `VITE_AGENT_WS_BASE_URL`（若適用）      | `VITE_AGENT_WS_BASE_URL`    | `DS-Online` | Frontend TL      | M1 start  |
| Scheme guard          | 前端啟動時拒收 `http/ws` 設定               | 啟用（build-time + runtime 檢查） | `DS-Online` | Frontend TL      | M1 start  |
| Mixed content UX      | 友善錯誤提示（指向 HTTPS/WSS）               | 啟用，訊息導向 runbook 與設定頁        | `DS-Online` | Frontend TL + UX | M2 start  |


### 5) `WebSlicer_PrinterControl` 介接參數


| 參數                         | 建議值（實務預設）                        | 最終值                                                        | Owner Repo                                     | Owner                           | Freeze By |
| -------------------------- | -------------------------------- | ---------------------------------------------------------- | ---------------------------------------------- | ------------------------------- | --------- |
| 與 agent 的通訊 scheme         | HTTPS/WSS only                   | HTTPS/WSS only                                             | `WebSlicer_PrinterControl` + `web_slicer_core` | PrinterControl TL + Backend TL  | M1 start  |
| 控制監控 callback URL          | 使用可配置 `https://127.0.0.1:<port>` | `https://127.0.0.1:5180`（狀態觸發維持 5181）                      | `WebSlicer_PrinterControl`                     | PrinterControl TL               | M1 start  |
| Port contract（5180/5181 等） | 保持現況或文件化變更                       | 維持 5179(agent), 5180(API), 5181(status)                    | `WebSlicer_PrinterControl` + `Bundle-Launcher` | PrinterControl TL + Launcher TL | M1 start  |
| 與 Launcher 的環境變數鍵名         | 與 Launcher 命名一致，避免雙標準            | `AGENT_API_BASE_URL`, `AGENT_WS_BASE_URL`（由 Launcher 統一注入） | `WebSlicer_PrinterControl` + `Bundle-Launcher` | Launcher TL + PrinterControl TL | M1 start  |


### 6) 驗收與發版門檻（Go/No-Go）


| Gate | 必要條件（全部必須為 Yes）                                     | 狀態   |
| ---- | --------------------------------------------------- | ---- |
| G1   | Safari + Chrome 皆可在 HTTPS 頁面成功呼叫 API                | Open |
| G2   | 若有 WS，Safari + Chrome 皆可 `wss://` 連線                | Open |
| G3   | dev/runtime 與 packaged 兩種模式主流程皆可跑通                  | **Pass**（2026-04：dev + mac 打包安裝包與前端連通已驗） |
| G4   | 首次安裝信任可完成；升級（根 CA 不變）不重複提示                          | **Pass**（產品沿用同一組內嵌 CA／憑證；Launcher 以 bundle 憑證 SHA256 比對略過重複引導。**覆蓋升級** E2E 留待後續補測。） |
| G5   | release note 已標示 BREAKING（`http/ws` -> `https/wss`） | Open |


### 7) 開工前最小決策清單（Meeting Checklist）

- 端點契約已凍結（API/WSS base URL、health、version prefix）
- 憑證封裝型式與檔案佈局已凍結（dev/runtime + packaged）
- 四個 repo owner 與 reviewer 已指派
- 驗收矩陣與 smoke cases 已同意
- M1 scope 與排程（含風險緩衝）已核准

---

## A. `web_slicer_core`（Agent: Python / FastAPI / Uvicorn）

### A-1 TLS 啟動與設定收斂（HTTPS-only）

- 移除或停用對外 `http://` 監聽路徑，預設僅啟用 `https://`.
- 建立統一啟動參數（env / config）：`HOST`、`PORT`、`TLS_CERT_PATH`、`TLS_KEY_PATH`（或 `P12` 對應欄位）。
- 啟動時輸出結構化 log：目前 scheme、host、port、憑證來源（不可輸出私密內容）。

**Definition of Done**

- 在本機以 `curl -k https://127.0.0.1:<port>/health` 可成功回應。
- 以 `http://127.0.0.1:<port>` 連線為「不支援」或明確失敗，不再被視為可用路徑。

**Depends on**

- 憑證材料路徑可用（見 B-1 / B-2 / C-1 / C-2）。

---

### A-2 憑證 SAN 與 loopback 相容性

- 確認伺服器憑證 SAN 至少包含 `127.0.0.1` 與 `localhost`.
- 啟動前加入憑證檢查（啟動時快速 fail-fast）：檔案存在、可讀、格式合法。

**Definition of Done**

- 以 `https://127.0.0.1:<port>` 與 `https://localhost:<port>` 皆可完成 TLS 交握（在已信任前提下）。

---

### A-3（若適用）WebSocket 升級為 WSS

- 盤點現有 WS 端點，將文件化 endpoint 改為 `wss://`.
- 確認 WSS 與 HTTPS 使用同一 TLS 情境（同憑證與可追蹤的埠策略）。

**Definition of Done**

- 從 `https:` 頁面觸發的 WebSocket 能以 `wss://` 完成 upgrade 並收發資料。

## B. `Bundle-Launcher`（Launcher Runtime: `main.cjs`）

### B-1 啟動參數與健康檢查改為 HTTPS

- `main.cjs` 啟動 agent 的命令列參數改為 TLS 版本（憑證路徑、port、host）。
- 連線偵測/health check 從 `http` client 改為 `https`（必要時加入本機 CA/agent CA 信任設定）。
- 啟動失敗錯誤訊息加入 scheme 指引（例如「請檢查 HTTPS 憑證與信任」）。

**Definition of Done**

- Launcher 啟動後，agent 可被 `https://127.0.0.1:<port>` 存取。
- 連線偵測與既有 splash/狀態流程不退化。

---

### B-2 首次安裝信任流程（D5）

- 僅首次安裝觸發 CA 信任引導（有明確使用者確認流程）。
- 升級安裝時，若根 CA 未變，跳過再次提示密碼與重複寫入。
- 失敗處理：權限拒絕、寫入失敗、使用者取消時，回報可操作訊息與診斷碼。

**Definition of Done**

- 首次安裝可完成信任；升級不重複提示（根 CA 不變）。

**實作備註（Launcher）**

- **打包啟動**（`app.isPackaged`）：在啟動後端前顯示**首屏對話框**（僅 **Quit** / **Continue to install**）；**Continue** 後觸發 **macOS** 密碼流程（先 login keychain，必要時 `osascript` + System keychain）或 **Windows UAC**（`certutil -addstore Root`）。憑證指紋寫入 `userData/tls-trust-onboarding.json`（`mode: installed`；舊版曾有 `skipped`）；**bundle 內憑證變更**時會再次引導。
- **開發模式**（`electron .`）：預設不彈窗；可設環境變數 `BUNDLE_FORCE_TRUST_ONBOARDING=1` 測試。
- **選單／Tray**：`Install HTTPS certificate for browsers…` 可強制再次開啟引導（`force: true`）。
- **若要再次看到首屏引導（測試用）**：請**手動刪除** `tls-trust-onboarding.json`。此檔**只有**在曾完成寫入狀態後才會存在（例如按過 **Continue to install** 且安裝流程寫入成功，或舊版曾寫入 `skipped`）；若從未跑到那一步，資料夾裡**本來就不會有這個檔**，屬正常。
  - **最穩的找法（macOS）**：在終端機執行  
    `find "$HOME/Library/Application Support" -name 'tls-trust-onboarding.json'`  
    因為 Electron 的 `userData` 目錄名**不一定**等於 DMG 上的 App 顯示名稱。
  - **macOS（本 repo 實測常見）**：`~/Library/Application Support/bundle-launcher/tls-trust-onboarding.json`（與 `package.json` 的 **`name`: `bundle-launcher`** 一致；**即使**是打包後的「Bundle Launcher.app」也常寫入此目錄）。
  - **macOS（少數環境可能不同）**：若曾見過 `~/Library/Application Support/Bundle Launcher/`，也可一併檢查該資料夾底下是否有同名檔案。
  - **Windows**：在檔案總管或 PowerShell 搜尋檔名 `tls-trust-onboarding.json`，或查看 `%APPDATA%\bundle-launcher\` 與 `%APPDATA%\Bundle Launcher\`（兩種目錄名皆可能，視執行方式而定）。
  - 刪除此檔**不會**從鑰匙圈／Windows 信任庫移除已安裝的憑證。
- 程式：`main.cjs`、`trust-onboarding.cjs`；打包清單已含 `trust-onboarding.cjs`（`electron-builder.yml` / `electron-builder-x64.yml`）。

## C. Packaging / Build Scripts

### C-1 macOS bundle 納入憑證材料

- 更新 `build-scripts/build-mac-bundle.sh`：將 TLS 憑證材料放入固定且可版本控管路徑。
- 打包產物中驗證憑證存在且權限正確（可讀，不暴露不必要權限）。

**Definition of Done**

- `bundle-mac` 與最終 `.app/.dmg` 中 agent 可正常載入憑證並啟動 HTTPS。

---

### C-2 Windows bundle 納入憑證材料

- 更新 `build-scripts/build-windows-bundle.ps1`：同上，確保憑證材料被複製到預期路徑。
- 確認 NSIS 安裝後路徑與 runtime 讀取邏輯一致。

**Definition of Done**

- `bundle-win` 與最終安裝產物中 agent 可正常載入憑證並啟動 HTTPS。

---

### C-3 Electron builder 設定校正

- 檢查 `electron-builder.yml` / `electron-builder.config.cjs` 的 extraResources、asarUnpack 等設定是否涵蓋憑證檔。
- 檢查簽章/公證流程不會遺漏或破壞憑證檔案佈局。

**Definition of Done**

- 打包後首次啟動可直接完成 TLS 啟動，不需人工補檔。

## D. `DS-Online`（Frontend Integration Contract）

### D-1 API/WSS Base URL 規約

- 將前端設定契約統一為 `https://127.0.0.1:<port>` 與（若適用）`wss://127.0.0.1:<port>`.
- 明訂 `http://` / `ws://` 在 HTTPS 頁面情境不支援。

**Definition of Done**

- HTTPS 網頁下不再出現 mixed content caused-by-scheme 的錯誤。

---

### D-2 dev/runtime 與 packaged 一致性驗證

- 建立一份共用測試矩陣，驗證兩種模式使用同一 API 契約與行為。
- 至少驗證：health、核心 API、登入/握手（若有）、WSS（若有）。

**Definition of Done**

- dev/runtime 與 packaged 均可由 HTTPS 前端完整跑通主流程。

**驗收備註（2026-04）：** 已確認本機 dev 與 **macOS 打包安裝包** 均可與前端連線；雲端 HTTPS 前端（`https://safari-mixed-content-local-https.onrender.com`）搭配本機 agent 時，已於 `web_slicer_core` CORS 白名單納入該 origin 並随包驗證通過。

## E. `WebSlicer_PrinterControl`（機台控制監控整合）

### E-1 控制監控通道的 HTTPS/WSS 契約對齊

- 盤點 `WebSlicer_PrinterControl` 與本機 agent 的互動（HTTP API、WebSocket、localhost callback）。
- 若存在 `http://` / `ws://` 寫死路徑，改為可設定且預設 `https://` / `wss://`.
- 與 `Bundle-Launcher` 啟動參數/環境變數命名對齊，避免兩邊各自管理 scheme。

**Definition of Done**

- 與控制監控相關主流程在 HTTPS 頁面下不因 scheme 不一致而失敗。

---

### E-2 與打包產物的整合驗證

- 驗證 `Bundle-Launcher` 打包產物中，`WebSlicer_PrinterControl` 與 agent 串接不受 TLS 導入影響。
- 若涉及跨 process 通訊，確認埠與 URL 契約在 dev/runtime 及 packaged 皆一致。

**Definition of Done**

- 控制監控流程在兩種執行型態皆可正常運作，且無未文件化的通訊行為變更。

**驗收備註（2026-04）：** mac 打包流程與實機啟動後，整體與前端連通測試已通過（與使用者驗收一致）。

## F. QA / Verification（跨 repo）

### F-1 雙瀏覽器 E2E（Safari + Chrome）

- 在兩瀏覽器分別驗證 HTTPS API 通訊成功。
- 若有 WebSocket，兩瀏覽器分別驗證 WSS 通訊成功。

**Definition of Done**

- Safari 與 Chrome 都能在同一 release 上通過相同信任流程並完成通訊。

---

### F-2 非迴歸煙霧（與 spec 對齊）

- splash 流程
- 連線偵測
- 連接埠啟動與監聽
- API 契約一致性

**Definition of Done**

- 無未文件化的行為變更；若有刻意變更，已在 release note 說明。

## G. Docs / Release Notes / Runbook

### G-1 使用者與支援文件

- 更新首次信任流程（macOS + 至少一款 Chromium）。
- 新增故障分流：mixed content vs TLS trust vs CORS.
- 補充「HTTPS/WSS only」與 breaking change 提示。

**Definition of Done**

- 支援人員可依文件快速定位為 scheme 錯誤或憑證信任問題。

---

### G-2 發版公告

- release note 明確標示 BREAKING：`http/ws` -> `https/wss`.
- 提供升級注意事項（根 CA 不變不重複信任；變更時另行公告）。

**Definition of Done**

- 對外敘述與 `proposal.md` / `design.md` / `spec.md` 一致。

## 建議執行順序（Sprint 排程）

1. **A-1, A-2**（先讓 agent HTTPS-only 跑起來）
2. **B-1**（讓 Launcher 能穩定啟動與檢測 HTTPS agent）
3. **C-1, C-2, C-3**（打包路徑打通）
4. **D-1, D-2, E-1**（前後端與控制監控契約對齊）
5. **A-3**（若產品使用 WebSocket）
6. **B-2**（首次信任流程完善）
7. **E-2, F-1, F-2, G-1, G-2**（驗收與發版）

## 里程碑（可直接開票）

- **M1: HTTPS-only core runtime**
  - 完成 A-1, A-2, B-1
- **M2: Packaged connectivity parity**
  - 完成 C-1, C-2, C-3, D-2, E-2
- **M3: Trust onboarding + cross-browser QA**
  - 完成 B-2, F-1, F-2
- **M4: Release readiness**
  - 完成 G-1, G-2（含 breaking note）

## 四個 Repo Sprint 拆票（直接可用）

### Sprint 1（目標：打通 HTTPS-only 主鏈路）

`**web_slicer_core`**

- A-1 TLS 啟動與設定收斂（HTTPS-only）
- A-2 SAN 與 loopback 相容性

`**Bundle-Launcher**`

- B-1 啟動參數與 health check 改 HTTPS
- C-1/C-2 憑證材料進入 mac/win bundle

`**DS-Online**`

- D-1 API/WSS Base URL 規約與 scheme guard

`**WebSlicer_PrinterControl**`

- E-1 通道契約對齊（移除 `http/ws` 寫死）

### Sprint 2（目標：兩種執行型態一致 + 打包可用）

`**web_slicer_core**`

- A-3 WSS（若產品使用 WebSocket）

`**Bundle-Launcher**`

- C-3 builder 設定校正
- B-2 首次安裝信任流程（根 CA 不變升級不重複）

`**DS-Online**`

- D-2 dev/runtime vs packaged 一致性驗證

`**WebSlicer_PrinterControl**`

- E-2 打包整合驗證（跨 process 契約一致）

### Sprint 3（目標：跨瀏覽器驗收與發版就緒）

**Cross-repo QA**

- F-1 Safari + Chrome E2E
- F-2 非迴歸煙霧（splash/偵測/埠/API）

**Docs/Release**

- G-1 使用者與支援文件
- G-2 release note（BREAKING 標示）

---

## 本地啟動順序（One-page Runbook）

目標：在本機以程式碼直接運行（dev/runtime）啟動 `DS-Online` + `web_slicer_core` + `WebSlicer_PrinterControl`，並確認 HTTPS 通訊正常。

**僅開發單一 repo 時：** 不必克隆 `Bundle-Launcher`。憑證可放在各 repo 內固定目錄（見 **0.1**），或一律用環境變數指向任意路徑。下列「Bundle-Launcher/bundle-mac|bundle-win」路徑僅在 **已拉下 Launcher 打包樹** 或 **本機 monorepo 與打包腳本對齊** 時作為便利預設。

### 0) 前提條件

- 已安裝 Node.js、Python 3。
- 已有可用 TLS 憑證一組（**PEM** `localhost.crt` + `localhost.key` 或團隊約定檔名）；放置位置見 **0.1**（**不**強制在 `Bundle-Launcher/...` 下）。
- 瀏覽器（與視需求之 Node）已信任本機憑證；詳見下節 **0.1**。若未信任，瀏覽器會出現 `ERR_CERT_AUTHORITY_INVALID`。

### 0.1) 本機開發：安裝與信任 TLS 憑證

**憑證檔要放哪裡？（擇一即可）**

| 情境 | 建議位置或方式 |
| ---- | -------------- |
| **只 clone `web_slicer_core`** | 將 `localhost.crt` / `localhost.key` 放在 repo 內 **`agent/tls/`**（與 `agent/config.py` 解析順序一致：先環境變數，再此目錄，最後才嘗試相對路徑下的 `../Bundle-Launcher/...`）。或僅設 **`AGENT_TLS_CERTFILE`** / **`AGENT_TLS_KEYFILE`** 指向任意絕對路徑。 |
| **只 clone `WebSlicer_PrinterControl`** | 放在專案根下 **`tls/localhost.crt`**、**`tls/localhost.key`**（`index.js` 會優先找此目錄）；或設 **`BUNDLE_TLS_CERT_PATH`** / **`BUNDLE_TLS_KEY_PATH`**（Launcher 注入名稱），亦可 **`SSL_CERTFILE`** / **`SSL_KEYFILE`**。未設 env 且本機沒有旁邊的 `Bundle-Launcher` 時，**不應**依賴 monorepo fallback。 |
| **已拉下完整 Bundle（含 Launcher）** | 可沿用打包樹 **`Bundle-Launcher/bundle-mac/agent/tls/`** 或 **`bundle-win/.../agent/tls/`**，與建置腳本一致；仍可用環境變數覆寫。 |

**`./scripts/run_agent.sh` 補充：** 腳本內建預設曾寫成相對的 `../Bundle-Launcher/bundle-mac/agent/tls/`。若你**沒有** Launcher 目錄，請在執行前匯出 **`AGENT_TLS_CERTFILE`** / **`AGENT_TLS_KEYFILE`**，或改將憑證放入 **`web_slicer_core/agent/tls/`** 並以團隊慣用之啟動方式載入 `config`（與直接執行 agent 模組行為一致）。

**目標分兩類**

| 目標 | 做法摘要 |
| ---- | -------- |
| **Safari／Chrome** 可直接連 `https://127.0.0.1:5179`（無紅色憑證警告） | 將 **`.crt`** 匯入作業系統信任庫並將 **SSL** 設為信任（見下方 macOS／Windows） |
| **Node**（例如 `curl`、或 Vite `server.proxy` 設 `secure: true`） | Node **不會**自動讀 macOS 鑰匙圈；請使用 **`NODE_EXTRA_CA_CERTS`** 指向 PEM 檔，或維持 dev proxy 的 `secure: false`（僅本機 loopback） |

**macOS（鑰匙圈）**

1. 雙擊 `localhost.crt`，或使用「鑰匙圈存取」→ **檔案** → **輸入項目**，選取該 `.crt`。
2. 建議匯入 **「登入」** 鑰匙圈（全機共用可選 **「系統」**，通常需管理員密碼）。
3. 在鑰匙圈中找到該憑證（名稱常為 `localhost` 或憑證的 Common Name）→ 雙擊 → **信任** → **「使用此憑證時」** 設為 **「永遠信任」**（SSL）。
4. 關閉時儲存變更；必要時輸入登入密碼。
5. 重新開啟瀏覽器分頁後再測 `https://127.0.0.1:5179`。

**Windows**

1. 雙擊 `localhost.crt` → **安裝憑證** → **本機電腦**。
2. 將憑證放入 **「受信任的根憑證授權單位」** 或 **「受信任的發行者」**（依實際憑證鏈為自簽或私有 CA 調整；以憑證用途為準）。

**Firefox**：使用自有憑證庫時，需另外在 Firefox 設定內匯入或設定例外；與 Safari／Chrome 分開處理。

**Node（可選，配合 Vite proxy 驗證 TLS）**

```bash
export NODE_EXTRA_CA_CERTS="/absolute/path/to/localhost.crt"
npm run dev
```

- 自簽 **leaf** 常可將 **同一 `localhost.crt`（PEM）** 作為額外信任檔使用。
- 若改為 **獨立根 CA** 簽發 server 憑證，請將 `NODE_EXTRA_CA_CERTS` 指向 **根 CA 的 `.pem`**，而非僅 leaf。

**快速自測**

```bash
# 不依賴系統信任時，可指定 CA／自簽檔：
curl -v --cacert /path/to/localhost.crt https://127.0.0.1:5179/api/health
```

**產品／法遵脈絡（長文）**

- `Bundle-Launcher/safari-support/https-mixed-content-communication-and-trust.md`（混合內容、信任模型、Launcher 主線）

### 1) 啟動 `web_slicer_core`（HTTPS :5179）

在 `web_slicer_core` 目錄執行：

```bash
./scripts/run_agent.sh
```

驗證：

```bash
curl -sk https://127.0.0.1:5179/api/health
```

預期回應包含 `{"service":"web_slicer_core","status":"running"...}`。

### 2) 啟動 `WebSlicer_PrinterControl`（HTTPS :5180）

在 `WebSlicer_PrinterControl` 目錄執行：

```bash
npm install
npm start
```

說明：`index.js` 優先使用 **`BUNDLE_TLS_CERT_PATH` / `BUNDLE_TLS_KEY_PATH`**（或 **`SSL_CERTFILE` / `SSL_KEYFILE`**）；否則嘗試專案內 **`tls/localhost.crt|key`**；僅在檔案存在時才會 fallback 到相對路徑下的 **`../Bundle-Launcher/bundle-mac|bundle-win/...`**（單獨 clone 本 repo 時請以前兩者為準）。

### 3) 啟動 `DS-Online`（dev server :5173）

在 `DS-Online` 目錄確認 `.env.development`：

- `VITE_AGENT_API_BASE_URL=https://127.0.0.1:5179`
- `VITE_AGENT_UDP_BASE_URL=https://127.0.0.1:5180/api/v1/printers`

啟動：

```bash
npm install
npm run dev
```

### 4) 前端連通驗證

- 打開 `http://localhost:5173`（或 Vite 顯示 URL）。
- DevTools 檢查：
  - `GET https://127.0.0.1:5179/api/health` 成功。
  - Printer/Resin 相關 API 可成功回應（無 CORS/Mixed Content 錯誤）。

### 5) 常見錯誤與處理

- `ERR_SSL_PROTOCOL_ERROR`
  - 後端可能以 HTTP 啟動。請確認 `web_slicer_core` 使用 `./scripts/run_agent.sh` 啟動，而非裸 `uvicorn`。

- `ERR_CERT_AUTHORITY_INVALID`
  - 本機憑證尚未受信任。請依 **§0.1** 將 `localhost.crt` 匯入系統並設為信任 SSL，再重開瀏覽器。若僅 **Node／Vite proxy** 失敗，另設 `NODE_EXTRA_CA_CERTS` 或保留 dev 專用之 `secure: false`（僅 loopback）。

- `No 'Access-Control-Allow-Origin' header`
  - 前端來源與後端 CORS 白名單不匹配。請確認目前前端來源（`http://localhost:5173` 或 `https://localhost:5173`）已在後端允許清單。

- `TLS certificate/key not found`
  - cert/key 路徑不存在。請依 **§0.1**：在 **`web_slicer_core/agent/tls/`** 或 **`WebSlicer_PrinterControl/tls/`** 放置檔案，或設環境變數（**不**必具備 `Bundle-Launcher` repo）：
    - Agent：`AGENT_TLS_CERTFILE`, `AGENT_TLS_KEYFILE`
    - PrinterControl：`BUNDLE_TLS_CERT_PATH`, `BUNDLE_TLS_KEY_PATH`（或 `SSL_CERTFILE`, `SSL_KEYFILE`）
    - Launcher 注入子行程時亦可能使用 `BUNDLE_TLS_CERT_PATH` / `BUNDLE_TLS_KEY_PATH`

---

## Packaged smoke（macOS，不簽章）

### 打包前（建議）

- 將最新 `web_slicer_core/agent` 同步進 `Bundle-Launcher/bundle-mac/agent/`（與 `build-mac-bundle.sh` 一致，避免打包內仍是舊程式）。

```bash
rsync -a --exclude='web/' --exclude='jobs/' --exclude='__pycache__' --exclude='*.pyc' --exclude='.cursor' \
  web_slicer_core/agent/ Bundle-Launcher/bundle-mac/agent/
```

### 打包（不簽章）

`electron-builder.yml` 已設 `mac.identity: null`；建議關閉自動找簽章身分：

```bash
cd Bundle-Launcher
npm install
CSC_IDENTITY_AUTO_DISCOVERY=false npm run build:mac:arm64
```

產物（本次建置實測）：

- `dist/Bundle Launcher-1.0.0-arm64.dmg`（本機 Apple Silicon）
- `dist/Bundle Launcher-1.0.0.dmg`（x64，同一設定會一併產出）
- 解包後：`dist/mac-arm64/Bundle Launcher.app`

建置 log 應出現：`skipped macOS code signing  reason=identity explicitly is set to null`。

### 打包內靜態檢查（可自動化）

確認 `.app` 內含 TLS 材料：

```bash
ls "dist/mac-arm64/Bundle Launcher.app/Contents/Resources/bundle/agent/tls/"
# 應有 localhost.crt、localhost.key
```

### 手動 smoke（安裝／執行後）

- [x] 雙擊啟動 Launcher，系統列圖示出現；無立即 crash。
- [x] `curl -sk https://127.0.0.1:5179/api/health` 回 200 且 JSON 含 `web_slicer_core`。
- [x] `curl -sk https://127.0.0.1:5180/api/v1/health` 回 200（Phrozen Control Server API）。
- [x] 未簽章 app：首次執行若被 Gatekeeper 擋下，屬預期；右鍵開啟或暫時於「隱私權與安全性」放行後再測。
- [x] 與雲端 HTTPS 前端搭配時：瀏覽器需完成憑證信任（與 dev 相同議題）；**雲端頁 ↔ 本機 agent 已驗可連通（含 CORS）。**

### 備註

- 完整 `build-mac-bundle.sh` 會重建 venv、PrusaSlicer、PrinterControl；若僅驗證 Launcher 打包與 HTTPS 路徑，可用既有 `bundle-mac` + 上方 rsync + `npm run build:mac:arm64` 縮短迭代。

