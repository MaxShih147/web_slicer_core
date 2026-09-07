## Context

### 現況

`prz_encoder.py` 是將切片結果封裝為 `.prz` 二進位格式的核心模組。其中計時相關的欄位目前存在三類問題：

| 問題 | 具體位置 | 影響 |
|------|----------|------|
| **Hardcode** | `delay_mode = 1`（永遠固定）、`before_lift_time = 0.0`、`after_lift_time = 0.0` | 前端無法控制，韌體行為不可配置 |
| **Key 共用** | `bottom_after_retract_time` 與 `after_retract_time` 讀取同一個 config key `"Print.Rest Time After Retract"` | 底層與一般層無法獨立設定 |
| **Pydantic 缺漏** | `SLAConfig` 完全沒有任何計時欄位 | 無型別驗證、無邊界值約束 |

`_convert_v2_config_to_sla()` 與 `SLAConfig` 目前服務的是 PrusaSlicer 幾何切片流程（`layer_height`、`exposure_time`、`hollowing_enable` 等），與 PRZ 列印運動控制的語意完全不同。

### 約束

- `SLAConfig` 不可修改（保護既有切片流程）
- API 輸入格式沿用 DS-Online 格式（`"Print.XXX"` section），不引入第三套命名慣例
- 向後相容：未傳入計時參數時後端以預設值運作

---

## Goals / Non-Goals

**Goals:**
- 新增 `PrzPrintTimingConfig` Pydantic model，提供型別安全的計時參數容器與邊界值驗證
- 新增 `_extract_prz_timing_config()` 從 DS-Online config dict 提取計時參數（對應表獨立維護）
- 重構 `prz_encoder.py`：解除所有計時 hardcode，實作 `delay_mode` 互斥邏輯與底層 fallback
- 底層與一般層的 `restAfterRetract`（及 `restBeforeLift`、`restAfterLift`）完全解耦

**Non-Goals:**
- 反向解析（`.prz` → API 回傳計時參數）：保留擴展空間，待前端 PRZ 讀取功能完成後實作
- 修改 `SLAConfig` 或 `_convert_v2_config_to_sla()`
- 支援 camelCase 輸入格式（統一走 DS-Online 格式）

---

## Decisions

### D1：獨立 `PrzPrintTimingConfig` 而非擴充 `SLAConfig`

**選擇**：新增獨立 model。

**理由**：`SLAConfig` 的語意是「幾何切片配置」，餵給 PrusaSlicer；`PrzPrintTimingConfig` 的語意是「列印運動控制」，餵給 PRZ encoder。兩者屬於不同關注點（concern separation）。若合併，未來 PrusaSlicer 的欄位演化與 PRZ 計時演化會相互干擾，且任何對 `SLAConfig` 的 validator 邏輯錯誤都可能破壞既有切片流程。

**捨棄替代方案**：Option A（加入 `SLAConfig`）—— 需同步修改 `_convert_v2_config_to_sla()` 的映射表，且 encoder 需改從 SLAConfig 物件讀取，影響面過大。

---

### D2：`delay_mode` 互斥邏輯落在 `prz_encoder.py` 的 `_resolve_timing_values()`

**選擇**：在 encoder 內部統一處理。

**理由**：`delay_mode` 的互斥規則是 PRZ binary 格式的不變量（invariant），不是 API 層的業務規則。由 encoder 強制執行，確保無論哪個呼叫路徑都不會產生語意矛盾的 binary（例如 `delay_mode=0` 卻有非零 `after_retract_time`）。

**互斥規則**：
- `delay_mode = 0`（lightOff 模式）：`lightOffDelay` 寫入傳入值，所有 rest 時間強制寫 `0.0`
- `delay_mode = 1`（waitTime 模式）：`lightOffDelay` 強制寫 `0.0`，rest 時間寫入傳入值

---

### D3：底層參數以 `Optional[float] = None` + `model_validator` fallback

**選擇**：Pydantic model 層處理 fallback，encoder 收到的是已解析完畢的值。

**理由**：讓 encoder 保持簡單——只接收明確的數值，不需要在 encoder 內部判斷 `None`。Pydantic 的 `model_validator(mode='after')` 在所有 field_validator 執行後運行，可安全讀取已驗證的 normal layer 值來填補底層預設值。

---

### D4：新增 DS-Online key 以 `"Print"` section 的 Title Case 格式定義

| DS-Online Key（前端傳入） | `PrzPrintTimingConfig` 欄位 |
|--------------------------|----------------------------|
| `"Exposure Delay Mode"` | `exposure_delay_mode: int` |
| `"Light-off Delay"` | `light_off_delay: float` |
| `"Rest Before Lift"` | `rest_before_lift: float` |
| `"Rest After Lift"` | `rest_after_lift: float` |
| `"Rest After Retract"` | `rest_after_retract: float` |
| `"Bottom Rest Before Lift"` | `bottom_rest_before_lift: Optional[float]` |
| `"Bottom Rest After Lift"` | `bottom_rest_after_lift: Optional[float]` |
| `"Bottom Rest After Retract"` | `bottom_rest_after_retract: Optional[float]` |

---

## 實作細節

### `PrzPrintTimingConfig` Model（`agent/models.py`）

```python
class PrzPrintTimingConfig(BaseModel):
    # delay_mode: 0=lightOff, 1=waitTime
    exposure_delay_mode: int = 1

    # lightOff 模式參數，0–120s
    light_off_delay: float = 1.0

    # waitTime 模式參數，0–60s
    rest_before_lift: float = 0.0
    rest_after_lift: float = 0.0
    rest_after_retract: float = 1.0

    # 底層獨立設定，None 時 model_validator fallback 至一般層值
    bottom_rest_before_lift: Optional[float] = None
    bottom_rest_after_lift: Optional[float] = None
    bottom_rest_after_retract: Optional[float] = None

    @field_validator('exposure_delay_mode')
    @classmethod
    def validate_delay_mode(cls, v: int) -> int:
        if v not in (0, 1):
            raise ValueError('exposure_delay_mode 必須為 0 或 1')
        return v

    @field_validator('light_off_delay')
    @classmethod
    def validate_light_off_delay(cls, v: float) -> float:
        if not 0.0 <= v <= 120.0:
            raise ValueError('light_off_delay 範圍為 0–120 秒')
        return v

    @field_validator('rest_before_lift', 'rest_after_lift', 'rest_after_retract')
    @classmethod
    def validate_rest(cls, v: float) -> float:
        if not 0.0 <= v <= 60.0:
            raise ValueError('rest 參數範圍為 0–60 秒')
        return v

    @field_validator(
        'bottom_rest_before_lift', 'bottom_rest_after_lift', 'bottom_rest_after_retract',
        mode='before'
    )
    @classmethod
    def validate_bottom_rest(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and not 0.0 <= v <= 60.0:
            raise ValueError('bottom rest 參數範圍為 0–60 秒')
        return v

    @model_validator(mode='after')
    def apply_bottom_fallbacks(self) -> 'PrzPrintTimingConfig':
        if self.bottom_rest_before_lift is None:
            self.bottom_rest_before_lift = self.rest_before_lift
        if self.bottom_rest_after_lift is None:
            self.bottom_rest_after_lift = self.rest_after_lift
        if self.bottom_rest_after_retract is None:
            self.bottom_rest_after_retract = self.rest_after_retract
        return self
```

---

### `_extract_prz_timing_config()` 函數（`agent/api_v2.py`）

```python
_DS_TO_PRZ_TIMING: Dict[str, str] = {
    "Exposure Delay Mode":      "exposure_delay_mode",
    "Light-off Delay":          "light_off_delay",
    "Rest Before Lift":         "rest_before_lift",
    "Rest After Lift":          "rest_after_lift",
    "Rest After Retract":       "rest_after_retract",
    "Bottom Rest Before Lift":  "bottom_rest_before_lift",
    "Bottom Rest After Lift":   "bottom_rest_after_lift",
    "Bottom Rest After Retract":"bottom_rest_after_retract",
}

def _extract_prz_timing_config(config: Dict[str, Any]) -> PrzPrintTimingConfig:
    """
    從 DS-Online config dict 提取 PRZ 計時參數。
    config 支援 {"Print": {...}} 巢狀格式或扁平格式（與 _convert_v2_config_to_sla 一致）。
    未傳入的欄位使用 PrzPrintTimingConfig 的預設值。
    """
    print_config = config.get("Print", config)
    timing_dict: Dict[str, Any] = {}
    for ds_key, field_name in _DS_TO_PRZ_TIMING.items():
        if ds_key in print_config:
            timing_dict[field_name] = print_config[ds_key]
    return PrzPrintTimingConfig(**timing_dict)
```

---

### `prz_encoder.py` 重構

#### 新增內部函數 `_resolve_timing_values()`

```python
def _resolve_timing_values(
    timing: PrzPrintTimingConfig, is_bottom: bool
) -> tuple[float, float, float, float]:
    """
    回傳 (light_off_time, before_lift_time, after_lift_time, after_retract_time)。
    依 delay_mode 實施互斥邏輯。
    """
    if timing.exposure_delay_mode == 0:  # lightOff 模式
        return (timing.light_off_delay, 0.0, 0.0, 0.0)
    else:  # waitTime 模式 (delay_mode == 1)
        if is_bottom:
            return (
                0.0,
                timing.bottom_rest_before_lift,
                timing.bottom_rest_after_lift,
                timing.bottom_rest_after_retract,
            )
        else:
            return (
                0.0,
                timing.rest_before_lift,
                timing.rest_after_lift,
                timing.rest_after_retract,
            )
```

#### `_write_header()` 修改（原 line 379–402）

函數簽名加入 `timing: PrzPrintTimingConfig`：

```
移除：
  buf.write(struct.pack("B", 1))                        # delay_mode hardcoded
  buf.write(struct.pack(">f", _get_float(..., "Print.Light-off Delay", 1.0)))
  buf.write(struct.pack(">f", 0.0))                     # bottom_before_lift
  buf.write(struct.pack(">f", 0.0))                     # bottom_after_lift
  rest_time = _get_float(..., "Print.Rest Time After Retract", 1.0)
  buf.write(struct.pack(">f", rest_time))               # bottom_after_retract
  buf.write(struct.pack(">f", 0.0))                     # before_lift
  buf.write(struct.pack(">f", 0.0))                     # after_lift
  buf.write(struct.pack(">f", rest_time))               # after_retract

替換為：
  bottom = _resolve_timing_values(timing, is_bottom=True)
  normal = _resolve_timing_values(timing, is_bottom=False)

  buf.write(struct.pack("B", timing.exposure_delay_mode))
  buf.write(struct.pack(">f", bottom[0]))               # light_off_time（bottom/normal 結果相同）
  buf.write(struct.pack(">f", bottom[1]))               # bottom_before_lift_time
  buf.write(struct.pack(">f", bottom[2]))               # bottom_after_lift_time
  buf.write(struct.pack(">f", bottom[3]))               # bottom_after_retract_time
  buf.write(struct.pack(">f", normal[1]))               # before_lift_time
  buf.write(struct.pack(">f", normal[2]))               # after_lift_time
  buf.write(struct.pack(">f", normal[3]))               # after_retract_time
```

#### `_write_layer_definition()` 修改（原 line 526–537）

函數簽名加入 `timing: PrzPrintTimingConfig`：

```
移除：
  off_time = _get_float(config, "Print.Light-off Delay", default=1.0)
  buf.write(struct.pack(">f", off_time))
  buf.write(struct.pack(">f", 0.0))
  buf.write(struct.pack(">f", 0.0))
  buf.write(struct.pack(">f", _get_float(config, "Print.Rest Time After Retract", 1.0)))

替換為：
  vals = _resolve_timing_values(timing, is_bottom=is_bottom)
  buf.write(struct.pack(">f", vals[0]))                 # light_off_time
  buf.write(struct.pack(">f", vals[1]))                 # before_lift_time
  buf.write(struct.pack(">f", vals[2]))                 # after_lift_time
  buf.write(struct.pack(">f", vals[3]))                 # after_retract_time
```

---

## Risks / Trade-offs

- **新 DS-Online Key 尚無歷史先例** → 前後端必須以本設計文件定義的 key 字串為合約，建議在 `_DS_TO_PRZ_TIMING` 旁加上這份 spec 的參照，防止命名漂移。

- **Header 的 `light_off_time` 欄位只有一個**（非底層/一般層分開），兩種 `is_bottom` 的計算結果在 `delay_mode=0` 時皆為 `timing.light_off_delay`，在 `delay_mode=1` 時皆為 `0.0`，因此取 bottom 或 normal 結果相同，設計上無歧義。

- **`PrzPrintTimingConfig` 的 `bottom_rest_*` 在 `model_validator` 後永遠不為 `None`**（已 fallback），encoder 可以安全地不做 None 檢查。

- **反向解析擴展**：未來要讓 `/prz/parse` 回傳計時欄位，只需將 `PrzHeader` dataclass 的欄位對應到 `PrzPrintTimingConfig`，不需改動 model 欄位定義。
