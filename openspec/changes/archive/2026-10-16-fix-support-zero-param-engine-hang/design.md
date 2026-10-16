## Context

動機與範圍見 `proposal.md`。這裡只記錄「怎麼做」與取捨。

現況重點：

- `SLAConfig`（`agent/models.py`）對 `support_max_bridge_length` 與 `support_base_diameter` 沒有任何下限。引擎分群條件（`DefaultSupportTree.cpp:692`）是嚴格小於，值為 0 時起點連自己都收不進群，`Clustering.cpp:60-69` 的迴圈永遠不前進。
- `SLAConfig` 在 API 層有五個建構點會把 `ValidationError` 轉成錯誤回應：
  - `_run_param_validation()`（`api_v2.py:528-539`）：給 `PUT /config` 與 `POST /support-params/validate` 用，錯誤變成 `problems[]`，每筆 code 固定為 `CONFIG_VALIDATION_ERROR`。
  - `execute`（`api_v2.py:791`）、`generate-supports`（`:836`）、`export-support-points`（`:885`）、`generate-hollow`（`:1132`）：統一用 `config_validation_error(_config_validation_message(exc))`。
- `POST /slices`（`api_v2.py:437-441`）把 `request.config` 原樣存進 `_pending_jobs`，完全不驗證。
- `POST /slices/{job_id}/support-points`（`api_v2.py:916-965`）只檢查 JSON 結構，不看點的內容。
- `run_prusa_cli()`（`sla_operations.py:319-353`）用 `await process.communicate()` 等子程序，沒有逾時。生成支撐（`sla_operations.py:464`）、匯出支撐點、鏤空、切割都走它；切片（`jobs.py:604`）自己開子程序。
- `APIError.to_response()`（`errors.py:19-32`）的回應只有 `success / code / message / data.retryable / data.traceId`，沒有放欄位位置的地方。
- 錯誤碼單一來源是 `agent/error_codes.py`；`errors.py:factory_registry()` 在執行期從 factory 函式反推 code 對照表，`test_error_code_contract.py` 驗證兩邊一致；`docs/error_codes.json` 與 `docs/err_code_spec.md` 由 `python -m agent.tools.error_codes --write` 產生。
- 執行環境：Python 3.13（`asyncio.TimeoutError is TimeoutError`），Pydantic 2.12.5。Windows 上引擎是直接執行 `slicer-engine.exe`，asyncio 用 Proactor 事件迴圈開子程序。

## Goals / Non-Goals

**Goals:**

- 兩個全域欄位小於各自的下限（連接長度 `1e-4`、底座直徑 `2e-4`；含 0、負數、`-0.0`）、NaN、正負 inf 時，所有會建 `SLAConfig` 的 API 路徑都在進入佇列前回 422。
- 支撐參數錯誤回 `SUPPORT_PARAM_INVALID`，單點錯誤回 `SUPPORT_POINT_PARAM_INVALID`，兩者都帶出錯誤位置。
- 生成支撐的引擎子程序超過 120 秒時被終止並回收，job 標成 `failed`，佇列繼續往下跑。
- 不傳 `timeout_sec` 的呼叫點行為與現在完全相同。

**Non-Goals:**

- 不改前端 DS-Online。
- 不修引擎 `Clustering.cpp`。
- 不在 `param_rules.py` 加規則（`SLAConfig` 會先失敗，規則跑不到）。
- 不替切片、鏤空、切割、匯出支撐點加逾時。
- 不新增取消 job 的端點，不改 `engine_job_queue.py`。
- 舊版 v1 `POST /api/jobs`（`main.py:595-620`）不改錯誤碼。它本來就把 `SLAConfig` 例外轉成 400，加了下限後會自動擋下 0，只是錯誤碼不是新的。
- 不檢查其他單點尺寸欄位（`head_width_mm` 等）。它們不會造成分群死迴圈。

## Decisions

### D1. 全域下限用 `Field(ge=<下限>, allow_inf_nan=False)`，不另寫 validator

在 `models.py` 定義常數：

- `SUPPORT_SIZE_FLOOR_MM = 1e-4`：`support_max_bridge_length` 的下限，也是 D5 單點 `base_radius_mm`（半徑）的門檻。
- `SUPPORT_BASE_DIAMETER_FLOOR_MM = 2 * SUPPORT_SIZE_FLOOR_MM`（`2e-4`）：`support_base_diameter` 的下限。
- `SUPPORT_POINT_RADIUS_FLOOR_F32`：`1e-4` 的單精度浮點值（`9.999999747378752e-05`），給 D5 比較用。

兩個欄位分別改成 `Field(<原預設>, ge=<各自下限>, allow_inf_nan=False)`，並在同處定義常數 `SUPPORT_POSITIVE_FIELDS = frozenset({"support_max_bridge_length", "support_base_diameter"})`，給 API 層判斷用。

下限原本是 `gt=0`。Phase 1 審查發現它擋不住次正規極小值：`support_base_diameter = 5e-324` 會通過 `gt=0`，但引擎算底座半徑時（`SLAPrint.cpp`：`base_radius_mm = 0.5 * support_base_diameter`）`0.5 * 5e-324` 在 double 裡下溢成 `0.0`，分群條件 `d2d < bases` 對起點本身就不成立，一樣卡死。所以改成 `ge=1e-4`。`1e-4` mm 遠小於任何實際可列印的尺寸，不會誤擋正常值。

底座直徑的下限再取 2 倍（`2e-4`），是最終審查發現的幾何不一致（2026-10-16）：單點門檻是對**半徑**取 `1e-4`，全域原本卻是對**直徑**取 `1e-4`。引擎把直徑折半成半徑（`SLAPrint.cpp:79`），寫進匯出的每個支撐點（`SupportPointIO.hpp:322`）。全域直徑若為 `1.5e-4`，匯出的半徑就是 `7.5e-5`，呼叫端把 `GET /support-points` 的清單原樣送回 `POST /support-points` 時會被拒絕。取 2 倍後，`0.5 * 2e-4 == 1e-4`（double 下折半是精確的），匯出的半徑一定不小於單點門檻。連接長度不會被折半，也不會出現在匯出的點裡，維持 `1e-4`。

已用專案的 Pydantic 2.12.5 實測：

- `0`、`-0.0`、`-1`、字串 `"0"`、`5e-324`、`1e-9`、`0.00009` 會被擋，錯誤 `type` 為 `greater_than_equal`。底座直徑另外擋 `0.0001`、`0.00015`、`0.00019`。
- `NaN`、`+inf`、`-inf` 會被擋，錯誤 `type` 為 `finite_number`。
- 兩種錯誤的 `loc` 都是 `("<欄位名>",)`，所以 D2 只看 `loc[0]` 就能一律映射為 `SUPPORT_PARAM_INVALID`，不必列舉 `type`。
- 連接長度 `0.0001`、底座直徑 `0.0002` 會通過。

擋 `inf` 的理由：`support_base_diameter = inf` 會讓所有落地點擠成同一群，引擎後續行為沒有驗證過；這兩個欄位的無限大也沒有任何合理用途。做法與 `support_points_min_distance` 的「正負無限大被拒絕」一致。

替代方案：照 `support_points_min_distance` 的寫法自己寫 `field_validator`，用 `not (1e-4 <= v < inf)` 擋 NaN 與 inf。不採用，因為宣告式寫法已確認全部擋得到，而且比較短、錯誤 `type` 固定，好判斷。另一個替代方案是維持 `gt=0` 再額外檢查 `0.5 * v > 0`，只補次正規數這個洞。不採用，因為門檻和單點不一致，而且仍會放行 `1e-300` 這類沒有意義的值。

`support_max_pillar_link_distance` 完全不動。

### D2. 統一的 `ValidationError` 轉換

在 `api_v2.py`（`_config_validation_message` 旁）新增兩個小函式：

```
_is_support_param_error(err) -> bool
    loc = err.get("loc") or ()
    return len(loc) >= 1 and loc[0] in SUPPORT_POSITIVE_FIELDS

_config_error_from_validation(exc: ValidationError) -> APIError
    errors = exc.errors()
    details = [{"loc": list(e["loc"]), "msg": e["msg"]} for e in errors]
    message = _config_validation_message(exc)
    if any(_is_support_param_error(e) for e in errors):
        return support_param_invalid(message, errors=details)
    return config_validation_error(message)
```

判斷依據只看 `loc[0]`，不看 `type`。原因是同一欄位將來若再加別的限制（例如上限），也應該歸到支撐參數錯誤；而 `loc[0]` 對頂層欄位一定是欄位名，對 `model_validator` 則是空的，空的就不特化。

只要錯誤裡**有任何一筆**是這兩個欄位，就回 `SUPPORT_PARAM_INVALID`，其他欄位的錯誤一起放進 `data.errors`，不會遺失。

套用點：

- `execute`、`generate-supports`、`export-support-points`、`generate-hollow` 四個 `except ValidationError` 改成 `raise _config_error_from_validation(exc)`。
- `_run_param_validation()` 產生 `problems[]` 時，每筆依 `_is_support_param_error()` 決定 code 是 `SUPPORT_PARAM_INVALID` 還是 `CONFIG_VALIDATION_ERROR`，並把支撐參數的那幾筆排到最前面。這樣 `PUT /config` 的 `_raise_for_first_problem()` 拿 `problems[0]` 時一定先拿到支撐參數錯誤，`POST /support-params/validate` 的回應也會標出正確的 code。
- `_raise_for_first_problem()`：當 code 是 `SUPPORT_PARAM_INVALID` 時，把所有同 code 的 problem 的 `fields` 轉成 `errors=[{"loc": fields, "msg": suggestion}]` 傳進 factory，讓 `PUT /config` 的 422 也帶出位置。其他 code 行為不變。

`main.py:822` 與 `api_v2.py:1660` 接的是 PRZ 時間設定 `_extract_prz_timing_config()` 的 `ValidationError`，不是 `SLAConfig`，不動。

替代方案：改 `main.py` 的全域 `RequestValidationError` handler。不採用，因為 `SLAConfig` 是在端點裡面手動建的，那個 handler 根本接不到。

### D3. `APIError` 增加可選的 `details`，回應放在 `data.errors`

`APIError.__init__` 增加 `details: Optional[list] = None`，`to_response()` 在 `details` 不是 `None` 時多寫一個 `data.errors`。沒有 `details` 的錯誤回應與現在一個 byte 都不差。

新 factory（`errors.py`）：

```
support_param_invalid(message: str, errors: Optional[list] = None) -> APIError       # 422, retryable=False
support_point_param_invalid(message: str, errors: Optional[list] = None) -> APIError # 422, retryable=False
```

`errors` 是有預設值的參數，`factory_registry()` 只會用必要參數呼叫 factory，所以反推 code 不受影響。

回應範例：

```
HTTP 422
{
  "success": false,
  "code": "SUPPORT_POINT_PARAM_INVALID",
  "message": "points[2].base_radius_mm (got 0.0): must be at least 0.0001; use a positive radius, or omit it / use a negative value to follow the global base diameter",
  "data": {
    "retryable": false,
    "traceId": "…",
    "errors": [ { "loc": ["points", 2, "base_radius_mm"], "msg": "must be at least 0.0001" } ]
  }
}
```

替代方案：只把位置寫進 `message` 字串。不採用，因為前端之後要定位到某一點，解析字串不可靠。

### D4. `POST /slices` 初始 config 驗證

在 `create_slice_job()` 存入 `_pending_jobs` 之前：

```
if request.config:
    try:
        _convert_v2_config_to_sla(request.config)
    except ValidationError as exc:          # ValueError 的子類別，必須排在前面
        raise _config_error_from_validation(exc)
    except (TypeError, AttributeError, ValueError) as exc:
        raise config_validation_error(f"config has an invalid structure: {exc}")
```

- 用 `_convert_v2_config_to_sla()`，不直接 `SLAConfig(**config)`。因為呼叫端可能送 DS-Online 格式的欄位名（如 `"Layer Height"`），直接建會漏掉轉換後才出現的欄位。這和 `/generate-supports`、`/export-support-points`、`/generate-hollow` 的轉換相同；`/execute` 走 `_build_sla_config()`，只看 snake_case 欄位，兩者對 DS-Online 欄位名的處理本來就不同，本變更不處理這個既有差異。
- 轉換函式只讀不寫，所以直接傳入原物件，存下的 `config` 就是請求送來的內容，不需要複製。
- 結構性錯誤（Phase 2 審查發現）：`"Print": null`、`"Print": "x"`、`center` 含非數值等結構，會讓轉換函式丟出 `TypeError`／`AttributeError`／`ValueError`。若不處理，會落入外層 `except Exception` 變成 500；若略過預檢，藏在其中的 0 會進入待處理工作。所以一律回 422 `CONFIG_VALIDATION_ERROR` 並拒絕建立工作。
- 只驗 `SLAConfig`，不跑 `param_rules`。`param_rules` 的部分規則（如 R5 密度為 0）要看之後才會送來的手動支撐點，建立 job 當下判斷會誤擋。
- 不驗 `prz_config`。它只影響切片幾何欄位，與本次的卡死無關；放進來會擴大這個端點的行為變更。
- 驗證失敗時不建立 job，`_pending_jobs` 不會留下任何東西。

DS-Online 目前呼叫 `createJob()` 時不帶 `config`，這段對它沒有影響。

### D5. `POST /support-points` 逐點檢查

在既有「`points` 必須是陣列」與「不可與支撐 mesh 並用」兩個檢查之後、`pending["support_points"] = raw` 之前，掃過 `parsed["points"]`：

```
bad = []                              # 門檻用 models.SUPPORT_POINT_RADIUS_FLOOR_F32（1e-4 的單精度值）
for i, p in enumerate(points):
    if not isinstance(p, dict) or "base_radius_mm" not in p:
        continue                      # 缺欄位 = 沿用全域，放行；非物件交給引擎判斷
    v = p["base_radius_mm"]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        continue                      # 型別錯誤不是本變更的範圍，交給引擎
    if 0 <= v < SUPPORT_POINT_RADIUS_FLOOR_F32:
        bad.append((i, v))
if bad:
    raise support_point_param_invalid(message, errors=[{"loc": ["points", i, "base_radius_mm"], …} for …])
```

為什麼是 `0 <= v`、且小於 `1e-4` 的單精度值：

- 引擎用 `v >= 0` 判斷「這點有自己的值」（`SupportPoint.hpp:173`），負數代表沿用全域，所以負數必須放行。`abs(v) < 1e-4` 會誤擋 `-0.00005` 這種合法的「沿用全域」。
- `-0.0 >= 0` 在 Python 與 C++ 都成立，引擎會把它當成 0，這個條件剛好擋得到。
- 引擎把這個值存成 `float`（單精度）。像 `1e-50` 這種很小的正數讀進去會變成 `0.0f`，一樣會卡死。用 `1e-4` 當門檻把這類值一起擋掉。
- 門檻用 `1e-4` 的單精度值（`9.999999747378752e-05`），而不是 double 的 `1e-4`（最終審查發現）。引擎把匯入的半徑存成 `float`，之後匯出時寫的是這個單精度值（`SupportPointIO.hpp` 開頭的精度說明）。半徑剛好 `1e-4` 的點，匯入後再匯出會變成 `9.999999747378752e-05`，用 double 的 `1e-4` 比較會被擋，匯出的清單就送不回來。單精度的進位是單調的：任何不小於 `1e-4` 的值，轉成單精度後都不小於這個門檻，所以引擎匯出的半徑一定能通過；`0.00009`、`1e-50`、`0` 仍然被擋。錯誤訊息仍寫「must be at least 0.0001」，對使用者比較好懂。
- NaN：`0 <= NaN` 不成立，所以本檢查放行。（Phase 2 審查更正：原本寫「引擎會當成沿用全域」是錯的。）引擎用 `nlohmann::json::parse` 讀支撐點檔（`SupportPointIO.hpp`），`NaN` 字面值不是合法 JSON，整份檔案會被判定無效，工作失敗並回報 `support point file is not valid JSON`，不會卡死。所以不需要在這裡擋。

`data.errors` 會列出**所有**不合法的點，讓呼叫端一次改完。訊息則最多只列前 10 個位置，超過時加上「and N more」，修正提示只寫一次，避免幾千個壞點把回應撐到 MB 等級（Phase 2 審查發現）。

儲存的仍是原始 `raw` bytes，不做任何改寫，維持這個端點「不正規化、不補預設值」的既有原則。

### D6. `run_prusa_cli(timeout_sec=None)` 與 Windows 上的終止流程

```
async def run_prusa_cli(cmd, stderr_file=None, stdout_file=None, timeout_sec=None):
    process = await asyncio.create_subprocess_exec(...)
    if timeout_sec is None:
        stdout, stderr = await process.communicate()          # 與現在完全相同
    else:
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout_sec)
        except TimeoutError:
            stdout, stderr = await _kill_and_reap(process)
            _write_logs(stdout, stderr + b"\n[agent] engine killed after {timeout_sec}s\n")
            raise EngineTimeoutError(timeout_sec)
        except asyncio.CancelledError:
            await _kill_and_reap(process)                     # 伺服器關閉等情況，不留下孤兒程序
            raise
    …（以下與現在相同：寫 log、notify_launcher_if_prusa_crashed、回傳）
```

`_kill_and_reap(process)`：

1. `if process.returncode is None:` 才呼叫 `process.kill()`，並用 `try/except ProcessLookupError` 包住。逾時判定與 kill 之間程序可能剛好自己結束，這時 kill 會丟 `ProcessLookupError`，直接忽略。
2. `await asyncio.wait_for(process.communicate(), 10)` 收掉剩下的輸出並回收程序。第一次的 `communicate()` 被取消時已讀到的部分會遺失，這次只能拿到 kill 之前還留在管線裡的內容，所以 log 可能不完整，這是可接受的。
3. 第 2 步如果 10 秒內也沒結束（理論上不該發生），記一筆 error log、回傳空輸出，不再等。佇列的釋放不依賴這一步。

Windows 上的行為：

- `process.kill()` 在 Windows 是 `TerminateProcess()`，程序立刻結束，退出碼為 1，引擎內部的 TBB 執行緒一起結束，記憶體由作業系統回收。
- 引擎是直接執行 `slicer-engine.exe`，中間沒有 `cmd.exe` 或 script，所以 kill 的就是引擎本身。
- Proactor 事件迴圈在程序結束後會收到管線 EOF，第 2 步的 `communicate()` 會正常返回。

`EngineTimeoutError` 定義在 `sla_operations.py`，繼承 `Exception`，帶 `timeout_sec`。逾時路徑**不呼叫** `notify_launcher_if_prusa_crashed()`：程序是我們主動終止的，不是當機。（Windows 退出碼 1 本來也不會觸發，但 macOS 被 kill 會是 `-9`，在測試模式下會被誤報。）

呼叫點：只有 `generate_supports()`（`sla_operations.py:464`）傳 `timeout_sec=SUPPORT_GENERATION_TIMEOUT_SEC`，常數值 120，定義在 `sla_operations.py` 頂端、`SUPPORT_DETECTION_LAYER_HEIGHT` 旁邊。

job 狀態：`run_support_generation()`（`jobs.py:821`）在既有的 `except Exception` 之前加一個 `except EngineTimeoutError`，寫入 `JobStatus.FAILED`、`error_code="SUPPORT_GENERATION_FAILED"`、`error` 寫明「引擎超過 120 秒被終止」。函式結束後 `serialized_engine_job` 的 `async with` 自動釋放佇列鎖，不需要額外程式碼。

替代方案：用 `asyncio.timeout()` context manager。效果相同，但 `wait_for` 與既有程式碼風格一致，且被取消時的語意大家比較熟。

### D7. 錯誤碼登錄

`agent/error_codes.py` 新增兩筆，都是 `http_status=422`、`retryable=False`、`owner="python"`：

- `SUPPORT_PARAM_INVALID`：note 說明「Max Connector Length（`support_max_bridge_length`）須為不小於 `1e-4`、Base Diameter（`support_base_diameter`）須為不小於 `2e-4` 的有限數值，否則引擎支撐分群會無窮迴圈」。
- `SUPPORT_POINT_PARAM_INVALID`：note 說明「手動支撐點的 `base_radius_mm` 不可為 0，負數或省略代表沿用全域」。

然後執行 `python -m agent.tools.error_codes --write` 重新產生 `docs/error_codes.json` 與 `docs/err_code_spec.md`。`test_error_code_contract.py` 會驗證 registry 與 factory 一致。

## Risks / Trade-offs

- [不需要支撐的操作也會被擋] 鏤空、匯出支撐點、切片在建 `SLAConfig` 時，若 config 帶著 0 也會回 `SUPPORT_PARAM_INVALID`，即使這次操作沒有用到支撐。→ 接受。這個 config 在 `PUT /config` 就會先被擋下，正常流程走不到這裡；走到了也代表 config 本身不合法。
- [合法但很慢的支撐生成被誤殺] 超大模型、超多支撐點時，支撐生成可能真的超過 120 秒。→ 實測正常情況都在 2 秒內；前端本來就在 120 秒放棄，後端在同一時間點終止不會讓使用者多失去什麼；常數集中在一處，之後要調很容易。
- [前端與後端計時幾乎同時到] 前端從開始輪詢起算 120 秒，後端從引擎啟動起算 120 秒，前端通常先放棄，所以使用者看到的多半是前端自己的逾時訊息，不是後端的 `failed`。→ 接受。後端逾時的目的是放開佇列，下一個 job 能正常跑才是重點。
- [逾時後 log 不完整] 第一次 `communicate()` 被取消時讀到的內容會遺失。→ 在 stderr log 末尾寫明「被 agent 終止」，除錯時一看就知道。
- [引擎將來若自己開子程序] 目前沒有看到 `slicer-engine.exe` 會再開子程序，但沒有逐一驗證所有路徑。若將來會，kill 只會結束父程序，子程序變孤兒。→ 屆時改用 Windows Job Object 一起結束。本次不處理。
- [前端過渡期顯示「未預期錯誤」] DS-Online 還不認得兩個新 code。→ proposal 已接受；請求在 0.1 秒內被擋，引擎與佇列不受影響。前端對照另開 task。
- [DS-Online 的錯誤碼對帳測試] 前端有一個測試會比對後端的 `error_codes.json`。前端同步新版 JSON 時這個測試會失敗，直到前端補上兩個 code。→ 在前端 task 一併處理。

## Migration Plan

- 沒有資料遷移。`_pending_jobs` 只在記憶體，Local Agent 重啟就清空；磁碟上的舊 job 不會重新驗證。
- 隨下一版 Local Agent 發布。
- 回滾：還原本變更的 commit 即可，沒有持久化的狀態需要處理。

## Open Questions

（無）

已決定：`inf` 一併擋下，見 D1 的 `allow_inf_nan=False`。
