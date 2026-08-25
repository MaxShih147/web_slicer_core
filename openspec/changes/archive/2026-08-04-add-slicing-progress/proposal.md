## Why

切片是整套流程中最耗時的環節，依模型大小可能耗時數十秒到數分鐘，但目前 Agent 對外**完全不提供進度資訊**——`GET /api/v2/slices/{job_id}` 只回傳 `pending` / `processing` / `completed` / `failed` 四種狀態，前端因而只能顯示不定態跑馬燈，使用者無從判斷「還要等多久」，也無法分辨「正在跑」與「卡死了」。

事實上進度資訊一直都存在，只是被丟棄了：切片引擎 CLI 在 SLA 路徑早已將 `百分比 => 階段標籤` 逐行印到 `stdout`（每行 flush），但 `run_slicing` 使用 `process.communicate()` 一次收完，**只保存 `stderr`，`stdout` 直接丟棄**。本變更要把這條既有訊號接出來並形成 API 契約。

前端的進度條顯示、補間平滑與 UI 呈現由 DS-online 的對應變更負責，本變更**僅涵蓋後端**。

## What Changes

- **切片子進程改為串流讀取**：`run_slicing` 從一次性 `communicate()` 改為並行 drain `stdout` 與 `stderr` 的雙流讀取，即時取得進度事件。`stderr` 落地為 log、退出碼處理、崩潰通知等既有行為完全不變。
- **stdout 進度事件解析**：辨識 CLI 的 `百分比 => 階段標籤` 格式，取出百分比與階段。沿用 `support-generation-error-codes` 已確立的「以 stdout 文字標記為真值來源」既有慣例。
- **階段標籤映射為穩定 Enum**：切片引擎輸出的是英文自然語言標籤，直接外流會讓前端 i18n 綁死在引擎的字串內容上。後端負責將其映射為穩定的 `STAGE_*` Enum，無法識別時降級為通用階段並留下告警記錄，作為映射漂移的偵測手段。
- **新增背景寫檔階段的完成訊號**：切片引擎回報 100% 之後仍會繼續寫出 `.sl1` 與 preview 封存檔，這段期間完全靜默。將封存完成的 stdout 訊號一併納入進度事件，使「引擎自報完成」與「子進程真正完成」成為兩個可區分的里程碑。
- **進度狀態存放於進程內記憶體**：新增模組級的 job 進度字典，不寫入 `status.json`。job 進入終態後清除。
- **`GET /api/v2/slices/{job_id}` 新增 `progress` 欄位**：非破壞性的可選欄位，僅在進度可用時出現；未提供進度的 job（含既有的 pending 分支）維持原有回應形狀。

## Capabilities

### New Capabilities

- `slice-progress-reporting`: 切片進度的擷取、階段語意與對外契約——雙流讀取的死鎖防護與既有行為保全、stdout 進度事件的解析規則、階段標籤到 `STAGE_*` Enum 的映射與未識別降級、進度狀態的存放位置與生命週期（含終態清除順序）、以及 `progress` 欄位在 job 狀態 API 上的出現條件與形狀。

### Modified Capabilities

無。既有 spec 中沒有涵蓋 job 狀態 API 回應形狀或切片子進程執行方式的需求；`support-generation-error-codes` 規範的是 `generate-supports` 的獨立程式路徑，本變更不觸及該路徑，其分類契約不受影響。

## Impact

**受影響程式碼**

- `agent/jobs.py` — `run_slicing()` 的子進程執行方式（`communicate()` → 雙流並行 drain）；新增進度解析、Enum 映射與模組級進度字典。
- `agent/api_v2.py` — `GET /slices/{job_id}` 回應組裝處新增 `progress` 欄位。
- `agent/main.py` — 為 `agent` 套件補上 logging 設定（design D8）。真機驗證時發現 uvicorn 只設定自己的 logger，導致本變更的階段漂移告警與耗時量測在實機上被完全丟棄。

**API 契約**

- `GET /api/v2/slices/{job_id}` 新增可選欄位 `progress`。**非破壞性**：既有欄位語意與型別皆不變，未帶進度的回應與現況完全一致。

**上游依賴**

- 切片引擎 fork（`third_party/prusaslicer_fork`）**零改動**。所需的進度輸出與封存完成訊號都已存在於現行 CLI 行為中，本變更僅消費之，不需重建三平台 binary。
- 但因此對引擎的 **stdout 文字內容產生依賴**。此依賴以「未識別即降級 + 告警記錄」承接，是可接受且可觀測的耦合；同型耦合已存在於 `support-generation-error-codes`。

**跨 repo**

- DS-online 有對應的前端變更消費本契約（進度條、補間平滑、階段文字 i18n、停滯超時）。兩者共用本變更定義的 `progress` 欄位形狀與 `STAGE_*` Enum 集合，**Enum 集合的權威定義在本變更**。

**不在範圍**

- `run_support_generation()` 走同一支 CLI 但不納入本次，支撐預覽維持無進度。
- 切片取消能力（目前 Agent 完全沒有 cancel / terminate 端點）。前端放棄輪詢後子進程仍會跑完，此為既有債，本變更不處理。
