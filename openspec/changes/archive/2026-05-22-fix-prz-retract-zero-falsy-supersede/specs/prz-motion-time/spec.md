## MODIFIED Requirements

### Requirement: PRZ Retract 4-case Override 邏輯

`prz_encoder.py` SHALL 在寫入 `Retract Distance` 與 `Retract Second Distance`（含 `Bottom` 變體）時，依下表 4 種情境分別處理：

| Case | dist 傳入？ | drop2 傳入？ | 最終 dist | 最終 drop2 | 與舊版差異 |
|------|------------|------------|-----------|------------|-----------|
| 1 | ✗（None） | ✓（非 None，含 0.0） | `max(0.0, lift + lift2 - drop2)` | drop2 | 不變 |
| 2 | ✓（非 None，含 0.0） | ✗（None） | dist | **0.0** | BREAKING：舊版為 `max(0, lift+lift2-dist)` |
| 3 | ✓（非 None，含 0.0） | ✓（非 None，含 0.0） | dist | **drop2（保留原值）** | BREAKING：舊版強制重算覆寫 drop2 |
| 4 | ✗（None） | ✗（None） | `0.0` | `lift + lift2` | 不變 |

**「傳入 ≠ None」語意定義**：`_get_float_opt(config, key)` 回傳非 `None`，包含顯式 `0.0`。
key 不存在或 config 中該位置為 `None` 則為「缺失（None）」。

**Case 4 布林判定式（唯一觸發條件）**：
```
dist is None AND drop2 is None
```
顯式傳入 `0.0` 不滿足此條件；僅 key 不存在或為 `None` 才觸發 Case 4。

bottom 與 normal SHALL 各自獨立套用此邏輯（共 4 種變體：bottom_retract / bottom_drop2、normal_retract / normal_drop2）。

#### Scenario: Case 1 — 僅 drop2 傳入（行為不變）
- **WHEN** config 含 `"Print.Retract Second Distance": 3.0`，未含 `"Print.Retract Distance"` key
- **AND** `Lifting Distance + Lifting Second Distance = 8.0`
- **THEN** PRZ header 與 per-layer 的 normal retract = 5.0、drop2 = 3.0

#### Scenario: Case 1 drop2=0.0 邊界（舊版錯落 Case 4，KI-1 翻案）
- **WHEN** config 含 `"Print.Retract Second Distance": 0.0`，未含 `"Print.Retract Distance"` key
- **AND** `Lifting Distance + Lifting Second Distance = 8.0`
- **THEN** PRZ header 與 per-layer 的 normal retract = `8.0`（`max(0, 8.0 - 0.0)`）、drop2 = `0.0`
- **AND** 不得落入 Case 4（`drop2 = 0.0` 為顯式傳入，非缺失）

#### Scenario: Case 1 underflow clamp
- **WHEN** Case 1 中 `drop2 = 99.0`，但 `lift + lift2 = 8.0`
- **THEN** retract = `max(0.0, 8.0 - 99.0) = 0.0`（clamp 而非負值）

#### Scenario: Case 2 — 僅 dist 傳入（BREAKING：drop2 固定為 0.0）
- **WHEN** config 含 `"Print.Retract Distance": 2.0`，未含 `"Print.Retract Second Distance"` key
- **AND** `Lifting Distance + Lifting Second Distance = 8.0`
- **THEN** PRZ header 與 per-layer 的 normal retract = 2.0、drop2 = **0.0**
- **AND** drop2 SHALL NOT 等於 `6.0`（舊版 `max(0, 8-2)` 公式已廢棄）

#### Scenario: Case 2 dist=0.0 邊界（KI-1 根因翻案）
- **WHEN** config 含 `"Print.Retract Distance": 0.0`，未含 `"Print.Retract Second Distance"` key
- **THEN** PRZ header 與 per-layer 的 normal retract = `0.0`、drop2 = `0.0`
- **AND** 不得落入 Case 4（`dist = 0.0` 為顯式傳入，非缺失）
- **AND** PRZ 寫入後解碼確認兩值均為 `0.0`

#### Scenario: Case 3 — dist 與 drop2 都傳入（BREAKING：drop2 保留原值）
- **WHEN** config 含 `"Print.Retract Distance": 2.0` 與 `"Print.Retract Second Distance": 99.0`
- **AND** `Lifting Distance + Lifting Second Distance = 8.0`
- **THEN** PRZ header 與 per-layer 的 normal retract = 2.0、drop2 = **99.0**（保留原值）
- **AND** drop2 SHALL NOT 等於 `6.0`（舊版強制重算已廢棄）

#### Scenario: Case 3 drop2=0.0 邊界
- **WHEN** config 含 `"Print.Retract Distance": 2.0` 與 `"Print.Retract Second Distance": 0.0`
- **THEN** PRZ header 與 per-layer 的 normal retract = 2.0、drop2 = `0.0`（使用者傳入值保留）
- **AND** 不得落入 Case 2（drop2 key 存在且為 0.0，非缺失）

#### Scenario: Case 4 — 兩者都缺失（嚴格 None 判定）
- **WHEN** config 中 `"Print.Retract Distance"` 與 `"Print.Retract Second Distance"` 完全不存在，或顯式為 `None`
- **AND** `Lifting Distance + Lifting Second Distance = 8.0`
- **THEN** PRZ header 與 per-layer 的 normal retract = `0.0`，drop2 = `8.0`

#### Scenario: Case 4 邊界 — lift 與 lift2 都為 0
- **WHEN** Case 4 觸發，且 `lift = 0, lift2 = 0`
- **THEN** retract = 0.0、drop2 = 0.0（不出錯）

#### Scenario: bottom 與 normal 獨立
- **WHEN** config 含 `"Print.Bottom Retract Distance": 1.0`（Case 2 for bottom）、`"Print.Retract Second Distance": 4.0`（Case 1 for normal）
- **THEN** bottom retract = 1.0、bottom drop2 = `0.0`（Case 2 新行為：無 drop2 key → 固定 0.0）
- **AND** normal retract = `max(0, lift_n + lift2_n - 4.0)`、normal drop2 = 4.0
- **AND** 兩組互不干擾
