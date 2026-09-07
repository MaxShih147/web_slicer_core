## Supersedes

本變更**取代**已 archive 的 `2026-05-21-fix-prz-output-correctness` 中的 **D3 決策**（「傳入值」語意為任意 falsy）。

- Archive 路徑：`openspec/changes/archive/2026-05-21-fix-prz-output-correctness/`
- 被取代決策：`design.md § D3`（`if dist:` falsy 判定）
- Archive KI-1 記載的根因現已被本變更修正

---

## Why

`_resolve_retract_pair()` 以 `if dist:` 判斷 retract 距離是否傳入，導致顯式傳入 `dist = 0.0`
（意圖：無第一段回退）被錯判為「未傳入」而落入 Case 4，最終 `drop2` 被改寫為 `lift + lift2`。
此 falsy 語意誤判已在 archive KI-1 中預告，但當時以「待前後端對齊」為由暫緩；
本次變更以 `Optional[float]` 雙函式策略徹底翻案，無需等待前端協議變更。

---

## What Changes

- **新增 `_get_float_opt(config, dotpath) -> Optional[float]`**：當 key 不存在或值為 `None` 時回傳 `None`；其餘（含 `0.0`）回傳 `float(value)`。
- **保留 `_get_float(config, dotpath, default=0.0) -> float`**：簽章與行為完全不變，所有既有呼叫點繼續使用此函式。
- **`_resolve_retract_pair()` 改用 `_get_float_opt()`**：`dist` 與 `drop2` 兩個讀值改呼叫 `_get_float_opt()`，判定改為 `if dist is not None:` 與 `if drop2 is not None:`。
- **BREAKING（局部）：Case 2 行為變更**：`dist` 存在且 `drop2` 缺失時，舊版 `drop2 = max(0, lift + lift2 - dist)`；新版 `drop2 = 0.0`（尊重使用者「僅一段回退」意圖）。
- **BREAKING（局部）：Case 3 行為變更**：`dist` 與 `drop2` 同時存在時，舊版強制重算 `drop2`（覆寫使用者傳入值）；新版保留兩者原始值 `(dist, drop2)`。
- **`prz-motion-time` delta spec 更新**：修正 Case 1–4 觸發契約，與新行為對齊。
- **補全 task 13.2 測試**：Case 1–4 全部重啟，加入 `dist=0.0` 與 `drop2=0.0` 顯式零值邊界。

---

## 新 D2 真值表

| Case | dist key | drop2 key | 最終 dist | 最終 drop2 | 異動 |
|------|----------|-----------|-----------|------------|------|
| 1 | 缺失 / None | 存在 ≠ None | `max(0, lift+lift2-drop2)` | drop2 | 不變 |
| 2 | 存在 ≠ None | 缺失 / None | dist | **0.0** | ← 翻案 |
| 3 | 存在 ≠ None | 存在 ≠ None | dist | **drop2（原值）** | ← 翻案（舊版重算） |
| 4 | 缺失 / None | 缺失 / None | 0.0 | lift+lift2 | 不變 |

「存在 ≠ None」= `_get_float_opt()` 回傳非 None（含 0.0）。

---

## Capabilities

### New Capabilities

（無）

### Modified Capabilities

- `prz-motion-time`：Case 2 觸發契約從「truthy」改為「非 None」；Case 2 的 drop2 結果從 `max(0, lift+lift2-dist)` 改為 `0.0`；Case 3 drop2 從強制重算改為保留原值。

---

## 重構衝擊清單：`_get_float()` 呼叫點分析

### Group B：需改用 `_get_float_opt()` ← 本次修改目標

| 位置 | 行號 | 說明 |
|------|------|------|
| `agent/prz_encoder.py` | 339 | `dist = _get_float(config, dist_key)` → 需辨別 absent vs 0.0 |
| `agent/prz_encoder.py` | 340 | `drop2 = _get_float(config, drop2_key)` → 需辨別 absent vs 0.0 |

**修改策略**：在 `_resolve_retract_pair()` 內部僅此 2 行替換為 `_get_float_opt()`；其餘所有呼叫點保持 `_get_float()` 不動。

### Group A：保留 `_get_float()`（0.0 fallback 物理語意正確）

| 位置 | 典型呼叫 | 為何 0.0 正確 |
|------|----------|---------------|
| prz_encoder.py:389, 686 | `_get_float(config, "...Lifting Second Distance")` | 0.0 = 無第二段上升，物理正確 |
| prz_encoder.py:391, 692 | `_get_float(config, "...Lifting Second Speed")` | 0.0 = 第二段速度為 0，motion_time 自動跳過 |
| prz_encoder.py:397, 698 | `_get_float(config, "...Retract Second Speed")` | 同上 |
| prz_encoder.py:400, 701 | `_get_float(config, "...Lifting Second Distance")` | 同上（normal 變體）|
| prz_encoder.py:402, 707 | `_get_float(config, "...Lifting Second Speed")` | 同上 |
| prz_encoder.py:408, 713 | `_get_float(config, "...Retract Second Speed")` | 同上 |
| prz_encoder.py:563, 686 | `_get_float(config, "...Bottom Lifting Second Distance")` | 同上 |
| prz_encoder.py:585, 587, 589, 591 | Second Speed 系列 binary 寫入 | 寫 0.0 韌體會忽略該段 |
| prz_encoder.py:607 | `_get_float(config, "Other.volume")` | 0.0 = 未提供體積，後續邏輯跳過 |
| prz_encoder.py:364–365, 514, 520, 523, 等 | 所有帶 `default=X.X` 的呼叫 | 顯式 default，不涉及 None 語意 |

**結論**：`_get_float()` 函式本體、回傳型態、所有既有 caller 全部不動。唯一改變是在 `_resolve_retract_pair()` 內新增 `_get_float_opt()` 呼叫（2 行），並更新判定邏輯。

---

## 測試驗證策略

### 補全 task 13.2：Case 1–4 重啟 + drop2=0 顯式邊界

測試對象：`agent/tests/test_prz_retract.py` → `TestResolveRetractPair` 類別

| 測試 ID | 情境 | dist 傳入 | drop2 傳入 | 預期結果 | 驗證重點 |
|---------|------|-----------|------------|----------|----------|
| 13.2-C1 | Case 1（純 drop2）| absent | 3.0 | `(max(0, L+L2-3), 3.0)` | 不變行為回歸 |
| 13.2-C2a | Case 2（dist=2.0）| 2.0 | absent | `(2.0, 0.0)` | **新行為**：drop2=0 非 max |
| 13.2-C2b | **Case 2 dist=0.0 邊界** | **0.0** | absent | `(0.0, 0.0)` | KI-1 翻案：舊版錯落 Case 4 |
| 13.2-C3a | Case 3（兩者皆傳）| 2.0 | 4.0 | `(2.0, 4.0)` | **新行為**：drop2 原值保留 |
| 13.2-C3b | **Case 3 drop2=0.0 邊界** | 2.0 | **0.0** | `(2.0, 0.0)` | 舊版：drop2=0.0 被忽略重算 |
| 13.2-C4 | Case 4（兩者皆缺）| absent | absent | `(0.0, L+L2)` | 不變行為回歸 |
| 13.2-C1b | **Case 1 drop2=0.0 邊界** | absent | **0.0** | `(L+L2, 0.0)` | 舊版：drop2=0.0 誤落 Case 4 |

總計 7 個測試案例，其中 4 個（C2b、C3b、C1b 及 C2a 新行為）為本次翻案後的**關鍵新綠燈**。

### 整合驗證

- `test_header_case2_dist_zero`：encode_prz config 傳 `dist=0.0`（無 drop2 key）→ PRZ header normal_retract_distance == 0.0、normal_drop2_distance == 0.0
- `test_layer_retract_matches_header_case2_zero`：per-layer 值與 header 一致（Case 2 dist=0 場景）

---

## Impact

| 受影響元件 | 類型 | 說明 |
|------------|------|------|
| `agent/prz_encoder.py` | 主要修改 | 新增 `_get_float_opt()`；`_resolve_retract_pair()` 改用 `_get_float_opt()` + `is not None` 判定 |
| `agent/tests/test_prz_retract.py` | 測試補全 | 重啟 task 13.2；加入 7 個 Case 1–4 含零值邊界測試 |
| `openspec/specs/prz-motion-time/spec.md` | Delta spec | Case 2 drop2 公式、Case 3 drop2 語意、觸發契約定義更新 |
| 下游 PRZ 消費端 | 行為通知 | Case 2 的 `drop2` 從 `max(0, lift+lift2-dist)` 改為 `0.0`；任何下游依賴第二段回退距離公式的消費端需重新評估 |
