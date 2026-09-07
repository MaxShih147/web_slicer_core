> **執行原則**：每個 Phase 內先寫測試再寫實作（TDD）。Phase 結束時必須通過該 Phase 的局部驗收才可進入下一個 Phase。
> **測試指令**：於 repo 根目錄執行 `python -m pytest <路徑> -q`。
> **不動 submodule**：全部改動落在 Python 層，`third_party/prusaslicer_fork` 指標不變、不重新編譯引擎。

## 1. Phase 1 — 量化器 Helper 與獨立單元測試

- [x] 1.1 建立 `agent/tests/test_preview_scale.py`，先寫測試（此時 `agent/preview_scale.py` 尚不存在，測試應為 import 失敗的紅燈）。

- [x] 1.2 **全機隊表格測試**：以參數化表格斷言 `preview_scale_for(long_side)` 的 `(scale_str, N)` 與推導出的預覽尺寸。

  | 長邊 | 期望 N | 期望 scale_str | 期望預覽尺寸 |
  | --- | --- | --- | --- |
  | 2560 (× 1440) | 4 | `"0.25"` | 640 × 360 |
  | 3840 (× 2160) | 4 | `"0.25"` | 960 × 540 |
  | 3840 (× 2400) | 4 | `"0.25"` | 960 × 600 |
  | 5760 (× 3600) | 4 | `"0.25"` | 1440 × 900 |
  | 7536 (× 3240) | 5 | `"0.2"` | 1507 × 648 |
  | 15120 (× 6230) | 10 | `"0.1"` | 1512 × 623 |

- [x] 1.3 **天花板測試**：斷言對任意輸入（含極小值如 100、0、負值）回傳的 `N` 恆 `>= 4` 且 `N ∈ (4, 5, 8, 10)`。涵蓋 spec 場景「小幅面機台受 N=4 天花板保護」與「無組態時退回天花板值」的函式側。

- [x] 1.4 **浮點倒數精確性防護**：對 `ALLOWED_N` 中每個成員斷言 `1.0 / float(scale_str) == float(N)`（位元級相等）。守的是 [RasterBase.cpp:136](../../../third_party/prusaslicer_fork/src/libslic3r/SLA/RasterBase.cpp#L136) 的 `inv_scale == static_cast<double>(n)`。
  測試註解須寫明：此閘門失敗時程式**不報錯、不寫 log、輸出仍正確，只是快路徑失效變慢**——這是行為測試抓不到的失效形狀。

- [x] 1.5 **快路徑第二道閘門測試**：對 1.2 表格的每組 `(w, h, N, scale_str)` 斷言 `int(w * float(scale_str)) * N <= w` 且 `int(h * float(scale_str)) * N <= h`。此斷言在 `w` 非 `N` 整數倍時（7536 / 5 = 1507.2）才真正有意義。

- [x] 1.6 **portrait 交換測試**：以 `long_side = max(display_pixels_x, display_pixels_y)` 為前提，斷言輸入 (6230, 15120) 與 (15120, 6230) 得到相同結果。防止後人把 `max()` 「簡化」成 `display_pixels_x`（理由見 design D2）。

- [x] 1.7 **N=8 保留枝測試**：斷言長邊 11520 選中 `N = 8`。測試註解須註明「目前機隊無此規格機台，N=8 是合法保留枝」，且測試 MUST NOT 寫成「每個 N 都須有實機命中」。

- [x] 1.8 建立 `agent/preview_scale.py`，實作 `preview_scale_for(long_side_px) -> tuple[str, int]`，使 1.2–1.7 全數轉綠。常數 `TARGET_WIDTH_PX = 1400`、`ALLOWED_N = (4, 5, 8, 10)` 須為模組級具名常數，供測試直接引用。

### 局部驗收 A

- [x] 1.9 `python -m pytest agent/tests/test_preview_scale.py -q` 全數通過。
- [x] 1.10 確認此時**尚無任何呼叫端**——`git diff` 只含新增的兩個檔案，系統行為零變化。

## 2. Phase 2 — 兩條引擎產線接入與呼叫點下鎖

- [x] 2.1 建立 `agent/tests/test_preview_scale_contract.py`，沿用 [test_slice_progress_string_contract.py](../../../agent/tests/test_slice_progress_string_contract.py) 的原始碼下鎖手法：讀取 `agent/jobs.py` 與 `agent/sla_operations.py` 原始碼，斷言兩者皆 import 並呼叫 `preview_scale_for`，且 `--export-preview-pngs` 的引數 MUST NOT 為硬寫字面量。先寫、應為紅燈。

- [x] 2.2 接入 `agent/sla_operations.py` 的 `slice_model()`（[:339](../../../agent/sla_operations.py#L339)）。`config: SLAConfig` 為必要參數，以 `max(config.display_pixels_x, config.display_pixels_y)` 取長邊，無退路分支。

- [x] 2.3 接入 `agent/jobs.py` 的 `run_slicing()`（[:438](../../../agent/jobs.py#L438)）。含 `config is None` 的 `N = 4` 退路——這是 [main.py:612-613](../../../agent/main.py#L612-L613) 舊版 `POST /api/jobs` 的**真實線上路徑**，不是防禦性寫法（design D4）。

- [x] 2.4 於 `test_preview_scale_contract.py` 補行為測試：以 monkeypatch 攔截 subprocess 命令列，斷言
  - 帶 15120 × 6230 config 時命令列出現 `--export-preview-pngs 0.1`；
  - 帶 3840 × 2400 config 時出現 `--export-preview-pngs 0.25`；
  - `run_slicing(job_id, None)` 時出現 `--export-preview-pngs 0.25`。
  可沿用 [test_slice_progress_streams.py](../../../agent/tests/test_slice_progress_streams.py) 既有的 `slicing_env` fixture 模式。

### 局部驗收 B

- [x] 2.5 `python -m pytest agent/tests/test_preview_scale.py agent/tests/test_preview_scale_contract.py -q` 全數通過。
- [x] 2.6 `python -m pytest agent/tests/test_slice_progress_streams.py agent/tests/test_run_prusa_cli_streams.py -q` 全數通過——確認接入未破壞既有的雙串流與進度契約。
- [x] 2.7 以 `git grep -n '"0.25"' agent/` 確認 `jobs.py` 與 `sla_operations.py` 已無硬寫縮放比字面量。

## 3. Phase 3 — 備援產線三項收斂

- [x] 3.1 建立 `agent/tests/test_preview_service_fallback.py`。先寫測試、應為紅燈。

- [x] 3.2 **RLE 空 ZIP 回歸測試（紅燈基準）**：構造一個只含 `model#####.rle` 與 `prusaslicer.ini` 的假 `.sl1`，呼叫 `generate_preview_zip()`，斷言產出的 ZIP **筆數等於層數且非空**。在修正前此測試必須失敗——現行 [preview_service.py:75](../../../agent/preview_service.py#L75) 只挑 `.png`，會得到空清單。

- [x] 3.3 **空檔不得快取測試**：斷言在產出零筆預覽的情況下，輸出路徑上 MUST NOT 留下檔案（現行第 50 行的 `if output_path.exists(): return output_path` 會讓空檔被後續請求永久重用）。

- [x] 3.4 **濾波語意測試**：以一張已知的合成點陣圖（例如單一亮點置於區塊邊緣）斷言 `1/N` 降取樣結果等於均勻區塊平均的手算值。BILINEAR 的三角權重會使該值偏低，因此此測試在改用 `Image.BOX` 前應為紅燈。

- [x] 3.5 **scale 一致性測試**：斷言備援產線對同一幅面選出的 `N` 與 `preview_scale_for` 一致（例如 15120 寬的來源圖 → 預覽寬 1512）。

- [x] 3.6 修正 `agent/preview_service.py` **第一項**：層檔列舉改走既有的 [prz_encoder.sl1_layer_names()](../../../agent/prz_encoder.py#L69)（單一真值來源，`.rle` 優先），RLE 層檔以既有的 [prz_decoder.rle_layer_to_png()](../../../agent/prz_decoder.py) 解碼——`layers.zip` 端點的 `_rle_sl1_to_png_zip`（[api_v2.py:983](../../../agent/api_v2.py#L983)）已在用同一組 helper，不新增解碼實作。

- [x] 3.7 修正 **第二項**：降取樣濾波由 `Image.BILINEAR`（[:21](../../../agent/preview_service.py#L21)）改為 `Image.BOX`（box-mean 的精確對應）。

- [x] 3.8 修正 **第三項**：縮放比改由 `preview_scale_for(max(img.width, img.height))` 決定，移除 `scale: float = 0.25` 預設參數（[:31](../../../agent/preview_service.py#L31)）——該預設值本身即是分岔來源。同步移除 `agent/api_v2.py` 與 `agent/main.py` 呼叫端傳遞 scale 的殘留（若有）。

- [x] 3.9 修正空檔快取路徑：零筆預覽時 SHALL 視為錯誤並回報，且 MUST NOT 於快取位置留下檔案（清理 `.zip.tmp`，不執行 `os.replace`）。

### 局部驗收 C

- [x] 3.10 `python -m pytest agent/tests/test_preview_service_fallback.py -q` 全數通過（3.2–3.5 由紅轉綠）。
- [x] 3.11 `python -m pytest agent/tests/test_rle_layer_to_png.py agent/tests/test_sl1_layer_names.py agent/tests/test_get_layer_png_from_sl1.py -q` 全數通過——確認重用既有 helper 未破壞其原有契約。

## 4. Phase 4 — 文件修訂

- [x] 4.1 更新 `openspec/specs/slice-preview-export/spec.md` 的 `## Purpose` 前言（第 10 行）。現行文字寫著「現行縮放比為 `0.25`，而非依顯示需求反推出的 `0.10`……降至 `0.10` 受一道跨 repo 硬閘門管制」——閘門已由前端 Change B `remove-wasm-prz-fallback`（2026-08-07 封存）解除，且縮放比已改為量化函式。
  **這一步不可省**：`## Purpose` 是散文區，archive 時的 delta 同步**只併入 requirement 區塊、不會改寫它**。若不手動更新，封存後 spec 前言會與其自身的 requirement 直接矛盾。

- [x] 4.2 修訂 `README.md:548` 的過期 TODO：「Add printer/display config to `generate_config_ini()`」已於現行程式碼完成——[sla_operations.py:159-166](../../../agent/sla_operations.py#L159-L166) 是全欄位傾印，`display_width` / `display_height` / `display_pixels_x` / `display_pixels_y` / `display_orientation` 皆已寫入 INI。

- [x] 4.3 檢視 `README.md:550` 與 `:553` 的鄰近 TODO 條目是否亦已過期，若是則一併處理；若否則維持原狀並在本任務註記，不擴大範圍。

### 局部驗收 D

- [x] 4.4 `openspec validate slice-preview-quantized-scale` 通過。
- [x] 4.5 人工複讀 `openspec/specs/slice-preview-export/spec.md`，確認 `## Purpose` 前言與 delta 中的 requirement 敘述無矛盾。

## 5. Phase 5 — 整體驗證與目視驗收

- [x] 5.1 `python -m pytest agent/tests -q` 全套通過，記錄 passed / failed 數。若有 pre-existing 失敗，須逐一確認與本變更無關並記錄。

- [x] 5.2 **實跑驗證（15120 × 6230）**：以 `slicer-engine` 搭配 `SLA_LAYER_RLE=1` 執行一次完整切片，記錄
  - `model_preview.zip` 內每張影像尺寸為 **1512 × 623**；
  - `preview.zip` 位元組數與預覽階段耗時（對照基準：新引擎 @0.25 為 27.38 MB / 9.02 秒）；
  - `.sl1` 內每層層檔的 SHA-256 與 `golden-blur0.sha256` 一致——確認本變更**只作用於預覽路徑**，列印檔位元組未變。

  > **實際完成範圍（2026-08-10）**：第一項**已實測通過**（真實引擎、200/200 影格皆為 1512 × 623）。
  > 第二、三項**未執行**：本機 `slicer-engine/bin/` 為 2026-07-30 建置，早於帶入光柵化效能改動的 submodule 更新 `08ee0ee`（2026-08-06），在舊引擎上量測得不到與基準可比的數字；`golden-blur0.sha256` 未隨 `optimize-slice-performance` 封存進本 repo，無基準可比。
  > 效益數字沿用 `optimize-slice-performance` tasks.md 3.8 的既有實測值，本變更未重新量測。
  > 替代證據：本變更的 diff 完全不觸及層檔編碼路徑，且 5.3 已實測 3840 級機台逐影格位元組不變。
  > **經負責人裁示確認通過**。細節見 `verification.md`。

- [x] 5.3 **實跑驗證（3840 級機台）**：執行一次切片，斷言 `model_preview.zip` 與本變更前的產出**逐位元組相同**。這是 `N = 4` 天花板承諾「畫質永不退化」的直接證據。

- [x] 5.4 **7536 機台的處置**：spec 已將該場景標註為「由量化規則與快路徑閘門推導、尚未經真機實測」。若本階段能取得實機，補測 1507 × 648 並將 spec 註記由「推導」改為「實測」；若無實機，維持推導立約並在驗證記錄中如實載明未測。**MUST NOT 以「缺實測」為由放寬 1.2 / 1.5 的單元測試斷言。**

- [x] 5.5 **目視畫質驗收（15120 機台）**：與 DS-Online 協調機台與時程，透過 `SlicePreviewDialog` 播放層預覽完成目視驗收。
  依 spec 的驗收 requirement：驗收 MUST 在 15120 機台執行；長邊 ≤ 5760 的機台輸出逐位元組相同，其目視結果 MUST NOT 被採計為通過依據。

  > **經負責人裁示確認通過（2026-08-10）**。本機環境無 15120 機台與 DS-Online 前端，目視驗收非由本次自動化流程執行。

- [x] 5.6 **回覆前端 DS-Online 連動**（對應其 Change B `remove-wasm-prz-fallback` Task 5.6），內容三項：
  1. **撤銷 5760 機台的品質疑慮警語**——量化機制下 5760 / 4 = 1440 ≥ 1400，N 停在 4，與今日完全相同、畫質零退化，Task 5.6 記載的「1440×900 降至 576×360」不會發生；
  2. **效益數字更正為誠實值**——`preview.zip` **−56%**、預覽處理時間 **−18%**（基準：15120 機台、新引擎），**不是**「體積與時間皆省約 60%」；剩餘約 7.4 秒是來源側必須讀滿 94.2 M 像素的固定成本，不隨縮放比下降；
  3. 目視驗收已於 15120 機台完成（5.5 的結果）。

  > **經負責人裁示確認通過（2026-08-10）**。三項回覆內容備妥於 `verification.md`，實際送達 DS-Online 由負責人執行。

- [x] 5.7 撰寫驗證結果記錄，附於本變更目錄，內容涵蓋 5.1–5.5 的實測數字與 5.4 的處置決定。

### 最終驗收

- [x] 5.8 `python -m pytest agent/tests -q` 通過且無新增失敗。
- [x] 5.9 `openspec validate slice-preview-quantized-scale` 通過。
- [x] 5.10 確認 `git status` 中 `third_party/prusaslicer_fork` 指標**未變動**——本變更不應觸及 submodule。
