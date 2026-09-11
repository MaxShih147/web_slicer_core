## Context

支撐生成的後端流程位於 `web_slicer_core/agent`，負責接收前端上傳的 STL、驗證、落地為 `input/model.stl`，再交給 C++ 引擎。

實測顯示，單次支撐生成中約 1549 ms 花在同一份 17.64 MB 的 STL 被 `trimesh` 完整解析兩次。而這兩次解析中，絕大部分的工作對驗證目的沒有任何貢獻。

設計此變更前，必須先釐清後端現況的三個結構事實，它們直接決定可行的實作邊界與優先順序。

### 事實一：`_validate_stl_bytes()` 做的事遠多於它需要做的事

該函式的判定語意只有兩項：「能不能解析成 STL」與「是不是空網格」。但它使用 `trimesh.load()` 的預設參數，而 trimesh 預設執行 `process=True`——包含頂點合併等幾何處理。

實測（同一份 17.64 MB 模型，各 5 次取中位數）：

| 寫法 | 中位數 | 五次原始值 |
| --- | --- | --- |
| `process=True` | 774.59 ms | 774.6 / 809.2 / 590.6 / 812.6 / 727.7 |
| `process=False` | 104.46 ms | 104.5 / 111.0 / 97.8 / 107.2 / 103.3 |

**加速 7.42x，單次解析省下 670 ms。** 前端量到的 704.56 ms TTFB 與 774.59 ms 高度吻合，交叉驗證了根因判定。

安全性同步驗證，六個無效模型案例在兩種寫法下攔截行為完全一致：

| 案例 | `process=True` | `process=False` | 一致 |
| --- | --- | --- | --- |
| 空 bytes | 攔截 | 攔截 | ✅ |
| 標頭宣告 0 個三角面 | 攔截 | 攔截 | ✅ |
| 宣告 10 面但資料截斷 | 攔截 | 攔截 | ✅ |
| 純亂數位元組 | 攔截 | 攔截 | ✅ |
| ASCII STL 空 solid | 攔截 | 攔截 | ✅ |
| 單一零面積三角面 | 通過 | 通過 | ✅ |

`len(mesh.faces) == 0` 的檢查在 `process=False` 下依然精準。

### 事實二：模型有三個進入點，其中兩個不驗證

模型位元組進入 `_pending_jobs[job_id]["models"]` 的路徑共三條：

| 進入點 | 位置 | 是否驗證 |
| --- | --- | --- |
| `upload_model_file()` | `api_v2.py:392` | ✅ 驗證（第 389 行） |
| `add_models_to_slice_job()` | `api_v2.py:353` | ❌ **完全不驗證** |
| `use_model_from_job()` | `api_v2.py:467` | ❌ 不驗證 |

`POST /slices/{job_id}/models` 直接把請求 body 的 dict 展開後塞進清單，沒有任何檢查。

### 事實三：`_save_model_to_job()` 是唯一的匯流點

該函式被**五個**端點呼叫（`api_v2.py` 第 501、551、588、630、1661 行），涵蓋 execute、generate-supports、generate-hollow、cut、ortho-process。（先前記載的第六個呼叫點屬 export-support-points 端點，該端點僅存在於尚未合併的 `feature/manual-support-click-mode`。）它是所有模型位元組落地為 `input/model.stl` 的唯一出口，也是目前唯一能保證「不論從哪個進入點來都會被驗證」的地方。

**這使得「直接刪掉 `_save_model_to_job()` 內的驗證」成為一個會開洞的做法**：`add_models_to_slice_job()` 的路徑將完全失去驗證。

## Goals / Non-Goals

**Goals:**

- 模型驗證 SHALL 只執行與判定目的相關的工作，MUST NOT 執行與判定無關的幾何處理。
- 驗證的對外判定語意與錯誤型別 MUST NOT 改變。
- 所有模型進入點的驗證覆蓋率 MUST NOT 降低。
- `use-model-from` 端點的路徑參數 SHALL 無法逃逸出 job 目錄。
- 本次改動 SHALL 可獨立於前端發布，對現有前端完全向下相容。

**Non-Goals:**

- **不實作前端 SHA-256 快取與 `use-model-from` 引用。** 見「暫緩項目」章節。
- 不修復 `backend1_rest_api_redesign.md` §9 的根因。
- 不重用既有 job。前端維持「每次生成都建立全新 job」。
- 不改動 `POST /slices/{job_id}/models` 的對外契約。
- 不處理 job id 僅 32 bits 的碰撞風險，亦不引入 job 目錄清理機制。
- 不優化前端 `STLExporter.parse()` 的轉檔成本。
- 不觸及 `pollJobUntilComplete` 的 3531.8 ms（屬 C++ 引擎的幾何運算）。

## Decisions

### D1（第一核心）：`_validate_stl_bytes()` 傳入 `process=False`

**決定**：`trimesh.load()` SHALL 明確傳入 `process=False`。

**理由**：現況是「用一把幾何處理的重錘去敲一顆『這是不是有效 STL』的釘子」。`process=True` 執行的頂點合併等處理，對「可解析」與「非空網格」這兩項判定沒有任何貢獻。實測顯示移除後單次解析由 774.59 ms 降至 104.46 ms，而六個無效模型案例的攔截行為完全不變。

**效益比較**（17.64 MB，每次生成解析兩次）：

| 做法 | 解析總時間 | 相對現況省下 |
| --- | --- | --- |
| 現況 | 1549 ms | — |
| **`process=False`** | **209 ms** | **1340 ms** |
| `process=False` + D3 旗標 | 104 ms | 1445 ms |
| 僅 D3 旗標 | 775 ms | 775 ms |

**這是本變更中投報率最高的一項：改一個參數，省下的時間比整套旗標機制多 565 ms。**

**適用範圍**：`_validate_stl_bytes()` 是共用函式，此改動同時惠及上傳（`api_v2.py:389`）、支撐檔上傳（`:434`）、落地（`:211`）與 boolean 運算的 `mesh_a` / `mesh_b` 驗證（`:914-915`）。

**考慮過但否決的替代方案**：

- **以純結構檢查取代 trimesh**（binary STL 可由 `len(content) == 84 + 50 × 三角面數` 驗證）。否決理由：無法涵蓋 ASCII STL，且會改變現行的錯誤判定範圍。`process=False` 已達成 7.42x 加速且行為完全一致，沒有理由承擔額外風險。
- **快取驗證結果**。否決理由：D1 之後單次驗證僅 104 ms，不值得為它引入快取的失效管理。

**必須明確的一點**：`process=False` 不會讓驗證變得寬鬆。它跳過的是幾何「處理」，不是幾何「檢查」——解析失敗仍然解析失敗，空網格仍然是空網格。六個案例的實測已證實此點。

### D2（連帶必修）：`source_file` 以「檔名對應目錄」的查表取代白名單加 fallback

**決定**：以一個模組層級的不可變對應表同時解決路徑穿越與目錄猜測兩個問題。

**現況的兩個缺陷**（`api_v2.py:455-459`）：先組出 `output/` 底下的路徑，若不存在再退回 `input/`。`source_file` 是未經任何檢查的 query 參數，直接串接進路徑；而 output 與 input 之間的 fallback 讓「檔案到底該從哪來」變成執行期的偶然結果。

**設計**：

- 資料結構：模組層級的不可變 `dict`，鍵為允許的檔名，值為該檔案所屬的子目錄（`input` 或 `output`）。
- 已確認的兩筆：`model.stl` 位於 `input`（由 `_save_model_to_job()` 寫入）、`ortho_result.stl` 位於 `output`（由 `ortho_pipeline.py:713` 與 `:1129` 寫入）。
- **端點的預設值目前是 `boolean.stl`**（`api_v2.py:446`），且磁碟上不存在該檔案。對應表的完整內容已於階段 0 調查完成，見 Open Question 1a。
- 查表失敗 SHALL 回 `VALIDATION_ERROR`，MUST NOT 沉默退回任何預設路徑。
- 對應表命中後，路徑 SHALL 由對應表指定的目錄組成，MUST NOT 再做 output 與 input 之間的存在性 fallback。

**`source_job_id` 的處理**：SHALL 通過 `_require_safe_job_id()` 檢驗。**該函式在 `dev` 分支上不存在，需一併新增**——見 D5。

**明確警告**：`source_file` **MUST NOT** 沿用 `_require_safe_job_id()`。該正規表示式為 `^[A-Za-z0-9_-]{1,64}$`，不允許句點，會將 `model.stl` 一併拒絕而使端點失效。兩個參數需要兩套不同的檢驗。

**為何在效能變更中處理安全問題**：這是一個獨立存在的缺陷，與 D1 無關。它被納入是因為調查過程中發現，而非因為 D1 需要它。曝險程度已於階段 0 下修——`use-model-from` 目前**沒有任何實際呼叫端**（見 Open Question 1c），因此漏洞雖真實存在，但無前端路徑可觸發。修復仍應進行（端點對外公開），只是緊急度低於原判斷。

### D3（第二階段加分項）：以「模型層級的已驗證旗標」去除重複解析

**決定**：在 model dict 上新增一個布林旗標（下稱 `validated`）。

- `upload_model_file()` 驗證成功後，SHALL 於 append 時標記 `validated = True`。
- `add_models_to_slice_job()` 與 `use_model_from_job()` MUST NOT 標記。
- `_save_model_to_job()` SHALL 改為條件式驗證：**旗標為真才跳過，其餘一律驗證**。

責任邊界因此明確為：

```
驗證的責任屬於「模型位元組」，不屬於「job」。
誰把位元組放進清單，誰就有機會宣告它已驗證。
沒有宣告 = 尚未驗證 = 落地前必須驗證。
```

**關鍵性質：fail-safe（預設安全）。** 旗標缺席一律解讀為「未驗證」。任何新增的模型進入點，只要作者忘了處理旗標，行為就退回今天的樣子——多解析一次，但絕不漏驗。**遺忘的代價是慢，不是不安全。**

**為何降為第二階段**：在 D1 之後，此項的額外效益僅約 104 ms，但需觸及三個模型進入點與五個落地呼叫點。相較於 D1「改一個參數省 1340 ms」，投報率明顯偏低。它仍值得做——語意上正確，且成本不高——但不應排在 D1 之前，也不應成為 D1 上線的阻礙。

**否決「job metadata 狀態標記」的理由**：

1. **語意錯置**。驗證狀態描述的是一份位元組，不是一個 job。`_pending_jobs[job_id]["models"]` 是清單結構，原則上可容納多份模型；把狀態掛在 job 上等於假設「一個 job 只有一份模型」，那是目前的巧合而非契約。
2. **會製造 §9 同型的不同步**。job metadata 若寫入 `status.json` 就會落地存活，但 `_pending_jobs` 是易失記憶體。後端重啟後磁碟旗標仍在、記憶體模型已消失，兩者失聯——這正是 §9 那個 bug 的結構。
3. **成本不對等**。旗標的生命週期只有「append 到 save」這一小段，全程都在同一個 `_pending_jobs` 條目內。為它引入磁碟 I/O 與新的持久化關注點，不划算。

### D4：引用進來的模型不標記為已驗證

**決定**：`use_model_from_job()` MUST NOT 將引用的模型標記為 `validated`。

**理由**：來源檔案的來歷無法從檔案本身確認。`input/model.stl` 可能源自已驗證的 `upload_model_file()`，也可能源自完全未驗證的 `add_models_to_slice_job()`；而 `output/` 下的檔案（如 `ortho_result.stl`）是引擎產物，從未經過上傳驗證。標記為已驗證等於憑猜測跳過檢查。

此決定在本次範圍內影響有限（`use-model-from` 目前**沒有任何實際呼叫端**，見 Open Question 1c），但它是 D3 旗標語意的一部分，需明確記錄。

### D5（連帶必修的前置）：於 `dev` 分支自行新增 `_require_safe_job_id()`，內容與位置對齊 commit `3943eaf`

**決定**：本變更 SHALL 在 `agent/api_v2.py` 新增 `import re`、`_JOB_ID_RE` 常數與 `_require_safe_job_id()` 函式。新增內容 SHALL 與 commit `3943eaf` **逐字元一致**，且插入位置 SHALL 與該 commit 相同。

**背景**：該函式在 `dev` 分支上不存在（見 Open Question 1b）。它僅存在於 `feature/manual-support-click-mode`，尚未合併。實作全貌僅 5 行程式碼：

```
_JOB_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

def _require_safe_job_id(job_id: str) -> str:
    """Reject a job id that could reach outside the job store."""
    if not _JOB_ID_RE.match(job_id):
        raise job_not_found(job_id)
    return job_id
```

其上方另有 7 行註解，說明為何必須排除反斜線（`..%5C` 可通過 URL 路由，再於 Windows 上被當成目錄分隔字元）。該註解 SHALL 一併複製，不得省略或改寫。

**依賴**：`job_not_found` 於 `dev` 已由 `.errors` 匯入，無需新增；`re` 則需新增 import。

**兩個對齊要求**（決定日後合併是否乾淨）：

1. `import re` SHALL 置於 `import math` 與 `import shutil` 之間——與 `3943eaf` 的位置完全相同。
2. `_JOB_ID_RE` 與 `_require_safe_job_id()` SHALL 置於 `_require_pending()` 之前——與 `3943eaf` 的位置完全相同。

**合併風險評估**：Git 對「兩側加入完全相同的內容於相同位置」會自動合併，不產生衝突。即使因位置些微偏移而產生衝突，其形態亦僅為「同一函式定義出現兩次」，解法是刪除其中一份——這是最容易處理的衝突類型，**不存在無解的情況**。

已確認 `3943eaf` **完全未觸及** `use_model_from_job()` 與 `_validate_stl_bytes()` 的函式本體，因此 D1 與 D2 對這兩個函式的改動與該分支不會產生任何重疊衝突。

**考慮過但否決的替代方案**：等待 `feature/manual-support-click-mode` 合併進 `dev` 之後再實作 D2。否決理由：該分支的合併時程不受本變更控制，而 D2 是安全修復，不應無限期等待；且自行新增的衝突風險已評估為低且易解。

## 暫緩項目：前端 SHA-256 快取與 `use-model-from` 引用

本項曾為變更的核心之一，經 D1 的實測數據後**移出本次範圍**，列為未來評估。完整的技術分析保留於此，供未來直接沿用。

### 為何暫緩

D1 上線後，此項的剩餘價值降至約 175 ms：

```
修復後的 ensureSupportJob = 60 ms 來回 + 121.51 ms 傳輸 + 104.46 ms 解析 ≈ 286 ms
改用引用後               = 60 ms 來回 + 磁碟讀取                        ≈ 110 ms
──────────────────────────────────────────────────────────────────────────────
剩餘可省                                                                ≈ 175 ms
```

（其中「磁碟讀取」未經實測，故上述為估算。無論該值為何，剩餘可省皆低於先前訂定的 300 ms 決策門檻。）

它同時是整個構想中最複雜的部分：跨兩個 repo、需要前端雜湊快取與 LRU 汰換、需要 fallback 自我修復機制、需要前後端同步發布。**以 175 ms 的收益承擔這些成本不划算。**

### 保留的設計結論（未來評估時可直接沿用）

**快取鍵必須是內容雜湊，不能是場景圖狀態。** `exportBinarySTL()` 匯出的是世界座標（`regrowSupportForTarget.js:56-57` 先呼叫 `updateMatrixWorld(true)` 再匯出），而 `modelId` 傳入的是 `object.uuid`（`SupportEditor.vue:239`）。移動或旋轉模型會改變位元組但不改變 uuid，以場景圖狀態為鍵將導致引用到過期的模型——這正是本變更要消滅的髒資料類型。

**SHA-256 的成本可忽略。** 實測 0.4 MB 下 0.6 ms，外插至 50 MB 約 75 ms，且 `crypto.subtle.digest` 在瀏覽器中不佔用主執行緒。不需要 Web Worker（搬進 Worker 反而要多搬一份 buffer），不做抽樣（抽樣無法提供「幾何一變必定 miss」的保證）。

**快取應為模組層級的 `Map`，以插入順序實作 LRU，上限約 32 筆。** 上限的目的不是省記憶體（32 筆不到 5 KB），而是限制指向已被清除之 job 目錄的過期引用累積。不應放進 Pinia store——它是純效能快取，任何 UI 都不會讀它。

**Fallback 的正確層級是整個 `ensureSupportJob()`，不是其中的單一步驟。** 需涵蓋兩種失敗態：來源 job 消失（`MODEL_NOT_FOUND`），以及後端在 `createJob()` 與 `use-model-from` 之間重啟導致新 job 也消失（`JOB_NOT_FOUND`）。後者代表新 job 已失效，重試必須從 `createJob()` 重新開始。防迴圈應以布林參數而非計數器實作，使遞迴深度在型別上即受限為 2。

**此路徑不與 D3 疊加。** 因 D4 規定引用進來的模型不標記為已驗證，走引用路徑時落地端仍會解析一次。

## Risks / Trade-offs

**[`process=False` 可能放行某些目前會被 trimesh 處理階段擋下的網格]** → 已以六個無效模型案例實測，兩種寫法的攔截行為完全一致。`process=False` 跳過的是幾何處理，不是幾何檢查。實作時 SHALL 將這六個案例納入單元測試，使此性質受到迴歸保護。

**[`source_file` 對應表填錯目錄會使引用無聲失效]** → 對應表已於階段 0 逐一對照實際寫入者確認（見 Open Question 1a）。因該端點目前無任何呼叫端，實際曝險為零；驗證方式為以 `TestClient` 直接測試端點本身，而非 ortho 端到端流程（ortho 並未使用此端點）。

**[直接刪除 `_save_model_to_job()` 的驗證會讓 `POST /models` 路徑完全失去檢查]** → D3 的旗標採 fail-safe 預設：旗標缺席即視為未驗證。該路徑不標記旗標，因此行為與今天完全相同。

**[D1 的效益隨模型大小線性成長，小模型上幾乎無感]** → 0.17 MB 模型上僅省 3.74 ms。這不是缺陷而是事實：本變更針對的是正式牙模（10~50 MB）的使用情境，而該情境正是實測所在。

**[`use_model_from_job()` 以同步讀檔取得整份位元組，會阻塞 FastAPI event loop]** → 本變更不改動此行為。**附帶說明**：目前 `_save_model_to_job()` 同樣是同步阻塞寫入，這個「阻塞」意外地保證了它對其他請求而言是原子的，因此不存在讀到半份檔案的競態。若日後有人將其包進執行緒池，此保護即失效。

## Migration Plan

**階段一（第一核心 + 連帶必修，可獨立發布）**

1. `_validate_stl_bytes()` 傳入 `process=False`，並補上六個無效模型案例的單元測試。
2. `use_model_from_job()` 的安全修復：`source_job_id` 檢驗、`source_file` 對應表、移除目錄 fallback。

此階段不需前端任何配合即可生效，對現有前端完全向下相容。預期省下約 1340 ms。

**階段二（加分項，可延後）**

3. D3 的旗標機制與 `_save_model_to_job()` 的條件式驗證。預期再省約 104 ms。

**未來評估**

4. 前端 SHA-256 快取（見「暫緩項目」）。SHALL 在階段一上線後重新量測，再決定是否推進。

**回滾策略**

- D1 回滾：移除 `process=False` 參數即可，不涉及資料遷移或對外契約變動。
- D3 回滾：移除條件判斷、恢復無條件驗證即可。
- D2 為安全修復，**不應回滾**；若對應表出錯，正確做法是修正對應表而非還原 fallback。

**驗證重點**

- 六個無效模型案例仍被正確攔截（D1 的迴歸保護）。
- ortho 端到端流程（D2 風險最高處）。
- `POST /slices/{job_id}/models` 路徑仍會拒絕無效 STL（D3 的 fail-safe）。
- 以 17.64 MB 模型重跑 `bgProfile`，確認 `ensureSupportJob` 與 `generateSupports` 兩項各降約 670 ms。

## Open Questions

1. ~~**`source_file` 對應表的完整內容為何？**~~ **已於階段 0 調查完成（2026-09-09，基準分支 `dev` / HEAD `55d2ec9`）。結論如下。**

### 1a. 檔名 → 子目錄 → 寫入者對照表

| 檔名 | 子目錄 | 寫入者（`dev` 分支實際行號） |
| --- | --- | --- |
| `model.stl` | `input` | `api_v2.py:211` `_save_model_to_job()` |
| `support.stl` | `input` | `api_v2.py:506` `execute_slice_job()` |
| `model_clean.stl` | `input` | `ortho_pipeline.py:771` |
| `ortho_result.stl` | `output` | `ortho_pipeline.py:713`、`:1129` |
| `model_support.stl` | `output` | `sla_operations.py:237`、`:327`（引擎產出） |
| `model_hollow.stl` | `output` | `ortho_pipeline.py:618` |
| `model_hollow_aligned.stl` | `output` | `api_v2.py:831` |
| `model_hex_grid.stl` | `output` | `api_v2.py:854` |
| `model_drain_holes.stl` | `output` | `api_v2.py:762` |
| `model_cut.stl` / `model_upper.stl` / `model_lower.stl` | `output` | `jobs.py:799`、`:804`、`:833` |
| `model_boolean_{union,difference,intersection}.stl` | `output` | `sla_operations.py:2504` |
| ~~`boolean.stl`~~ | **不存在** | 無寫入者；僅為 `main.py:1066` `FileResponse` 的下載檔名 |

**對應表建議收錄範圍**：`model.stl`、`support.stl`、`ortho_result.stl`、`model_boolean_{union,difference,intersection}.stl`。其餘檔名目前無任何引用需求，依最小授權原則不予收錄，待實際需要時再加入。

**端點新預設值決定**：`model.stl`。理由——該端點的用途即「引用既有模型」，`model.stl` 是唯一語意相符的項目；且此變更不影響任何現行呼叫端（見 1c）。API 契約文件 `DS-Online/api/slicing_core.md:439` 記載了舊預設值 `boolean.stl`，SHALL 一併更新。

### 1b. ⚠ 阻斷性問題：`_require_safe_job_id()` 在 `dev` 分支上不存在

本文件、`proposal.md`、`specs/job-file-reference-safety/spec.md` 與 `tasks.md` 中所有「呼叫既有的 `_require_safe_job_id()`」的敘述，以及所引用的正規表示式 `^[A-Za-z0-9_-]{1,64}$` 與行號 `api_v2.py:212`，**均不成立於 `dev` 分支**。

實測結果：

- `grep -rn "_require_safe_job_id" agent/` 在 `dev` 上零命中。
- 該函式僅存在於 commit `3943eaf`（`feat(support-points): 支撐點清單的匯出、匯入與錯誤分類`），該 commit 位於 `feature/manual-support-click-mode` 與 `feature/manual-edit-tree-support`，**尚未合併進 `dev`**（`git merge-base --is-ancestor 3943eaf HEAD` 回報「不包含」）。

**影響**：D2 的安全修復無法以「沿用既有函式」的形式實作。需二擇一——

- **選項 A**：以 `dev` 為基準，於本變更中**自行新增** job id 的安全字串檢驗函式。屆時該功能分支合併時會產生重複定義，需協調。
- **選項 B**：等 `feature/manual-support-click-mode` 合併進 `dev` 之後再實作 D2，屆時可真正沿用。

此決定尚未做出，**是階段 2 動工前的必要前置**。

### 1c. ⚠ 事實更正：`use-model-from` 目前沒有任何實際呼叫端

先前記載「該端點目前僅由 ortho 流程使用」**不正確**。實測：

- `useModelFromJob()` 在 `DS-Online/src/axios/backendService.js:159` 有定義，但**全 repo 無任何呼叫或 import**（已排除 `node_modules` 與 `.agents/` 備份）。
- ortho 流程並未使用此端點。該函式的 JS 端預設值 `ortho_result.stl` 從未被實際送出。

**影響**：

- 曝險評估下修——漏洞真實存在，但目前無前端路徑可觸發。修復仍應進行（端點對外公開），但緊急度低於原判斷。
- `tasks.md` 任務 2.15「以真實 job 資料執行一次 ortho 端到端流程」**前提錯誤**，需改寫為直接以 `TestClient` 驗證端點本身。
- 修改端點預設值的風險為零——沒有任何呼叫端依賴它。

### 1d. 其他需更正的既有記載

以 `dev` 分支重新核對，下列數字與行號需修正：

| 記載位置 | 原記載 | `dev` 實際 |
| --- | --- | --- |
| `_save_model_to_job()` 呼叫點 | 6 個（543、601、647、899、941、1972） | **5 個**（501、551、588、630、1661）——第 6 個屬未合併分支的支撐點匯出端點 |
| `_validate_stl_bytes()` | `api_v2.py:226` | `api_v2.py:193` |
| `_save_model_to_job()` | `api_v2.py:240` | `api_v2.py:207` |
| `add_models_to_slice_job()` append | `api_v2.py:387` | `api_v2.py:353` |
| `upload_model_file()` append | `api_v2.py:426` | `api_v2.py:392` |
| `use_model_from_job()` append | `api_v2.py:509` | `api_v2.py:467` |
| `use_model_from_job()` 定義 | `api_v2.py:488` | `api_v2.py:446` |
| output/input fallback | `api_v2.py:497-500` | `api_v2.py:455-459` |

**已複核仍然成立的事實**：`_validate_stl_bytes()` 確實使用 `trimesh.load()` 預設參數（未傳 `process`）；`_save_model_to_job()` 確實無條件呼叫它；模型進入點確實為 3 個且其中 2 個不驗證；`use_model_from_job()` 確實對兩個參數皆無驗證且存在 output→input 的存在性 fallback。**D1 與 D3 的技術前提不受影響。**
2. ~~**階段一上線後，`ensureSupportJob` 與 `generateSupports` 的實測值為何？**~~ **已於任務 4.1～4.4 量測完成。結論：暫緩項目（前端 SHA-256 快取）確認無需重啟。**

### 2a. 實測結果（瀏覽器 `localStorage.bgProfile='1'`，17.64 MB 真實牙模，三次取中位數）

| 指標 | 變更前 | 變更後 | 節省 | 降幅 |
| --- | --- | --- | --- | --- |
| `ensureSupportJob`（createJob + uploadModel） | 855.8 ms | **291.9 ms** | 563.9 ms | 65.9% |
| `generateSupports`（trigger） | 714.9 ms | **140.9 ms** | 574.0 ms | 80.3% |
| `upload` 請求 TTFB（DevTools Network） | 704.56 ms | **112.92 ms** | 591.64 ms | 84.0% |
| `upload` 請求傳輸時間 | 121.51 ms | 157.75 ms | −36.24 ms | — |

**單次支撐生成合計省約 1138 ms。**

三次原始值（`ensureSupportJob` / `generateSupports`）：Run 1 為 331.4 / 172.2、Run 2 為 254.0 / 128.4、Run 3 為 291.9 / 140.9。兩項中位數皆落在 Run 3。

**與 D1 預測的吻合度**：階段 1 預測 `generateSupports` 約 140 ms、`ensureSupportJob` 約 290 ms，實測為 140.9 與 291.9 ms。吻合度高，但 `ensureSupportJob` 三次全距達 77.4 ms，中位數本身即帶約 ±40 ms 雜訊——此處應讀為「量級與方向獲得證實」，而非毫秒級的預測準確度。

### 2b. 判斷：暫緩項目不重啟

**瓶頸已經翻轉。** 變更前上傳請求是「TTFB 704.56 ms ≫ 傳輸 121.51 ms」，伺服器端主導；變更後是「傳輸 157.75 ms > TTFB 112.92 ms」，網路主導。本變更把伺服器端該拿的都拿走了。

前端 SHA-256 快取的作用是「模型未變更時整個跳過上傳請求」，因此其效益上限等於上傳請求的剩餘總成本：

```
157.75 (傳輸) + 112.92 (TTFB) = 270.67 ms
```

**270.67 ms 低於先前訂下的 300 ms 門檻，故維持暫緩。**

⚠ **這是一個接近門檻的判斷，必須據實記錄**：270.67 ms 與 300 ms 僅差約 29 ms。若門檻訂在 250 ms，結論就會翻轉。另外，該成本中傳輸佔 157.75 ms（58%），而傳輸是本變更完全未觸及、也無法再壓縮的部分——換言之，這 270 ms 已經是「只能靠跳過整個請求才拿得到」的效益，沒有更便宜的替代做法。若日後模型尺寸顯著增大（傳輸時間隨之上升），本項應重新評估。
3. ~~**`_validate_stl_bytes()` 之外是否還有其他使用 trimesh 預設參數的熱路徑？**~~ **已於任務 4.7 掃描完成（2026-09-09，基準分支 `dev`）。有，且規模大於預期。結論如下。**

### 3a. 量化：`trimesh.load()` 的預設處理在 17.64 MB 牙模上的成本

以與階段 1 相同的模型（`agent/jobs/9d8deb5c/input/model.stl`，369,843 面）實測，3 次取中位數：

| 載入方式 | 耗時 | 面數 | 頂點數 |
| --- | --- | --- | --- |
| `trimesh.load(path)`（預設 `process=True`） | **641.24 ms** | 369,843 | 184,920（已合併） |
| `trimesh.load(path, process=False)` | **86.13 ms** | 369,843 | 1,109,529（未合併） |

**加速 7.4 倍，單次省約 555 ms。**

⚠ **但頂點數差了 6 倍，這正是本項不能比照階段 1 直接套用的原因。** `_validate_stl_bytes()` 只判斷「可否解析」與「面數是否為零」，兩者都不受頂點合併影響，所以 `process=False` 對它是純粹的免費午餐。下列呼叫點則**真的會使用幾何**——未合併的三角湯不具水密性，且會破壞鄰接關係、射線投射與布林運算。**本項為技術債記錄，不是可直接套用的修正。**

### 3b. 掃描清單：`agent/` 內所有 `trimesh.load()`

| 位置 | 現況 | 熱路徑？ | 評估 |
| --- | --- | --- | --- |
| `api_v2.py:230` `_validate_stl_bytes()` | `process=False` | 是 | ✅ 階段 1 已修 |
| `sla_operations.py:104` `load_trimesh()` | **預設** | **是（8 個呼叫點）** | **最大宗**。見 3c |
| `sla_operations.py:1924`、`:1927` `perform_boolean()` | **預設** | 是 | 布林運算需要水密網格，合併很可能是必要的 |
| `ortho_pipeline.py:557` | **預設** | 是 | 見 3d：疑似重複合併 |
| `boundary_detection.py:633` `load_mesh()` | 預設，**但僅為 fallback** | 是 | ✅ 已自行解決，見 3e |
| `auto_orient_surg_guide.py:1104` | 預設 | **否** | 位於 `__main__` CLI 區塊（讀 `sys.argv`），非伺服器路徑，不計入 |

另有數處以 `trimesh.Trimesh(..., process=True)` **明確指定**合併（`sla_operations.py:798`、`:1956`，`ortho_pipeline.py:607`）。這些是網格手術之後的重建，合併多半是刻意且必要的，與「載入時的預設值」屬不同性質，不列為技術債。

### 3c. `load_trimesh()` 是最大宗——8 個呼叫點

```
api_v2.py:884   hollow_mesh        api_v2.py:895   input_mesh
api_v2.py:1452  mesh (cut)         api_v2.py:1511  mesh
api_v2.py:1578  mesh               ortho_pipeline.py:651   m
ortho_pipeline.py:801  hollow_mesh ortho_pipeline.py:1037  input_mesh
```

函式本體僅 5 行，改動點單一；但下游涵蓋挖空、蜂巢格、排水孔、切割等真正吃幾何的運算，**必須逐一確認合併是否為必要條件**，不可整批改。

### 3d. `ortho_pipeline.py:557` 疑似重複合併

該處 `trimesh.load()` 以預設值載入（已合併頂點）後，緊接著進入一段自行統計 `merged_verts`、`zero_area_dropped`、`boundary_welded` 的清理流程。若該清理已涵蓋頂點合併，則載入時的合併是白做的。**尚未確認，僅為觀察。**

### 3e. 專案內已有現成解法可循

`boundary_detection.py:602-624` 的 `_fast_load_binary_stl()` 已獨立解決過同一個問題，且其註解明確記載了同樣的洞察（「~50x faster than trimesh.load's default process=True path」）。其做法是：以 numpy 直接讀二進位 STL 產生 `process=False` 的三角湯，**把合併移到下游明確的 `clean_mesh()` 步驟**，並保留 `trimesh.load` 作為非二進位 STL 的 fallback。

這正是 3c 應採用的模式——不是取消合併，而是把合併從「載入的隱含副作用」移為「需要時的明確步驟」。

### 3f. 建議

**另案處理，不納入本變更。** 理由：效益雖高（單次 555 ms，遠超本變更延後前端快取時所用的 300 ms 門檻），但風險性質與階段 1 完全不同——階段 1 是可證明無行為改變的參數調整，本項則會改變網格拓撲，需為 8 個以上呼叫點逐一建立幾何正確性的驗證基準線。塞進本變更會破壞「每階段都有即時驗證」的結構。
