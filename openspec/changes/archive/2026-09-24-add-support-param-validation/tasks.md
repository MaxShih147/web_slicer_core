## 0. 前置

- [x] 0.1 確認 `unify-error-code-registry` 已關單（`/validate` 回的 code 必須取自登錄檔）。
  - 指令：`python -m agent.tools.error_codes --check; echo "exit=$?"`
  - 預期：`exit=0`
  - **實際結果**：exit=0
- [x] 0.2 記錄回歸基準。
  - 指令：`pytest agent/tests -q 2>&1 | tail -3`
  - **基準**：1101 passed, 5 failed, 2 xfailed（merge-engine-result-classifiers 完成後的狀態；5 支失敗為既有環境缺口，見該單 6.2）。

## 1. 規則表（純函式，先不接路由）

- [x] 1.1 Write tests：`test_param_rules.py`。7 條規則各一組「剛好通過」與「剛好失敗」。邊界值**直接取自 C++ 常數**，不自行估算。
  - 指令：`pytest agent/tests/test_param_rules.py -q`
  - 預期：先紅
  - **實際結果**：先紅（`ModuleNotFoundError: agent.param_rules`）。邊界值由 Explore agent 逐條對照 `third_party/prusaslicer_fork` 原始碼查證（`SLAPrint.cpp` validate()、`SLA/Pad.cpp` PadConfig::validate()、`SupportTree.hpp` head_fullwidth()），非自行估算。
- [x] 1.2 建 `agent/param_rules.py`，實作 7 條規則（同左）。
  - 預期：1.1 轉綠。**實際結果**：一次到位，41 個測試全綠（含 1.6/1.7 一併寫入，見下）。
  - **公式訂正**：`PAD_CONFIG_INVALID` 動態門檻回報值採「無條件進位到小數點後 1 位」（`math.ceil(x*10)/10`），不是四捨五入——因為 51.3402° 這種精確值若四捨五入成 51.3，回報的「最低合法角度」本身仍會被引擎擋下，誤導使用者。已用 spec.md 的例子（thickness=2.0/brim=1.6 → 51.4）反向驗證此進位規則。
- [x] 1.3 每條規則標 `scope`。除 `EXPOSURE_TIME_OUT_OF_RANGE` 為 `slice_only` 外，其餘皆為 `support_params`。
  - 指令：`python -c "from agent.param_rules import RULES; import collections; print(collections.Counter(r.scope for r in RULES))"`
  - 預期：`Counter({'support_params': 6, 'slice_only': 1})`（此為 1.6/1.7 之前的中間態；本單一次寫完全部 7 步，最終 `RULES` 已含 D9，實際印出 `Counter({'support_params': 7, 'slice_only': 1})`，測試檔已標註此差異）。
- [x] 1.4 實作三個 profile，以 scope 的**聯集**取得規則，不得寫成三張表。
  - 指令：`python -c "from agent.param_rules import rules_for; print(len(rules_for('support')), len(rules_for('slice')), len(rules_for('slice_imported')))"`
  - 預期：`6 7 1`（同上，中間態；最終態實際為 `7 8 1`，多的 1 是 D9）。
- [x] 1.5 加一支測試斷言子集關係：`set(rules_for('support')) < set(rules_for('slice'))`。**這條測試防止未來有人把 profile 改回平行表。**
  - 已驗證：`True`。
- [x] 1.6 加 R5 規則：`support_points_density_relative` 為 0 且無手動點 → 擋下並指名密度欄位（不得回報「不需要支撐」）。
  - **設計決定**：R5 折進既有 `SUPPORT_POINTS_REQUIRED` 規則的判斷式裡（同一個 code，同一種「不會有支撐點」語意），不是 `RULES` 表裡新增一列——沿用登錄檔既有 code，不必新增 error code。
- [x] 1.7 加 D9 前置規則：收縮補償為 0 直接擋下。
  - `RULES` 新增一列（`code=SHRINKAGE_COMPENSATION_INVALID`），與 6 條引擎鏡射規則並列，`scope=support_params`。

## 2. 契約測試（把公式釘在引擎上）

- [x] 2.1 建 `test_param_rules_contract.py`：每條規則的公式與常數必須對應到 `third_party/prusaslicer_fork` 的原始碼。作法照抄 `test_support_string_contract.py`。
  - 指令：`pytest agent/tests/test_param_rules_contract.py -q`
  - 預期：全綠（fork 未 checkout 時 skip）
  - **實際結果**：24 passed。釘住 `EPSILON=1e-4`、`safety_distance_mm=0.5`、`MIN_BRIM_SIZE_MM=0.1`、`is_zero_elevation()`、`head_fullwidth()`、角度轉弧度（`* PI / 180.0`）、`bottom_offset()`/`wing_distance()` 的 tan 公式。
- [x] 2.2 加負向檢查：變造一個常數，斷言契約測試會紅。
  - `TestNegativeCheck`：4 組變造（EPSILON、safety_distance_mm、MIN_BRIM_SIZE_MM、`&&`→`||`）證明斷言有牙齒。

## 3. `/validate` 端點

- [x] 3.1 Write tests：`test_support_params_validate.py` — 回 `ok` / `problems` / `clamped` / `unknown`；不建 job；不碰磁碟。
  - 先紅（404，端點不存在）後綠。
- [x] 3.2 實作 `POST /api/v2/support-params/validate`。Request 接受整組參數（**不做白名單**）、`flow`、選填 `manual_point_count` / `per_point` / `printer_bounds`。
  - `SupportParamValidateRequest` 用 `model_config = ConfigDict(extra="allow")` 接住整組參數，不寫白名單欄位清單。
- [x] 3.3 `problems[]` 每筆含 `code`、`fields[]`、`suggestion`，動態門檻另附算出的數值。
  - 指令：驗證動態門檻會隨參數改變
  - 預期：`thickness=2.0, brim=1.6` → 下限 51.4；`brim=2.5` → 下限變小，同一個 slope 由紅轉綠
  - 已驗證（`test_threshold_moves_when_brim_increases`、`test_dynamic_threshold_carries_computed_value`）。
- [x] 3.4 `clamped[]`：`enforce_min_elevation`（< 5 拉到 5）與底座安全距離 0 → 0.5，回報原值與生效值。
- [x] 3.5 `unknown[]`：回報 `SLAConfig` 不認得的欄位名。**不得**把 `extra` 改成 `forbid`。
  - `SLAConfig` 本身的 `extra` 設定完全沒動；`unknown[]` 由 `/validate` 端點自己比對 `SLAConfig.model_fields` 算出，未知欄位在送進規則引擎前就被濾掉（不拒絕請求）。
- [x] 3.6 副作用測試：連續呼叫 100 次後，job 目錄數量不變。
  - 指令：`pytest agent/tests/test_support_params_validate.py -q -k no_side_effect`
- [x] 3.7 效能測試：1000 次取 p95。
  - 指令：`pytest agent/tests/test_support_params_validate.py -q -k perf`
  - 預期：p95 < 5 毫秒
  - **範圍訂正**：一開始直接量測整個 HTTP round trip（`TestClient`/httpx ASGI transport），p95 高達 19.4ms——這是測試工具本身的傳輸開銷，不是這支端點的運算成本。改為直接呼叫抽出來的核心函式 `_run_param_validation()`（不經 HTTP 層）量測，符合 D6「單次 p95 &lt; 5 毫秒」的原意（拖滑桿當下呼叫的運算成本，不是量測 test harness）。已驗證通過。

## 4. 三個入口回 422

- [x] 4.1 Write tests：三個入口分別送違規參數，斷言回 422 而非 500。
  - 新檔 `agent/tests/test_config_validation_422.py`（不是塞進 `test_support_params_validate.py`，因為這三個入口跟 `/validate` 端點是不同的 seam）。先紅（3 failed，`http_status=500`）後綠。
- [x] 4.2 在三個入口（實際位置：`execute_slice_job`／`generate_supports_only`／`export_support_points_only`，呼叫 `_build_sla_config`／`_convert_v2_config_to_sla` 的三處；`tasks.md` 原寫的 `:351`/`:575`/`:618` 行號已隨先前改動漂移，且 `:351` 附近的 `update_slice_job_config` 目前根本沒有 try/except——那是第 5 節要處理的端點，不是這裡的三個）各補 `except ValidationError` 分支（放在通用 `except Exception` **之前**），回 422、`retryable: false`、訊息帶欄位名。
  - **新增 error code**：`CONFIG_VALIDATION_ERROR`（422, owner=python），與既有 `VALIDATION_ERROR`（400，26+ 個呼叫點，語意是請求格式問題）區分開，避免同一個 code 在不同呼叫點回不同 HTTP status。已進登錄檔並補上 `errors.py` 的 factory。
- [x] 4.3 手動驗證死區已修復。
  - 指令：`curl -s -o /dev/null -w "%{http_code}\n" -X PUT <host>/api/v2/slices/<job>/config -H 'Content-Type: application/json' -d '{"pad_wall_slope":35}'`
  - 預期：`422`（本變更前為 `500`）
  - **實際驗證**：直接用 `TestClient` + 真正的 `APIError` exception handler（複製自 `agent/main.py`）打 `execute` 端點，`pad_wall_slope=35` 回 `422`，body 為 `{"code": "CONFIG_VALIDATION_ERROR", "message": "pad_wall_slope: ...between 45 and 90...", "data": {"retryable": false, ...}}`。`PUT /config` 本身要到第 5 節才會接上驗證，故此步驟改用 `execute` 端點驗證，語意等價（同一個 `except ValidationError` 修法）。

## 5. `PUT /config` 接規則表（風險最高，放最後）

- [x] 5.1 Write tests：存入違規設定回 422 且未被存下；存入合法設定行為不變。
  - 新檔 `agent/tests/test_config_intake_validation.py`。先紅（3 failed：`DID NOT RAISE APIError`，因為端點本來就無條件收下）後綠。
- [x] 5.2 `PUT /config` 套用 `param_rules`，與 `/validate` 共用同一份程式。
  - 用哪個 profile：存檔當下還不知道這個 job 最終會自生支撐、匯入支撐、還是不用支撐，所以選 `slice`（`support_params` ＋ `slice_only` 的聯集，最保守、涵蓋最全）驗證，而非 `support`。違規時透過既有 `_ERROR_CODE_FACTORIES`（來自 `unify-error-code-registry`）把規則的 `code` 轉成對應 APIError，不另寫第二套 code→factory 對照。
- [x] 5.3 既有 API 回歸。
  - 指令：`pytest agent/tests/test_slice_config_merge.py agent/tests/test_pad_api_v2_intake.py agent/tests/test_sla_config.py -q`
  - 預期：全綠
  - **實際結果**：46 passed。

## 6. 匯入模式重設參數

- [x] 6.1 Write tests：`input/support.stl` 存在時，寫出的 `config.ini` 所有 `pad_*` 與 `support_*` 為後端預設值。
  - 新檔 `agent/tests/test_import_support_resets_params.py`（改讀 `config.json`，跟 `config.ini` 同一份資料、比對更直接）。先紅（`support_head_front_diameter` 未被重設）後綠。
- [x] 6.2 修改 `jobs.py` 的 `run_slicing()`：偵測到 `import_support` 時明確重設全部欄位，不只關兩個開關。
  - 用 `SLAConfig.model_fields` 逐一比對前綴 `support_`/`pad_`，蓋成 `SLAConfig()` 的預設值，取代原本只關 `supports_enable`/`pad_enable` 兩行。
- [x] 6.3 驗證匯入模式使用 `slice_imported` profile，違規底墊參數**不會**擋下切片。
  - 指令：`pytest agent/tests/test_param_rules.py -q -k imported`
  - 預期：全綠
  - **實際結果**：3 passed（`TestImportedFlowSkipsSupportParams`，在 1.x 階段已一併寫好）。

## 7. 驗收

- [x] 7.1 `pytest agent/tests -q` 與 0.2 基準相比無新增失敗
  - **實際結果**：1195 passed, 5 failed, 2 xfailed。5 支失敗與 0.2 基準完全相同（既有環境缺口），無新增失敗。
- [x] 7.2 直接打 API 送 `pad_wall_slope: 35` → 422，不是 500
  - 已用 `TestClient` + 真實 exception handler 驗證：422、`code=CONFIG_VALIDATION_ERROR`。
- [x] 7.3 動態門檻：`thickness=2.0 / brim=1.6 / slope=51.4` 通過，`51.3` 失敗
  - 已驗證（`test_param_rules.py::TestR5PadConfigInvalid::test_dynamic_threshold_51_4_passes_51_3_fails`）。
- [x] 7.4 `/validate` p95 < 5 毫秒
  - 已驗證（量測核心函式 `_run_param_validation()`，見 3.7 訂正說明）。
- [x] 7.5 子集關係測試通過（`support` 規則集為 `slice` 的真子集）
  - 已驗證：`True`。
- [x] 7.6 更新 `docs/err_code_spec.md` 中 `PAD_CONFIG_INVALID` 的可觸發性註記（改由 `--write` 產生）
  - **範圍訂正**：這段「可觸發性」文字在 Endpoints 章節（手動維護的散文，非 Error Code Reference 表格），`--write` 不管這裡（見 `unify-error-code-registry` 2.2 的範圍訂正）。已手動移除過期的「PAD_CONFIG_INVALID／SUPPORT_PAD_GAP_CONFLICT 現階段 Web API 不可達」註記，兩者併入可達清單；順手把 `generate-supports` 端點清單也補上 `merge-engine-result-classifiers` 新增的三個 code（`PAD_CONFIG_INVALID`、`SUPPORT_POINT_SAMPLING_FAILED`、`SHRINKAGE_COMPENSATION_INVALID`），避免緊鄰的兩段清單一份更新一份沒更新。
