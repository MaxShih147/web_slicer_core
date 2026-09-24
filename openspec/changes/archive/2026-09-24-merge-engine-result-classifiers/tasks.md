## 0. 前置

- [x] 0.1 確認 `unify-error-code-registry` 已完成並關單。
  - 指令：`python -m agent.tools.error_codes --check; echo "exit=$?"`
  - 預期：`exit=0`
  - **實際結果**：exit=0（尚未 archive，但 21/21 任務完成、`openspec validate` 通過）。
- [x] 0.2 記錄回歸基準（本單完成後要能證明沒有新增失敗）。
  - 指令：`pytest agent/tests -q 2>&1 | tail -3`
  - 預期：記下目前的 passed / failed 數字
  - **基準**：1052 passed, 5 failed（同 `unify-error-code-registry` 6.2 記錄的既有環境缺口：`test_prz_print_time.py`、`test_subprocess_boundary_5_11.py`、`test_support_e2e.py::TestRealEngine` 3 支）。

## 1. 原封不動搬遷（第一個檢查點）

- [x] 1.1 建 `agent/engine_rules.py`，定義 `Rule` 結構（`code` / `flows` / `stream` / `matchers` / `priority` / `fallback_by_design`）與 `Substring` 比對器。**結構中不得有 `exit_code` 欄位。**
- [x] 1.2 把 `support_classifier.VALIDATE_CODE_MAP`（5 列）與 `slicing_classifier._VALIDATE_CODE_MAP`（6 列）**原封不動**併成 `ENGINE_RULES`，交集列合併為一列並標記 `flows=("support","slice")`。**此步驟不補任何漏列。**
  - 指令：`python -c "from agent.engine_rules import ENGINE_RULES; print(len(ENGINE_RULES))"`
  - 預期：7（4 條交集 + 支撐獨有 1 + 切片獨有 2）
  - **範圍說明**：`_PROCESS_CODE_MAP`（切片專屬的 process() 例外表，3 列）、`MODEL_MISMATCH_MARKER`、`OUT_OF_BOUNDS_MARKER`、支撐的正面成功標記、切片的 STL parse / empty-model 判斷，都從未在兩支分類器間重複，本單不搬進 `ENGINE_RULES`，維持各自模組內。
- [x] 1.3 `support_classifier.py` 改薄殼：保留 `classify_support_result()` 簽名與 `SupportClassification` 型別，內部改查 `ENGINE_RULES`。
  - **設計決定**：`VALIDATE_CODE_MAP`／`NONSPECIFIC_VALIDATE_MARKERS` 常數保留、內容不變（`test_support_classifier.py` 有 pin 住 `VALIDATE_CODE_MAP` 的 5 碼集合，且此鎖定要撐到本單結束——見 2.2 之後 `PAD_CONFIG_INVALID` 會加入 support 的 `flows`，若常數是動態算的就會變 6 碼，把既有測試打壞）；只有 `classify_support_result()` 內部的查表動作改成呼叫 `engine_rules.find_code("support", err)`。
- [x] 1.4 `slicing_classifier.py` 改薄殼：保留 `classify_slice_result()` 簽名與 `SliceClassification` 型別。`INVALID_MODEL` / `MODEL_OUT_OF_BOUNDS` 的 exit-code 相依移到具名常數 `_LEGACY_EXIT0_ONLY_CODES`，附註解說明存在原因與可移除條件。
  - 同 1.3：`_VALIDATE_CODE_MAP`／`_PROCESS_CODE_MAP` 常數保留、內容不變（同樣被 `test_slicing_classifier.py` pin 住 6 碼／3 碼集合），只有查表動作改呼叫 `find_code("slice", err)`。`_PROCESS_CODE_MAP` 維持原樣，不搬進 `ENGINE_RULES`（見 1.2 範圍說明）。
- [x] 1.5 **檢查點：既有測試零修改全綠。**
  - 指令：`pytest agent/tests/test_support_classifier.py agent/tests/test_slicing_classifier.py -q; git diff --stat agent/tests/`
  - 預期：全綠，且 `git diff --stat agent/tests/` **無任何輸出**（一支既有測試都沒改）
  - **此步驟不過，不得往下。**
  - **實際結果**：96 passed。`git diff --stat agent/tests/` 只顯示 `test_support_string_contract.py`（來自上一份 change `unify-error-code-registry` 的合法擴充），`test_support_classifier.py`／`test_slicing_classifier.py` 零差異。通過。

## 2. 補漏列

- [x] 2.1 Write tests：支撐路徑遇 `Pad brim size is too small` → `PAD_CONFIG_INVALID`。
  - 指令：`pytest agent/tests/test_engine_rules.py -q -k pad_brim`
  - 預期：先紅（規則尚未加）
  - **實際結果**：先紅（`SUPPORT_GENERATION_FAILED` != `PAD_CONFIG_INVALID`），改 flows 後轉綠。
- [x] 2.2 支撐路徑加 `PAD_CONFIG_INVALID`（把該列的 `flows` 從 `("slice",)` 改成 `("support","slice")`）。
  - 預期：2.1 轉綠
- [x] 2.3 Write tests + 實作：切片路徑加 `SUPPORT_POINTS_REQUIRED`（`flows` 補上 `slice`）。
  - 先紅（`error_code=None`）→ 加 `flows=("support","slice")` 後轉綠。
- [x] 2.4 `Disabling the 'Use tilt' function` 加上 `fallback_by_design=True`，並補一支測試斷言「此訊息歸 fallback 是刻意的」。
  - 新增 `ENGINE_RULES` 明確列（`code=SUPPORT_GENERATION_FAILED`, `flows=("support",)`, `fallback_by_design=True`），並從 `support_classifier.NONSPECIFIC_VALIDATE_MARKERS` 移除，避免兩處各自維護。

## 3. 兩條新規則

- [x] 3.1 在 `agent/error_codes.py` 新增 `SUPPORT_POINT_SAMPLING_FAILED` 與 `SHRINKAGE_COMPENSATION_INVALID`（`owner=engine`，含 `engine_needles`、`http_status=422`、`retryable=false`、繁中 `note`）。
  - 指令：`python -m agent.tools.error_codes --write; python -m agent.tools.error_codes --check; echo "exit=$?"`
  - 預期：`exit=0`，且 `docs/error_codes.json` 出現兩個新 code
  - **連帶更新**：`agent/errors.py` 新增對應 2 個 factory；`test_error_code_registry.py` 的 `EXPECTED_TOTAL`／`EXPECTED_OWNER_COUNTS` 從 28/(13,15) 更新為 30/(15,15)（新增 2 碼皆 `owner=engine`），屬預期維護，非破壞既有斷言。
- [x] 3.2 Write tests + 實作：`SLA support point generator has failed.` → `SUPPORT_POINT_SAMPLING_FAILED`，`flows=("support","slice")`。
  - 真實 needle 已在 `third_party/prusaslicer_fork/src/libslic3r/SLA/SupportIslands/UniformSupportIsland.cpp:2146` 查證。
- [x] 3.3 Write tests + 實作：`the object transform is not invertible` → `SHRINKAGE_COMPENSATION_INVALID`，`flows=("support","slice")`。
  - 真實 needle 已在 `third_party/prusaslicer_fork/src/CLI/ProcessActions.cpp:868` 查證。
- [x] 3.4 擴充引擎字串契約測試到新表全部規則，並加負向檢查（變造字串必須找不到）。
  - 指令：`pytest agent/tests/test_support_string_contract.py -q`
  - 預期：全綠
  - **訂正**：`SHRINKAGE_COMPENSATION_INVALID` 原本選的 needle `"the object transform is not invertible"` 在 C++ 原始碼裡被拆成兩個相鄰字串字面值（`"...is "` 換行 `"not invertible..."`），原始檔案裡不是連續子字串（編譯後、執行期的字串才是連續的）。已改用只取前半句 `"the object transform is"` 當 needle，`error_codes.py`／`engine_rules.py` 同步修正並附註解。另新增 fixture `uniform_support_island_src`（`SLA/SupportIslands/UniformSupportIsland.cpp`）給 `SUPPORT_POINT_SAMPLING_FAILED` 的 needle，並補了這兩條新 needle 的負向檢查。

## 4. D7 挖空與切割帶原文

- [x] 4.1 Write tests：`generate_hollow` 失敗且 stderr 非空 → `detail` 含引擎原文。
  - 新檔 `agent/tests/test_hollow_and_cut_raw_stderr.py`（先前無任何測試覆蓋這兩個函式）。先紅（3 failed）後綠。
- [x] 4.2 修改 `agent/sla_operations.py` 的 `generate_hollow` 與 `cut`：攜帶原始 stderr，罐頭訊息只在 stderr 為空時使用，且不得猜測原因。
- [x] 4.3 移除切割那句「切割高度超出範圍」的猜測性文字。
  - 罐頭訊息改為中性的「沒有產生輸出檔」，不再宣稱具體原因。

## 5. Exit code 獨立性安全網

- [x] 5.1 建 `agent/tests/test_exit_code_independence.py`：對每一種已知輸出樣本，`exit_code` 分別餵 0 與 1，斷言分類結果相同。
  - 樣本範圍＝`ENGINE_RULES` 裡 `flows` 含 `slice` 的規則 ＋ `MODEL_MISMATCH_MARKER` ＋ `_LEGACY_EXIT0_ONLY_CODES` 的兩個 legacy marker；`_PROCESS_CODE_MAP`／STL-parse 檔名比對不在範圍內（design.md 只點名 `INVALID_MODEL`／`MODEL_OUT_OF_BOUNDS` 兩碼為已知未爆彈）。
- [x] 5.2 `INVALID_MODEL` 與 `MODEL_OUT_OF_BOUNDS` 兩例以 `pytest.mark.xfail(strict=True)` 標記，reason 註明「未爆彈，待 exit-code 解耦 change 拆除」。
  - 指令：`pytest agent/tests/test_exit_code_independence.py -q`
  - 預期：全綠（兩例為 xfail，其餘 pass）。`strict=True` 確保拆彈後這兩例轉綠時測試會提醒你改掉標記。
  - **實際結果**：14 passed, 2 xfailed。

## 6. 驗收

- [x] 6.1 `pytest agent/tests/test_support_classifier.py agent/tests/test_slicing_classifier.py -q` 全綠，且 `git diff --stat agent/tests/test_support_classifier.py agent/tests/test_slicing_classifier.py` 無輸出
  - **實際結果**：96 passed；`git diff --stat` 對這兩支檔案無輸出。
- [x] 6.2 `pytest agent/tests -q` 與 0.2 的基準相比無新增失敗
  - **實際結果**：1101 passed, 5 failed, 2 xfailed（0.2 基準是 1052 passed / 5 failed；同一批 5 支既有環境缺口，無新增失敗；1101 = 1052 + 49 新測試 − 0；2 xfailed 是 5.2 的預期標記）。
- [x] 6.3 `python -m agent.tools.error_codes --check` 回零
  - **實際結果**：exit=0
- [x] 6.4 手動抽驗：對同一段含 `Pad brim size is too small` 的 stderr，`classify_support_result()` 與 `classify_slice_result()` **回同一個 code**
  - 指令：`python -c "from agent.support_classifier import classify_support_result as s; from agent.slicing_classifier import classify_slice_result as c; e='Pad brim size is too small'; print(s('',e,False).error_code, c(1,'',e,'m.stl',False).error_code)"`
  - 預期：`PAD_CONFIG_INVALID PAD_CONFIG_INVALID`
  - **實際結果**：`PAD_CONFIG_INVALID PAD_CONFIG_INVALID`
