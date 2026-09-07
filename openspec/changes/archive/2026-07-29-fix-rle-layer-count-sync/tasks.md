# Tasks — fix-rle-layer-count-sync

> 規範：採 TDD 小階段粒度；**每個小階段自帶即時驗證步驟**，禁止「全部做完最後才驗證」。
> 驗證用測試皆置於 [agent/tests/](../../../agent/tests/)，執行前 `cd d:/repos/web_slicer_core`。

## 1. 層檔列舉真值來源 `sl1_layer_names()`（spec: sl1-layer-access）

- [x] 1.1 在 [agent/prz_encoder.py](../../../agent/prz_encoder.py) 新增 `sl1_layer_names(names)`：以 `re.compile(r"^model\d{5}\.(rle|png)$")` 匹配；同一 .sl1 內 `.rle` 存在時優先取 `.rle`，否則取 `.png`；回傳 `sorted()`。於函式加註解說明 `model` 前綴綁定 `output/model.sl1`（D2 耦合警示）。
  - [x] 1.1-V 即時驗證：新增 `agent/tests/test_sl1_layer_names.py`，涵蓋純 `.rle`、純 `.png`、`.rle`+`.png` 並存（`.rle` 優先）、排序、含 `thumbnail/thumbnail400x400.png` 應排除。執行 `python -m pytest agent/tests/test_sl1_layer_names.py -q`，全綠。

## 2. 修正層數統計 `parse_sl1_metadata()`（spec: sl1-layer-access / print-time-sync）

- [x] 2.1 [agent/jobs.py](../../../agent/jobs.py) `parse_sl1_metadata()`：層數改由 `sl1_layer_names(zf.namelist())` 計算（取代 `sum(... endswith(".png"))`）。`printTime` / `usedMaterial` 解析維持不變。
  - [x] 2.1-V 即時驗證：新增測試以「只含 N 個 `model#####.rle` 的假 .sl1（zipfile 寫入）」呼叫 `parse_sl1_metadata`，斷言層數 == N（非 0）；另斷言 `printTime`/`usedMaterial` 仍正確解析。執行對應 pytest 全綠。
- [x] 2.2 端到端同步斷言：擴充 [agent/tests/test_jobs_sync.py](../../../agent/tests/test_jobs_sync.py)——以有效 `prz_config` + RLE 假 .sl1，斷言 `resolve_estimated_print_time(prz_config, N, T_fork)` == `_compute_print_time(prz_config, N, timing)` 且 != `T_fork`。
  - [x] 2.2-V 即時驗證：`python -m pytest agent/tests/test_jobs_sync.py -q`，全綠（確認守衛不再恆退回 fallback）。

## 3. 單層 RLE 解碼支援（spec: sl1-layer-access）

- [x] 3.1 抽出單層解碼 helper：把 [api_v2.py:965-1002](../../../agent/api_v2.py) `_rle_sl1_to_png_zip()` 內「讀 `prusaslicer.ini` 取 `display_pixels_x/y` → `prz_decoder._rle_decode_layer()` → `PIL.Image.fromarray(gray,"L").save(PNG)`」抽為單層函式，回 `Optional[bytes]`；ini 缺失／`display_pixels` 解析失敗回 `None`。`_rle_sl1_to_png_zip()` 改呼叫此 helper 但**維持整包失敗時 raise** 的既有語意。（helper 置於 `prz_decoder.py`：`sl1_display_resolution()` + `rle_layer_to_png()`，供 jobs.py 與 api_v2.py 共用，避免循環相依。）
  - [x] 3.1-V 即時驗證：新增測試——正常 RLE .sl1 單層解碼回可被 `PIL.Image.open` 開啟的 PNG；缺 `prusaslicer.ini` / 壞 `display_pixels` 的 .sl1 回 `None`。執行 pytest 全綠。
- [x] 3.2 [agent/jobs.py](../../../agent/jobs.py) `get_layer_png_from_sl1()`：層檔改用 `sl1_layer_names()` 定位；選中檔為 `.rle` 時呼叫 3.1 helper 解碼；索引越界或解碼失敗回 `None`（上層 [main.py:690](../../../agent/main.py) 轉 404，不需改 main.py）。
  - [x] 3.2-V 即時驗證：測試斷言 RLE .sl1 的合法 idx 回 PNG bytes；`idx < 0` 與 `idx >= N` 回 `None`；解析度缺失回 `None`。執行 pytest 全綠。

## 4. PRZ 編碼端共用列舉 + 位元不變回歸（spec: sl1-layer-access）

- [x] 4.1 [agent/prz_encoder.py](../../../agent/prz_encoder.py) `encode_prz_streaming()`（第 875-880 行邏輯）與 `encode_prz()`（第 803 行僅 `.png`）改用 `sl1_layer_names()`，消除分歧。（選項 A：4 個 PRZ 測試 fixture 的 .sl1 層檔命名由 `{i:08d}.png` 對齊生產命名 `model{i:05d}.png`。）
  - [x] 4.1-V 即時驗證（byte-identical）：以 `git stash` 取改動前版本編碼同一顆 .sl1，與改動後比對 `hashlib.sha256`（中和 header file_time 時間戳欄位 [68:92]）。PNG-encode / stream-png / stream-rle 三者皆 **PASS（byte-identical）**。
- [x] 4.2 [api_v2.py](../../../agent/api_v2.py) `_rle_sl1_to_png_zip()` 的 `rle_names` 列舉改用 `sl1_layer_names()`（一致性，不改行為）。
  - [x] 4.2-V 即時驗證：PRZ 全套 + 本變更測試 113 passed；唯一失敗 `test_6_11_single_normal_layer_full_params` 經 `git stash` 確認為**改動前既存失敗**（`_compute_print_time` retract，與本變更無關），本變更引入 0 個新失敗。

## 5. 全域回歸與 spec 對齊

- [x] 5.1 全測試套件：`python -m pytest agent/tests/ -q` → 256 passed；2 個失敗（`test_6_11...`、`test_engine_runs_as_separate_process`）經 `git stash` 確認為改動前**既存失敗**（分別為 `_compute_print_time` retract、缺 pytest-asyncio plugin），與本變更無關、0 新失敗。
- [x] 5.2 精度斷言（spec: print-time-sync，選項 A）：於 [test_jobs_sync.py](../../../agent/tests/test_jobs_sync.py) 新增 `TestPrecisionOptionA`——實際 `encode_prz → parse_prz` 取 header `print_time`（int），與 `resolve_estimated_print_time`（float）比對，斷言 `header_int == int(status_float)` 且 `0 ≤ status_float - header_int < 1`。
  - [x] 5.2-V 即時驗證：`pytest ...::TestPrecisionOptionA` → 1 passed。
- [x] 5.3 `openspec validate --changes fix-rle-layer-count-sync` → passed（Totals: 2 passed, 0 failed）。

## 手動端到端驗證（實作完成後）

- [x] E1 重跑多物件切片，檢查 `agent/jobs/{id}/status.json`：`layer_count` == .sl1 內 `.rle` 檔數（非 0）；`estimated_print_time` == `_compute_print_time(prz_config, layer_count, timing)`。（使用者手動驗證通過）
- [x] E2 對同一 job 下載 PRZ，以 [agent/prz_decoder.py](../../../agent/prz_decoder.py) 解 header `print_time`，與 API `estimatedPrintTime` 比對，差 < 1s。（使用者手動驗證通過）
- [x] E3 `GET /api/v2/slices/{id}` 的 `layerCount` 非 0；`GET .../layers/0.png` 回傳影像。（使用者手動驗證通過）