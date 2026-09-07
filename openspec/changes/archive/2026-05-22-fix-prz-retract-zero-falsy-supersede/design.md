## Context

### 現況

`_resolve_retract_pair()` 在讀取 `dist` 與 `drop2` 時使用 `_get_float()`，後者在 key 不存在或值為 `None` 時回傳預設值 `0.0`。函式內部以 `if dist:` 判定「是否傳入」，導致顯式傳入 `dist = 0.0`（使用者意圖：第一段回退距離為零）與「key 完全不存在」完全無法區分——兩者皆被視為 falsy，錯落 Case 4。

此問題早在 `archive/2026-05-21-fix-prz-output-correctness` 的 **KI-1** 中預告，當時以「待前後端協議對齊」為由暫緩。本次以雙函式策略徹底翻案，無需協議變更。

### 受影響範圍

- 主體：`agent/prz_encoder.py`，僅 `_resolve_retract_pair()` 內 2 行讀值改動
- 測試：`agent/tests/test_prz_retract.py`，補全 task 13.2（Case 1–4 + 顯式零值邊界）
- Spec：`openspec/specs/prz-motion-time/spec.md`，delta 更新 Case 2/3 觸發契約

---

## Goals / Non-Goals

**Goals:**
- 修正 `_resolve_retract_pair()` 的 falsy 語意誤判，使 `dist = 0.0` 正確落入 Case 2
- 保留 `_get_float()` 原始簽章與行為，避免影響其他 ~48 個 caller
- 以 DRY 共用底層消除 `_get_float` 與 `_get_float_opt` 的重複遍歷邏輯

**Non-Goals:**
- 修改前端 API 協議（無需變更 JSON schema）
- 修改 `_get_int`、`_get_str`、`_get_list` 等其他讀值 helper
- 實作 Case 2/3 行為之外的任何 retract 邏輯變更

---

## Decisions

### D1：雙函式策略（保留 `_get_float` + 新增 `_get_float_opt`）

**選項比較：**

| 選項 | 說明 | 問題 |
|------|------|------|
| A：修改 `_get_float` 簽章回傳 `Optional[float]` | 單一函式，統一語意 | 破壞所有 ~48 個 caller（需全部補 `or 0.0`），重構風險過高 |
| B：新增 `_get_float_opt` + 保留原函式 | 局部改動 2 行，其餘 caller 零影響 | 多一個函式，但差異明確 |
| C：在 `_resolve_retract_pair` 內直接用 `.get()` 手工遍歷 | 最少改動 | 重複 dotpath 遍歷邏輯，不 DRY |

**決策：採用 B（雙函式策略）。** `_get_float()` 的「absent → 0.0」語意對物理距離參數是正確的（0.0 = 無此段運動），只有在 `_resolve_retract_pair()` 中才需要辨別「absent」與「顯式 0」。

---

### D2：DRY — 提取 `_traverse_dotpath` 共用底層

兩個函式共享同一段 dotpath 遍歷邏輯。提取 private helper 避免未來維護時兩處各自偏移：

```python
def _traverse_dotpath(config: dict, dotpath: str):
    """回傳 (found: bool, value: Any)；found=False 代表路徑中斷或 key 不存在。"""
    parts = dotpath.split(".")
    val = config
    for part in parts:
        if not isinstance(val, dict):
            return False, None
        if part not in val:
            return False, None
        val = val[part]
    return True, val


def _get_float(config: dict, dotpath: str, default: float = 0.0) -> float:
    """absent / None / 非法值 → default（0.0）；含 0.0 在內所有合法值 → float(value)。"""
    found, val = _traverse_dotpath(config, dotpath)
    if not found or val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _get_float_opt(config: dict, dotpath: str) -> Optional[float]:
    """absent / None → None；其餘（含 0.0）→ float(value)。"""
    found, val = _traverse_dotpath(config, dotpath)
    if not found or val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None
```

> `_traverse_dotpath` 與舊版 `_get_float` 的差異：舊版在路徑中斷時直接 return default，`_traverse_dotpath` 改為回傳 `(False, None)`，由 caller 自行決定如何處理缺失。

---

### D3：翻案 `_resolve_retract_pair()` 判定邏輯（取代 archive D3）

**舊版**（archive D3）：以 falsy 判定「是否傳入」
```python
dist  = _get_float(config, dist_key)   # absent → 0.0
drop2 = _get_float(config, drop2_key)  # absent → 0.0
if dist:   # 0.0 被視為 falsy → Case 2 路徑跳過
    return dist, max(0.0, lift + lift2 - dist)
if drop2:  # 同上
    return max(0.0, lift + lift2 - drop2), drop2
return 0.0, lift + lift2
```

**新版**（本 D3）：以 `is not None` 嚴格判定「是否傳入」
```python
dist  = _get_float_opt(config, dist_key)   # absent/None → None；0.0 → 0.0
drop2 = _get_float_opt(config, drop2_key)  # 同上
if dist is not None and drop2 is not None:  # Case 3
    return dist, drop2
if dist is not None:                        # Case 2
    return dist, 0.0
if drop2 is not None:                       # Case 1
    return max(0.0, lift + lift2 - drop2), drop2
return 0.0, lift + lift2                    # Case 4
```

**新 D2 真值表（本次取代 archive D2）：**

| Case | dist key | drop2 key | 最終 dist | 最終 drop2 | 與舊版差異 |
|------|----------|-----------|-----------|------------|-----------|
| 1 | 缺失 / None | 存在 ≠ None | `max(0, lift+lift2-drop2)` | drop2 | 不變 |
| 2 | 存在 ≠ None | 缺失 / None | dist | **0.0** | ← 翻案（舊：max 公式） |
| 3 | 存在 ≠ None | 存在 ≠ None | dist | **drop2（原值）** | ← 翻案（舊：重算覆寫） |
| 4 | 缺失 / None | 缺失 / None | 0.0 | lift+lift2 | 不變 |

「存在 ≠ None」≡ `_get_float_opt()` 回傳非 `None`（含 `0.0`）。  
「缺失 / None」≡ `_get_float_opt()` 回傳 `None`（key 不存在，或 config 該位置顯式為 `None`）。

**Case 4 精確布林判定式：**
```
dist is None AND drop2 is None
```
等價於：config 中 dist_key 路徑不存在或為 None，且 drop2_key 路徑不存在或為 None。顯式 `0.0` 不滿足此條件。

---

### D4：Case 2 語意決策——`drop2 = 0.0`（非 `max` 公式）

舊版 Case 2（僅傳 dist）的 `drop2 = max(0, lift+lift2-dist)` 源自「全段回退必須等於 lift 總量」的物理假設。  
翻案後改為 `drop2 = 0.0`，理由：

1. 使用者僅傳 `dist`（未傳 `drop2`），意圖是「單段回退，僅使用第一段」
2. 韌體以 `motion_time(d, v) = 0 if d == 0` 處理：`drop2 = 0.0` → 第二段靜止，行為正確
3. 若要全段回退等量，使用者應傳兩個值（Case 3）

---

## Risks / Trade-offs

**[Risk 1] Case 2 行為變更影響下游**  
→ 任何依賴「Case 2 drop2 = max(0, lift+lift2-dist)」的消費端（韌體、後處理器）需重新評估。  
→ Mitigation：在 `prz-motion-time` delta spec 明確標注 BREAKING；`_compute_print_time()` 已透過 `_resolve_retract_pair()` 取得 retract 值，自動跟著新行為，不需額外改動。

**[Risk 2] Case 3 行為變更：drop2 原值可能超出物理上限**  
→ 舊版強制重算保證了 `dist + drop2 = lift + lift2`；新版允許使用者傳入任意 `drop2`，可能造成回退距離與上升距離不等。  
→ Mitigation：此為設計決策，尊重使用者意圖；韌體容許不等距，無安全風險。

**[Risk 3] `_traverse_dotpath` 語意改變 `_get_float` 內部行為**  
→ 新的 `_traverse_dotpath` 在路徑中斷（中間節點非 dict）時回傳 `(False, None)`，再由 `_get_float` 回傳 default；舊版直接 return default。外部行為等價，但需確認單元測試覆蓋「中間節點為非 dict 值」的邊界。  
→ Mitigation：既有 `_get_float` 單元測試需在實作後完整執行，確認回歸。

**[Risk 4] `_get_float_opt` 對非法型別（dict、list）的處理**  
→ 若 config 中某 key 值為 `dict` 或 `list`，`float(val)` 會丟出 `TypeError`，`_get_float_opt` 回傳 `None`（視為缺失）。  
→ 此行為與 `_get_float` 一致（回傳 default），可接受。

---

## Migration Plan

1. 在 `_get_float` 之前插入 `_traverse_dotpath`（私有 helper，不對外）
2. 以 `_traverse_dotpath` 重構 `_get_float`（行為不變，需回歸測試）
3. 新增 `_get_float_opt`（使用 `_traverse_dotpath`）
4. 修改 `_resolve_retract_pair()` 內 2 行（`_get_float` → `_get_float_opt`）+ 更新判定邏輯
5. 更新 `_resolve_retract_pair()` docstring（移除舊 falsy 語意描述）
6. 補全 `agent/tests/test_prz_retract.py` task 13.2（7 個 Case 邊界測試）
7. 更新 `openspec/specs/prz-motion-time/spec.md`（delta：Case 2/3 觸發契約）

**Rollback：** 所有變更集中在 `_resolve_retract_pair()` + 新增 2 個函式（`_traverse_dotpath`、`_get_float_opt`），如需還原只需刪除新函式、還原 `_resolve_retract_pair()` 內 4 行。

---

## Open Questions

（無——藍圖已與顧問收斂，技術細節已全數決定。）
