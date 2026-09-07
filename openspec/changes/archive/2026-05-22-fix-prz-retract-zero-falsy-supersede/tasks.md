## 1. 【階段一：基礎設施重構】新增 `_traverse_dotpath` 與 `_get_float_opt`

- [x] 1.1 在 `agent/prz_encoder.py` line 61（`_get_float` 之前）插入 private helper `_traverse_dotpath(config: dict, dotpath: str) -> tuple[bool, Any]`：逐段分割 dotpath，若中途 key 不存在或節點非 dict 則回傳 `(False, None)`，成功走完回傳 `(True, 末端值)`
- [x] 1.2 以 `_traverse_dotpath` 重構 `_get_float()`（line 61-75）：改為呼叫 `_traverse_dotpath`，not found 或 val is None → return default；外部行為與重構前完全等價
- [x] 1.3 緊接 `_get_float` 之後新增 `_get_float_opt(config: dict, dotpath: str) -> Optional[float]`：呼叫 `_traverse_dotpath`，not found 或 val is None → return `None`；其餘（含 `0.0`）→ return `float(val)`（TypeError/ValueError → return `None`）
- [x] 1.4 Unit test（新檔或併入 `test_prz_retract.py`）— `_traverse_dotpath` 三情境：
  - key 存在且有值：`(True, value)`
  - key 不存在：`(False, None)`
  - 中間節點非 dict（路徑中斷）：`(False, None)`
- [x] 1.5 Unit test — `_get_float_opt` 三情境：
  - key 存在，值為 `0.0` → 回傳 `0.0`（非 `None`，這是核心翻案驗證點）
  - key 不存在 → 回傳 `None`
  - key 存在，值為 `None` → 回傳 `None`
- [x] 1.6 回歸驗證：執行 `pytest agent/tests/test_prz_retract.py -v`，確認重構 `_get_float` 後既有所有測試仍全數通過（無新失敗）

---

## 2. 【階段二：核心邏輯替換】修改 `_resolve_retract_pair()`

- [x] 2.1 `agent/prz_encoder.py` line 339：將 `dist = _get_float(config, dist_key)` 改為 `dist = _get_float_opt(config, dist_key)`
- [x] 2.2 `agent/prz_encoder.py` line 340：將 `drop2 = _get_float(config, drop2_key)` 改為 `drop2 = _get_float_opt(config, drop2_key)`
- [x] 2.3 更新 `_resolve_retract_pair()` 判定邏輯（line 341-345）為新 4-case 流程：
  ```
  if dist is not None and drop2 is not None:   # Case 3
      return dist, drop2
  if dist is not None:                          # Case 2
      return dist, 0.0
  if drop2 is not None:                         # Case 1
      return max(0.0, lift + lift2 - drop2), drop2
  return 0.0, lift + lift2                      # Case 4
  ```
- [x] 2.4 更新 `_resolve_retract_pair()` docstring（line 331-338）：移除舊版「falsy 視為未傳入」描述，改為新版「`is not None` 判定」語意與新真值表
- [x] 2.5 確認 `_compute_print_time()`：grep 確認其已透過 `_resolve_retract_pair()` 取得 retract 值，無直接讀取 raw config，**無需額外修改**（此為驗查步驟，非實作步驟）

---

## 3. 【階段三：完整測試矩陣】補全 task 13.2

### 3a. 更新既有測試（舊行為期望值 → 新行為期望值）

- [x] 3.1 更新 `test_case2_only_dist`（`test_prz_retract.py` line 111）：`drop2` 期望值從 `max(0, LIFT+LIFT2-2.0)` 改為 `0.0`（Case 2 BREAKING 新行為）
- [x] 3.2 更新 `test_case3_both_dist_wins`（line 117）：`drop2` 期望值從 `max(0, LIFT+LIFT2-2.0)` 改為 `99.0`（Case 3 BREAKING 新行為：保留原值），並將測試名稱改為 `test_case3_both_values_preserved`
- [x] 3.3 更新 `test_header_case2_normal_dist_only`（line 166-179）：header `normal_drop2_distance` 期望值從 `max(0, lift-2.0)` 改為 `0.0`

### 3b. 新增邊界測試（13.2 矩陣 — 4 個關鍵翻案綠燈）

- [x] 3.4 新增 `test_case2b_dist_zero_boundary`（13.2-C2b）：`_call(dist=0.0)` → 應得 `(0.0, 0.0)`；斷言：`retract == 0.0, drop2 == 0.0`（KI-1 根因翻案：舊版此 case 錯落 Case 4）
- [x] 3.5 新增 `test_case3b_drop2_zero_boundary`（13.2-C3b）：`_call(dist=2.0, drop2=0.0)` → 應得 `(2.0, 0.0)`；斷言 drop2 保留為 `0.0`（非重算）
- [x] 3.6 新增 `test_case1b_drop2_zero_boundary`（13.2-C1b）：`_call(drop2=0.0)` → 應得 `(LIFT+LIFT2, 0.0)` 即 `(10.0, 0.0)`；斷言：`retract == 10.0, drop2 == 0.0`（舊版此 case 錯落 Case 4）
- [x] 3.7 新增 `test_case3a_both_values_nonzero`（13.2-C3a）：`_call(dist=2.0, drop2=4.0)` → 應得 `(2.0, 4.0)`；斷言兩值均保留（補充驗證 Case 3 正常路徑）

### 3c. 整合驗證（encode_prz 端對端）

- [x] 3.8 新增 `test_header_case2_dist_zero`（整合）：encode_prz config 傳 `"Print.Retract Distance": 0.0`（無 drop2 key）→ PRZ header `normal_retract_distance == 0.0`、`normal_drop2_distance == 0.0`
- [x] 3.9 新增 `test_layer_retract_matches_header_case2_zero`（整合）：解碼 per-layer 值，確認與 header 一致（Case 2 dist=0.0 場景）
- [x] 3.10 執行完整測試套件：`pytest agent/tests/test_prz_retract.py -v`，確認 13.2 矩陣全 7 個 Case（C1、C2a、C2b、C3a、C3b、C4、C1b）全部綠燈，且既有回歸測試無新失敗
