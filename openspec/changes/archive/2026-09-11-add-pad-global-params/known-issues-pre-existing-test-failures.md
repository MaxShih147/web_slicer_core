# 已知問題：2 個既有測試失敗（與本次 change 無關）

**發現時間**：本次 `add-pad-global-params` 執行 `pytest agent/tests/` 全套件時發現。
**驗證方式**：`git stash` 還原到本次改動前的 baseline，兩者皆已失敗，證實與底墊參數
無關，非本次回歸。**不擋本次 change 的完工／archive**，僅作獨立追蹤記錄。

---

## 問題 1：`test_prz_print_time.py::test_6_11_single_normal_layer_full_params`

**現象**：`assert t == pytest.approx(14.0)` 失敗，實際值為 `11.0`，差 `3.0` 秒。

**根本原因**：測試的期望值算法已過期，沒有跟上另一個獨立 change 對退料
（retract）二段式邏輯的**刻意**行為變更。

- 退料動作分兩段：第一段 `retract`、第二段 `drop2`。
- **舊規則**（本測試期望值所依據的規則）：只提供 `Retract Distance`（第一段）
  時，系統自動反推第二段 `drop2 = max(0, lift + lift2 - dist)`，讓兩段之和
  等於升起總距離。
- 這個「自動補滿」規則在 `fix-prz-retract-zero-falsy-supersede`
  （2026-05-22 封存）被判定為 bug：系統原本用 `if dist:` 判斷「是否有傳
  值」，導致使用者顯式傳入 `dist = 0.0`（真的想要「不退」）與「完全沒傳」
  無法區分，兩者都被當成「沒傳」而觸發自動補滿。
- 該 change 修正判斷邏輯的同時，**刻意**把 Case 2（只傳 `dist`）的行為改為
  `drop2 = 0.0`（不再自動補滿），並在文件中明確標記為 **BREAKING**
  （見該 change 的 design.md D4：「Case 2 語意決策——`drop2 = 0.0`」）。
- `test_prz_print_time.py` 的測試案例（很可能是更早的
  `sync-prz-print-time` change 所寫）沒有跟著這次語意變更更新期望值，
  註解裡仍寫著舊公式 `drop2=max(0,5+2-4)=3mm`，導致期望總時間仍是舊算法的
  `14.0`，而程式碼已照新規則算出 `11.0`。

**結論**：不是程式碼 bug，是一份沒跟上規則變更的舊測試。修法是把
`test_prz_print_time.py` 這個案例的期望值（與可能存在的其他同類案例）
依 `fix-prz-retract-zero-falsy-supersede` 的新真值表重新核算。

**相關檔案**：
- `agent/tests/test_prz_print_time.py:174`
- `agent/prz_encoder.py` 的 `_resolve_retract_pair()`
- `openspec/changes/archive/2026-05-22-fix-prz-retract-zero-falsy-supersede/design.md`

---

## 問題 2：`test_subprocess_boundary_5_11.py::test_engine_runs_as_separate_process`

**現象**：`async def functions are not natively supported` 直接報錯，測試
沒有真正執行到內容。

**根本原因**：環境缺套件，不是邏輯錯誤。

- 這個測試函式是 `async def`，並標記 `@pytest.mark.asyncio`——這個標記
  只有裝了 `pytest-asyncio` 套件才會被辨識、才知道要用非同步的方式執行
  這個函式。
- 目前 `.venv` 只裝了 `anyio`（`pip show pytest-asyncio` 回報未安裝）。
  `anyio` 也能跑 async 測試，但它認的標記是 `@pytest.mark.anyio`，不是
  `@pytest.mark.asyncio`。
- 兩者標記不同、誰也不認得對方的標記，所以 pytest 找不到任何外掛能處理
  這個 async 函式，只好把它當一般同步函式硬跑，直接失敗。

**結論**：裝 `pytest-asyncio`（或把測試改用 `@pytest.mark.anyio` 搭配
現有的 `anyio` 套件）即可修復，屬於環境／相依套件設定問題。

**相關檔案**：
- `agent/tests/test_subprocess_boundary_5_11.py:26-27`

---

## 待處理（不在本次 change 範圍）

- [ ] 核算 `test_prz_print_time.py` 受影響的測試案例，依新 retract 真值表
      更新期望值。
- [ ] 決定 `pytest-asyncio` 或 `@pytest.mark.anyio`，統一專案內 async
      測試的標記慣例，並更新 `requirements`／`pyproject` 相依宣告。

（若要正式立案處理，依 workspace CLAUDE.md 規則，動手前先搜尋
`DS-Online/.agents/skills/` 找相關 skill 並與使用者確認。）
