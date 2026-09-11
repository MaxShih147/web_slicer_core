## Why

調整支撐參數是使用者在支撐編輯流程中的高頻操作。每按一次「產生支撐」，同一份模型都會被後端完整解析兩次，等待時間直接放大使用者的迭代成本。

### 實測證據

測試模型為一份牙科模型，上傳酬載 `Content-Length` 為 **18,492,431 bytes**，其中 18,492,234 bytes 為 STL 本體（17.64 MB），另 197 bytes 為 multipart 外框。

以 `localStorage.bgProfile='1'` 量測單次支撐生成的五個階段：

| 階段 | 耗時 |
| --- | --- |
| `ensureSupportJob (createJob + uploadModel)` | 855.8 ms |
| `updateJobConfig` | 29.6 ms |
| `generateSupports (trigger)` | 714.9 ms |
| `pollJobUntilComplete` | 3531.8 ms |
| `getSupportStl (download)` | 53.7 ms |

`updateJobConfig` 僅更新一個記憶體 dict，其 29.6 ms 即為單次 HTTP 來回的基準成本。以此為基準線，`ensureSupportJob` 與 `generateSupports` 各自多出約 700 ms，而兩者共通的重活只有一項：`_validate_stl_bytes()` 內的 `trimesh.load()`。

DevTools Network 面板的 Timing 分解證實了這項推論：

- **TTFB（伺服器端處理）：704.56 ms — 佔 85%**
- **網路傳送（Content Upload）：121.51 ms — 佔 15%**

### 根因：驗證用錯了工具

`_validate_stl_bytes()` 的語意只有兩項判定——「能不能解析成 STL」與「是不是空網格」。但它使用 `trimesh.load()` 的預設參數，而 trimesh 預設執行 `process=True`，會額外進行頂點合併等幾何處理。**這些處理對上述兩項判定沒有任何貢獻，卻佔據了絕大部分耗時。**

以同一份 17.64 MB 模型實測（各 5 次取中位數）：

| 寫法 | 17.64 MB | 0.17 MB |
| --- | --- | --- |
| `process=True`（現況） | **774.59 ms** | 4.90 ms |
| `process=False` | **104.46 ms** | 1.15 ms |
| 加速倍率 | **7.42x** | 4.24x |

實測的 774.59 ms 與前端量到的 704.56 ms TTFB 高度吻合，交叉驗證了根因判定。

安全性同步驗證：六個無效模型案例（空 bytes、標頭宣告 0 個三角面、資料截斷、純亂數位元組、ASCII 空 solid、零面積三角面）在兩種寫法下的攔截行為**完全一致**。`len(mesh.faces) == 0` 的檢查在 `process=False` 下依然精準。

### 效益量級

| 做法 | 每次生成的解析總時間 | 相對現況省下 |
| --- | --- | --- |
| 現況（2 次 × 774.59） | 1549 ms | — |
| **`process=False`（2 次 × 104.46）** | **209 ms** | **1340 ms** |
| `process=False` + 去除重複解析（1 次） | 104 ms | 1445 ms |
| 僅去除重複解析（1 次 × 774.59） | 775 ms | 775 ms |

**改一個參數所省下的時間，比整套「避免重複解析」的機制多出 565 ms。** 這決定了本變更的優先順序。

## What Changes

### 第一核心改進：`_validate_stl_bytes()` 改用 `process=False`

- `_validate_stl_bytes()` 內的 `trimesh.load()` SHALL 明確傳入 `process=False`。
- 該函式對外的判定語意與錯誤型別 MUST NOT 改變：無法解析或空網格仍拋 `INVALID_MODEL`。
- 此改進對**每一次**模型驗證生效，涵蓋上傳、落地、以及 boolean 運算的 `mesh_a` / `mesh_b` 驗證。不需前端任何配合。

### 連帶必修：`use-model-from` 的路徑穿越漏洞

- 本變更 SHALL 於 `agent/api_v2.py` **新增** `_require_safe_job_id()` 函式與 `_JOB_ID_RE` 常數，並新增 `import re`。該函式在 `dev` 分支上不存在（僅存在於尚未合併的 `feature/manual-support-click-mode`，commit `3943eaf`），故無法沿用。新增的內容 SHALL 與 `3943eaf` 完全一致（含註解、正規表示式 `^[A-Za-z0-9_-]{1,64}$`、`import re` 的位置），以確保該分支日後合併時可乾淨併入。
- `use_model_from_job()` 的 `source_job_id` SHALL 通過上述 `_require_safe_job_id()` 檢驗。目前該參數未經任何驗證即進入 `get_job_dir()`。
- `source_file` SHALL 通過**獨立的檔名對應表**檢驗。**MUST NOT 沿用 `_require_safe_job_id()`** —— 該正規表示式不允許句點，會將 `model.stl` 一併拒絕而使端點失效。
- 該端點「先找 `output/`、找不到再退回 `input/`」的隱含 fallback SHALL 改為由對應表明確指定。

此項與效能無關，是獨立的安全缺陷，本次一併修復。

### 第二階段加分項：去除重複的模型解析

- `_save_model_to_job()` SHALL 改為條件式驗證，僅在模型位元組尚未被驗證時才解析。
- 已驗證的宣告 SHALL 掛在 model dict 上，採 fail-safe 預設：**旗標缺席一律視為未驗證**。
- 額外效益約 104 ms（在 `process=False` 之後）。因其需觸及三個模型進入點與五個落地呼叫點，投報率明顯低於第一核心改進，故列為第二階段。

### 暫緩：前端 SHA-256 快取與 `use-model-from` 引用（原「做法甲」）

本項**移出本次範圍**，列為未來評估。

理由：在 `process=False` 上線後，該優化的剩餘價值降至約 175 ms——低於先前訂定的 300 ms 決策門檻。

```
修復後的 ensureSupportJob = 60 ms 來回 + 121.51 ms 傳輸 + 104.46 ms 解析 ≈ 286 ms
改用引用後               = 60 ms 來回 + 磁碟讀取                        ≈ 110 ms
──────────────────────────────────────────────────────────────────────────────
剩餘可省                                                                ≈ 175 ms
```

它同時是整個構想中最複雜的部分：跨兩個 repo、需要前端雜湊快取與 LRU 汰換、需要 fallback 自我修復機制、需要前後端同步發布。**以 175 ms 的收益承擔這些成本不划算。**

本次僅專注於後端高投報率範圍。待 `process=False` 上線並重新量測後，再決定是否推進。相關的技術分析已完整保留於 `design.md` 的「暫緩項目」章節，未來評估時可直接沿用。

## Capabilities

### New Capabilities

- `model-upload-validation`：定義模型位元組的驗證契約——驗證的判定語意（可解析、非空網格）、驗證方法 MUST NOT 執行與判定無關的幾何處理、驗證在何處執行、以及同一份位元組不得被重複解析的責任邊界。
- `job-file-reference-safety`：定義 `use-model-from` 端點的路徑參數驗證契約，涵蓋 job id 檢驗、檔名對應目錄的查表機制，以及禁止目錄猜測式 fallback。

### Modified Capabilities

（無。既有 spec 中沒有涵蓋模型上傳驗證或 job 間檔案引用的需求。）

> 註：既有的 `support-point-model-fingerprint` 是 C++ 引擎端、供支撐點清單交換使用的幾何指紋，其規格明確要求「MUST NOT 以上傳檔案的位元組雜湊作為指紋」且必須不受排版影響。若未來推進暫緩項目，其 SHA-256 用途與該指紋完全不同——它識別的是「同一份上傳酬載」，且必須對任何變換敏感。兩者互不取代、互不衝突，實作時不得混用。

## Impact

### 後端（`web_slicer_core`）—— 本次的程式碼改動範圍

- `agent/api_v2.py`
  - `_validate_stl_bytes()` —— 傳入 `process=False`（第一核心改進）
  - **新增** `_require_safe_job_id()` 與 `_JOB_ID_RE`，並新增 `import re`（內容與位置對齊 commit `3943eaf`）（連帶必修）
  - `use_model_from_job()` —— 補上 `source_job_id` 與 `source_file` 的路徑驗證；以對應表明確指定來源目錄；預設值由不存在的 `boolean.stl` 改為 `model.stl`（連帶必修）
  - **新增** `_SOURCE_FILE_DIRS` 對應表（`MappingProxyType`，收錄六個實際存在於磁碟的檔名）
- `agent/tests/test_validate_stl_bytes.py`（新增）、`agent/tests/test_use_model_from_job.py`（新增）

### 前端（`DS-Online`）

**程式碼無任何改動。** 第一核心改進與安全修復皆為後端內部行為，對現有前端完全向下相容。

**僅同步修訂 API 文件** `DS-Online/api/slicing_core.md`（`use-model-from` 該列）：`source_file` 預設值由 `boolean.stl` 更正為 `model.stl`，錯誤碼補上 `400 VALIDATION_ERROR`，並將「output/input file」的敘述改為白名單查表的實際行為。此為文件與後端行為的同步，不涉及任何前端程式碼。

### 不在本次範圍

- **條件式跳過驗證的旗標機制（原規劃的第二階段，已延後）。** 原本規劃於 `agent/api_v2.py` 改動兩處——`_save_model_to_job()` 改為條件式驗證、`upload_model_file()` 於驗證成功後標記模型為已驗證——以消除同一份位元組的重複解析。**本次不實作**，`tasks.md` 的階段 3 全數維持未勾選並標記為「[已延後]」。

  決策依據：實測效益約 104～127 ms，低於本變更延後前端快取時所採用的 300 ms 門檻，且僅為第一核心改進已取得成果（單次支撐生成約 1138 ms）的一成。跨分支調查另確認衝突風險為零，但 `feature/manual-support-click-mode` 合併後 `_save_model_to_job()` 的落地呼叫點將由 5 個增為 6 個，宜待呼叫點穩定後另案評估。技術分析完整保留於 `design.md` 的 D3、D4 與 `tasks.md` 階段 3。
- 前端 SHA-256 快取與 `use-model-from` 引用（見上方「暫緩」說明）。
- `backend1_rest_api_redesign.md` §9 的三項根治建議（config 落地、移除 short-circuit、重設 `has_support_mesh`）。
- job id 僅 8 個十六進位字元（32 bits）且無任何目錄清理機制所導致的碰撞風險。
- `STLExporter.parse()` 在前端主執行緒的轉檔成本。
- `pollJobUntilComplete` 的 3531.8 ms —— 該時間屬 C++ 引擎的幾何運算，非本變更可觸及。

### 預期效益

以實測的 17.64 MB 模型計算，單次支撐生成可省約 1340 ms（第一階段）至 1445 ms（含第二階段）。此節省隨模型大小線性成長，且**每一次生成都生效，包含第一次**。
