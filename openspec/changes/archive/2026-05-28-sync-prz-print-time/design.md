## Context

目前列印時間有兩條獨立的計算路徑：

- **切片路徑**：[run_slicing()](agent/jobs.py#L92) 跑完 PrusaSlicer CLI 後，呼叫 [parse_sl1_metadata()](agent/jobs.py#L223) 從 `.sl1` ZIP 內的 `printTime`（fork SL1 估值）讀出時間，寫入 `status.json["estimated_print_time"]`。Web API（`GET /jobs/{id}`）回傳的即是此值。
- **PRZ 匯出路徑**：下載 PRZ 時，[api_v2.py](agent/api_v2.py#L964) 以 `_extract_prz_timing_config()` 萃取 timing，再由 [prz_encoder.py](agent/prz_encoder.py#L631) 的 `_compute_print_time(config, total_layers, timing)` 以物理公式（exposure + light-off + lift/retract motion，速度 mm/min ÷ 60）算出時間寫入 PRZ binary。

兩者公式不同、來源不同，使用者在網頁看到的時間與實機列印（PRZ）依據的時間因此不一致。

**現有約束：**
- `run_slicing()` 收到的是 `SLAConfig`（切片用），但 `_compute_print_time()` / `_extract_prz_timing_config()` 吃的是 Mechado dict（含 `Print.*` Title Case key）。兩者結構不同，故需要另存一份 **Mechado config dict**。
- **【實測根因，2026-05-27】** 前端（DS-online）用同一份 `uiParams` 產出**兩包不同的 config**：切片用 `adapters.uiToBackendSlicingConfig()`（snake_case，僅 `layer_height` / `display_*` / `center` 等幾何欄位，**無 `Print` 區段**），下載 PRZ 用 `adapters.uiToDefaultConfig()`（完整 Mechado `Print.*`）。前者經 `updateJobConfig` 存成 `pending["config"]`；若直接把它落檔成 `prz_config.json`，`_compute_print_time` 會因找不到任何 `Print.*` key 而**全跑預設值**（實測 200 層 = 2629.75s，既非 fork 3080s 亦非 PRZ 3585s）。故必須改由前端**額外送出 Mechado config**（方案 1）。
- `_extract_prz_timing_config()` 與其映射表 `_DS_TO_PRZ_TIMING` 目前住在 [api_v2.py](agent/api_v2.py#L1390-L1415)；而 `api_v2.py` 已 import `jobs.py`。若 `jobs.py` 反向 import `api_v2.py` 會造成循環依賴。
- `_compute_print_time()` 已是純函式，且 [prz_encoder.py](agent/prz_encoder.py#L30) 僅 import `models`，不 import `jobs` / `api_v2`，故 `jobs.py → prz_encoder.py` 安全無環。

## Goals / Non-Goals

**Goals:**
- 讓 `status.json["estimated_print_time"]` 成為 PRZ 物理公式的單一真值來源，與 PRZ binary 內的時間一致。
- 重用既有的 `_compute_print_time()`，不另寫第二套公式。
- 將時間同步的決策邏輯封裝成**純函式**，可在不使用 mock 的情況下單元測試（對應 `test_jobs_sync.py`）。
- 任一環節失敗時優雅退回 fork SL1 估值，不讓切片流程崩潰、不回傳空值。

**Non-Goals:**
- 不更動 `_compute_print_time()` 的公式本身（屬 `prz-motion-time` 既有需求，不變）。
- 不更動 PRZ binary 的寫入路徑與韌體期望。
- 不更動 Web API 的回傳結構（`estimatedPrintTime` 欄位保留，僅數值來源改變）。
- 不處理切片進行中的即時時間估算（僅在切片完成後一次性複寫）。

## Decisions

### D1：`prz_config.json` 的來源、寫入與讀取時機（方案 1）

**資料來源（前端，雙保險）**：前端在 `createJob` 與 `updateJobConfig` 兩個端點的 request body 中，**新增選填欄位 `prz_config`**，內容為 `adapters.uiToDefaultConfig(uiParams)`（即與 `downloadPrz` 完全相同的那包 Mechado config，含 `Print.*`）。切片用的 `config`（snake_case）**維持不變**，兩者分流互不污染。雙端皆送是為避免「未經 `updateJobConfig` 即 `execute`」的漏接死角（質詢 2 拍板）。

**為何用獨立 `prz_config` 欄位而非 merge 進 `config`**：見 D4（`_convert_v2_config_to_sla` 的 `print_config` 翻轉陷阱）。

**接應與寫入（[execute_slice_job()](agent/api_v2.py#L395)）**：後端將 `prz_config` 存入 `pending["prz_config"]`；於 `create_job(job_id)` 之後、排程 `run_slicing` 之前，落檔為 `jobs/{id}/prz_config.json`。**落檔前必須套用與 PRZ 下載端相同的 `_inject_retract_overrides()` 前處理**（D5），確保存入的就是「與下載端逐位元一致」的前處理結果：

```
job_dir = create_job(job_id)
...
prz_cfg = pending.get("prz_config")          # 前端送來的 Mechado config（可能為 None）
if prz_cfg is not None:
    _inject_retract_overrides(prz_cfg)       # 與 download.prz 完全相同的前處理（D5）
    with open(job_dir / "prz_config.json", "w") as f:
        json.dump(prz_cfg, f)
# 缺欄位 → 不落檔 → run_slicing 走 fallback 並記 info log（D3）
sla_config = _convert_v2_config_to_sla(pending["config"])   # 切片設定，維持不變
background_tasks.add_task(run_slicing, job_id, sla_config)
```

**清理（取代，不並存）**：原 Task 4.1 落的是 `pending["config"]`（snake_case，已證實無效）。此處**直接替換**為 Mechado `prz_config`，不保留舊內容，維持 `prz_config.json` 語意純粹（永遠是 Title Case Mechado config）（質詢 4 拍板）。`_inject_retract_overrides` 仍住 `api_v2.py`，於 `execute_slice_job` 呼叫不涉循環依賴；`jobs.py` 無須改動。

**讀取（[run_slicing()](agent/jobs.py#L92)）**：在 `parse_sl1_metadata()` 取得 `layer_count` 與 fork 估值之後、`write_job_status(...)` 之前，讀取 `prz_config.json` 並計算物理時間以覆寫 `estimated_print_time`；缺檔時記 info log（D3）：

```
layer_count, fork_print_time, resin_volume_ml = parse_sl1_metadata(output_file)
prz_config = _load_prz_config(job_dir)                     # IO；失敗回 None
if prz_config is None:
    logger.info("prz_config missing, falling back to fork time (job=%s)", job_id)  # D3
est = resolve_estimated_print_time(prz_config, layer_count, fork_print_time)  # 純函式
write_job_status(job_id, JobStatus.COMPLETED,
                 layer_count=layer_count,
                 estimated_print_time=est,
                 resin_volume_ml=resin_volume_ml,
                 has_support_mesh=has_support_mesh)
```

**替代方案（已否決）**：
- *在 PRZ 匯出時才回寫 status.json*：使用者不一定會下載 PRZ，網頁時間將長期停留在 fork 估值；且「下載前顯示錯、下載後變對」屬災難 UX。
- *把 Mechado config merge 進切片 `config`*：觸發 D4 的 `print_config` 翻轉陷阱，破壞既有切片幾何轉換。
- *把 config 當參數傳給 `run_slicing`*：`run_slicing` 由 `BackgroundTasks` 排程，落地成檔同時提供除錯與重算依據。

### D2：重構後的依賴拓樸

將 `_extract_prz_timing_config()` 與其映射表 `_DS_TO_PRZ_TIMING`（[api_v2.py:1388-1415](agent/api_v2.py#L1388-L1415)）一併移入 [models.py](agent/models.py)（緊鄰 `PrzPrintTimingConfig` 定義）。`api_v2.py` 與 [main.py](agent/main.py#L797) 改為從 `models` 匯入。

**移動前**（`jobs.py` 若要用萃取邏輯會成環）：

```
              ┌────────────┐
              │  api_v2.py │  ← _extract_prz_timing_config, _DS_TO_PRZ_TIMING
              └─────┬──────┘
        import jobs │ │ import models
                    ▼ ▼
        ┌──────────┐   ┌──────────┐
        │ jobs.py  │──▶│ models.py│
        └──────────┘   └──────────┘
   ✗ jobs.py 想用萃取邏輯 → 須 import api_v2 → 與 api_v2 import jobs 形成環
```

**移動後**（`models.py` 為無內部相依的葉節點，所有人朝它單向匯入）：

```
        ┌──────────┐         ┌──────────────┐
        │ main.py  │         │   api_v2.py  │
        └────┬─────┘         └──┬────────┬──┘
   import    │         import   │        │ import jobs
   models    │         models   │        ▼
   (timing)  │        (timing)  │   ┌──────────┐
             │                  │   │ jobs.py  │
             ▼                  ▼   └──┬────┬───┘
        ┌─────────────────────────┐   │    │ import _compute_print_time
        │        models.py        │◀──┘    ▼
        │  PrzPrintTimingConfig   │   ┌──────────────┐
        │  _DS_TO_PRZ_TIMING      │   │ prz_encoder  │
        │  _extract_prz_timing_…  │◀──┤ _compute_…   │
        └─────────────────────────┘   └──────────────┘
              （葉節點，零內部 import）
```

- `models.py`：純 pydantic / enum / typing，無任何 agent 內部 import → 永遠是匯入鏈終點，不可能成環。
- `jobs.py` 新增相依：`from .models import _extract_prz_timing_config`（已 import models）、`from .prz_encoder import _compute_print_time`。
- `jobs.py → prz_encoder.py → models.py` 為單向鏈（`prz_encoder` 不 import `jobs`/`api_v2`），無環。
- `api_v2.py` 行為不變，僅匯入來源由「自身模組」改為 `models`；`main.py` 第 797 行的延遲 import 同步改指向 `models`。

**理由**：`models.py` 本就是型別與設定的家；萃取函式是 dict → `PrzPrintTimingConfig` 的純轉換，語意上屬於 model 層，移過去最自然，也順帶解開循環依賴。

**替代方案（已否決）**：新增 `timing_utils.py` 之類的第三模組——徒增檔案，且 `PrzPrintTimingConfig` 仍在 `models.py`，分家反而割裂內聚。

### D3：Fallback 的 try-except 邊界

採「IO 與決策分離」，切出兩個邊界，使核心決策為可測純函式：

**邊界 1 — `_load_prz_config(job_dir) -> Optional[dict]`（IO，置於 jobs.py）**
只負責讀檔與 JSON 解析，吞掉所有 IO / 解析錯誤回傳 `None`：

```
def _load_prz_config(job_dir: Path) -> Optional[dict]:
    path = job_dir / "prz_config.json"
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (OSError, ValueError):   # 檔案不存在 / JSON 壞掉
        return None
```

**邊界 2 — `resolve_estimated_print_time(prz_config, total_layers, fallback) -> Optional[float]`（純函式，`test_jobs_sync.py` 的主測標的）**
無 IO、無副作用，將「萃取 + 計算」整段包在單一 `try`，任一例外都退回 `fallback`：

```
def resolve_estimated_print_time(
    prz_config: Optional[dict],
    total_layers: Optional[int],
    fallback: Optional[float],
) -> Optional[float]:
    if not prz_config or not total_layers:
        return fallback                       # 無 config / 無層數 → 用 fork 估值
    try:
        timing = _extract_prz_timing_config(prz_config)
        return _compute_print_time(prz_config, total_layers, timing)
    except Exception:
        return fallback                       # 萃取/計算任一失敗 → 用 fork 估值
```

**try-except 涵蓋範圍明確界定：**
- `try` **內**：`_extract_prz_timing_config`（含 pydantic `ValidationError`）與 `_compute_print_time`（除零、缺 key、型別錯誤等）。
- `try` **外**：`prz_config` 與 `total_layers` 的空值守門（提早 return，不靠例外控流）。
- 檔案 IO 不在此函式（已隔離於邊界 1），確保本函式對相同輸入恆等輸出，可純測。
- `run_slicing` 主流程的 PrusaSlicer 執行維持原有 `try/except Exception → write_job_status(FAILED)`，時間同步邏輯**不得**讓已成功的切片轉為失敗——故同步失敗只降級為 fallback，不向上拋。

**Fallback 語意分層**：物理值 → fork 估值（`fallback`）→ 若 fork 亦為 `None` 則欄位為 `None`（與現狀一致，不退化）。

**可觀測性（靜默降級 + Log，質詢 3 拍板）**：當 `prz_config.json` 缺失（`_load_prz_config` 回 `None`）時，`run_slicing` SHALL 記一筆 `info` 等級 log：`"prz_config missing, falling back to fork time"`（含 `job_id`），以追蹤前端是否漏送 `prz_config`。降級本身不改變 `COMPLETED` 狀態、不向上拋例外。萃取/計算例外（`resolve_estimated_print_time` 內部）維持靜默退回 `fallback`。

### D4：為何用獨立 `prz_config` 欄位，而非 merge 進切片 `config`

切片 `config`（snake_case）會被 [_convert_v2_config_to_sla()](agent/api_v2.py#L1438) 消費，其中關鍵一行：

```
print_config = config.get("Print", config)   # 有 "Print" key → 用子字典；否則用整包
center = print_config.get("center")           # 算 center_x / center_y
image_size = print_config.get("Image Size")   # 算 display_pixels_*
```

目前切片 config 無 `Print` key，故 `print_config = config`（整包 snake_case），`center` 等查得到。**若把 Mechado config（含 `Print` 區段）merge 進同一 dict，`print_config` 會翻轉成 Mechado `Print` 子字典**，導致：
- `print_config.get("center")` 在 Mechado 區段找不到 snake_case `center` → **center_x / center_y 不再設定 → 切片擺位錯誤**；
- snake_case → Title Case 的覆寫分支（mapping 迴圈）被觸發，可能用 Mechado 值蓋掉切片值。

亦即 merge 不只「污染」，而是**會破壞既有切片幾何轉換**。故採獨立欄位：`config` 一字不動、零回歸，Mechado config 走 `prz_config` 獨立通道。

### D5：落檔前 Pre-inject —— Web 與 PRZ 的二進位一致性（質詢 1 拍板）

PRZ 下載端在計算前必跑 `_inject_retract_overrides(config)`（[api_v2.py:965](agent/api_v2.py#L965)）再 `_extract_prz_timing_config` + `_compute_print_time`；而 `run_slicing` 的 `resolve_estimated_print_time` 不跑 inject。Mechado 預設 profile 的 `Print` 區段有 `Retract Second Distance` 卻**無 `Retract Distance`**，正是靠 inject 補齊；若兩端前處理不對稱，`_resolve_retract_pair` 會解出不同的 retract pair → Web 與 PRZ 仍有殘差。

**決策**：在 `execute_slice_job` **落檔前**對 `prz_cfg` 套一次 `_inject_retract_overrides`，使 `prz_config.json` 內就是「與下載端 body 經相同前處理後」的狀態。如此 `run_slicing` 直接讀檔即與下載端**逐位元一致（bit-wise）**，一致性由構造保證而非巧合。inject 留在 `execute_slice_job`（api_v2.py）而不下放 `jobs.py`，可同時避免循環依賴並維持 `jobs.py` 的純粹。

## Risks / Trade-offs

- **[前端漏送 `prz_config`]** 任一端點未帶 `prz_config` → 不落檔 → `run_slicing` 靜默降級為 fork 估值並記 info log（D3）。雙端（create + update）皆送以降低漏接機率；info log 供追蹤前端是否漏送。
- **[兩端前處理不對稱致殘差]** 由 D5 的落檔前 pre-inject 消除：存檔即為與下載端相同 `_inject_retract_overrides` 前處理後的結果，達二進位一致。
- **[物理值與 fork 值差異顯著，使用者感到「時間變了」]** → 此即本變更的預期目的（單一真值來源）；於 proposal / release note 說明數值來源變更，回傳欄位不變故非破壞性。
- **[切片時與下載時的 Mechado config 不同步]** 兩者皆源自同一 `uiToDefaultConfig(uiParams)`；風險僅在使用者於切片後、下載前改參數——屬使用者行為而非本設計缺陷，且下載端仍以當下 body 重算 PRZ。
- **[merge 污染切片轉換]** 已由 D4 的獨立欄位設計根除（`config` 一字不動）。
- **[移動 `_extract_prz_timing_config` 漏改匯入點]** → 全庫搜尋現有引用（`api_v2.py`、`main.py`、`tests/test_prz_timing.py`）逐一改為 `from .models import ...`；測試應全綠以驗證。

## Migration Plan

1. 在 `models.py` 新增 `_DS_TO_PRZ_TIMING` 與 `_extract_prz_timing_config`；自 `api_v2.py` 移除原定義。**【已完成】**
2. 更新 `api_v2.py`、`main.py`、`tests/test_prz_timing.py` 的匯入來源為 `models`。**【已完成】**
3. 於 `jobs.py` 加入 `_load_prz_config` 與 `resolve_estimated_print_time`，並在 `run_slicing` 串接覆寫（缺檔 info log 待補）。**【純函式/IO/串接已完成；info log 待補】**
4. 新增 `tests/test_jobs_sync.py`（純函式，無 mock）。**【已完成】**
5. **前端 DS-online**：`createJob` / `updateJobConfig` 的 request body 新增選填 `prz_config = adapters.uiToDefaultConfig(uiParams)`（與 `downloadPrz` 同源）。
6. **後端 `api_v2.py`**：`V2SliceCreateRequest` / `V2ConfigUpdateRequest` 新增選填 `prz_config`；`create_slice_job` / `update_slice_job_config` 將其存入 `pending["prz_config"]`；`execute_slice_job` 改為對 `pending["prz_config"]` 套 `_inject_retract_overrides` 後落檔（**取代**原 `pending["config"]` 落檔，Task 4.1）。
7. `run_slicing` 缺檔時補 info log（D3）。

**回滾**：前端移除 `prz_config` 欄位、後端移除選填欄位與落檔段即可；舊 job 無 `prz_config.json` 時自動走 fallback，向後相容。重構（步驟 1-4）為純加成 + 函式搬移，可獨立保留。

## Open Questions

- 物理時間是否需與 PRZ binary 寫入端一致地以 `int()` 截斷後存入 status.json，或保留浮點數讓 Web 層自行格式化？（傾向保留浮點，截斷僅屬 PRZ binary 欄位需求——待 spec 與既有回傳型別 `Optional[float]` 對齊後確認。）
