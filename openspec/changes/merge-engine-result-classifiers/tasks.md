## 0. 前置

- [ ] 0.1 確認 `unify-error-code-registry` 已完成並關單。
  - 指令：`python -m agent.tools.error_codes --check; echo "exit=$?"`
  - 預期：`exit=0`
- [ ] 0.2 記錄回歸基準（本單完成後要能證明沒有新增失敗）。
  - 指令：`pytest agent/tests -q 2>&1 | tail -3`
  - 預期：記下目前的 passed / failed 數字

## 1. 原封不動搬遷（第一個檢查點）

- [ ] 1.1 建 `agent/engine_rules.py`，定義 `Rule` 結構（`code` / `flows` / `stream` / `matchers` / `priority` / `fallback_by_design`）與 `Substring` 比對器。**結構中不得有 `exit_code` 欄位。**
- [ ] 1.2 把 `support_classifier.VALIDATE_CODE_MAP`（5 列）與 `slicing_classifier._VALIDATE_CODE_MAP`（6 列）**原封不動**併成 `ENGINE_RULES`，交集列合併為一列並標記 `flows=("support","slice")`。**此步驟不補任何漏列。**
  - 指令：`python -c "from agent.engine_rules import ENGINE_RULES; print(len(ENGINE_RULES))"`
  - 預期：7（4 條交集 + 支撐獨有 1 + 切片獨有 2）
- [ ] 1.3 `support_classifier.py` 改薄殼：保留 `classify_support_result()` 簽名與 `SupportClassification` 型別，內部改查 `ENGINE_RULES`。
- [ ] 1.4 `slicing_classifier.py` 改薄殼：保留 `classify_slice_result()` 簽名與 `SliceClassification` 型別。`INVALID_MODEL` / `MODEL_OUT_OF_BOUNDS` 的 exit-code 相依移到具名常數 `_LEGACY_EXIT0_ONLY_CODES`，附註解說明存在原因與可移除條件。
- [ ] 1.5 **檢查點：既有測試零修改全綠。**
  - 指令：`pytest agent/tests/test_support_classifier.py agent/tests/test_slicing_classifier.py -q; git diff --stat agent/tests/`
  - 預期：全綠，且 `git diff --stat agent/tests/` **無任何輸出**（一支既有測試都沒改）
  - **此步驟不過，不得往下。**

## 2. 補漏列

- [ ] 2.1 Write tests：支撐路徑遇 `Pad brim size is too small` → `PAD_CONFIG_INVALID`。
  - 指令：`pytest agent/tests/test_engine_rules.py -q -k pad_brim`
  - 預期：先紅（規則尚未加）
- [ ] 2.2 支撐路徑加 `PAD_CONFIG_INVALID`（把該列的 `flows` 從 `("slice",)` 改成 `("support","slice")`）。
  - 預期：2.1 轉綠
- [ ] 2.3 Write tests + 實作：切片路徑加 `SUPPORT_POINTS_REQUIRED`（`flows` 補上 `slice`）。
- [ ] 2.4 `Disabling the 'Use tilt' function` 加上 `fallback_by_design=True`，並補一支測試斷言「此訊息歸 fallback 是刻意的」。

## 3. 兩條新規則

- [ ] 3.1 在 `agent/error_codes.py` 新增 `SUPPORT_POINT_SAMPLING_FAILED` 與 `SHRINKAGE_COMPENSATION_INVALID`（`owner=engine`，含 `engine_needles`、`http_status=422`、`retryable=false`、繁中 `note`）。
  - 指令：`python -m agent.tools.error_codes --write; python -m agent.tools.error_codes --check; echo "exit=$?"`
  - 預期：`exit=0`，且 `docs/error_codes.json` 出現兩個新 code
- [ ] 3.2 Write tests + 實作：`SLA support point generator has failed.` → `SUPPORT_POINT_SAMPLING_FAILED`，`flows=("support","slice")`。
- [ ] 3.3 Write tests + 實作：`the object transform is not invertible` → `SHRINKAGE_COMPENSATION_INVALID`，`flows=("support","slice")`。
- [ ] 3.4 擴充引擎字串契約測試到新表全部規則，並加負向檢查（變造字串必須找不到）。
  - 指令：`pytest agent/tests/test_support_string_contract.py -q`
  - 預期：全綠

## 4. D7 挖空與切割帶原文

- [ ] 4.1 Write tests：`generate_hollow` 失敗且 stderr 非空 → `detail` 含引擎原文。
- [ ] 4.2 修改 `agent/sla_operations.py` 的 `generate_hollow` 與 `cut`：攜帶原始 stderr，罐頭訊息只在 stderr 為空時使用，且不得猜測原因。
- [ ] 4.3 移除切割那句「切割高度超出範圍」的猜測性文字。

## 5. Exit code 獨立性安全網

- [ ] 5.1 建 `agent/tests/test_exit_code_independence.py`：對每一種已知輸出樣本，`exit_code` 分別餵 0 與 1，斷言分類結果相同。
- [ ] 5.2 `INVALID_MODEL` 與 `MODEL_OUT_OF_BOUNDS` 兩例以 `pytest.mark.xfail(strict=True)` 標記，reason 註明「未爆彈，待 exit-code 解耦 change 拆除」。
  - 指令：`pytest agent/tests/test_exit_code_independence.py -q`
  - 預期：全綠（兩例為 xfail，其餘 pass）。`strict=True` 確保拆彈後這兩例轉綠時測試會提醒你改掉標記。

## 6. 驗收

- [ ] 6.1 `pytest agent/tests/test_support_classifier.py agent/tests/test_slicing_classifier.py -q` 全綠，且 `git diff --stat agent/tests/test_support_classifier.py agent/tests/test_slicing_classifier.py` 無輸出
- [ ] 6.2 `pytest agent/tests -q` 與 0.2 的基準相比無新增失敗
- [ ] 6.3 `python -m agent.tools.error_codes --check` 回零
- [ ] 6.4 手動抽驗：對同一段含 `Pad brim size is too small` 的 stderr，`classify_support_result()` 與 `classify_slice_result()` **回同一個 code**
  - 指令：`python -c "from agent.support_classifier import classify_support_result as s; from agent.slicing_classifier import classify_slice_result as c; e='Pad brim size is too small'; print(s('',e,False).error_code, c(1,'',e,'m.stl',False).error_code)"`
  - 預期：`PAD_CONFIG_INVALID PAD_CONFIG_INVALID`
