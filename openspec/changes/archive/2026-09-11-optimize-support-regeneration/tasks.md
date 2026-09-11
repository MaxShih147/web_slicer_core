> **驗證原則**：每個階段結束前必須通過該階段自己的驗證任務才可進入下一階段。**禁止累積到最後才驗證。**
>
> **階段獨立性**：階段 1、2、3 彼此無相依，可獨立回滾。階段 1 與 2 合併為第一次發布（後端獨立，不需前端配合）；階段 3 可延後。
>
> **測試素材**：六個無效模型案例的位元組皆可於測試中直接建構，不依賴任何外部檔案。效能量測使用 `agent/jobs/9d8deb5c/input/model.stl`（17.64 MB）與 `agent/jobs/5eaafe65/input/model.stl`（0.17 MB）；若檔案已不存在則跳過該量測任務，不得因此阻擋單元測試。
>
> **基準數據**（已於 design D1 實測，各 5 次取中位數）：17.64 MB 模型，`process=True` 為 774.59 ms、`process=False` 為 104.46 ms。

## 0. 前置調查（不得改動任何程式碼）

> **已於 2026-09-09 完成**，結論記錄於 `design.md` 的 Open Question 1（含檔名對應表、`_require_safe_job_id()` 缺席問題、端點無呼叫端的事實更正，以及 `dev` 分支的正確行號對照）。

- [x] 0.1 列出 `use_model_from_job()` 現行所有呼叫端，確認實際傳入的 `source_file` 值有哪些（已知：前端 `backendService.js:159` 的 `useModelFromJob()` 一律明確傳參，預設 `ortho_result.stl`）
- [x] 0.2 對每一個候選檔名，追出實際寫入它的程式碼位置，記錄其所屬子目錄。已確認兩筆：`model.stl` 位於 `input`（`api_v2.py:_save_model_to_job()` 寫入）、`ortho_result.stl` 位於 `output`（`ortho_pipeline.py:713` 與 `:1129` 寫入）
- [x] 0.3 確認 `input/support.stl` 的寫入者與是否需納入對應表（`api_v2.py:execute_slice_job()` 會寫入）
- [x] 0.4 確認端點現行預設值 `boolean.stl` 於磁碟上不存在——實際產物為 `output/model_boolean_{union,difference,intersection}.stl`，`boolean.stl` 僅是 `main.py:1066` 的 `FileResponse` 下載檔名
- [x] 0.5 決定端點新的預設值，並確認變更不影響任何現行呼叫端
- [x] 0.6 **驗證**：產出一份完整的「檔名 → 子目錄 → 寫入者程式碼位置」清單，每一筆都有對應的寫入者。**清單中 MUST NOT 含有任何找不到寫入者的檔名。** 將結論回填至 `design.md` 的 Open Question 1

## 1. `process=False` 與六個無效邊界案例（第一核心改進）

- [x] 1.1 新增測試檔 `agent/tests/test_validate_stl_bytes.py`，建立六個無效模型案例的位元組建構輔助函式：空 bytes、標頭宣告 0 面、宣告 10 面但資料截斷、純亂數位元組、ASCII 空 solid、單一零面積三角面
- [x] 1.2 **先寫測試**：針對現行實作（`process=True`）撰寫六個案例的斷言，記錄每個案例當下的實際行為（前五個攔截並拋 `INVALID_MODEL`、第六個通過）
- [x] 1.3 **驗證**：執行 `python -m pytest agent/tests/test_validate_stl_bytes.py -v`，六個測試全數通過。**此時尚未改動任何實作程式碼——這一步在建立變更前的行為基準線**
- [x] 1.4 修改 `agent/api_v2.py` 的 `_validate_stl_bytes()`，於 `trimesh.load()` 傳入 `process=False`
- [x] 1.5 **驗證**：重新執行 1.3 的同一組測試，六個測試 **必須全數維持通過且行為不變**。任何一個案例的行為改變即代表 `process=False` 不安全，SHALL 立即停止並回報
- [x] 1.6 補上正向案例測試：一份有效的最小二進位 STL SHALL 通過驗證
- [x] 1.7 補上錯誤型別測試：純亂數位元組導致底層拋出非 `ValueError` 的例外時，SHALL 仍被轉換為 `INVALID_MODEL`，MUST NOT 洩漏為未處理的內部錯誤 —— **已由 `test_invalid_model_is_rejected` 涵蓋**：該測試斷言 `code == "INVALID_MODEL"`，而亂數位元組在底層拋出的是 `ModuleNotFoundError`（非 `ValueError`），能斷言到該 code 即證明例外已被收攏轉換。原先另寫的 `test_rejection_never_leaks_internal_exception` 只斷言「有拋 APIError」，嚴格弱於本測試、無法獨立失敗，經 code review 判定為冗餘並移除
- [x] 1.8 **驗證**：執行 `python -m pytest agent/tests/ -v`，確認全套測試無迴歸（特別注意 `test_support_e2e.py`、`test_run_support_generation.py`）—— **結果 652 passed / 7 failed**。7 筆失敗全數為既有問題，以兩種方式獨立確認：(a) `test_prz_print_time`、`test_slice_progress_streams`、`test_subprocess_boundary_5_11` 三個檔案皆未引用 `api_v2`、`trimesh` 或 `_validate_stl_bytes`；(b) 暫時還原 `agent/api_v2.py` 後重跑，失敗清單完全相同（7 failed）。`test_subprocess_boundary_5_11` 的失敗肇因於環境缺少 `pytest-asyncio` 套件，與本變更無關
- [x] 1.9 效能量測：以 `agent/jobs/9d8deb5c/input/model.stl`（17.64 MB）量測改動後的單次驗證耗時，5 次取中位數 —— **實測（暖機一次後）：132.56 / 129.05 / 127.61 / 119.46 / 101.97 ms，中位數 127.61 ms**。量測直接呼叫 `agent.api_v2._validate_stl_bytes()` 本體（非重寫複本），並先斷言原始碼含 `process=False` 以確認受測的是改動後版本。模型 18,492,234 bytes、369,843 個三角面
- [x] 1.10 **驗證**：1.9 的中位數 SHALL 落在 104.46 ms 的合理範圍內（基準的 ±50% 以內）。若明顯偏高，代表改動未生效或環境有其他變因，SHALL 查明後再繼續 —— **通過**。允收區間 52.23 ~ 156.69 ms，實測中位數 127.61 ms 落於區間內。相對 `process=True` 基準（774.59 ms）加速 **6.07x**，單次驗證省下約 647 ms。較 design D1 的 104.46 ms 高約 22%，屬同一量級的機器負載差異（本次量測時機器同時在跑其他工作），非改動未生效——`process=True` 的量級為 774 ms，兩者相差超過六倍，不存在誤判空間

## 2. `use-model-from` 路徑安全防禦與目錄查表（連帶必修）

- [x] 2.1 新增測試檔 `agent/tests/test_use_model_from_job.py`，以 `fastapi.testclient.TestClient` 建立測試骨架（可參考 `agent/tests/test_support_status_endpoint.py` 的既有寫法）
- [x] 2.2 **先寫測試**：`source_job_id` 的三個案例——合法 id 通過；含反斜線的 id 被拒回 `JOB_NOT_FOUND`；含點號的 id 被拒回 `JOB_NOT_FOUND` —— **案例三由 `../../etc` 改為 `a.b`**：正斜線會使 Starlette 路由比對不到該 POST 路由而直接回 405，請求根本到不了 `use_model_from_job()`，用它等於測路由而非測防禦，且修正前後皆不變。含點號的 `a.b` 才會真正進到程式碼且行為會改變（修正前 `MODEL_NOT_FOUND` → 修正後 `JOB_NOT_FOUND`）
- [x] 2.3 **驗證**：執行該測試，確認後兩個案例**目前會失敗**（漏洞尚存）。這證明測試確實有偵測能力，不是空轉 —— **基準線結果：1 passed / 2 failed**。且證實漏洞為真而非理論：在 job 儲存區外放置誘餌檔案後，`..\secret` 修正前回 **HTTP 200 且誘餌被吸收成該 job 的模型**（實際資料外洩），`a.b` 則回 `MODEL_NOT_FOUND`（已進入程式碼並碰觸檔案系統，只是未命中）
- [x] 2.4a **新增** `import re`（置於 `import math` 與 `import shutil` 之間），以及 `_JOB_ID_RE` 常數與 `_require_safe_job_id()` 函式（置於 `_require_pending()` 之前）。內容 SHALL 逐字元對齊 commit `3943eaf`，含說明反斜線攻擊面的 7 行註解
- [x] 2.4b **驗證對齊**：以 `git show 3943eaf:agent/api_v2.py` 取出對應片段，逐字元比對本次新增的內容與位置，確認完全一致（此為日後乾淨合併的前提）—— **PASS**。以程式化方式比對兩個區塊：函式區塊（`# A job id is a server generated token` 起至 `def _require_pending` 前，含註解與空行，16 行）與 import 區塊（`import logging` 起至 `from typing import` 前，含前後文，7 行），兩者皆逐行完全相同
- [x] 2.4c 於 `use_model_from_job()` 對 `source_job_id` 呼叫 `_require_safe_job_id()`
- [x] 2.5 **驗證**：重新執行 2.2 的測試，三個案例全數通過 —— **3 passed**。全套測試同步確認無迴歸：655 passed / 7 failed，7 筆失敗與階段 1 記錄的既有問題完全相同（通過數由 652 增為 655，即本次新增的 3 筆）
- [x] 2.6 依 0.6 的清單，於 `agent/api_v2.py` 建立模組層級的不可變「檔名 → 子目錄」對應表 —— 以 `MappingProxyType` 實作真正不可變的 `_SOURCE_FILE_DIRS`，收錄 1a 建議範圍的六個檔名（`model.stl`、`support.stl` → `input`；`ortho_result.stl`、`model_boolean_{union,difference,intersection}.stl` → `output`）。位置置於 Helpers 區段末端（`_require_completed()` 之後），刻意遠離 `3943eaf` 的修改區以降低合併風險
- [x] 2.7 **先寫測試**：`source_file` 的五個案例——`model.stl` 僅存取 `input/`；`ortho_result.stl` 僅存取 `output/`；不在表中的檔名回 `VALIDATION_ERROR`；路徑穿越字串（如 `../../../../x.stl`）回 `VALIDATION_ERROR`；`model.stl` 不因含點號而被拒 —— 五個案例皆已實作，並強化為**可證偽**的形式：每份檔案在 80 bytes 標頭寫入不同標記，斷言比對的是「讀到的是哪一份」而非僅有狀態碼（僅斷言 200 的話，保留 fallback 的實作一樣會綠）。三點差異：①「僅存取」兩例各在對側目錄放同名誘餌；②穿越案例改用 `../../../loot.stl`（正/反斜線各一），深度經計算對齊 `JOBS_DIR/<job>/output/` 的三層上溯而**確實命中**外部誘餌——原文的四層深度會因「檔案不存在」而非「防禦生效」通過，等於空轉；③「不因含點號被拒」改為對 `_SOURCE_FILE_DIRS` 全部鍵值參數化，同時涵蓋 `model.stl` 並確認表中無「收錄卻拿不到」的死條目
- [x] 2.8 改寫 `use_model_from_job()` 的路徑組成邏輯：以對應表查表決定子目錄，查表未命中回 `VALIDATION_ERROR` 且不存取檔案系統 —— 查表在組成任何路徑前執行，未命中即 `raise validation_error(...)`，因此穿越字串連一次 `Path` 運算都不會發生
- [x] 2.9 **移除** `output/` 找不到就退回 `input/` 的存在性 fallback（`api_v2.py:455-459`）—— 已移除。`source_path` 現由 `get_job_dir(source_job_id) / subdir / source_file` 單一組成，只做一次存在性檢查
- [x] 2.10 **先寫測試**：對應表指向 `input` 但檔案不存在時，SHALL 回 `MODEL_NOT_FOUND`，且 MUST NOT 嘗試存取 `output/` 的同名檔案 —— `test_missing_input_file_does_not_fall_back_to_output`：`output/model.stl` 存在且可讀，`input/model.stl` 不存在，斷言回 `MODEL_NOT_FOUND` 且 `models == []`
- [x] 2.11 **驗證**：執行 `python -m pytest agent/tests/test_use_model_from_job.py -v`，2.7 與 2.10 的所有案例通過 —— **15 passed**（原 3 筆 + 本次 12 筆，含參數化展開）。另補做兩項驗證：
  - **偵測能力基準線**（補足 2.7「先寫測試」的意圖）：暫時將路徑組成還原為舊邏輯後重跑，**5 failed / 10 passed**——失敗者為 `model_stl_reads_input_only`、`unlisted_filename_is_rejected`、`source_file_traversal_is_rejected[forward-slash]`、`[backslash]`、`missing_input_file_does_not_fall_back_to_output`。還原後以 SHA-256 確認 `api_v2.py` 與還原前完全一致。`ortho_result_reads_output_only` 與 `listed_filename_is_not_rejected_for_its_dot` 在舊邏輯下即通過，屬「防禦不得過度收緊」的護欄而非漏洞偵測器
  - **合併衝突模擬**：以 `git merge-file`（base `7258458` = `dev` 與 `feature/manual-support-click-mode` 的 merge-base，theirs = `3943eaf`）模擬三方合併，**rc=0、衝突數 0**。合併結果通過 `ast.parse()` 語法檢查，且同時含兩側成果（`_SOURCE_FILE_DIRS`、`from types import MappingProxyType`、`run_support_points_export`、`write_support_points_input`）。註：首次模擬誤報整檔衝突，原因是 `git show` 輸出為 LF 而工作區檔案為 CRLF；正規化行尾後結果為零衝突。`git diff --numstat` 亦確認本次改動僅 77 增 6 刪，未觸及行尾
- [x] 2.11a **驗證**：全套測試無迴歸 —— **667 passed / 7 failed**，7 筆失敗與階段 1、2 記錄的既有問題完全相同（通過數由 655 增為 667，即本次新增的 12 筆）
- [x] 2.12 依 0.5 的決定修正端點的 `source_file` 預設值，使其指向對應表中的項目（現行的 `boolean.stl` 於磁碟上不存在）—— 已改為 `"model.stl"`。`agent/main.py:1066` 的 `boolean.stl` 為 `FileResponse` 的下載檔名，與本端點無關，未動
- [x] 2.13 **先寫測試**：不帶 `source_file` 參數呼叫時，SHALL 以新預設值查表成功，MUST NOT 回 `VALIDATION_ERROR` —— 兩筆測試：
  - `test_omitted_source_file_uses_the_default`：完全不帶 `source_file` 查詢參數呼叫，斷言 200 且讀到的是 `input/model.stl`（`output/` 放同名誘餌，順帶確認預設值走的是對應表指定目錄而非舊的「先試 output」）
  - `test_default_source_file_is_in_the_lookup_table`：以 `inspect.signature()` 直接斷言函式簽章的預設值屬於 `_SOURCE_FILE_DIRS`。缺陷本質是「預設值與對應表脫節」，在簽章層級釘住可讓日後改動任一邊立即被抓到
- [x] 2.14 **驗證**：執行 `python -m pytest agent/tests/test_use_model_from_job.py -v` 全數通過 —— **17 passed**。並補做兩項驗證：
  - **偵測能力基準線**：暫時將預設值還原為 `boolean.stl` 後重跑，**2 failed / 15 passed**，失敗者正是 2.13 的兩筆。還原後以 SHA-256 確認 `api_v2.py` 與還原前完全一致
  - **全套無迴歸**：**669 passed / 7 failed**，7 筆失敗與前述既有問題完全相同（通過數由 667 增為 669）
  - **合併衝突模擬**（行尾正規化為 LF 後）：base `7258458` / theirs `3943eaf`，**rc=0、衝突數 0**，且合併結果保有新預設值
- [x] 2.15 **驗證**：以 `TestClient` 直接測試端點——建立來源 job 與其 `output/ortho_result.stl`，以 `source_file=ortho_result.stl` 呼叫，確認引用成功。**不執行 ortho 端到端流程**：階段 0 已確認 ortho 並未使用此端點（`useModelFromJob()` 在前端無任何呼叫處），原任務的前提不成立 —— 由既有兩筆測試涵蓋，未另寫重複測試：
  - `test_legal_job_id_is_accepted`：`_make_source_job()` 建立 `output/ortho_result.stl`，以 `source_file=ortho_result.stl` 呼叫，斷言 200、`success is True`、`data.sourceJobId` 正確、`models` 長度為 1
  - `test_ortho_result_reads_output_only`：同一條路徑再加上 `input/` 同名誘餌，斷言讀到的位元組確為 `output/` 那一份

> **待辦（不屬本階段範圍）**：`DS-Online/api/slicing_core.md:439` 仍記載 `source_file` 預設值為 `boolean.stl`，且未列出新增的 `400 VALIDATION_ERROR`。design.md 1a 已載明該文件 SHALL 一併更新；因位於另一個 repo 且不在任務 2.12~2.15 範圍內，本次未動

## 3. 條件式跳過驗證的旗標機制（第二階段加分項）— **[已延後]**

> **[已延後]**（決策依據：實測效益 104 ms 低於 300 ms 門檻，且階段 1 已達 1294 ms 核心戰果，待後續多分支呼叫點穩定後再另案評估）
>
> 以下任務**維持未勾選且不執行**，保留內容供日後另案評估之用。
>
> **本次跨分支調查的補充事實（2026-09-09，基準 `dev` HEAD `55d2ec9` 對 `feature/manual-support-click-mode`）：**
>
> - **衝突風險並非延後的理由——實測為零。** 逐字比對確認該分支對 `_save_model_to_job()`、`upload_model_file()`、`add_models_to_slice_job()`、`_validate_stl_bytes()` 四個函式**完全未修改**（本體位元組相同），最近的改動距離為 7～27 行。進一步將階段 3 的擬議改動（3.4 的旗標標記與 3.5 的條件式驗證）套用後以 `git merge-file` 模擬三方合併（base `7258458`），結果 **rc=0、衝突數 0**
> - **延後的真正理由是投報率。** 先前決定延後前端 SHA-256 快取時採用的門檻為「剩餘效益低於 300 ms 即延後」（該項為 175 ms）。階段 3 的 104～127 ms 低於同一門檻，且僅為階段 1 已取得成果（單次支撐生成約 1294 ms）的一成，卻需 13 項任務並觸及全檔最常被合併的函式
> - **⚠ 日後重啟時必須先重算呼叫點。** 該分支新增 8 個端點，其中一個會呼叫 `_save_model_to_job()`，合併後落地呼叫點將由 **5 個增為 6 個**。任務 3.6 的稽核清單屆時需一併更新。所幸 fail-safe 語意（僅明確為真才跳過）使新呼叫點自動走驗證，設計本身不需改動
> - **本結論僅適用於當時的分支快照。** 兩側分支皆仍活躍（後端最後 commit 距調查時 23 小時、前端 2 天），重啟前應重跑合併模擬

- [ ] 3.1 **先寫測試**：於 `agent/tests/test_validate_stl_bytes.py` 新增 fail-safe 語意測試——model dict 缺少已驗證旗標時，落地 SHALL 執行驗證
- [ ] 3.2 **先寫測試**：透過 `POST /slices/{job_id}/models` 加入的無效 STL，落地時 SHALL 被攔截並拋 `INVALID_MODEL`，且 MUST NOT 寫入磁碟
- [ ] 3.3 **驗證**：執行測試，確認 3.1、3.2 在現行實作下即通過（現況是無條件驗證，本來就會攔截）。這建立了「改動後不得退步」的基準線
- [ ] 3.4 於 `upload_model_file()` 驗證成功後，於 append 的 model dict 標記已驗證旗標
- [ ] 3.5 於 `_save_model_to_job()` 改為條件式驗證：旗標為真才跳過，其餘一律驗證
- [ ] 3.6 確認 `add_models_to_slice_job()`（`api_v2.py:353`）與 `use_model_from_job()`（`:467`）**皆未**標記該旗標
- [ ] 3.7 **驗證**：重新執行 3.1、3.2 的測試，必須全數維持通過。任何一項失敗即代表 fail-safe 語意破損，SHALL 立即停止
- [ ] 3.8 **先寫測試**：上傳一份有效 STL 後觸發落地，斷言 `_validate_stl_bytes()` 僅被呼叫一次（以 mock 或計數器驗證）
- [ ] 3.9 **驗證**：執行 3.8，確認重複解析確實已被消除
- [ ] 3.10 **先寫測試**：引用進來的模型（`use-model-from`）於落地時 SHALL 仍執行驗證，MUST NOT 因來源位於伺服器磁碟而跳過
- [ ] 3.11 **驗證**：執行 3.10 通過
- [ ] 3.12 **驗證**：檢視任一已完成 job 的 `status.json`，確認其中 MUST NOT 含有任何表示模型已驗證的欄位（旗標不得落地）
- [ ] 3.13 **驗證**：執行 `python -m pytest agent/tests/ -v`，全套測試無迴歸

## 4. 端到端驗證與收尾

- [x] 4.1 以 17.64 MB 的真實牙模，於瀏覽器開啟 `localStorage.bgProfile='1'` 重跑支撐生成三次，取中間一次的數字 —— **完成**。三次實測（`ensureSupportJob` / `generateSupports`）：

  | Run | `ensureSupportJob` | `generateSupports` |
  | --- | --- | --- |
  | 1 | 331.4 ms | 172.2 ms |
  | 2 | 254.0 ms | 128.4 ms |
  | 3 | **291.9 ms** | **140.9 ms** |

  兩項指標的中位數皆落在 Run 3，故以 Run 3 為代表值。三次全距 77.4 ms，即中位數本身帶約 ±40 ms 的量測雜訊，下方的「與預測吻合」不應解讀為毫秒級精度。
- [x] 4.2 **驗證**：`generateSupports (trigger)` SHALL 由 714.9 ms 明顯下降（階段 1 之後預期約 140 ms；階段 3 之後預期約 30 ms）—— **通過**。714.9 → **140.9 ms**，省 **574.0 ms**（降幅 80.3%）。階段 1 的預測值為「約 140 ms」，實測 140.9 ms
- [x] 4.3 **驗證**：`ensureSupportJob (createJob + uploadModel)` SHALL 由 855.8 ms 明顯下降（階段 1 之後預期約 290 ms）—— **通過**。855.8 → **291.9 ms**，省 **563.9 ms**（降幅 65.9%）。階段 1 的預測值為「約 290 ms」，實測 291.9 ms
- [x] 4.4 **驗證**：DevTools Network 的 `upload` 請求 TTFB SHALL 由 704.56 ms 明顯下降 —— **通過**。704.56 → **112.92 ms**，省 **591.64 ms**（降幅 84.0%）。同次量測的傳輸時間為 157.75 ms（原 121.51 ms，+36.24 ms，屬網路／機器雜訊，本變更未觸及傳輸路徑）。

  ⚠ **瓶頸已翻轉**：上傳請求原本是「TTFB 704.56 ms ≫ 傳輸 121.51 ms」（伺服器端主導），現在是「傳輸 157.75 ms > TTFB 112.92 ms」（網路主導）。伺服器端已無明顯可再壓縮的空間，這也是判斷暫緩項目的關鍵依據（見 design.md Open Question 2）
- [x] 4.5 **驗證**：產出的支撐網格與變更前一致——同一份模型、同一組參數，`support.stl` 的 SHA-256 SHALL 不變 —— **通過，SHA-256 逐位元組相同，無需退回幾何不變量比對**

  **比對標的**：引擎產物 `output/model_support.stl`（非 `input/support.stl`——後者是「上傳的支撐檔」，屬不同語意）。

  **方法**：以 `agent/jobs/9d8deb5c/input/model.stl`（18,492,234 bytes、369,843 面）與同一組參數（`{"supports_enable": True}` 經 `_convert_v2_config_to_sla()`，即端點實際使用的路徑）跑三次 `generate_supports()`。**未修改任何專案檔案**：改動前的行為是在驗證行程內包裝 `trimesh.load` 強制 `process=True`，讓正式的 `_validate_stl_bytes()` 以舊參數實際執行。

  | run | 條件 | `_save_model_to_job()` 耗時 | `model_support.stl` SHA-256 |
  | --- | --- | --- | --- |
  | run1_new | 現行（`process=False`） | 125.1 ms | `478533ae…5ca89e45` |
  | run2_new | 現行（`process=False`） | 121.1 ms | `478533ae…5ca89e45` |
  | run3_old | 模擬改動前（`process=True`） | **645.0 ms** | `478533ae…5ca89e45` |

  三者輸出皆為 2,627,284 bytes，SHA-256 完全相同（`478533aeea7c57cb11c5279ccbb717e34c486733db3c551a81e4d1a95ca89e45`）。

  - **引擎確定性成立**（run1 == run2）：同輸入連跑兩次逐位元組相同，面順序不浮動，因此 SHA-256 是有效的判準
  - **改動前後一致**（run1 == run3）：`process` 參數不影響支撐產出
  - **run3 的 monkeypatch 確實生效**，不是空跑：`_save_model_to_job()` 耗時 645.0 ms vs 現行的 121～125 ms，相差逾 5 倍，與階段 1 量到的 774 ms / 127 ms 同一量級
  - **落地位元組保真度**（三次皆通過）：`_save_model_to_job()` 寫入 `input/model.stl` 的內容與傳入的 `stl_data` SHA-256 相同。這是上述結果的結構性成因——`_validate_stl_bytes()` 解析出的網格是區域變數、用完即丟，寫入磁碟的是原始 bytes，因此 `process` 不可能改變引擎的輸入
  - 驗證於暫存目錄執行，`git status` 確認專案與 `agent/jobs/` 均未被污染
- [x] 4.6 將 4.1～4.4 的實測數字回填至 `design.md` 的 Open Question 2，作為「暫緩項目（前端 SHA-256 快取）是否值得重啟」的判斷依據 —— **完成**，全文見 design.md Open Question 2（2a、2b）。結論：**實測 `ensureSupportJob`（291.9 ms）與 `generateSupports`（140.9 ms）與階段 1 預測高度吻合，單次生成立省約 1138 ms；確認暫緩項目（前端 SHA-256 快取）無需重啟。**

  判斷依據：瓶頸已由伺服器端翻轉為網路端（變更前 TTFB 704.56 ≫ 傳輸 121.51；變更後傳輸 157.75 > TTFB 112.92）。前端快取的效益上限等於上傳請求的剩餘總成本 `157.75 + 112.92 = 270.67 ms`，低於 300 ms 門檻。

  ⚠ 已於 design.md 註記這是**接近門檻的判斷**（與 300 ms 僅差約 29 ms，門檻若訂 250 ms 即會翻轉），且其中 157.75 ms 為本變更無法觸及的傳輸時間；模型尺寸若顯著增大應重新評估
- [x] 4.7 掃描 `agent/` 其餘模組是否存在同型問題（其他使用 trimesh 預設參數的熱路徑，特別是 `ortho_pipeline.py`），將發現回填至 `design.md` 的 Open Question 3。**本次不修，僅記錄** —— 已完成，全文回填於 design.md Open Question 3（3a～3f）。摘要：
  - **有，且規模大於預期。** 同一份 17.64 MB 牙模實測 `trimesh.load()` 預設 **641.24 ms** vs `process=False` **86.13 ms**，加速 7.4 倍、單次省約 555 ms
  - ⚠ **但不可比照階段 1 直接套用**：頂點數由 184,920（合併）變為 1,109,529（未合併），差 6 倍。階段 1 的函式只判斷「可否解析／面數是否為零」，兩者皆不受影響；下列呼叫點則真的使用幾何，未合併的三角湯不具水密性
  - **最大宗為 `sla_operations.py:104` `load_trimesh()`**，共 8 個呼叫點（`api_v2.py` 5 處、`ortho_pipeline.py` 3 處），下游涵蓋挖空、蜂巢格、排水孔、切割
  - 其餘：`sla_operations.py:1924/:1927`（布林，很可能必須合併）、`ortho_pipeline.py:557`（疑似與其後的清理流程重複合併）。`auto_orient_surg_guide.py:1104` 位於 `__main__` CLI 區塊，非伺服器路徑，不計入
  - **專案內已有現成解法**：`boundary_detection.py:602-624` 早已獨立解決同一問題（其註解即記載「~50x faster than trimesh.load's default process=True path」），做法是以 numpy 讀出 `process=False` 的三角湯、把合併移為下游明確的 `clean_mesh()` 步驟
  - **建議另案處理**：效益雖遠超 300 ms 門檻，但會改變網格拓撲，需為 8 個以上呼叫點逐一建立幾何正確性基準線，塞進本變更會破壞「每階段都有即時驗證」的結構
- [x] 4.8 **驗證**：執行 `openspec validate optimize-support-regeneration`，確認變更文件與規格一致 —— **通過**。輸出 `Change 'optimize-support-regeneration' is valid`，**exit 0**
