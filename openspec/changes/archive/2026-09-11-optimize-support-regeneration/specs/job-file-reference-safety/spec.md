## ADDED Requirements

### Requirement: `source_job_id` 須通過安全 job id 檢驗

`POST /slices/{job_id}/use-model-from/{source_job_id}` 的 `source_job_id` 參數 SHALL 在被用於組成任何檔案系統路徑之前，通過 `_require_safe_job_id()` 檢驗。

該函式在 `dev` 分支上不存在，本變更 SHALL 一併新增之——見下方「須新增 job id 檢驗函式」需求。

檢驗未通過時，系統 SHALL 回 `JOB_NOT_FOUND`，MUST NOT 存取檔案系統，亦 MUST NOT 於錯誤訊息中回傳任何解析後的路徑。

此檢驗存在的理由：job id 是伺服器產生的字元集受限字串，其中刻意排除的點號、斜線與**反斜線**是關鍵——反斜線不是 URL 的路徑分隔字元，因此形如 `..%5C` 的字串會以單一路徑片段的形式通過路由，接著在 Windows 上被視為目錄分隔字元。

#### Scenario: 合法的 job id 通過檢驗

- **假設** 一個由伺服器產生的 job id（僅含英數字、底線與連字號）
- **當** 呼叫 `use-model-from` 並帶入該 id 作為 `source_job_id`
- **則** 檢驗 SHALL 通過並繼續後續流程

#### Scenario: 含反斜線的 job id 被拒絕

- **當** 呼叫 `use-model-from` 並帶入含反斜線的 `source_job_id`（例如 `..%5Csecret`）
- **則** 系統 SHALL 回 `JOB_NOT_FOUND`
- **且** MUST NOT 對檔案系統進行任何存取

#### Scenario: 含點號的 job id 被拒絕

- **當** 呼叫 `use-model-from` 並帶入含點號的 `source_job_id`（例如 `a.b`）
- **則** 系統 SHALL 回 `JOB_NOT_FOUND`
- **且** MUST NOT 對檔案系統進行任何存取

> **關於含正斜線的字串**：形如 `../../etc` 的 `source_job_id` **不會**到達本端點，因此不適用上述規範。正斜線是 URL 的路徑分隔字元，該字串會使 Starlette 的路由比對不到這條 POST 路由，請求於路由層即被攔下並回 **HTTP 405**（`..%2F..%2F` 形式則回路由層的 HTTP 404），兩者皆不帶結構化錯誤碼。
>
> 此處記錄的是實測結果，非設計意圖：以正斜線字串作為驗收案例會變成在測路由而非測本需求的防禦，且該行為在本變更前後完全相同。真正必須由 `_require_safe_job_id()` 攔下的是**反斜線**（見上一個場景）與**點號**（本場景）——它們都會以單一路徑片段的形式通過路由並實際到達端點。

### Requirement: `source_file` 須通過「檔名對應目錄」的查表，且不得沿用 job id 的檢驗規則

`source_file` 參數 SHALL 以一份模組層級的不可變對應表進行檢驗。該表的鍵為允許的檔名，值為該檔案所屬的子目錄（`input` 或 `output`）。

`source_file` **MUST NOT** 使用 `_require_safe_job_id()` 進行檢驗。該函式的正規表示式為 `^[A-Za-z0-9_-]{1,64}$`，不允許點號，會將 `model.stl` 一併拒絕而使端點失效。兩個參數需要兩套不同的檢驗機制。

查表未命中時，系統 SHALL 回 `VALIDATION_ERROR`，MUST NOT 退回任何預設路徑，亦 MUST NOT 存取檔案系統。

#### Scenario: 表中的檔名解析至正確目錄

- **假設** 對應表中 `model.stl` 對應至 `input`
- **當** 呼叫 `use-model-from` 並帶入 `source_file=model.stl`
- **則** 系統 SHALL 僅存取來源 job 的 `input/model.stl`
- **且** MUST NOT 存取 `output/model.stl`

#### Scenario: 位於 output 的檔名解析至正確目錄

- **假設** 對應表中 `ortho_result.stl` 對應至 `output`
- **當** 呼叫 `use-model-from` 並帶入 `source_file=ortho_result.stl`
- **則** 系統 SHALL 僅存取來源 job 的 `output/ortho_result.stl`

#### Scenario: 不在表中的檔名被拒絕

- **當** 呼叫 `use-model-from` 並帶入任何未列於對應表的 `source_file`
- **則** 系統 SHALL 回 `VALIDATION_ERROR`
- **且** MUST NOT 對檔案系統進行任何存取

#### Scenario: 路徑穿越字串被拒絕

- **當** 呼叫 `use-model-from` 並帶入含路徑分隔字元或相對路徑片段的 `source_file`（例如 `../../../../x.stl`）
- **則** 系統 SHALL 回 `VALIDATION_ERROR`
- **且** MUST NOT 讀取 job 目錄以外的任何檔案

#### Scenario: 檢驗機制不得使 `model.stl` 失效

- **當** 呼叫 `use-model-from` 並帶入 `source_file=model.stl`
- **則** 該請求 SHALL 通過檔名檢驗
- **且** 系統 MUST NOT 因檔名含點號而拒絕該請求

### Requirement: 來源目錄須由對應表明確指定，不得以存在性猜測

檔案路徑 SHALL 完全由對應表指定的子目錄組成。系統 MUST NOT 先嘗試某一目錄、於檔案不存在時再退回另一目錄。

對應表命中但檔案實際不存在時，系統 SHALL 回 `MODEL_NOT_FOUND`，MUST NOT 轉而搜尋其他目錄。

#### Scenario: 對應目錄中檔案不存在時直接回報找不到

- **假設** 對應表中 `model.stl` 對應至 `input`，且來源 job 的 `input/model.stl` 不存在
- **當** 呼叫 `use-model-from` 並帶入 `source_file=model.stl`
- **則** 系統 SHALL 回 `MODEL_NOT_FOUND`
- **且** MUST NOT 嘗試存取 `output/model.stl`

#### Scenario: 引用失敗須為明確的錯誤回應

- **假設** 來源 job 目錄已被清除
- **當** 呼叫 `use-model-from`
- **則** 系統 SHALL 回 `MODEL_NOT_FOUND`
- **且** 呼叫端 SHALL 能據此判定需退回完整上傳

### Requirement: 對應表只得收錄實際存在於磁碟的檔名，端點預設值須指向表中項目

對應表 SHALL 僅收錄實際會被寫入 job 目錄的檔名。僅作為 HTTP 下載檔名、於磁碟上並不存在的名稱 MUST NOT 被收錄。

端點的 `source_file` 預設值 SHALL 為對應表中的項目。

現況中 `use_model_from_job()` 的預設值為 `boolean.stl`，但磁碟上並不存在該檔案——boolean 運算的實際產物為 `output/model_boolean_union.stl`、`model_boolean_difference.stl` 與 `model_boolean_intersection.stl`，`boolean.stl` 僅是 `GET /api/jobs/{job_id}/boolean.stl` 回傳時使用的下載檔名。該預設值因此永遠無法命中任何檔案。

修正此預設值不影響任何呼叫端：`backendService.js` 的 `useModelFromJob()` 一律以查詢參數明確傳入 `source_file`，從不依賴後端預設值；且該函式目前在前端**沒有任何呼叫處**（已於階段 0 全 repo 掃描確認）。

#### Scenario: 不對應任何實體檔案的名稱不得列入對應表

- **當** 檢視對應表的內容
- **則** `boolean.stl` MUST NOT 出現於表中
- **且** 表中每一個檔名 SHALL 對應至一個實際會被寫入該子目錄的檔案

#### Scenario: 端點預設值可被成功解析

- **假設** 一個含有對應表所指定之預設檔案的來源 job
- **當** 呼叫 `use-model-from` 且不帶 `source_file` 參數
- **則** 系統 SHALL 以預設值查表成功並讀取該檔案
- **且** MUST NOT 因預設值不在表中而回 `VALIDATION_ERROR`

#### Scenario: 以明確參數呼叫時行為不變

- **假設** 呼叫端以 `source_file=ortho_result.stl` 明確傳參（`backendService.js` 的 `useModelFromJob()` 即為此形式）
- **當** 來源 job 的 `output/ortho_result.stl` 存在
- **則** 引用 SHALL 成功
- **且** 該呼叫的行為 MUST NOT 因預設值的修正而改變

### Requirement: 須於 `dev` 分支新增 job id 檢驗函式，內容與位置對齊既有實作

`_require_safe_job_id()` 與其正規表示式常數在 `dev` 分支上不存在（僅存在於尚未合併的 `feature/manual-support-click-mode`，commit `3943eaf`）。本變更 SHALL 於 `agent/api_v2.py` 新增之。

新增的內容 SHALL 與 `3943eaf` 逐字元一致，包含說明反斜線攻擊面的註解區塊。註解 MUST NOT 被省略或改寫。

新增的位置 SHALL 與 `3943eaf` 相同：`import re` 置於 `import math` 與 `import shutil` 之間；常數與函式置於 `_require_pending()` 之前。此對齊要求的目的是使該功能分支日後合併回 `dev` 時能自動併入而不產生衝突。

#### Scenario: 函式行為符合既有實作

- **假設** 新增後的 `_require_safe_job_id()`
- **當** 傳入僅含英數字、底線與連字號且長度介於 1 至 64 的字串
- **則** SHALL 原樣回傳該字串
- **且** 傳入任何含點號、斜線或反斜線的字串時 SHALL 拋出 `JOB_NOT_FOUND`

#### Scenario: 註解與正規表示式須完整保留

- **當** 檢視新增後的程式碼
- **則** 正規表示式 SHALL 為 `^[A-Za-z0-9_-]{1,64}$`
- **且** 說明反斜線攻擊面的註解區塊 SHALL 完整存在

#### Scenario: 新增位置須可與功能分支乾淨合併

- **當** 檢視 `agent/api_v2.py` 的 import 區塊
- **則** `import re` SHALL 位於 `import math` 與 `import shutil` 之間
- **且** `_JOB_ID_RE` 與 `_require_safe_job_id()` SHALL 位於 `_require_pending()` 之前
