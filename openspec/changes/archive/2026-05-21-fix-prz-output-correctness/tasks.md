## 1. `SLAConfig` 加 `initial_layer_height` 欄位（`agent/models.py`）

- [x] 1.1 在 `SLAConfig` 的欄位區段新增 `initial_layer_height: Optional[float] = None`，註解標明「未設定時自動 fallback 至 `layer_height`」
- [x] 1.2 引入 `model_validator`（若尚未引入），新增 `fallback_initial_layer_height(self) -> 'SLAConfig'` with `mode='after'`：若 `self.initial_layer_height is None` 則設為 `self.layer_height`
- [x] 1.3 單元測試：建構 `SLAConfig(layer_height=0.05)` → 確認 `initial_layer_height == 0.05`
- [x] 1.4 單元測試：建構 `SLAConfig(layer_height=0.05, initial_layer_height=0.30)` → 確認 `initial_layer_height == 0.30`（user 顯式 override 路徑保留）
- [x] 1.5 整合測試：呼叫 `generate_config_ini(config, ...)` → 確認產生的 INI 中含 `initial_layer_height = 0.05` 一行

## 2. 驗證 #2 端對端修正

- [x] 2.1 編譯後跑 10×10×10mm cube 切片，`layer_height = 0.05`，無顯式設定 `initial_layer_height`
- [x] 2.2 解 PRZ → 驗證 `total_layers == 200`
- [x] 2.3 解 PRZ → 驗證最後一層的 `LayerPositionZ == 10.00`
- [x] 2.4 解 PRZ → 驗證任一層 `layer_height == 0.05`（含第 1 層）

## 3. 新增 `_resolve_retract_pair()` helper（`agent/prz_encoder.py`）

- [x] 3.1 在 `prz_encoder.py` 適當位置（建議 `_write_header()` 之前）新增 `_resolve_retract_pair(config, dist_key, drop2_key, lift, lift2) -> tuple[float, float]` 函數
- [x] 3.2 實作 4-case 邏輯（Case 1/2/3 含 `max(0.0, ...)` clamp，Case 4 回傳 `(0.0, lift + lift2)`）
- [x] 3.3 單元測試 Case 1：`dist=0, drop2=3` → 回傳 `(max(0, lift+lift2-3), 3)`
- [x] 3.4 單元測試 Case 2：`dist=2, drop2=0` → 回傳 `(2, max(0, lift+lift2-2))`
- [x] 3.5 單元測試 Case 3：`dist=2, drop2=99` → 回傳 `(2, max(0, lift+lift2-2))`（drop2=99 被覆寫）
- [x] 3.6 單元測試 Case 4：`dist=0, drop2=0` → 回傳 `(0.0, lift+lift2)`
- [x] 3.7 單元測試 Case 1 underflow：`dist=0, drop2=lift+lift2+1` → 回傳 `(0.0, lift+lift2+1)` (dist 被 clamp 到 0)
- [x] 3.8 單元測試 Case 4 lift+lift2=0 邊界：`lift=0, lift2=0` → 回傳 `(0.0, 0.0)`

## 4. 整合 `_resolve_retract_pair()` 到 header 寫入（`_write_header()` line 448-474）

- [x] 4.1 在 `_write_header()` line 448-457 用 `_resolve_retract_pair()` 取代既有 `bottom_lift + bottom_lift2 - bottom_drop2` 計算（bottom）
- [x] 4.2 同上對 normal（`Print.Retract Distance` + `Print.Retract Second Distance`）
- [x] 4.3 line 459-474 對應寫入點不變，但寫入值來自 helper 回傳的 `(retract, drop2)`
- [x] 4.4 整合測試：未傳 4 個 retract 欄位的 config → PRZ header 中 retract = 0、drop2 = lift + lift2（Case 4 行為）

## 5. 整合 `_resolve_retract_pair()` 到 per-layer 寫入（`_write_layer_definition()` line 567-596）

- [x] 5.1 在 `_write_layer_definition()` line 567-596（bottom 與 normal 兩段）用 `_resolve_retract_pair()` 取代既有計算
- [x] 5.2 移除舊有的 `if retract <= 0.0: retract = lift + lift2`（line 572-573 與 587-588）——此 fallback 已被 helper 的 Case 4 取代
- [x] 5.3 整合測試：解 PRZ → 驗證 per-layer 的 retract、drop2 與 header 一致（同一層 cycle 中）

## 6. 新增 `_compute_print_time()` helper（`agent/prz_encoder.py`）

- [x] 6.1 新增模組內 helper `_to_mm_per_sec(v_mm_per_min: float) -> float`：回傳 `v / 60.0 if v else 0.0`（D5 致命單位坑修正）
- [x] 6.2 新增 `_compute_print_time(config, total_layers, timing) -> float` 函數，回傳秒
- [x] 6.3 函數內定義 `motion_time(d, v_mm_per_min)`：**內部呼叫 `_to_mm_per_sec()` 轉換後**再做 `d / v`；若 d 或 v 為 0 回 `0.0`
- [x] 6.4 外層迴圈 `for layer_idx in range(total_layers)`，按 design.md 公式累加
- [x] 6.5 內部判斷 `is_bottom = layer_idx < bottom_count`，依此取 bottom / normal 兩組 motion 參數
- [x] 6.6 exposure 計算對齊 [_write_layer_definition() @ line 543-555](agent/prz_encoder.py#L543-L555)（bottom / transition ramp / normal 三段）
- [x] 6.7 retract 兩值透過 `_resolve_retract_pair()` 取得，**復用** #3 完成的 helper
- [x] 6.8 light_off_time、before_lift_time、after_lift_time、after_retract_time 透過既有的 `_resolve_timing_values(timing, is_bottom)` 取得，**復用**
- [x] 6.9 **單元測試 — 單位轉換 regression guard**：`Lifting Speed = 60` mm/min + `Lifting Distance = 1` mm + 其餘 0 → 段時間 = `1.0` 秒（漏 ÷ 60 會錯算 `0.0167`，測試必須 fail）
- [x] 6.10 **單元測試 — 單位轉換 regression guard**：`Lifting Speed = 120` mm/min + `Lifting Distance = 1` mm → 段時間 = `0.5` 秒
- [x] 6.11 單元測試：1 個 normal layer + 已知 motion params → 手算 vs 公式比對（含 ÷ 60 轉換）
- [x] 6.12 單元測試：1 個 bottom layer → 手算 vs 公式比對（驗證 bottom params 路徑）
- [x] 6.13 單元測試：transition layer 處 exposure 線性內插值正確
- [x] 6.14 單元測試：lift2 = 0 / drop2 = 0 / speed = 0 → 對應 motion_time 段為 0，總和不含 NaN / ZeroDivisionError
- [x] 6.15 單元測試：驗證 PRZ binary 中 speed 欄位寫入仍為 raw mm/min 值（與 `_compute_print_time()` 內部的 ÷ 60 完全隔離）

## 7. `_write_header()` 整合 `_compute_print_time()`（取代 fork 估值）

- [x] 7.1 在 `_write_header()` line 486-487 處（既有 `print_time = estimated_print_time or _get_float(...)` 區塊）改為呼叫 `print_time = _compute_print_time(config, total_layers, timing)`
- [x] 7.2 廢棄 `estimated_print_time` 參數但保留簽章（避免 caller chain 大改）；加入 docstring 標記 deprecated
- [x] 7.3 整合測試：encode 後解 PRZ → `print_time == _compute_print_time(...)` 值

## 8. Volume mL → mm³ 重構（`agent/prz_encoder.py`）

- [x] 8.1 將 `encode_prz`、`encode_prz_streaming`、`_write_header` 三個函數的 `resin_volume_ml: float = 0` 參數改名為 `resin_volume_mm3: float = 0`
- [x] 8.2 更新所有 docstring（"Resin volume in ml" → "Resin volume in mm³"）
- [x] 8.3 [prz_encoder.py:490](agent/prz_encoder.py#L490) 改用 `resin_volume_mm3` 直接寫入
- [x] 8.4 line 494, 497（weight、price 複用 volume）不改邏輯，自動跟著 ×1000

## 9. Caller chain 對齊 mm³ 單位

- [x] 9.1 [agent/jobs.py:170](agent/jobs.py#L170)：jobs.py 不直接呼叫 encoder（僅寫入 status），無需修改；意圖由 9.5 保證
- [x] 9.2 [agent/main.py:637](agent/main.py#L637)：該行為 `JobStatusResponse` 欄位（API 對外 mL 語意保留），非 encoder caller — 不適用
- [x] 9.3 [agent/main.py:809](agent/main.py#L809)：同上
- [x] 9.4 [agent/api_v2.py:975](agent/api_v2.py#L975)：同上
- [x] 9.5 `agent/jobs.py` 的 `resin_volume_ml` 變數名稱**保留**（仍是從 SL1 metadata 解出的 mL 值），僅 caller 傳給 encoder 時 ×1000

## 10. 驗證 #1 端對端修正

- [x] 10.1 切 10×10×10mm cube → 解 PRZ → `volume` 欄位應 ≈ 1000 (mm³)（cube 體積範圍）
- [x] 10.2 解 PRZ → 驗證 `weight == price == volume`（鏡像不變）
- [x] 10.3 對比舊版本 PRZ → 數值應為舊版 ~1000×

## 11. 加入 `Print.Retract Distance` 與 `Print.Bottom Retract Distance` 兩個新 config key

- [x] 11.1 在 [prz_encoder.py header 區段註解](agent/prz_encoder.py) 列出新接受的 config key（前端 / API 文件參考用）
- [x] 11.2 確認 `_extract_prz_timing_config()`（`api_v2.py`）**不受影響**——這兩個新 key 不屬於 timing config，由 `prz_encoder._get_float()` 直接從 config dict 讀
- [x] 11.3 整合測試：發送含 `"Print.Retract Distance": 2.0` 的 config → 驗證 PRZ header retract = 2.0、drop2 = max(0, lift+lift2-2.0)（Case 2 路徑）

## 12. 文件 / 註解更新

- [x] 12.1 [prz_encoder.py](agent/prz_encoder.py) 模組級 docstring 加註：`volume` / `weight` / `price` 單位語意已從 mL 改為 mm³（含 release version / date）
- [x] 12.2 [prz_decoder.py:108-109](agent/prz_decoder.py#L108-L109) 註解更新：`weight: float  # same as volume in encoder (mm³ since 2026-05-21)`
- [x] 12.3 `prz_decoder.py` 對應 docstring 更新 unit 語意

## 13. 跨 capability 驗證

- [x] 13.1 端對端跑 10×10×10mm cube：200 layers、volume ≈ 1000、print_time = Σ 公式、4 retract 欄位走 Case 4
- [ ] 13.2 Case 1-4 retract 切換測試：分別在 config 中傳 dist / drop2 / 兩者 / 皆不傳，驗證最終寫入 PRZ 的值符合 design.md D2 真值表（已知限制：dist=0 落入 Case 4，詳見 design.md KI-1，本階段不予修正）
- [x] 13.3 print_time 對拍：手算一份「已知 layer count、已知 motion params（速度 mm/min）」的列印時間，與 encoder 計算值比對；**若實機列印時間數據存在，加入該對拍並驗證 20–40% 等速模型低估風險落在預期範圍**

> **註**：加速度（acceleration）模型已從本 change 範疇移出，由獨立 change 接續處理（design.md D4 / Risks）。
