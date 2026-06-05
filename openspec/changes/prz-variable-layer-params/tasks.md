> 驗證準則：每個小階段完成後**立即驗證**（單元測試／檢查中間產物／模擬報錯路徑），嚴禁累積到最後才測。
> 共用契約（貫穿全程）：`z_end` 錨點 + µm 量化（`int(round(mm*1000))`）+ 半開區間 `[low, high)`。

## 1. 階段 1 — API Config 接收與 µm 量化校驗（slice-config-intake）

- [ ] 1.1 在設定 schema（`agent/models.py` / `agent/config.py`）新增可選的「高度區間參數組合」結構：`HeightRange{ low_mm, high_mm, params }` 與其陣列欄位；不破壞既有等高欄位。
- [ ] 1.2 **驗證**：撰寫並執行單元測試，確認未提供區間欄位的舊請求可正常 parse、不回 422（向後相容）。
- [ ] 1.3 實作 `to_um(mm)=int(round(mm*1000))` 與區間契約校驗函式：升冪、自 0 起、相鄰連續（`high_um==next.low_um`）、無重疊、無缺口；全部以 µm 整數比較。
- [ ] 1.4 **驗證**：單元測試覆蓋四種失敗情境（缺口 / 重疊 / 未自 0 起 / 邊界 `10.0000001` 量化後視為連續），各自斷言對應結果（前三者回 422、最後通過）。
- [ ] 1.5 在 `POST /api/v2/slices` 萃取流程接上校驗，並依「區間數 > 1」標記該 job 為變動層厚流程（傳遞至切片端設定）。
- [ ] 1.6 **驗證**：以合法雙區間請求打 API，斷言 job 被標記為變動層厚流程；以單區間 / 無區間請求斷言走等高流程。

## 2. 階段 2 — PrusaSlicer 輸出 layers.json 與內容指紋（variable-layer-slicing）

- [ ] 2.1 先在後端（Python）實作 `compute_sl1_fingerprint(sl1_path)`（design 決策 2：排序 `name|size|crc32` → sha256），作為跨語言對拍的「黃金值」來源。
- [ ] 2.2 **驗證**：對一個既有 `.sl1` 計算指紋，斷言為穩定值；改動其中一張 PNG 後斷言指紋改變（內容敏感性）。
- [ ] 2.3 在 prusaslicer_fork 切片端依高度區間實作變動層厚切片，並以 `z_end` 錨點 + µm + `[low,high)` 選每層層厚。
- [ ] 2.4 **驗證**：以 `[0,10)@0.04`、`[10,20)@0.10` 切片，檢查產出 PNG 張數與預期一致，且邊界層（z_end=10mm）歸上方區間（厚度為 0.10）。
- [ ] 2.5 切片端在 `.sl1` 完整寫出後計算指紋並輸出 `model.layers.json`（schema_version / source{sl1_name, layer_count, fingerprint} / units="um" / layers[{index,z_end_um,thickness_um}]）。
- [ ] 2.6 **驗證**：檢查產出的 `model.layers.json` 內容——`layer_count==`PNG 張數、`z_end_um` 嚴格單調遞增、`z_end_um==前層+thickness_um`、`units=="um"`。
- [ ] 2.7 **驗證（跨語言對拍）**：對同一份 `.sl1`，斷言 C++ 端寫入的 `fingerprint` 等於步驟 2.1 Python 端算出的黃金值。
- [ ] 2.8 **驗證（原子性）**：模擬切片中途中止，斷言不會留下「`.sl1` 半套 + `layers.json`」的產物對（無 `layers.json` 即可）。

## 3. 階段 3 — Encoder 指紋校驗與 Z 軸查表照抄（prz-variable-layer-encode）

- [ ] 3.1 在 `agent/prz_encoder.py` 新增例外階層：`VariableLayerError(ValueError)` 及 `LayerTableMissingError` / `LayerTableFingerprintMismatch` / `LayerTableLayerCountMismatch` / `LayerRangeCoverageError`。
- [ ] 3.2 實作 `load_layer_table(path)`：解析 `model.layers.json`、套用 design 決策 1 的結構驗證（連續 index、單調、層數自洽）。
- [ ] 3.3 **驗證**：單元測試——合法表載入成功；層數不符 / 非單調 / 缺欄位的壞表各自拋對應例外。
- [ ] 3.4 實作條件式 mandatory 判定：`is_variable = len(height_ranges) > 1`；變動任務缺 `layers.json` → `LayerTableMissingError`，單一層厚缺檔 → 走等高路徑不報錯。
- [ ] 3.5 **驗證**：模擬「多區間 + 無 layers.json」斷言拋 `LayerTableMissingError`；「單一層厚 + 無檔」斷言成功走等高路徑。
- [ ] 3.6 接上雙重校驗：重算指紋比對 `source.fingerprint`、層數比對 PNG 張數，不符各拋對應例外。
- [ ] 3.7 **驗證（報錯路徑）**：人為造出 `sl1_v1 + table_v2`（指紋不符）斷言拋 `LayerTableFingerprintMismatch`；改層數斷言拋 `LayerTableLayerCountMismatch`；斷言此時**無任何 PRZ 輸出**。
- [ ] 3.8 改寫 `_write_layer_definition` 的 Z 來源：變動任務取 `z_end_um/1000.0` 寫入 `PausePositionZ`/`LayerPositionZ`，MUST NOT 用 `layer_height*(idx+1)`；等高任務維持原公式。
- [ ] 3.9 **驗證**：變動任務解碼 PRZ，斷言第 250/251 層 `z_pos` 為 10.0/10.1（來自表）；等高任務回歸測試確認 Z 不變。
- [ ] 3.10 在 API PRZ 端點（`agent/api_v2.py` / `agent/main.py`）對映例外：表類例外 → `internal_error`(500)、`LayerRangeCoverageError` → `validation_error`(422)；明確訊息。
- [ ] 3.11 **驗證**：透過端點觸發各例外，斷言回傳對應 HTTP 狀態碼與訊息，且絕不降級輸出等高 PRZ。

## 4. 階段 4 — 逐層參數區間比對與列印時間修正（prz-variable-layer-encode + prz-motion-time）

- [ ] 4.1 實作 `build_ranges()`（含契約驗證、末區間上界收尾以涵蓋頂層）與 `select_params(z_end_um, ranges)`（`z_end` 錨點 + `[low,high)`）。
- [ ] 4.2 **驗證**：單元測試——`z_end_um==10000` 歸上方區間；浮點殘差 `10.00000003mm`→`10000µm` 判定一致；非法區間拋 `LayerRangeCoverageError`。
- [ ] 4.3 在 `_write_layer_definition` 變動任務分支以 `select_params` 取代固定值挑曝光／光熄／抬升／回抽／PWM；bottom 層判定（`idx < Bottom Layer Count`）優先於區間。
- [ ] 4.4 **驗證**：解碼 PRZ，斷言跨界層「厚度與參數同屬一區間」（不出現厚度屬 A、曝光屬 B）；斷言 bottom 段仍套 bottom 參數。
- [ ] 4.5 修正 `_compute_print_time`：變動任務逐層依 `select_params` 取曝光/motion/timing 累加 `T_layer`，retract 仍套 4-case override；等高任務行為不變。
- [ ] 4.6 **驗證**：以區間 `A@2.5s`、`B@3.0s` 的小模型手算對拍 `_compute_print_time`；等高任務既有 print-time 測試全數通過（回歸）。
- [ ] 4.7 **端到端驗證**：跑一個雙區間任務（切片→layers.json→PRZ），解碼確認逐層 Z、厚度對應參數、print_time 一致且無錯位；再跑一個等高任務確認零回歸。
- [ ] 4.8 **最終驗證**：`openspec validate prz-variable-layer-params` 通過，且所有新增單元測試與既有測試套件全綠。