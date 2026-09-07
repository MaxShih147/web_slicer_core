## 1. 重構：抽離萃取邏輯至 models.py（獨立階段，先行完成）

- [x] 1.1 將 `_DS_TO_PRZ_TIMING` 映射表與 `_extract_prz_timing_config()` 從 [api_v2.py](agent/api_v2.py#L1388-L1415) 移至 [models.py](agent/models.py)（緊鄰 `PrzPrintTimingConfig` 定義），保持函式內容不變
- [x] 1.2 更新 [api_v2.py](agent/api_v2.py) — 移除原定義，於檔頭新增 `from .models import _extract_prz_timing_config`（若有引用 `_DS_TO_PRZ_TIMING` 一併匯入）
- [x] 1.3 更新 [main.py:797](agent/main.py#L797) 的延遲 import，將 `_extract_prz_timing_config` 來源由 `.api_v2` 改為 `.models`
- [x] 1.4 更新 [tests/test_prz_timing.py:26](agent/tests/test_prz_timing.py#L26) 的 import 來源由 `agent.api_v2` 改為 `agent.models`
- [x] 1.5 [驗證] 執行既有 PRZ 測試確認重構未破壞行為：`python -m pytest agent/tests/test_prz_timing.py agent/tests/test_prz_print_time.py -q`（26 passed；唯一失敗 `test_6_11_single_normal_layer_full_params` 經 stash 比對證實為重構前即存在之既有失敗，與本變更無關）
- [x] 1.6 [驗證] 確認無循環 import 且模組可載入：`python -c "import agent.jobs, agent.api_v2, agent.main, agent.models"`（須無 ImportError）

## 2. 測試先行：建立 test_jobs_sync.py（TDD，先寫失敗測試）

- [x] 2.1 建立 [agent/tests/test_jobs_sync.py](agent/tests/test_jobs_sync.py)，`from agent.jobs import resolve_estimated_print_time, _load_prz_config`（此時函式尚未實作）；不使用任何 mock
- [x] 2.2 撰寫「正常同步」測試：給定有效 `prz_config` 與 `total_layers=N`，斷言 `resolve_estimated_print_time(...)` == `_compute_print_time(prz_config, N, _extract_prz_timing_config(prz_config))`
- [x] 2.3 撰寫「fallback 降級」測試：`prz_config` 為 `None`、為觸發 `_compute_print_time` 例外的內容時，斷言回傳 == `fallback`（fork 估值）
- [x] 2.4 撰寫「極端邊界」測試：`total_layers` 為 `0` / `None`、`prz_config == {}` 時，斷言回傳 == `fallback` 且不拋例外、不為 NaN
- [x] 2.5 撰寫 `_load_prz_config` 測試：以 `tmp_path` 建立缺檔與壞 JSON 情境，斷言回傳 `None`（吞 `OSError` / `ValueError`）
- [x] 2.6 [驗證] 執行新測試確認為紅燈（函式未實作）：`python -m pytest agent/tests/test_jobs_sync.py -q`（預期 ImportError / 失敗）— 實得 `ImportError: cannot import name 'resolve_estimated_print_time' from 'agent.jobs'`，符合預期

## 3. 小步實作：純函式與 IO 邊界（jobs.py）

- [x] 3.1 在 [jobs.py](agent/jobs.py) 實作純函式 `resolve_estimated_print_time(prz_config, total_layers, fallback)`，依 design D3：空值守門在 `try` 外、`_extract_prz_timing_config` + `_compute_print_time` 包在單一 `try`，例外退回 `fallback`；新增 `from .prz_encoder import _compute_print_time` 與 `from .models import _extract_prz_timing_config`
- [x] 3.2 在 [jobs.py](agent/jobs.py) 實作 `_load_prz_config(job_dir)`：讀取 `prz_config.json`，`except (OSError, ValueError)` 回傳 `None`
- [x] 3.3 [驗證] 第 2 節測試全數轉綠：`python -m pytest agent/tests/test_jobs_sync.py -q`（12 passed；並確認 `import agent.jobs, agent.api_v2, agent.main, agent.models, agent.prz_encoder` 無循環依賴）

## 4. 前端 DS-online：傳遞 Mechado `prz_config`（雙保險，方案 1）

> 修改位置：`D:\repos\DS-online`。`mechadoConfig = adapters.uiToDefaultConfig(uiParams)` 為 PRZ 下載端已在用的同一物件，於 slice 流程 scope 可取得（[slicingService.js:873](D:/repos/DS-online/src/services/slicingService.js#L873)）。僅在有值時帶入欄位，維持向後相容。

- [x] 4.1 [前端] [backendService.js](D:/repos/DS-online/src/axios/backendService.js)：`createJob(config, przConfig)` 與 `updateJobConfig(jobId, config, isAppend, przConfig)` 的 request body 新增選填 `prz_config`（`undefined` 時不放入 body，向後相容）
- [x] 4.2 [前端] [slicingService.js](D:/repos/DS-online/src/services/slicingService.js)：`runBackendPipeline` 的 `updateJobConfig(jobId, slicingConfig, true, mechadoConfig)` 帶入 `prz_config`；並將 `mechadoConfig` 串接進 `ensureSlicingJob`（簽章 + 初始呼叫 + 2 個 retry 呼叫）→ `createJob({}, mechadoConfig)`，建立階段一併送出（雙保險）
- [x] 4.3 [驗證] 後端接收契約已以模擬請求驗證（見 5.2）：`pending["prz_config"]` 收到 Mechado `Print.*`、切片 `config` 未被污染。＊前端實際送出 body 的 DevTools live 確認待前端啟動時進行（無法於此環境跑瀏覽器）

## 5. 後端 api_v2.py：接應 `prz_config` 並落檔（pre-inject，取代舊落檔）

> 取代原「持久化」區段。原作法（落 `pending["config"]` snake_case）已證實無效——`_compute_print_time` 全跑預設值得 2629.75s。依質詢 4「直接替換、不並存」，`prz_config.json` 永遠只存 Mechado config。

- [x] ~~(舊 4.1) execute_slice_job 落 `pending["config"]`（snake_case）至 prz_config.json~~ — **作廢**，由 5.3 取代（內容無 `Print.*` → 物理公式全跑預設）
- [x] ~~(舊 4.2) 驗證上述落檔內容~~ — **作廢**，由 5.4 取代
- [x] 5.1 在 [V2SliceCreateRequest](agent/api_v2.py#L76) 與 [V2ConfigUpdateRequest](agent/api_v2.py#L81) 新增選填欄位 `prz_config: Optional[Dict[str, Any]] = None`（純加成，向後相容）
- [x] 5.2 在 [create_slice_job()](agent/api_v2.py#L253) 與 [update_slice_job_config()](agent/api_v2.py#L275)：當 `request.prz_config is not None` 時存入 `pending["prz_config"]`（不受 `isAppend` 影響）。已模擬驗證：create/update 帶 `prz_config` → `pending["prz_config"]` 含 Title Case `Print.*`、`config` 未污染、缺欄位則無該鍵
- [x] 5.3 在 [execute_slice_job()](agent/api_v2.py#L395)：改為 `prz_cfg = pending.get("prz_config")`；若非 `None` 則先 `_inject_retract_overrides(prz_cfg)`（design D5 pre-inject，與下載端同前處理）再 `json.dump` 至 `prz_config.json`；**移除**原 `pending["config"]` 落檔行；`_convert_v2_config_to_sla(pending["config"])` 維持不變
- [x] 5.4 [驗證] 以暫存 JOBS_DIR 直呼 `execute_slice_job`（attach `prz_config`）：確認 `prz_config.json` 為 Mechado `Print.*` 且已含 inject 後的 `Retract Distance`；另測缺 `prz_config` 時不落檔（已驗：Case A 落檔含 Title Case `Print.*`、非標準來源 `Retract Distance=6.0` 經 inject 進巢狀 `Print`、無 snake_case 洩漏；Case B 無 `prz_config` → 不落檔）

## 6. 後端 jobs.py：run_slicing 串接 + 缺檔降級 log

- [x] 6.1 在 [run_slicing()](agent/jobs.py#L127) `parse_sl1_metadata()` 之後串接 `_load_prz_config` → `resolve_estimated_print_time` → `write_job_status(estimated_print_time=est)`；同步失敗不影響 `COMPLETED`（已完成，原 5.1）
- [x] 6.2 在 6.1 串接中補 info log：`prz_config` 為 `None` 時 `logger.info("prz_config missing, falling back to fork time (job=%s)", job_id)`（design D3，質詢 3）— 已於 [jobs.py](agent/jobs.py) 新增 `import logging` 與 module `logger`，並在 `_load_prz_config` 回傳 `None` 時記 log

## 7. 整體驗證與收尾

- [x] 7.1 [驗證] 端到端 + **二進位一致**：跑一個切片 job 後以**相同 Mechado config** 下載 PRZ，確認 `status.json["estimated_print_time"]` 與 PRZ 下載端列印時間一致（PRZ binary `int()` 截斷差異除外），且不再是 2629.75s 預設值 — **手動網頁實測通過：網頁顯示 59m45s (3585s)、PRZ `print_time` = 3585s，完全一致，不再是 2629.75s 預設值**
- [x] 7.2 [驗證] fallback 路徑：缺 `prz_config.json` 時退回 fork 估值、狀態仍 `COMPLETED`、且有 info log — **已驗：真實 `_load_prz_config(missing)` 回傳 `None`，`agent.jobs` logger 印出 `INFO:agent.jobs:prz_config missing, falling back to fork time (job=...)`；fork 估值退回與不轉 FAILED 由 test_jobs_sync.py 單元覆蓋**
- [x] 7.3 [驗證] 邏輯測試套件：`python -m pytest agent/tests/test_jobs_sync.py`（12 passed）— 完整 `agent/tests/` 全套留待封存前最終確認
- [x] 7.4 [驗證] 規格一致性：`openspec validate sync-prz-print-time` — **`Change 'sync-prz-print-time' is valid`**
- [x] 7.5 [驗證] Web API 回傳結構未變（`estimatedPrintTime` 仍存在、型別仍 `Optional[float]`），僅數值來源改變 — 未改動回傳模型，僅 `run_slicing` 內 `estimated_print_time` 來源換為物理公式
