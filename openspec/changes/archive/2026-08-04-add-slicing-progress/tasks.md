> **執行原則**
> 依序執行，**每個子任務完成後立即跑該任務指定的驗證指令**，綠燈才進入下一個子任務。
> 純函式（第 2、3 節）先於有副作用的改動（第 5 節），讓高風險的子進程改動在已被測試包圍的環境下進行。
> 測試環境**未安裝 `pytest-asyncio`**，非同步流程一律以 `asyncio.run()` 同步驅動（沿用 `agent/tests/test_run_prusa_cli_streams.py` 的既有作法）。

## 1. 測試骨架與樣本資料

- [x] 1.1 建立 `agent/tests/test_slice_progress_parse.py`，放入一份取自真實切片的 stdout 樣本常數：含前導對齊空白的進度行、帶尾端句點的階段行、共享前綴的三個階段行、封存完成行、以及數行非進度雜訊。先只寫一個 `assert True` 佔位。
  - 驗證：`pytest agent/tests/test_slice_progress_parse.py -q` 綠燈（確認檔案可被收集）
- [x] 1.2 建立 `agent/tests/test_slice_progress_stage_map.py` 與 `agent/tests/test_slice_progress_store.py` 兩個空殼檔，同樣先放佔位。
  - 驗證：`pytest agent/tests/ -q --collect-only` 能列出三個新檔且無 import 錯誤

## 2. 進度行解析（純函式）

- [x] 2.1 在 `agent/jobs.py` 新增進度行解析函式：輸入單行文字，回傳 `(百分比, 階段標籤)` 或 `None`。先只處理標準格式。
  - 驗證：在 `test_slice_progress_parse.py` 補上標準格式的斷言，`pytest agent/tests/test_slice_progress_parse.py -q` 綠燈
- [x] 2.2 補上前導對齊空白的處理（引擎的百分比為右對齊輸出）。
  - 驗證：新增前導空白樣本的斷言並跑綠
- [x] 2.3 補上行尾字元（`\r\n` / `\n`）的正規化。
  - 驗證：同一行分別以兩種行尾送入，斷言解析結果相同
- [x] 2.4 補上非進度行回傳 `None` 的分支，涵蓋空行、引擎一般訊息、以及形似但不合格式的行。
  - 驗證：逐一斷言回傳 `None`，且函式不拋例外
- [x] 2.5 補上百分比邊界：`0`、`100`、以及三位數以外的異常輸入。
  - 驗證：斷言 `0` / `100` 正常解析，異常輸入回傳 `None`

## 3. 階段標籤映射（純函式 + 契約鎖定）

- [x] 3.1 在 `agent/jobs.py` 定義 12 個階段識別碼常數與「引擎標籤 → 識別碼」映射表，內容依 `specs/slice-progress-reporting/spec.md` 的權威定義表。
  - 驗證：`pytest agent/tests/test_slice_progress_stage_map.py -q`，斷言表內項目數為 **11**（8 個物件步驟 + 2 個列印步驟 + 收尾訊息；`STAGE_ARCHIVED` 由第 4 節的封存訊號產生，不在標籤表內）
- [x] 3.2 實作標籤正規化（統一大小寫、去除尾端標點、收斂連續空白）。
  - 驗證：斷言帶尾端句點的標籤與不帶者正規化後相同
- [x] 3.3 實作映射查詢函式，採正規化後精確比對。
  - 驗證：對 10 個已知標籤逐一斷言映射到正確識別碼
- [x] 3.4 補上共享前綴的反向斷言：三個共享前綴、語意不同的標籤各自映射到自己的識別碼，且**兩兩不相等**。
  - 驗證：斷言通過（這是禁止子字串比對的守門測試）
- [x] 3.5 實作未識別降級：回傳 `STAGE_SLICING` 並發出一筆含原始標籤內容的告警記錄。
  - 驗證：以 `caplog` 斷言告警被記錄且訊息含原始標籤；斷言回傳值為 `STAGE_SLICING`
- [x] 3.6 新增 `agent/tests/test_slice_progress_string_contract.py`，比照既有的 `test_support_string_contract.py`，將映射表的每個引擎標籤**直接對 fork C++ 原始碼**斷言其仍逐字存在（來源：`third_party/prusaslicer_fork/src/libslic3r/SLAPrintSteps.cpp` 的兩張標籤表與 `SLAPrint.cpp` 的完成訊息）。
  - 驗證：全數綠燈。**這是字串漂移的 CI 級防線**——去識別化改造若改動任一標籤，此測試會直接失敗，而非讓映射在執行期默默降級
- [x] 3.7 於同檔補上一則刻意變造的標籤的反向斷言（該變造字串 MUST NOT 存在於原始碼中）。
  - 驗證：斷言通過，證明 3.6 的斷言確實有效而非恆真

## 4. 封存完成訊號

- [x] 4.1 在 `agent/jobs.py` 定義封存完成訊號的辨識規則（來源：`third_party/prusaslicer_fork/src/CLI/ProcessActions.cpp` 中封存匯出後的輸出行）。
  - 驗證：於 `test_slice_progress_parse.py` 斷言該行被辨識，並產生 `(100, STAGE_ARCHIVED)`
- [x] 4.2 將此訊號納入 3.6 的原始碼契約測試。
  - 驗證：`pytest agent/tests/test_slice_progress_string_contract.py -q` 綠燈
- [x] 4.3 斷言階段順序語意：引擎完成行產生 `STAGE_FINALIZING`、封存完成行產生 `STAGE_ARCHIVED`，兩者百分比皆為 100 且**僅以階段區分**。
  - 驗證：斷言兩者百分比相等、階段不等

## 5. 進度儲存與生命週期

- [x] 5.1 在 `agent/jobs.py` 新增模組級進度字典與三個存取函式（設定、讀取、清除）。
  - 驗證：`pytest agent/tests/test_slice_progress_store.py -q`，斷言設定後可讀回、未設定的 job 讀回 `None`
- [x] 5.2 在設定函式中加入單調保護：新百分比低於已記錄值時保留較高值。
  - 驗證：依序送入遞減的百分比，斷言讀回值不下降
- [x] 5.3 確認階段可隨百分比一併更新（單調保護僅約束百分比，不阻擋同百分比下的階段推進）。
  - 驗證：以相同百分比、不同階段送入兩次，斷言階段已更新
- [x] 5.4 補上清除函式的冪等性（清除不存在的 job 不拋例外）。
  - 驗證：連續清除同一 job 兩次，斷言無例外
- [x] 5.5 加入測試間的字典重置 fixture，避免跨測試污染。
  - 驗證：`pytest agent/tests/ -q` 全綠，且任意調換測試順序仍全綠

## 6. 雙流串流讀取（高風險改動）

- [x] 6.1 在 `agent/jobs.py` 新增 `stdout` 逐行讀取的協程：每讀到一行即嘗試解析，成功則寫入進度字典。
  - 驗證：以假的串流物件單測該協程，斷言進度字典依樣本 stdout 逐步更新
- [x] 6.2 新增 `stderr` **分塊**讀取的協程（`read(n)` 迴圈，**不得使用 `readline()` 或 `async for`**），累積為 bytes。
  - 驗證：單測餵入一個長度遠超串流單行上限的單行 bytes，斷言**不拋例外**且內容完整回收
- [x] 6.3 將 `run_slicing()` 的 `process.communicate()` 改為 `asyncio.gather(讀 stdout, 讀 stderr)` 後 `await process.wait()`。
  - 驗證：`pytest agent/tests/test_jobs_sync.py agent/tests/test_job_status_persistence.py -q` 全綠（既有回歸）
- [x] 6.4 確認 `stderr.log` 仍完整落地、退出碼判定與崩潰通知的呼叫時機不變。
  - 驗證：以假子進程模擬非零退出碼，斷言 job 轉 `failed`、錯誤訊息含退出碼與 stderr、崩潰通知被呼叫
- [x] 6.5 新增死鎖回歸測試：假子進程在 `stdout` 產出進度的同時，向 `stderr` 寫入遠超管線緩衝區容量的資料。
  - 驗證：測試在合理時限內完成且不掛起（加上 `pytest-timeout` 或以 `asyncio.wait_for` 自行設限）
- [x] 6.6 確認成功路徑的既有產物解析不變（層數、預估列印時間、樹脂體積）。
  - 驗證：`pytest agent/tests/test_parse_sl1_metadata.py agent/tests/test_prz_print_time.py -q` 全綠
- [x] 6.7 在 `run_slicing()` 的 `finally` 中清除該 job 的進度，並確認清除發生在終態寫入 `status.json` **之後**。
  - 驗證：斷言成功與失敗兩條路徑結束後進度字典皆不含該 job；並斷言終態寫入的呼叫順序早於清除

## 7. API 欄位契約

- [x] 7.1 在 `agent/api_v2.py` 的 `GET /slices/{job_id}` 回應組裝處，於進度可用時附上 `progress` 物件（百分比 + 階段識別碼）。
  - 驗證：新增 `agent/tests/test_slice_progress_endpoint.py`，以 TestClient 斷言執行中的 job 回應含 `progress` 且欄位型別正確
- [x] 7.2 實作進度不可用時**整個省略**該欄位（不得填 `0` / `null`）。
  - 驗證：斷言尚未產生進度的 job 回應中 `"progress" not in data`
- [x] 7.3 確認尚未執行的 job（pending 分支）不受影響。
  - 驗證：斷言 pending 回應不含 `progress`，其餘內容與既有行為一致
- [x] 7.4 既有欄位回歸：狀態、層數、預估列印時間、樹脂體積、支撐結果的名稱／語意／型別皆不變。
  - 驗證：`pytest agent/tests/test_support_status_endpoint.py -q` 全綠，並於新測試中逐一斷言既有鍵仍存在

## 8. 量測記錄

- [x] 8.1 在 `run_slicing()` 中記錄「引擎回報運算完成」的時間點。
  - 驗證：單測斷言該時間點在收到完成行時被設定
- [x] 8.2 於子進程結束時輸出兩個時間點的差值至 log（供前端日後校準封存尾段的進度權重）。
  - 驗證：以 `caplog` 斷言該筆記錄存在且含耗時數值；未出現完成行時不記錄且不拋例外

## 9. 整體驗證

- [x] 9.1 執行後端完整測試套件。
  - 驗證：`pytest agent/tests/ -q` → **470 passed, 2 failed**。兩個失敗**先於本變更即存在**，且已證明與本變更無關：
    - `test_prz_print_time.py::test_6_11_single_normal_layer_full_params`（列印時間 `11.0 vs 14.0`）
    - `test_subprocess_boundary_5_11.py::test_engine_runs_as_separate_process`（環境未安裝 `pytest-asyncio`，`@pytest.mark.asyncio` 無效）
    - 證明：這兩個測試檔**及其受測程式碼**（`agent/prz_encoder.py`、`agent/config.py`）與 HEAD 逐位元相同；本變更只改動 `agent/jobs.py`、`agent/api_v2.py` 與 `agent/main.py`，三者皆非上述測試的相依。
    - 本變更**新增 212 個測試全數通過**，且未使任何既有測試由綠轉紅。以 `--ignore` 排除 6 個新測試檔實測既有基線為 **258 passed, 2 failed**；258 + 212 = 470，失敗數始終維持 2。
- [x] 9.2 以真實 Agent 切一個小模型（3DBenchy 等級），觀察輪詢回應。
  - 驗證：**通過**（5.4MB 模型 / 466 層 / 全程 4.0s，100ms 輪詢）。`percent` 27→100 單調遞增；`stage` 依序為 SLICING → SUPPORT_POINTS → SUPPORT_TREE → SLICING_SUPPORTS → MERGING → RASTERIZING → FINALIZING → ARCHIVED；終態後 `progress` 欄位消失。
- [x] 9.3 以真實 Agent 切一個大型牙科盤（多物件、高層數、**匯入支撐**）。
  - 驗證：**通過**（46MB 模型 + 84MB 匯入支撐 / 632 層 / 全程 30.5s）。無死鎖；`STAGE_SUPPORT_POINTS` 與 `STAGE_PAD` 完全未出現（匯入支撐已強制 `supports_enable=0`／`pad_enable=0`，該兩步空轉），符合預期；percent 單調遞增至 100；終態後欄位消失。
  - **實測時序（供前端校準，回填 10.2）**：
    - 首個進度事件前的靜默 **6.93s**（大型 STL 載入，此期間無 `progress` 欄位）
    - 最長中段停滯 **9.03s**（55% `STAGE_SLICING_SUPPORTS`）
    - 最大瞬時跳躍 **0→27%（0.12s）**
    - 封存尾段 FINALIZING→ARCHIVED **僅 0.45s**（小模型為 0.11s）
- [x] 9.4 舊用戶端相容性檢查：以不讀取 `progress` 欄位的既有前端跑完一趟切片。
  - 驗證：**通過**（經 `DS-online.bat` 啟動完整服務組，人工確認可正常切片，行為與改動前一致）

## 10. 收尾（選配硬化）

- [x] 10.1 評估是否將 `sla_operations._english_locale_env()` 的語系鎖定沿用至切片子進程的環境變數。
  - 驗證：**確認無影響，維持現狀不改動**。結構證據：`I18N::translate()` 在回呼未掛載時原樣回傳，全 repo 唯一的 `set_translate_callback` 在 GUI 模組。實測證據：於 `Chinese (Traditional)_Taiwan / cp950` 環境下的兩趟真實切片映射出 9 個相異且正確的階段識別碼（若語系有影響會全數降級為 `STAGE_SLICING`）。結論已寫入 `design.md` 的 Open Questions。
- [x] 10.2 於 `openspec/changes/add-slicing-progress/design.md` 回填封存尾段的實測耗時區間，供 DS-online 端校準進度權重常數。
  - 驗證：已回填。封存尾段 **0.11s（小模型）/ 0.45s（大型牙科盤）**——遠短於設計時的假設，前端保留的 76→80 四點過於慷慨，可上調至 78–79。同批量測另記錄了兩個對前端更關鍵的數字：**起始靜默 6.93s**、**最長中段停滯 9.03s**、**最大瞬時跳躍 0→27%（0.12s）**。

- [x] 10.3 修正 `agent/main.py` 缺少 logging 設定，導致 `agent.*` 的訊息在實機上被完全丟棄（真機驗證時發現）。
  - 影響：**Task 8.2 的耗時量測與 Task 3.5 的標籤漂移告警在實機上形同無效**——兩者是本設計僅有的執行期可觀測性手段。
  - 作法：只為 `agent` 套件 logger 掛 handler 並設 INFO，不動 root logger（避免第三方 INFO 噪音）；以 handler 存在與否保持冪等。詳見 `design.md` 決策 D8。
  - 驗證：匯入 `agent.main` 前後對比——修正前 INFO 完全消失、WARNING 僅靠 lastResort 露出；修正後兩則皆以 uvicorn 風格輸出。

- [x] 10.4 補上 spec R2 場景「成功切片的產物與統計不變」的單元斷言（封存前 `/opsx:verify` 查出的覆蓋缺口）。
  - 背景：`run_slicing()` 在本變更前**沒有任何測試涵蓋**，成功路徑的 metadata 寫入因此沒有回歸網。原先只有真機一次性觀察（466／632 層正確），非可重複的防線。
  - 作法：新增三條以場景命名的測試——`test_success_path_preserves_metadata_statistics`（斷言 `layer_count` / `estimated_print_time` / `resin_volume_ml` / `error` 確實寫入 `status.json`）、`test_success_path_reports_a_generated_support_mesh`、`test_missing_output_file_is_still_a_failure`（退出碼 0 但無產出檔仍須判失敗）。
  - 驗證：`pytest agent/tests/test_slice_progress_streams.py -q` → 31 passed。spec 的 25 個 Scenario 達成 **25/25 測試覆蓋**。
