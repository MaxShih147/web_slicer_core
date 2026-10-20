所有指令都在 repo 根目錄 `D:\repos\web_slicer_core` 執行。測試用 `asyncio.run()` 驅動，不依賴 pytest-asyncio（環境沒裝）。每個階段的「驗證」與「Code Review」全部打勾後，才進下一個階段。

## 1. Phase 1：基礎模型與錯誤碼註冊

實作項目

- [x] 1.1 先寫測試 `agent/tests/test_support_positive_params.py`（模型層，直接建 `SLAConfig`）：
  - 兩個欄位各自對 `0`、`-0.0`、`-1`、`float("nan")`、`float("inf")`、`float("-inf")`、字串 `"0"` 拋 `ValidationError`，且每筆錯誤的 `loc[0]` 為該欄位名
  - 小於門檻的正數 `1e-9`、`0.00009`、`5e-324` 拋 `ValidationError`；`1e-4` 通過；不帶參數時預設值仍為 15.0 與 4.0
  - （最終審查後補：底座直徑下限為 `2e-4`，底座直徑為 `0.0001`、`0.00015`、`0.00019` 時也拋 `ValidationError`，`0.0002` 通過；連接長度下限仍為 `1e-4`）
  - `support_max_pillar_link_distance=0` 通過
  - 確認此時測試為紅燈
- [x] 1.2 `agent/models.py`：`support_max_bridge_length` 使用 `Field(15.0, ge=1e-4, allow_inf_nan=False)`（常數 `SUPPORT_SIZE_FLOOR_MM`）、`support_base_diameter` 使用 `Field(4.0, ge=2e-4, allow_inf_nan=False)`（常數 `SUPPORT_BASE_DIAMETER_FLOOR_MM = 2 * SUPPORT_SIZE_FLOOR_MM`：底座直徑會被引擎折半成匯出點的半徑，取單點半徑門檻的 2 倍，匯出的清單才能原樣送回；`gt=0` 擋不住 `5e-324`，見 design D1）；在同處新增 `SUPPORT_POSITIVE_FIELDS = frozenset({...})`，註解寫明「值為 0 時引擎分群會無窮迴圈，見本變更」；`support_max_pillar_link_distance` 與其既有註解不動（design D1）
- [x] 1.3 `agent/error_codes.py`：新增 `SUPPORT_PARAM_INVALID` 與 `SUPPORT_POINT_PARAM_INVALID`，皆 `http_status=422`、`retryable=False`、`owner="python"`，note 依 design D7
- [x] 1.4 `agent/errors.py`：`APIError.__init__` 新增 `details: Optional[list] = None`；`to_response()` 只在 `details is not None` 時寫入 `data.errors`（design D3）
- [x] 1.5 `agent/errors.py`：新增 factory `support_param_invalid(message: str, errors: Optional[list] = None) -> APIError` 與 `support_point_param_invalid(...)`，回傳型別標註必須是 `APIError`，`factory_registry()` 才收得到
- [x] 1.6 `agent/tests/test_error_code_registry.py`：`EXPECTED_TOTAL` 由 32 改為 34；`EXPECTED_OWNER_COUNTS` 的 `python` 由 16 改為 18
- [x] 1.7 執行 `.venv/Scripts/python -m agent.tools.error_codes --write`，重新產生 `docs/error_codes.json` 與 `docs/err_code_spec.md`；不手改這兩個檔案的自動產生區段

即時驗證

- [x] 1.8 `.venv/Scripts/python -m pytest agent/tests/test_support_positive_params.py agent/tests/test_sla_config.py -q` 全綠
- [x] 1.9 `.venv/Scripts/python -m pytest agent/tests/test_error_code_registry.py agent/tests/test_error_code_contract.py agent/tests/test_support_error_codes.py -q` 全綠
- [x] 1.10 `.venv/Scripts/python -m agent.tools.error_codes --check` 結束碼為 0
- [x] 1.11 在 `test_support_positive_params.py` 補一筆：沒有帶 `details` 的 `APIError.to_response()` 內容與改動前完全相同（`data` 只有 `retryable` 與 `traceId`）；帶 `details` 時 `data.errors` 與傳入值相同

Code Review 檢核點

- [x] 1.12 `support_max_pillar_link_distance` 沒有被加任何限制，`models.py` 第 118-120 行的「MUST NOT get a min-value validator」註解仍在
- [x] 1.13 `APIError` 的既有回應形狀沒有任何變化（只有新增的可選欄位）
- [x] 1.14 `docs/` 兩個檔案的差異只有兩個新錯誤碼，沒有其他意外變動
- [x] 1.15 這個階段沒有改到 `api_v2.py`、`sla_operations.py`、`jobs.py`

## 2. Phase 2：API 驗證與錯誤碼轉換

實作項目

- [x] 2.1 先寫測試 `agent/tests/test_support_param_invalid_api.py`，沿用 `test_config_validation_422.py` 的寫法（直接呼叫端點函式、最小 ASCII STL、`monkeypatch` 隔離 `JOBS_DIR`）。涵蓋 spec `support-param-validation` 與 `slice-config-intake` 的所有情境，先確認為紅燈
- [x] 2.2 `agent/api_v2.py`：在 `_config_validation_message()` 旁新增 `_is_support_param_error(err)`（只看 `loc[0]` 是否在 `SUPPORT_POSITIVE_FIELDS`）與 `_config_error_from_validation(exc) -> APIError`（任一筆命中即回 `support_param_invalid(message, errors=[{loc, msg}, ...])`，否則回 `config_validation_error(message)`）（design D2）
- [x] 2.3 `execute`、`generate-supports`、`export-support-points`、`generate-hollow` 四個 `except ValidationError` 改為 `raise _config_error_from_validation(exc)`；`main.py:822` 與 `api_v2.py:1660`（PRZ 時間設定）不動
- [x] 2.4 `_run_param_validation()`：建 `SLAConfig` 失敗時，每筆 problem 的 `code` 依 `_is_support_param_error()` 決定；`SUPPORT_PARAM_INVALID` 的項目排在 `problems[]` 最前面，其餘維持 pydantic 原順序
- [x] 2.5 `_raise_for_first_problem()`：當 `problems[0].code == "SUPPORT_PARAM_INVALID"` 時，把**所有** problem（含其他欄位的 `CONFIG_VALIDATION_ERROR`；這條路徑只在 `SLAConfig` 失敗時出現，problems 全是欄位驗證錯誤）轉成 `errors=[{"loc": fields, "msg": suggestion}]` 傳給 factory，訊息以「欄位名: 原因」串接；其他 code 行為不變。（實作時修正：原寫「只轉同 code 項目」會違反 spec「與其他欄位錯誤同時發生」要求 `data.errors` 兩筆都在）
- [x] 2.6 `create_slice_job()`（`POST /slices`）：`request.config` 非空時，在寫入 `_pending_jobs` 之前以 `_convert_v2_config_to_sla(dict(request.config))` 驗證；`ValidationError` 轉為 `_config_error_from_validation(exc)`；不跑 `param_rules`、不驗 `prz_config`；`APIError` 必須在 `except Exception` 之前重新拋出（design D4）。（審查後補：轉換函式丟出的 `TypeError`／`AttributeError`／`ValueError` 也回 422 `CONFIG_VALIDATION_ERROR`，不得 500、不得略過；直接傳 `request.config`，不複製）
- [x] 2.7 先寫測試 `agent/tests/test_support_points_zero_radius.py`，涵蓋 spec `support-point-api` 的所有情境（0、`-0.0`、`1e-50`、`0.00009` 擋、`0.0001` 放、多點一次回報、負數與缺欄位放行、被拒時不覆蓋舊清單、通過時 bytes 原樣存下），先確認為紅燈
- [x] 2.8 `set_support_points()`（`POST /support-points`）：在既有結構檢查之後、`pending["support_points"] = raw` 之前逐點檢查；條件 `0 <= v < SUPPORT_POINT_RADIUS_FLOOR_F32`（`1e-4` 的單精度值 `9.999999747378752e-05`；引擎匯入後再匯出的半徑是單精度值，用 double 的 `1e-4` 會擋掉引擎自己匯出的清單），排除 `bool` 與非數值、非物件的點；收集所有不合法索引後一次拋 `support_point_param_invalid(message, errors=[{"loc": ["points", i, "base_radius_mm"], "msg": ...}])`（design D5）。訊息最多列 10 點並附剩餘數量、提示只出現一次，`data.errors` 仍列全部

即時驗證

- [x] 2.9 `.venv/Scripts/python -m pytest agent/tests/test_support_param_invalid_api.py agent/tests/test_support_points_zero_radius.py -q` 全綠
- [x] 2.10 既有回歸：`.venv/Scripts/python -m pytest agent/tests/test_config_validation_422.py agent/tests/test_support_params_validate.py agent/tests/test_config_intake_validation.py agent/tests/test_v1_jobs_config_validation.py agent/tests/test_support_points_api.py agent/tests/test_support_points_wiring.py agent/tests/test_param_rules.py agent/tests/test_param_rules_contract.py agent/tests/test_slice_config_merge.py -q` 全綠
- [x] 2.11 情境抽查（寫在 2.1 的測試裡）：`PUT /config` 同時送 `pad_wall_slope=35` 與 `support_max_bridge_length=0`，回 `SUPPORT_PARAM_INVALID` 且 `data.errors` 兩筆都在；`POST /slices` 送 `{"support_max_bridge_length": 0}` 後 `_pending_jobs` 數量不變

Code Review 檢核點

- [x] 2.12 專案內所有 `except ValidationError` 都已檢查過：轉 `SLAConfig` 的五處改用新函式，PRZ 時間設定兩處維持原樣，沒有漏網的 `config_validation_error(_config_validation_message(...))`
- [x] 2.13 `param_rules.py` 沒有任何變動
- [x] 2.14 `POST /slices` 驗證失敗時不會產生 `job_id`、不會寫入 `_pending_jobs`；通過時存下的 `config` 與請求完全相同（沒有被 `supports_enable` 之類的轉換改到）
- [x] 2.15 `POST /support-points` 被拒時不改動 `pending` 的任何欄位；通過時存的仍是原始 `raw` bytes
- [x] 2.16 錯誤訊息都含欄位名（單點錯誤含 `points[i].base_radius_mm`），且是英文，與既有訊息風格一致

## 3. Phase 3：引擎逾時與程序清理

實作項目

- [x] 3.1 先寫測試 `agent/tests/test_run_prusa_cli_timeout.py`，先確認為紅燈：
  - 假子程序（`communicate()` 永遠不返回、`kill()` 會記錄被呼叫）＋ `timeout_sec=0.1`：拋 `EngineTimeoutError`、`kill()` 被呼叫一次、stderr log 末尾含「killed after」說明、沒有寫出當機通知檔（設定 `BUNDLE_FORCE_PRUSA_STACK_OVERFLOW=1` 與 sentinel 路徑來驗證）
  - 假子程序在 kill 時丟 `ProcessLookupError`：不得往外拋這個例外，仍拋 `EngineTimeoutError`
  - 外層 task 被取消（`CancelledError`）：子程序被 kill，`CancelledError` 照常往外拋
  - 不傳 `timeout_sec`：沿用 `test_run_prusa_cli_streams.py` 的 `_FakeProc`，行為與現在完全相同
  - **真實子程序**（驗證 Windows Proactor 下真的砍得掉）：以 `[sys.executable, "-c", "import time; time.sleep(60)"]` 搭配 `timeout_sec=1`，2 秒內拋 `EngineTimeoutError`，且 `process.returncode` 不為 `None`
- [x] 3.2 `agent/sla_operations.py`：新增 `EngineTimeoutError(Exception)`（帶 `timeout_sec`）與常數 `SUPPORT_GENERATION_TIMEOUT_SEC = 120`（放在 `SUPPORT_DETECTION_LAYER_HEIGHT` 旁）
- [x] 3.3 `agent/sla_operations.py`：新增 `_kill_and_reap(process)`：`returncode is None` 才 `kill()`，吞掉 `ProcessLookupError`；`await asyncio.wait_for(process.communicate(), 10)` 收尾；收尾逾時則記 error log 並回傳空輸出（design D6）
- [x] 3.4 `run_prusa_cli()` 新增參數 `timeout_sec: Optional[float] = None`：`None` 走原本的 `await process.communicate()`；有值時以 `asyncio.wait_for` 包住，`TimeoutError` → `_kill_and_reap` → 寫 log（stderr 末尾加說明行）→ 拋 `EngineTimeoutError`，此路徑不呼叫 `notify_launcher_if_prusa_crashed()`；`CancelledError` → `_kill_and_reap` → 重新拋出
- [x] 3.5 `generate_supports()`（`sla_operations.py:464`）的 `run_prusa_cli` 呼叫加上 `timeout_sec=SUPPORT_GENERATION_TIMEOUT_SEC`；其他四個呼叫點不動。（實作時補：會走 `generate_supports` 的既有測試替身原本不收 `timeout_sec`，已在 `test_run_support_generation.py`、`test_support_e2e.py`、`test_engine_error_values_api.py`、`test_import_support_resets_params.py`、`test_support_points_wiring.py` 的替身加上 `timeout_sec=None` 參數，只改簽名、不改行為）
- [x] 3.6 在 `agent/tests/test_run_support_generation.py` 補測試並先確認紅燈：`generate_supports` 拋 `EngineTimeoutError` 時，job 為 `FAILED`、`error_code` 為 `SUPPORT_GENERATION_FAILED`、`error` 含逾時說明
- [x] 3.7 `agent/jobs.py` 的 `run_support_generation()`：在既有 `except Exception` 之前加 `except EngineTimeoutError`，寫入 `JobStatus.FAILED`、`error_code="SUPPORT_GENERATION_FAILED"`、說明逾時秒數的 `error`
- [x] 3.8 在 `agent/tests/test_engine_job_queue.py` 補測試：job A 的支撐生成以假子程序卡住並逾時（`monkeypatch` 把 `SUPPORT_GENERATION_TIMEOUT_SEC` 調小），job B 排在後面；A 結束後 B 開始並完成；任何時刻 `running_count <= 1`

即時驗證

- [x] 3.9 `.venv/Scripts/python -m pytest agent/tests/test_run_prusa_cli_timeout.py agent/tests/test_run_support_generation.py agent/tests/test_engine_job_queue.py -q` 全綠
- [x] 3.10 既有回歸：`.venv/Scripts/python -m pytest agent/tests/test_run_prusa_cli_streams.py agent/tests/test_hollow_and_cut_raw_stderr.py agent/tests/test_import_support_resets_params.py agent/tests/test_engine_job_queue_profiling.py agent/tests/test_support_points_wiring.py -q` 全綠
- [x] 3.11 確認 3.1 的真實子程序測試在本機 Windows 實際跑過（不是被 skip），並記下耗時（2026-10-16 本機 Windows 11、Python 3.13.11：PASSED，耗時 1.03 秒）

Code Review 檢核點

- [x] 3.12 `timeout_sec=None` 的程式路徑與改動前逐行等價（沒有被包進 `wait_for`）
- [x] 3.13 只有 `generate_supports()` 傳了 `timeout_sec`；`grep -n "run_prusa_cli(" agent/` 的其他呼叫點都沒有帶這個參數，`jobs.py` 的切片子程序完全沒動
- [x] 3.14 逾時路徑沒有呼叫 `notify_launcher_if_prusa_crashed()`；正常路徑仍有呼叫
- [x] 3.15 `engine_job_queue.py` 沒有任何變動；佇列鎖的釋放完全依賴既有的 `async with`
- [x] 3.16 `_kill_and_reap` 不可能無限等待（收尾一定有上限），也不會把 `ProcessLookupError` 往外拋

## 4. Phase 4：端到端整合與邊界測試

規格對照

- [x] 4.1 逐一對照 4 份差異規格的每個 Scenario，確認都有對應的測試；在每個測試的 docstring 寫上它對應的 spec 檔名與 Scenario 名稱。找不到對應測試的 Scenario 要補上：
  - `specs/support-param-validation/spec.md`（含 MODIFIED 需求「參數錯誤須回 422 而非 500」的所有既有與新增情境）
  - `specs/slice-config-intake/spec.md`
  - `specs/support-point-api/spec.md`
  - `specs/support-generation-error-codes/spec.md`
  - （結果：51 個 Scenario 都已對到測試，並以程式比對確認每個名稱都出現在測試 docstring。補上的缺口：「四個入口一致」原本以 `pad_wall_slope` 只測 3 個入口，新增含 `/generate-hollow` 的四入口測試；「負數被拒絕」補 `-0.5`；「門檻值本身可通過」補兩欄同時 `0.0001`；「執行端點遇到連接長度為 0」補檢查引擎佇列為空）
- [x] 4.2 補「其他 CLI 流程不加逾時」的測試：以 `monkeypatch` 攔截 `run_prusa_cli`，確認鏤空、切割、匯出支撐點三個呼叫點收到的 `timeout_sec` 為 `None`（或未傳）；確認切片的 `jobs.py` 子程序沒有 `wait_for`（另含 `slice_model`，以及 `generate_supports` 收到 120 的對照組；寫在 `test_run_prusa_cli_timeout.py`）
- [x] 4.3 補「時限內完成不受影響」的測試：支撐生成在時限內結束時，`status.json`、stdout/stderr log、分類結果與改動前相同（以真實 `run_prusa_cli` 分別走時限 120 與無時限舊路徑，四種輸出逐 byte 相同；寫在 `test_run_support_generation.py`）

完整驗證

- [x] 4.4 全套測試：`.venv/Scripts/python -m pytest agent/tests -q`，與改動前的基準比較，不得新增任何失敗；若基準本來就有失敗，列出清單並確認與本變更無關（改動後 1727 passed / 1 failed；基準為 HEAD `b931c44` 的 `agent/`，1485 passed / 122 skipped / 1 failed。兩邊唯一的失敗相同：`test_prz_print_time.py::test_6_11_single_normal_layer_full_params`（列印時間計算，本變更未碰相關程式），沒有新增失敗）
- [x] 4.5 `.venv/Scripts/python -m agent.tools.error_codes --check` 結束碼為 0
- [x] 4.6 `openspec validate fix-support-zero-param-engine-hang` 通過
- [x] 4.7 手動冒煙（真實 Local Agent ＋ 真實引擎，Windows）：
  - 啟動 agent，以 API 依序建 job、上傳任一模型、`PUT /config` 送 `support_max_bridge_length: 0`，確認 0.1 秒內回 422 `SUPPORT_PARAM_INVALID`，工作管理員看不到 `slicer-engine.exe`
  - 接著用預設參數再走一次生成支撐，確認幾秒內完成（佇列沒有被卡住）
  - Link Distance 設 0、其他預設，確認生成支撐正常完成
  - 鏤空與切割各跑一次，確認行為與改動前相同
  - （2026-10-16 結果：以 uvicorn 在 5199 埠起 `agent.main:app`（HTTP，未用 TLS），真實 `slicer-engine.exe`，`BUNDLE_JOBS_DIR` 指向暫存區，模型 `disk.stl`。PUT 0 → 422 `SUPPORT_PARAM_INVALID`，0.005 秒，前後 `slicer-engine` 程序數皆 0；同一 job 以預設參數生成支撐 0.45 秒 completed、`hasSupportMesh: true`；Link Distance 0 生成支撐 0.44 秒 completed。鏤空與切割以改動前的 `agent/`（HEAD）在 5198 埠起基準 agent 對照，`disk.stl` 與 20 mm 方塊各跑一次：四組的 `status.json`、log、輸出 STL 逐 byte 相同。其中 `disk.stl` 鏤空失敗（interior mesh is empty，模型太薄）、方塊切割失敗（Failed to separate cut parts），兩者改動前後一致，屬模型本身的既有行為）
  - （2026-10-16 真機 Round-trip：同樣以 uvicorn 在 5199 埠、真實 `slicer-engine.exe`、暫存 jobs 目錄、模型 `disk.stl`。`PUT /config` 底座直徑 `0.0002` → 200；匯出支撐點 0.42 秒，9 點半徑皆 `0.0001` → 送回 `/support-points` 200；生成支撐 0.43 秒 completed、`hasSupportMesh: true`，引擎讀入的就是送回的清單 → 再匯出 0.41 秒 → 再送回 200。另以引擎命令列同時帶 `--import-support-points` 與 `--export-support-points`（API 的匯出每次都重算，不走這條路）：9 點半徑皆變成單精度值 `9.999999747378752e-05`，送回 200，未被單點門檻誤殺。對照組 `9.9999e-05` 與 `0` 皆回 422 `SUPPORT_POINT_PARAM_INVALID`，`data.errors` 指向該點。全程沒有卡住，結束後無殘留 `slicer-engine` 程序）

Code Review 檢核點

- [x] 4.8 整體 diff 只動到 design.md 列出的檔案：`models.py`、`errors.py`、`error_codes.py`、`api_v2.py`、`sla_operations.py`、`jobs.py`、`docs/error_codes.json`、`docs/err_code_spec.md`，以及測試檔；前端 DS-Online、`param_rules.py`、`engine_job_queue.py`、引擎原始碼都沒有變動
  - （2026-10-16 審查結果：`git diff HEAD --name-only` 加未追蹤檔，屬本變更的只有上列 8 個檔案、15 個測試檔（11 改 4 新）與本 change 目錄。`agent/param_rules.py`、`agent/engine_job_queue.py` 0 diff；`D:\repos\DS-Online` 工作區乾淨，HEAD `4697c6e7`（2026-10-15）。清單外另有 3 項，皆早於本變更（change 目錄建立於 2026-10-15），不是本變更所改：`.gitignore`（新增 `.gemini/`、`.agent/`，檔案時間 2026-09-17）、`.gitmodules`（`prusaslicer_fork` 的 url 由 SSH 改 HTTPS、縮排與結尾換行被改掉，檔案時間 2026-09-08）、`third_party/prusaslicer_fork` 子模組（checkout 的 commit `7764188f1` 與 HEAD 記錄的 gitlink 相同，gitlink 沒有變動；子模組內 dirty 的是 `.gitignore`、`src/libslic3r/CMakeLists.txt`（註解掉 `encoding_check`、補 Blosc 連結）、`src/slic3r/CMakeLists.txt`（註解掉 `encoding_check`），只是本機建置設定，沒有動到引擎演算法原始碼，檔案時間 2026-10-06）。這 3 項提交本變更時不要一起加進去）
- [x] 4.9 沒有任何違反 proposal「不在範圍內」清單的改動（沒有 cancel 端點、沒有替其他流程加逾時）
  - （審查結果：diff 沒有新增任何路由；`timeout_sec` 只有 `generate_supports()` 傳入，`slice_model`、`export_support_points`、`generate_hollow`、`cut` 四個 `run_prusa_cli` 呼叫點與 `jobs.py` 的切片子程序都沒動；`Clustering.cpp` 等引擎原始碼 0 diff；`param_rules.py` 沒有新增規則。已知限制（不違反範圍，列為後續）：開啟 `support_avoid_guide_holes` 時，`generate_supports()` 內的 keep-out 會先跑一次 `export_support_points`，那一次引擎執行沒有逾時）
- [x] 4.10 在變更說明中列出前端待辦，供另開 DS-Online task：`BACKEND_ERROR_KEYS` 加兩個新碼、四語 i18n、兩個滑桿下限、同步 `api/error_codes.json` 後的對帳測試
  - 前端待辦（DS-Online，另開 task，本變更不動前端）：
    1. `src/services/errors.js` 的 `BACKEND_ERROR_KEYS` 新增 `SUPPORT_PARAM_INVALID: 'errors.backend.supportParamInvalid'` 與 `SUPPORT_POINT_PARAM_INVALID: 'errors.backend.supportPointParamInvalid'`。兩者都是請求當下同步回 422（不是 job status 的 `error_code`），回應的 `data.errors` 是 `[{loc, msg}]`，可用來標出欄位（單點為 `["points", i, "base_radius_mm"]`）
    2. 四語 i18n（`src/i18n/locales/{tw,cn,en,jp}.json` 的 `errors.backend`）。後端下限是連接長度 `1e-4` mm、底座直徑 `2e-4` mm，對使用者沒有意義，文案只說「必須大於 0」，實際下限交給滑桿。建議文案：
       - tw：`supportParamInvalid`「連接柱最大長度與底座直徑必須大於 0，請調高數值後再試一次。」；`supportPointParamInvalid`「有支撐的底座直徑被設為 0，請調大該支撐的底座直徑，或改回沿用全域設定。」
       - cn：`supportParamInvalid`「连接柱最大长度与底座直径必须大于 0，请调高数值后重试。」；`supportPointParamInvalid`「有支撑的底座直径被设为 0，请调大该支撑的底座直径，或改回沿用全局设置。」
       - en：`supportParamInvalid` "Max Connector Length and Base Diameter must be greater than 0. Increase the value and try again."；`supportPointParamInvalid` "One or more supports have a base diameter of 0. Increase that support's base diameter, or reset it to follow the global setting."
       - jp：`supportParamInvalid`「コネクター最大長さとベース直径は 0 より大きい値にしてください。値を大きくしてから再試行してください。」；`supportPointParamInvalid`「ベース直径が 0 のサポートがあります。そのサポートのベース直径を大きくするか、全体設定に戻してください。」
    3. `src/constants/supportPanelFields.js` 滑桿下限：`support_max_bridge_length`（Max Connector Length）`min: 0` 改 `0.5`（step 0.5）；`support_base_diameter`（Base Diameter）`min: 0` 改 `0.1`（step 0.1）。同時更新 `support_base_diameter` 上方「0 is "no flare", not "no foot"」的註解，0 現在會被後端拒絕（引擎會卡死）
    4. 單支撐的底座直徑：`src/services/supportService.js` 的 `perPointSizeFields()` 對 `value >= 0` 一律送出，單支撐底座直徑為 0 會送出 `base_radius_mm: 0` 而被 `POST /support-points` 拒絕。單支撐面板若共用同一份欄位定義，套用第 3 點的下限即可；另外要處理舊專案或預設裡已存的 0（載入時夾到下限，或送出前省略該欄位改回沿用全域）
    5. 把本 repo 的 `docs/error_codes.json` 同步到 DS-Online 的 `api/error_codes.json`（目前兩邊只差這兩個 code），然後跑 `src/services/__tests__/backendErrorKeys.spec.js`：三條對帳測試（code 有 key、不落到 `unexpected`、四語都有非空文案）要在完成第 1、2 點後全綠
    6. 備註：前端 `SUPPORT_POLLING.timeout` 是 120 秒，後端引擎逾時也是 120 秒但從引擎啟動才開始算（不含排隊與 keep-out），前端通常會先放棄輪詢，看不到後端的 `SUPPORT_GENERATION_FAILED` 逾時狀態。前端 task 可考慮把輪詢上限調得比後端長一些
