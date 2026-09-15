## 0. 前置

- [ ] 0.1 確認 `unify-error-code-registry` 已關單（`/validate` 回的 code 必須取自登錄檔）。
  - 指令：`python -m agent.tools.error_codes --check; echo "exit=$?"`
  - 預期：`exit=0`
- [ ] 0.2 記錄回歸基準。
  - 指令：`pytest agent/tests -q 2>&1 | tail -3`

## 1. 規則表（純函式，先不接路由）

- [ ] 1.1 Write tests：`test_param_rules.py`。7 條規則各一組「剛好通過」與「剛好失敗」。邊界值**直接取自 C++ 常數**，不自行估算。
  - 指令：`pytest agent/tests/test_param_rules.py -q`
  - 預期：先紅
- [ ] 1.2 建 `agent/param_rules.py`，實作 7 條規則：
  - `SUPPORT_HEAD_TOO_WIDE`：`support_head_front_diameter > support_pillar_diameter`
  - `SUPPORT_HEAD_PENETRATION_INVALID`：`support_head_penetration > support_head_width`
  - `SUPPORT_ELEVATION_TOO_LOW`：`support_object_elevation` 小於頭部全寬（含 `pad_enable`、`pad_around_object` 條件）
  - `SUPPORT_PAD_GAP_CONFLICT`：`support_base_safety_distance < pad_object_gap`（含 pad 條件）
  - `PAD_CONFIG_INVALID`：`pad_wall_thickness / tan(pad_wall_slope) > pad_brim_size`
  - `SUPPORT_POINTS_REQUIRED`：`supports_enable` 為真且手動點數為 0
  - `EXPOSURE_TIME_OUT_OF_RANGE`：曝光時間超出機型上下限（`scope=slice_only`）
  - 預期：1.1 轉綠
- [ ] 1.3 每條規則標 `scope`。除 `EXPOSURE_TIME_OUT_OF_RANGE` 為 `slice_only` 外，其餘皆為 `support_params`。
  - 指令：`python -c "from agent.param_rules import RULES; import collections; print(collections.Counter(r.scope for r in RULES))"`
  - 預期：`Counter({'support_params': 6, 'slice_only': 1})`
- [ ] 1.4 實作三個 profile，以 scope 的**聯集**取得規則，不得寫成三張表。
  - 指令：`python -c "from agent.param_rules import rules_for; print(len(rules_for('support')), len(rules_for('slice')), len(rules_for('slice_imported')))"`
  - 預期：`6 7 1`
- [ ] 1.5 加一支測試斷言子集關係：`set(rules_for('support')) < set(rules_for('slice'))`。**這條測試防止未來有人把 profile 改回平行表。**
- [ ] 1.6 加 R5 規則：`support_points_density_relative` 為 0 且無手動點 → 擋下並指名密度欄位（不得回報「不需要支撐」）。
- [ ] 1.7 加 D9 前置規則：收縮補償為 0 直接擋下。

## 2. 契約測試（把公式釘在引擎上）

- [ ] 2.1 建 `test_param_rules_contract.py`：每條規則的公式與常數必須對應到 `third_party/prusaslicer_fork` 的原始碼。作法照抄 `test_support_string_contract.py`。
  - 指令：`pytest agent/tests/test_param_rules_contract.py -q`
  - 預期：全綠（fork 未 checkout 時 skip）
- [ ] 2.2 加負向檢查：變造一個常數，斷言契約測試會紅。

## 3. `/validate` 端點

- [ ] 3.1 Write tests：`test_support_params_validate.py` — 回 `ok` / `problems` / `clamped` / `unknown`；不建 job；不碰磁碟。
- [ ] 3.2 實作 `POST /api/v2/support-params/validate`。Request 接受整組參數（**不做白名單**）、`flow`、選填 `manual_point_count` / `per_point` / `printer_bounds`。
- [ ] 3.3 `problems[]` 每筆含 `code`、`fields[]`、`suggestion`，動態門檻另附算出的數值。
  - 指令：驗證動態門檻會隨參數改變
  - 預期：`thickness=2.0, brim=1.6` → 下限 51.4；`brim=2.5` → 下限變小，同一個 slope 由紅轉綠
- [ ] 3.4 `clamped[]`：`enforce_min_elevation`（< 5 拉到 5）與底座安全距離 0 → 0.5，回報原值與生效值。
- [ ] 3.5 `unknown[]`：回報 `SLAConfig` 不認得的欄位名。**不得**把 `extra` 改成 `forbid`。
- [ ] 3.6 副作用測試：連續呼叫 100 次後，job 目錄數量不變。
  - 指令：`pytest agent/tests/test_support_params_validate.py -q -k no_side_effect`
- [ ] 3.7 效能測試：1000 次取 p95。
  - 指令：`pytest agent/tests/test_support_params_validate.py -q -k perf`
  - 預期：p95 < 5 毫秒

## 4. 三個入口回 422

- [ ] 4.1 Write tests：三個入口分別送違規參數，斷言回 422 而非 500。
  - 指令：`pytest agent/tests/test_support_params_validate.py -q -k "entry or 422"`
  - 預期：先紅
- [ ] 4.2 在 `api_v2.py:351`、`:575`、`:618` 各補 `except ValidationError` 分支（放在通用 `except Exception` **之前**），回 422、`retryable: false`、訊息帶欄位名。
- [ ] 4.3 手動驗證死區已修復。
  - 指令：`curl -s -o /dev/null -w "%{http_code}\n" -X PUT <host>/api/v2/slices/<job>/config -H 'Content-Type: application/json' -d '{"pad_wall_slope":35}'`
  - 預期：`422`（本變更前為 `500`）

## 5. `PUT /config` 接規則表（風險最高，放最後）

- [ ] 5.1 Write tests：存入違規設定回 422 且未被存下；存入合法設定行為不變。
- [ ] 5.2 `PUT /config` 套用 `param_rules`，與 `/validate` 共用同一份程式。
- [ ] 5.3 既有 API 回歸。
  - 指令：`pytest agent/tests/test_slice_config_merge.py agent/tests/test_pad_api_v2_intake.py agent/tests/test_sla_config.py -q`
  - 預期：全綠

## 6. 匯入模式重設參數

- [ ] 6.1 Write tests：`input/support.stl` 存在時，寫出的 `config.ini` 所有 `pad_*` 與 `support_*` 為後端預設值。
- [ ] 6.2 修改 `jobs.py` 的 `run_slicing()`：偵測到 `import_support` 時明確重設全部欄位，不只關兩個開關。
- [ ] 6.3 驗證匯入模式使用 `slice_imported` profile，違規底墊參數**不會**擋下切片。
  - 指令：`pytest agent/tests/test_param_rules.py -q -k imported`
  - 預期：全綠

## 7. 驗收

- [ ] 7.1 `pytest agent/tests -q` 與 0.2 基準相比無新增失敗
- [ ] 7.2 直接打 API 送 `pad_wall_slope: 35` → 422，不是 500
- [ ] 7.3 動態門檻：`thickness=2.0 / brim=1.6 / slope=51.4` 通過，`51.3` 失敗
- [ ] 7.4 `/validate` p95 < 5 毫秒
- [ ] 7.5 子集關係測試通過（`support` 規則集為 `slice` 的真子集）
- [ ] 7.6 更新 `docs/err_code_spec.md` 中 `PAD_CONFIG_INVALID` 的可觸發性註記（改由 `--write` 產生）
