## Context

兩支分類器的公開行為已由 `support-generation-error-codes` 與 `slicing-error-codes` 兩份 spec 鎖定，測試覆蓋良好。問題不在行為，在**結構**：

- `support_classifier.py:71-77` 的 `VALIDATE_CODE_MAP` 有 5 列。
- `slicing_classifier.py:44-51` 的 `_VALIDATE_CODE_MAP` 有 6 列。
- 兩張表的交集是 4 列。**各自漏掉對方有的一列。**

而且兩張表的元素形狀是 `(needle, code)` 的 tuple——**字串是主、code 是附**。這個形狀在引擎改成直接輸出 code 之後會失去意義，屆時必須換整張表的形狀。

另有一顆未爆彈：`INVALID_MODEL` 與 `MODEL_OUT_OF_BOUNDS` 目前只掛在 `slicing_classifier` 的 Path B（`exit_code == 0` 且輸出檔不存在）。引擎 `CLI/ProcessActions.cpp` 有 15 處在 `bool` 函式裡寫 `return 1`，修正後 exit code 會變 1，這兩個 code 立刻退化成 `JOB_FAILED`。

## Goals / Non-Goals

**Goals**

- 一張規則表，兩個薄殼。同一條引擎規則只登記一次。
- 表的形狀能容納未來的「引擎直接給 code」，不需重做。
- 分類**結構上**不依賴 exit code。
- 補齊已知漏列與四條新發現。

**Non-Goals**

- 不改 `INVALID_MODEL` / `MODEL_OUT_OF_BOUNDS` 的**行為**（那是後續 change）。本單只把它們隔離成具名的 legacy 分支。
- 不動引擎。
- 不改兩支分類器的公開函式簽名。
- 不改前端。

## Decisions

### D1：規則表以 error code 為主鍵，字串降級為 matcher

**決定**：

```
Rule(
  code     = "SUPPORT_HEAD_TOO_WIDE",   # 主鍵，永不改變
  flows    = ("support", "slice"),       # 這條規則屬於哪些流程
  stream   = "stderr",                   # 字串印在哪個串流
  matchers = [Substring("Invalid pinhead diameter")],
  priority = 10,
)
```

**理由**：後續 `engine-error-code-table` 只需在 `matchers` 最前面插入一個 `EngineCode("SUPPORT_HEAD_TOO_WIDE")` 比對器。列不動、code 不動、既有測試不動。

若沿用 `(needle, code)` tuple，屆時要換整張表的形狀，等於重做一次。

### D2：matcher 是**列表**，比對分層而非取代

**決定**：比對邏輯為「依序試每個 matcher，第一個命中就贏」。

**理由**：引擎與 Python **分開出版**。Bundle-Launcher 打包的是編好的引擎 binary，使用者手上可能是舊版。引擎開始輸出 code 之後，字串比對層 MUST 保留為後備，否則舊 binary 立刻全部退化。

現有實作是硬寫死的 for 迴圈跑 tuple（`support_classifier.py:150`、`slicing_classifier.py:158`），插不進第二種比對方式。本單先把迴圈改成可擴充的形狀。

**字串層的存續條件（已查證並拍板）**

引擎與 Python **同包出版**：`Bundle-Launcher/bundle-win/` 底下 `agent/`（Python）與 `slicer-engine/`（引擎 binary）在同一個 bundle，版本為整包的 `phrozen-slicergo-dental-local-agent`（現為 `v1.0.5-rc4`），`package.json` 無 auto-updater 設定，更新為整包重裝。

因此**正式環境不存在「新 Python ＋ 舊引擎」的組合**：使用者要嘛兩個都舊，要嘛兩個都新。版本歪斜只存在於**開發環境**（RD 在 repo 跑 Python，配本機較舊的自建引擎）。

字串層的退場條件（供後續 `engine-error-code-table` 執行）：

1. 引擎出 code 的那一版，字串層**保留**為第二層 fallback。
2. 同版加入契約測試：每個 `owner=engine` 的 code 在引擎原始碼中都找得到對應的 code token。
3. 該測試全綠、且該版 bundle 已出過一次之後，**下一版刪除字串層**。

刪除後省下 9 條字串常數、對應契約測試，以及「引擎改寫訊息文字就會靜默壞掉」這個長期風險。**在條件 2 成立前不得刪除。**

### D3：`exit_code` 不是規則表的欄位

**決定**：`ENGINE_RULES` 的資料結構**不含** `exit_code`。離開代碼只保留一個用途：判斷引擎是否被訊號殺死。

**分辨**：`output_file_exists` 是**可信訊號**（引擎到底有沒有生出東西，那是事實），`exit_code` 不是。合表時不得一起丟掉前者。

**行為留給後續**：`INVALID_MODEL` / `MODEL_OUT_OF_BOUNDS` 的 exit-code 相依留在呼叫端的具名 legacy 分支 `_LEGACY_EXIT0_ONLY_CODES`，附註解說明它為何存在、何時可刪，並有一支記錄現況的測試。後續 change 刪掉該分支即可，不必改 schema。

**若讓 exit_code 進表**，後續就從「刪一個分支」變成「改 schema，兩個呼叫端一起動」。

### D4：兩個舊模組改薄殼，既有測試零修改

**決定**：`classify_support_result()` 與 `classify_slice_result()` 的簽名、回傳型別、欄位語意完全不變，內部轉呼 `ENGINE_RULES`。

**驗收**：`test_support_classifier.py` 與 `test_slicing_classifier.py` **一行都不改**且全綠。**這比任何新測試更能證明相容性。**

### D5：Use tilt 明確標成「刻意歸 fallback」

**決定**：`Disabling the 'Use tilt' function` 在表上以 `fallback_by_design=True` 標記，而非從表上缺席。

**理由**：讓「漏登記」與「刻意歸類」在資料上分得開。缺席看起來就像漏了，下一個人會困惑要不要補。

### D6：`exit_code` 獨立性測試現在就寫

**決定**：`test_exit_code_independence.py` — 同一組 stdout/stderr，`exit_code` 分別餵 0 與 1，分類結果必須完全相同。

**現況**：本單完成後，此測試在 `INVALID_MODEL` 與 `MODEL_OUT_OF_BOUNDS` 兩例會**紅**——那正是未爆彈的位置。因此本單先以 `xfail` 標記那兩例並註明原因，後續 change 拆彈後改為正常斷言。

**理由**：這條測試寫上去，往後改 C++ 就不可能悄悄打壞分類。

## Risks

| 風險 | 影響 | 緩解 |
|---|---|---|
| 薄殼改寫時，某條規則的優先序被無意改動 | 高（分類結果變動） | 既有兩支測試零修改全綠；優先序在表上顯式宣告 `priority`，不依賴列的順序 |
| 新增的四條規則字串抄錯 | 中（規則永不命中，靜默失效） | 全部納入引擎字串契約測試；並加負向檢查證明斷言有牙齒 |
| `sla_operations.py` 改帶原始 stderr 後，錯誤訊息變長影響前端顯示 | 低 | 原文寫進 `detail`，前端 UI 只顯示 i18n 文案，不顯示 detail |

## Migration

1. 先完成 `unify-error-code-registry`（新增的兩個 code 要先進登錄檔）。
2. 建 `engine_rules.py`，把兩張表**原封不動**搬進去（先不補漏列）。
3. 兩支 classifier 改薄殼，跑既有測試——**必須零修改全綠**。這是第一個檢查點。
4. 才開始補四條漏列與新規則。
5. 最後改 `sla_operations.py`。

**順序不可顛倒**：步驟 3 之前補漏列，就無法用「既有測試全綠」證明搬遷無損。
