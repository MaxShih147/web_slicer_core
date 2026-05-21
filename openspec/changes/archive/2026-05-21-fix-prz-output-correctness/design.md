## Context

### grill-me 質詢過程的關鍵發現

本 change 經過 4 輪深度 grill-me 質詢與多輪源碼追蹤後形成。關鍵推導：

1. **層數缺失的物理特徵**：使用者實驗 layer_height ∈ {0.10, 0.05, 0.02} 得到 frame count 與 last Z：
   - 0.10 → 98 frames, last Z = 9.80mm
   - 0.05 → 195 frames, last Z = 9.75mm
   - 0.02 → 486 frames, last Z = 9.72mm

   完美擬合公式 `num_frames = floor((10 - 0.30) / layer_height) + 1`，其中 0.30mm 為硬編碼常數。

2. **根因定位**：在 [SLAPrintSteps.cpp:650](third_party/prusaslicer_fork/src/libslic3r/SLAPrintSteps.cpp#L650) 找到首 frame 寫入用 `ilh = initial_layer_height = 0.30`（[PrintConfig.cpp:4502](third_party/prusaslicer_fork/src/libslic3r/PrintConfig.cpp#L4502) 預設）。

3. **PRZ writer 是 Python**：原以為 PRZ 由 fork 的 `SL1Archive` 衍生類寫出，實際是 [agent/prz_encoder.py](agent/prz_encoder.py) 純 Python 移植自 Mechado C++。所有 4 項修正都在 Python 層完成，fork 不動。

4. **使用者決策**：
   - 首層意圖 = **全部均一層厚（取消加厚首層）** ← 排除「保留 thick burn-in layer」的設計選項
   - retract 「傳入值」語意 = **任何 falsy（None / 0 / 0.0 / ""）** ← 排除「key 存在但值為 None 才算未傳入」的較嚴謹語意
   - print time 重寫的源頭 = **從 PRZ 參數從物理推導**（含加速度與所有 Rest 時間）

### 既有架構約束

- `SLAConfig` 服務 PrusaSlicer 幾何切片流程，本 change 加欄位但**不修改既有欄位語意**。
- `PrzPrintTimingConfig`（[2026-05-18 archive](openspec/changes/archive/2026-05-18-add-prz-timing-params) 引入）服務 PRZ 寫入流程的計時參數，本 change 不修改。
- PRZ binary layout 由 Mechado C++ 鎖定（[prz_encoder.py header @ line 313-517](agent/prz_encoder.py#L313-L517)），本 change **不變動任何 byte offset / 欄位順序**，僅變動欄位**內容值**（mL → mm³）。
- `prz_decoder.py` 解析欄位的 offset 與型別不動，僅語意（unit）變動。

---

## Goals / Non-Goals

**Goals**：
- PRZ volume / weight / price 三欄輸出單位從 mL 改為 mm³。
- 切 10mm cube + 0.05mm layer_height 得 200 frame、最後 frame Z = 10.00。
- PRZ print_time 由 encoder 內部從 PRZ-aware 物理公式推導，與實機列印時間在合理誤差內（Phase 1 目標 ≤15%，Phase 2 加速度模型後 ≤5%）。
- PRZ retract 4 欄位支援 4-case override 邏輯，含新版 Case 4 強制 retract = 0.0 / drop2 = lift + lift2。

**Non-Goals**：
- 不修改 PrusaSlicer fork 任何 C++ 程式碼（fork 預設值錯誤透過 WSC 端 config 覆寫處理）。
- 不修改 PRZ binary 格式 layout、byte offset、欄位定義。
- 不修改 `prz_decoder.py` 的 offset 對映與型別（僅 unit 語意變更）。
- 不修改 `_convert_v2_config_to_sla()` 既有 SLA 欄位映射。
- Phase 1 不引入加速度（acceleration）模型；以等速近似上線，誤差容忍 ≤15%。

---

## Decisions

### D1：`initial_layer_height` 修正放 Python 端 SLAConfig 而非 fork

**選擇**：在 [agent/models.py](agent/models.py) `SLAConfig` 新增 `initial_layer_height` 欄位，透過 `model_validator` fallback 到 `layer_height`。

**理由**：
- fork 是 third-party submodule，修改 [PrintConfig.cpp:4502](third_party/prusaslicer_fork/src/libslic3r/PrintConfig.cpp#L4502) 的 `0.3` 預設值會造成 upstream rebase 衝突。
- WSC 端透過 INI 顯式 override 即可，無侵入性。
- 同時保留「使用者未來想要 thick first layer 時直接傳值即可」的延展性。

**捨棄替代方案**：
- (A) 改 fork PrintConfig.cpp 預設 → 與 upstream 漂移。
- (B) 在 [generate_config_ini()](agent/sla_operations.py#L87) 中硬寫 `initial_layer_height = layer_height` → 跳過 Pydantic validator，且每加一個類似 override 都要動 generate 邏輯。
- (C) 在 fork CLI 命令列加 `--initial-layer-height` flag → fork CLI 不一定支援所有 SLA config 的 CLI flag；INI 較通用。

---

### D2：Retract 4-case 新版 Case 4 行為（**已核准** — retract = 0, drop2 = lift + lift2）

**選擇（使用者核准）**：當 dist 與 drop2 都未傳入時，**強制設定 retract = 0.0、drop2 = lift + lift2**。此行為對應 Phrozen 機種的「單段回退」實機物理意圖。

**理由**：
- 「不做第一段 retract，全段下降一次到位」是 SLA resin printer 的合理 default motion model。
- `lift + lift2` 是「總上升距離」的數學上界，drop2 = 此值意味著 second-stage 一次完整退回，物理上保證 Z 軸回到起點 + layer_height。
- 對比舊版「使用系統預設」會引入「系統預設」這個需要定義的新概念，新版直接從幾何不變量推導，**消除一層 config 預設值的命名空間**。

**真值表**（為 bottom 與 normal 各跑一遍）：

| dist 傳入？ | drop2 傳入？ | 最終 dist | 最終 drop2 | Case |
|---|---|---|---|---|
| ✓ | ✓ | dist | `max(0, lift + lift2 − dist)` | 3 |
| ✓ | ✗ | dist | `max(0, lift + lift2 − dist)` | 2 |
| ✗ | ✓ | `max(0, lift + lift2 − drop2)` | drop2 | 1 |
| ✗ | ✗ | **0.0** | **lift + lift2** | **4（新版）** |

注意 Case 2 與 Case 3 程式行為相同——dist 傳入時，drop2 永遠重算。Case 3 的「強制重算 drop2 覆寫使用者傳入值」是顯式語意。

**捨棄替代方案**：
- (A) Case 4 用系統預設 → 需定義新的預設值，且預設值漂移時影響面廣。
- (B) Case 4 與 Case 1 / Case 2 對稱（也走 `max(0, lift + lift2 - 0) = lift + lift2`）→ 但需明確區分 dist 與 drop2 的角色，dist=0 應對應「無第一段」，drop2=lift+lift2 對應「第二段一次到位」，所以最終 retract = 0、drop2 = lift+lift2，不是兩個都 = lift+lift2。

---

### D3：「傳入值」語意為任意 falsy

**選擇**：dist 與 drop2 透過 `_get_float(config, key)` 取值（falsy → 0.0），`if dist:` 判斷視為傳入。

**理由**：使用者明確選擇此語意（grill-me 第 4 輪）。實作上最簡，無需引入 `Optional[float]` 或 sentinel value。

**取捨**：使用者**無法顯式傳入 retract = 0** 來達成「真的沒有第一段 retract」（會被當作 Case 4 處理，drop2 被改寫為 lift + lift2）。這是已知 trade-off：物理上 retract = 0 已對應到 Case 4 的行為（無 first-stage、全 second-stage），所以不會丟失語意。

---

### D4：print_time 物理公式 Phase 1 採等速模型（**已核准，Phase 2 移出本 change**）

**選擇**：每段 motion 用 `t = distance / speed`（若皆 > 0，否則 t = 0）。

**理由**：
- PRZ header 目前無 acceleration 欄位，引入加速度需新增 config key。
- 無使用者實機量測數據前，acceleration 預設值無從決定。
- 等速模型可立即上線並作為未來加速度模型的對拍 baseline。

**已知 trade-off（已核准上線）**：等速模型對短距離頻繁起停的 SLA 流程造成 **20%~40% 時間低估**（見 Risks 章節）。

**Phase 2（acceleration 模型）已移出本 change 的工作範疇**，由獨立 change 接續處理；本 change 的 tasks.md 不再包含 Phase 2 任務。

**捨棄替代方案**：
- (A) 直接寫加速度公式但 a 用預設 100 mm/s² → 預設值瞎填，誤差不可控。
- (B) 全程沿用 fork 估值 → 不滿足使用者「完全重寫」要求。

---

### D5：速度單位強制 mm/min → mm/s 轉換（**已鎖定 / 致命坑修正**）

**已確認事實**（使用者最終決策）：
- 實機 UI 與使用者傳入 API 的速度配置單位 = **mm/min**（典型值 60、120 等）。
- 物理公式 `t = d / v` 必須使用 SI 單位（mm 與 mm/s），否則時間單位不一致。
- PRZ binary 寫入端對速度欄位的語意 = mm/min（與韌體期望一致），**不能改**。

**選擇**：`_compute_print_time()` 在讀取所有速度參數（`Bottom Lifting Speed`、`Lifting Speed`、`Bottom Lifting Second Speed`、`Lifting Second Speed`、`Bottom Retract Speed`、`Normal Retract Speed`、`Bottom Retract Second Speed`、`Normal Retract Second Speed`）後，SHALL **強制將該值 ÷ 60 轉換為 mm/s** 後再代入 `motion_time(d, v)`。

```python
def _to_mm_per_sec(v_mm_per_min: float) -> float:
    """將 UI / config 的 mm/min 速度單位轉換為 mm/s，供物理公式使用。"""
    return v_mm_per_min / 60.0 if v_mm_per_min else 0.0
```

**為什麼這是致命坑**：若漏掉這層轉換，時間估算會出現 **60× 誤差**——例如真實 60 秒列印會被估成 1 小時。等速模型本就低估 20–40%，再疊加 60× 單位錯誤後完全失去意義，連 baseline 都不能信。

**距離單位**：保持 mm（與 lift / retract / drop2 距離參數一致）。
**輸出單位**：秒（int 截斷後寫入 PRZ header）。

**約束範圍**：此轉換**僅**適用於 `_compute_print_time()` 內部物理推導。PRZ binary 中速度欄位的寫入（line 459–474、575–595）寫的仍是 raw mm/min 值，那是給韌體用的。換言之：`_compute_print_time()` 是**唯一**需要做單位轉換的地方。

**單元測試必須涵蓋**（regression guard）：
- `Lifting Speed = 60` mm/min（= 1 mm/s）+ `Lifting Distance = 1` mm → 對應段時間 = 1.0 秒
- `Lifting Speed = 120` mm/min（= 2 mm/s）+ `Lifting Distance = 1` mm → 對應段時間 = 0.5 秒
- 若漏掉 ÷ 60 → 上述兩例會分別錯算為 0.0167 秒與 0.0083 秒（60× 低估），測試 SHALL 抓到此 regression。

**捨棄替代方案**：
- (A) 同時接受 mm/s 與 mm/min（透過 config flag 切換）→ 引入額外的判斷分支，違反「PRZ 寫入端與 UI 慣例對齊」的不變量。
- (B) 在 PRZ 寫入時把速度欄位也 ÷ 60 寫成 mm/s → 會破壞既有韌體期望的 mm/min 語意。

---

## 公式推導

### 每層 motion cycle 順序（由 [_write_layer_definition()](agent/prz_encoder.py#L522) 欄位順序鎖定）

```
1. Expose          for exposure_time (light on)
2. Light off       for light_off_time
3. Wait            for before_lift_time
4. Lift stage 1    distance=LiftDist,       speed=LiftSpeed
5. Lift stage 2    distance=LiftSecondDist, speed=LiftSecondSpeed
6. Wait            for after_lift_time
7. Retract stage 1 distance=RetractDist,       speed=RetractSpeed
8. Retract stage 2 distance=RetractSecondDist, speed=RetractSecondSpeed
9. Wait            for after_retract_time
```

每層時間（速度先 ÷ 60 轉成 mm/s，見 D5）：

```
T_layer = exposure(layer_idx)
        + light_off_time
        + before_lift_time
        + (LiftDist        / (LiftSpeed/60)        if both > 0 else 0)
        + (LiftSecondDist  / (LiftSecondSpeed/60)  if both > 0 else 0)
        + after_lift_time
        + (RetractDist     / (RetractSpeed/60)     if both > 0 else 0)
        + (RetractSecondDist / (RetractSecondSpeed/60) if both > 0 else 0)
        + after_retract_time
```

說明：所有 `*Speed` 來源為 mm/min（UI / config 慣例），代入物理公式前 ÷ 60 轉成 mm/s。距離 mm，時間秒，單位閉合。

`exposure(layer_idx)` 依 [_write_layer_definition() @ line 543-555](agent/prz_encoder.py#L543-L555) 的 ramp 邏輯：

```
if layer_idx < bottom_layer_count:
    exposure = Bottom Exposure Time
elif layer_idx < bottom_layer_count + transition_layer_count:
    transition_idx = layer_idx - bottom_layer_count
    exposure = bottom_exp + (normal_exp - bottom_exp) / (1 + transition_count) * (transition_idx + 1)
else:
    exposure = Exposure Time
```

`light_off_time`、`before_lift_time`、`after_lift_time`、`after_retract_time` 由 [_resolve_timing_values()](agent/prz_encoder.py) 依 `delay_mode` 與 `is_bottom` 計算。

`LiftDist`、`LiftSecondDist`、`RetractDist`、`RetractSecondDist` 依 `is_bottom` 取 bottom / normal 對應 config 值，retract 兩欄套 4-case override（D2）。

總時間：

```
T_total = Σ T_layer  for layer_idx in 0..total_layers-1
```

---

## 實作細節

### `SLAConfig.initial_layer_height` 欄位（`agent/models.py`）

```python
class SLAConfig(BaseModel):
    # ... 既有欄位 ...
    layer_height: float
    initial_layer_height: Optional[float] = None  # 新增

    @model_validator(mode='after')
    def fallback_initial_layer_height(self) -> 'SLAConfig':
        if self.initial_layer_height is None:
            self.initial_layer_height = self.layer_height
        return self
```

### `_resolve_retract_pair()` helper（`agent/prz_encoder.py`）

```python
def _resolve_retract_pair(
    config: dict,
    dist_key: str,
    drop2_key: str,
    lift: float,
    lift2: float,
) -> tuple[float, float]:
    """
    回傳 (retract_distance, retract_second_distance)。
    falsy（None/0/0.0/""）視為未傳入。4-case override 邏輯（詳見 D2 真值表）。
    """
    dist  = _get_float(config, dist_key)
    drop2 = _get_float(config, drop2_key)
    if dist:                                  # Case 2 + Case 3
        return dist, max(0.0, lift + lift2 - dist)
    if drop2:                                 # Case 1
        return max(0.0, lift + lift2 - drop2), drop2
    return 0.0, lift + lift2                  # Case 4（新版）
```

### `_compute_print_time()` helper（`agent/prz_encoder.py`）

```python
def _compute_print_time(
    config: dict,
    total_layers: int,
    timing: PrzPrintTimingConfig,
) -> float:
    """從 PRZ-aware 參數推導列印時間（秒），Phase 1 採等速模型。"""
    bottom_count = _get_int(config, "Print.Bottom Layer Count", default=5)
    transition_count = _get_int(config, "Print.Transition Layer Count", default=5)
    bottom_exp = _get_float(config, "Print.Bottom Exposure Time", default=35.0)
    normal_exp = _get_float(config, "Print.Exposure Time", default=2.5)

    def _to_mm_per_sec(v_mm_per_min: float) -> float:
        return v_mm_per_min / 60.0 if v_mm_per_min else 0.0

    def motion_time(d: float, v_mm_per_min: float) -> float:
        """d in mm, v in mm/min (UI 慣例)。內部 ÷ 60 轉 mm/s。回傳秒。"""
        v = _to_mm_per_sec(v_mm_per_min)
        return d / v if d > 0 and v > 0 else 0.0

    total = 0.0
    for layer_idx in range(total_layers):
        is_bottom = layer_idx < bottom_count
        vals = _resolve_timing_values(timing, is_bottom=is_bottom)

        # 1. exposure（含 transition ramp）
        if is_bottom:
            exposure = bottom_exp
        else:
            transition_idx = layer_idx - bottom_count
            if 0 <= transition_idx < transition_count:
                exposure = bottom_exp + (normal_exp - bottom_exp) / (1.0 + transition_count) * (transition_idx + 1.0)
            else:
                exposure = normal_exp

        # 2-9. motion + rest
        if is_bottom:
            lift  = _get_float(config, "Print.Bottom Lifting Distance", default=8.0)
            lift2 = _get_float(config, "Print.Bottom Lifting Second Distance")
            lift_v  = _get_float(config, "Print.Bottom Lifting Speed", default=50.0)
            lift2_v = _get_float(config, "Print.Bottom Lifting Second Speed")
            retract, drop2 = _resolve_retract_pair(
                config, "Print.Bottom Retract Distance",
                "Print.Bottom Retract Second Distance", lift, lift2
            )
            retract_v = _get_float(config, "Print.Bottom Retract Speed", default=100.0)
            drop2_v   = _get_float(config, "Print.Bottom Retract Second Speed")
        else:
            lift  = _get_float(config, "Print.Lifting Distance", default=7.0)
            lift2 = _get_float(config, "Print.Lifting Second Distance")
            lift_v  = _get_float(config, "Print.Lifting Speed", default=50.0)
            lift2_v = _get_float(config, "Print.Lifting Second Speed")
            retract, drop2 = _resolve_retract_pair(
                config, "Print.Retract Distance",
                "Print.Retract Second Distance", lift, lift2
            )
            retract_v = _get_float(config, "Print.Normal Retract Speed", default=100.0)
            drop2_v   = _get_float(config, "Print.Normal Retract Second Speed")

        total += (
            exposure
            + vals[0]                              # light_off_time
            + vals[1]                              # before_lift_time
            + motion_time(lift,  lift_v)
            + motion_time(lift2, lift2_v)
            + vals[2]                              # after_lift_time
            + motion_time(retract, retract_v)
            + motion_time(drop2,   drop2_v)
            + vals[3]                              # after_retract_time
        )

    return total
```

### `encode_prz()` 簽章變更

```python
def encode_prz(
    config: dict,
    sl1_path: Path,
    timing: PrzPrintTimingConfig,
    estimated_print_time: float = 0,      # 廢棄但保留接收，不再使用
    resin_volume_mm3: float = 0,          # 新名稱（取代 resin_volume_ml）
    preview_small_rgb: Optional[np.ndarray] = None,
    preview_large_rgb: Optional[np.ndarray] = None,
) -> bytes:
    # ...
    # 不再用 estimated_print_time 參數，改在內部呼叫 _compute_print_time()
```

`_write_header()` 對應：

```python
# Print Times (4B int BE) — 改用 internal 計算
print_time = _compute_print_time(config, total_layers, timing)
buf.write(struct.pack(">I", int(print_time)))

# Volume (4B float BE) — 直接寫 mm³
volume = resin_volume_mm3 or _get_float(config, "Other.volume")
buf.write(struct.pack(">f", volume))

# Weight + Price 同步寫 mm³ 值（複用，鏡像 C++ 原作）
buf.write(struct.pack(">f", volume))
buf.write(struct.pack(">f", volume))
```

---

## Risks / Trade-offs

- **mL → mm³ 是 breaking change**：任何讀 PRZ volume / weight / price 並期待 mL 的下游消費端會看到 1000× 數值。已驗證 [agent/](agent/) 內無此類消費，但**前端 / 韌體若有依賴需同步通知**。
- **`estimated_print_time` 參數廢棄但簽章保留**：避免 caller chain 全改；參數仍接收但被忽略，下次 cleanup 可移除。
- **Phase 1 等速模型未考慮減速區（重大風險，已核准）**：等速模型假設馬達瞬間達到目標速度、瞬間停止，但實機 SLA 每層 motion cycle 包含多次短距離起停（lift1 → lift2、retract1 → retract2 都是獨立段），每段都有加減速過程。對短距離頻繁起停的 SLA 流程，**等速模型會造成 20%~40% 的時間低估**。Phase 1 接受此風險上線，作為 acceleration 模型的 baseline；Phase 2 工作項已從本 change 剪枝，由獨立 change 接續。
- **速度單位已鎖定為 mm/min（D5）**：`_compute_print_time()` 內部 SHALL ÷ 60 轉成 mm/s 再代入物理公式。若漏轉 → 60× 時間低估，與等速模型 20–40% 低估疊加後完全失去意義。單元測試（spec Scenario）為主要 regression guard。
- **Case 4 行為改變對既有 PRZ 輸出**：若使用者既有 config 未傳 retract dist 與 drop2（走舊版 Case 4 = 系統預設），新版改成 `retract = 0, drop2 = lift + lift2`，可能改變 motion 模式。**建議在 release notes 強調此 behavior change**。
- **`initial_layer_height` 新欄位若 user 顯式傳值**：表示 user 真的想要 thick first layer，本 change 不阻止；但需確認 PRZ writer 與 SLAConfig 的 `layer_height` 共用情境下不會誤觸層數 mismatch（首層厚度不等於 layer_height 時 200 frame 的契約失效——這是 user 主動選擇的 trade-off）。

---

## Known Issues（已知遺留問題）

### KI-1：Retract Distance 設為總長且 Second 為 0 時落入 Case 4 的邊界現象

**狀態**：待與前端 DS-online 對齊 Falsy 語意，本階段暫不修正。

**現象描述**：
當使用者顯式傳入 `"Print.Retract Distance": <lift + lift2>` 且 `"Print.Retract Second Distance": 0`（或未傳入）時：
- 預期走 Case 2（dist 有值 → retract = dist, drop2 = max(0, lift+lift2-dist) = 0）
- 實測行為：若前端以 `0`（而非 `null`/omit）傳遞 Second Distance，`_get_float()` 取到 `0.0` → `if dist:` 判斷視 Second Distance falsy，仍正確走 Case 2。
- **但**：若前端省略 `Print.Retract Distance` key 但 `Print.Retract Second Distance` 也設 0，會落入 Case 4（`retract=0, drop2=lift+lift2`），與使用者意圖（無 retract 動作）一致，**但 drop2 被設為 lift+lift2 而非 0**。

**根因推測**：前端 DS-online 傳入「falsy 值語意」與 D3 設計假設（任意 falsy 視為未傳入）可能不對齊；前端有時傳 `0` 意圖表達「第二段 retract = 0 mm」，但被 `if dist:` 判斷視為 Case 4 的「未傳入」語意。

**影響範圍**：僅在 `dist = 0 AND drop2 = 0` 的特殊組合下觸發。Case 1/2/3 行為正常。

**暫不修正原因**：修正需與前端對齊「如何區分『顯式傳 0』與『未傳入』」的 API 語意，屬跨系統協議變更；本階段不引入此複雜度。

**待辦**：與 DS-online 前端對齊後，若需區分，可在 API layer 改用 `Optional[float]` 並以 `None` 表示未傳入，`0.0` 表示顯式零值。
