## 0. 測試骨架與回歸錨點

- [x] 0.1 建立測試檔 `agent/tests/test_prz_header_metadata.py`，匯入 `prz_encoder` 與 `prz_decoder`，並建立一個最小可用的 `config` fixture（含 `Machine`、`Resin`、`Other` 區塊）與最小 `.sl1`（或直接呼叫 `_write_header()`）。
  - **驗證**：`pytest agent/tests/test_prz_header_metadata.py -q` 至少能 collect 並執行（允許先 RED）。→ 2 passed, 2 xfailed ✅
- [x] 0.2 寫入赤兔樣本回歸錨點常數：`volume=1002`、`density=1.1`、`cost=33` → 期望 `weight≈1.1022`、`price≈0.033066`（容差 1e-3），先標記為待實作。
  - **驗證**：`pytest agent/tests/test_prz_header_metadata.py -q -k regression_anchor`（此時可 xfail/skip，確認測試已登記）。→ 以 `@pytest.mark.xfail` 登記，2 xfailed ✅

## 1. `_pack_str` 防禦性硬化（先做，因所有字串欄位相依）

- [x] 1.1 依 design D3 改寫 `_pack_str(s, size)`：`budget=size-1` → byte 粗切 → `decode("utf-8", errors="ignore")` 字元安全回退 → `ljust(size, b"\x00")`。
  - **驗證**：`pytest agent/tests/test_prz_header_metadata.py -q -k pack_str`，涵蓋 spec 四場景：(a) 超長 ASCII（34B→32B 且尾端含 NUL）、(b) CJK 多位元組不斷字（去 NUL 後 UTF-8 解碼無替代字元）、(c) 恰好填滿仍保留 NUL、(d) 空字串/None → 全 `0x00`。→ 4 passed ✅
- [x] 1.2 加入「輸出長度恆等於 size」與「至少 1 個尾端 `\x00`」的不變式斷言測試（對多種 size：8/24/32）。
  - **驗證**：`pytest agent/tests/test_prz_header_metadata.py -q -k pack_str_invariant`。→ 15 passed（3 sizes × 5 字串）✅

## 2. 常數定義（software / softwareVersion / priceUnit）

- [x] 2.1 於 `prz_encoder.py` 檔首 Constants 區塊新增 `SOFTWARE_NAME = "Phrozen DS"`、`SOFTWARE_VERSION = "0.0.1"`、`PRICE_UNIT = "$/L"`（依 design D4）。
  - **驗證**：`python -c "from agent.prz_encoder import SOFTWARE_NAME, SOFTWARE_VERSION, PRICE_UNIT; print(SOFTWARE_NAME, SOFTWARE_VERSION, PRICE_UNIT)"` 輸出符合預期。→ 常數已定義於 Constants 區 ✅
- [x] 2.2 `_write_header()` 中以 `_pack_str(SOFTWARE_NAME, 32)`、`_pack_str(SOFTWARE_VERSION, 24)`、`_pack_str(PRICE_UNIT, 8)` 取代原 `b"\x00"*32` / `b"\x00"*24` / `b"\x00"*8`。
  - **驗證**：`pytest -q -k header_constants`——以 `prz_decoder._parse_header()` 解析後斷言 `software=="Phrozen DS"`、`software_version=="0.0.1"`、且 `[195462:195470]` 去 NUL 解碼 == `"$/L"`。→ 2 passed ✅

## 3. 印表機與樹脂顯示名（printerName / printerType / profileName）

- [x] 3.1 `profileName` 寫入來源由 `Machine.Machine Name` 改為 `_get_str(config, "Other.profile_name")`（design D4 契約）；`printerName`/`printerType` 維持讀 `Machine.Machine Name` / `Machine.machine_type`。
  - **驗證**：`pytest -q -k profile_name_source`——config 內 `Machine.Machine Name` 與 `Other.profile_name` 設不同值，解析後斷言 `profile_name == Other.profile_name` 且 `!= printer_name`。→ passed ✅
- [x] 3.2 樹脂名稱缺漏降級：`Other.profile_name` 不存在時 `profileName` 寫空字串、不拋例外。
  - **驗證**：`pytest -q -k profile_name_missing`——移除該 key，斷言 `profile_name == ""` 且 `_write_header()` 不拋錯、header 長度仍為 195477。→ passed ✅
- [x] 3.3 動態顯示名讀取：印表機名/型別由 config 帶入並原樣解析。
  - **驗證**：`pytest -q -k printer_display_names`——斷言解析值等於 config 注入值。→ passed（3 tests 合計 3 passed）✅

## 4. weight / price 動態計算與降級

- [x] 4.1 在 `_write_header()` weight/price 寫入區塊上方加入技術債註解 `# TODO(tech-debt): per-resin-density ...`（design D4 文字）。
  - **驗證**：`grep -n "TODO(tech-debt): per-resin-density" agent/prz_encoder.py` 命中 1 次。→ 命中 1 次 ✅
- [x] 4.2 實作密度/單價讀取與公式（design D2）：`weight = (volume_mm3/1000)*density`、`price = (volume_mm3/1_000_000)*cost`，分別以 `struct.pack(">f", v)` 寫入。
  - **驗證**：`pytest -q -k weight_price_compute`——以 0.2 的赤兔錨點斷言 `weight≈1.1022`、`price≈0.033066`（容差 1e-3）。→ passed（含 regression_anchor 解除 xfail 轉綠）✅
- [x] 4.3 降級邏輯：density 缺漏/為 0 → `weight` 寫 `volume`(mm³)；cost 缺漏/為 0 → `price` 寫 `volume`；兩者獨立判斷。
  - **驗證**：`pytest -q -k weight_price_degrade`——分別移除 density、cost，斷言對應欄位解析值 == volume。→ 2 passed ✅

## 5. 整合與回歸（端到端，不取代上述局部驗證）

- [x] 5.1 端到端：用完整 config + 最小 `.sl1` 跑 `encode_prz()`／`encode_prz_streaming()`，再以 `parse_prz()` 還原，斷言 8 欄位全部正確、header 長度 == 195477。
  - **驗證**：`pytest -q -k end_to_end_header`。→ 1 passed（8 欄位全綠）✅
- [x] 5.2 全套件回歸，確認未破壞既有 PRZ 行為（時間/lift/retract/preview/RLE）。
  - **驗證**：`pytest agent/tests -q`。→ 111 passed；唯一失敗 `test_prz_print_time.py::test_6_11_single_normal_layer_full_params` 經 git stash 比對確認**為既有失敗、與本變更無關**（`_compute_print_time`，本變更未觸及）。本變更測試檔單獨跑 32 passed ✅
- [x] 5.3 `openspec validate prz-header-metadata` 通過，確認實作與 spec 場景對齊。
  - **驗證**：`openspec validate prz-header-metadata`。→ Change 'prz-header-metadata' is valid ✅
