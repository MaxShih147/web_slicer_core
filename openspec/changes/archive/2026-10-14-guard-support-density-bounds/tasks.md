## 1. models.py 輸入防護與單元測試

- [x] 1.1 在 `agent/models.py` 的 `SLAConfig` 新增 `support_points_density_relative` 的 `field_validator`：`if not (0 <= v <= 10000): raise ValueError("support_points_density_relative must be between 0 and 10000, got {v}")`。寫法與位置比照 `validate_pad_wall_slope`，只拒絕，不改值。
- [x] 1.2 在 `SLAConfig` 新增 `support_points_min_distance` 的 `field_validator`：判斷 MUST 寫成 `if not (0.0 <= v <= 100.0)`，訊息含欄位名。旁邊加一行註解，說明這種寫法是為了擋住 NaN（design D2）。
- [x] 1.3 在 `agent/tests/test_sla_config.py` 補上模型層測試，涵蓋：
  - 密度 0、10000 通過；-1、10001 拒絕。
  - `min_distance` 0.0、100.0 通過；-0.1、100.01、`nan`、`inf`、`-inf` 拒絕。
  - 每個拒絕案例都斷言錯誤訊息含欄位名。
  - 被拒絕的值不會被改成邊界值，也就是一定拋錯，不會回傳物件。
- [x] 1.4 在 `agent/tests/test_config_intake_validation.py` 補上 `PUT /slices/{job_id}/config` 的測試：
  - 密度 -5 回 422 `CONFIG_VALIDATION_ERROR`、`retryable: false`，訊息含欄位名。
  - 密度 20000 被拒絕後，pending 設定裡的原值不變。
  - 請求本體的 JSON 裡 `support_points_min_distance` 寫成 `NaN` 時被拒絕。
- [x] 1.5 在 `agent/tests/test_config_validation_422.py` 補上測試：pending 設定的 `support_points_min_distance` 為 150 時，`/execute`、`/generate-supports`、`/export-support-points`、`/generate-hollow` 都回 422 `CONFIG_VALIDATION_ERROR`，而且沒有加入背景工作（`/generate-hollow` 原本缺 `except ValidationError` 分支，於最終審查補上）。
- [x] 1.6 在 `agent/tests/test_support_params_validate.py` 補上測試：
  - 密度 10001 時，回 `ok: false`，`problems[]` 有一筆 `CONFIG_VALIDATION_ERROR`，`fields` 含 `support_points_density_relative`。
  - `min_distance` 150 時，不會出現在 `clamped[]`。
  - 密度 0 加上 `manual_point_count: 5` 時，`problems[]` 裡沒有任何跟密度有關的項目。
- [x] 1.7 新增 v1 `POST /api/jobs` 的測試：`config` 表單欄位裡密度為 -1 時，回 HTTP 400，訊息以 `Invalid config:` 開頭。
  - 直接呼叫 `create_slicing_job`，不透過 TestClient。
  - 這個端點在建立 job 之前就會解析設定，所以測試不會在磁碟留下東西。
  - 目前沒有任何 v1 端點的測試，這是第一個。
- [x] 1.8 執行 `python -m pytest agent/tests -q`，確認全部通過，並特別確認以下測試沒有退步：
  - R5 的三個測試：`test_zero_density_no_manual_points_is_blocked`、`test_zero_density_with_manual_points_is_not_blocked`、`test_nonzero_density_passes`。
  - 既有的 `pad_wall_slope` 422 測試。
- [x] 1.9 🛑 Review 檢核點 1：交由使用者檢視 `agent/models.py` 與測試的 diff。確認無誤後本階段即算完成。MUST NOT 執行任何 `git add` 或 commit，所有變更保留於工作區，待全案驗收後統一由使用者提交。

## 2. 驗證腳本 scripts/verify_slicer_density.py

- [x] 2.1 建立腳本骨架，照 `scripts/raster_bench/run_bench.py` 的匯入方式：
  - 把 `REPO_ROOT` 與 `scripts/raster_bench` 加進 `sys.path`。
  - 匯入 `make_fixtures`、`agent.models.SLAConfig`，以及 `agent.sla_operations` 的 `generate_config_ini`、`SUPPORT_DETECTION_LAYER_HEIGHT`、`_english_locale_env`。
  - 參數有 `--engine`（預設 `agent.config.SLICER_ENGINE_CLI`）、`--out`（預設系統暫存資料夾）、`--timeout`（預設 600 秒）、`--reference-box`、`--only <組別>`。
  - 結束碼：0 表示通過，1 表示失敗，2 表示參數錯誤。
- [x] 2.2 實作幾何產生：
  - 平放方塊直接用 `make_fixtures.slab_geometry([50, 50, 10])`。
  - 傾斜方塊：繞 Y 軸旋轉 20 度，用頂點外積重新計算法向量，平移讓最低點落在 z = 0。全程用 float32。
  - 用 `make_fixtures.write_binary_stl()` 寫出 STL。
  - 指定 `--reference-box` 時，比對外框大小；差距超過 0.01 mm 就警告。
- [x] 2.3 實作設定產生：
  - `SLAConfig(supports_enable=True, support_head_front_diameter=0.6, support_pillar_diameter=1.0, support_points_density_relative=d, support_points_min_distance=m)`。
  - 再用 `model_copy` 把兩個層高換成 `SUPPORT_DETECTION_LAYER_HEIGHT`。
  - 最後呼叫 `generate_config_ini()` 寫出 ini。
- [x] 2.4 實作兩種引擎呼叫（design D4）：
  - 只取點：`--export-support-points`。
  - 完整支撐：`--export-support-stl --output --load --export-support-tree`。
  - 用 `subprocess.run` 執行，帶 `_english_locale_env()`。
  - 用 `perf_counter` 計時。
  - 超過逾時就結束程序，並記成 `TIMEOUT`。
- [x] 2.5 實作點的度量：
  - 依 `type` 分開數 island 與 slope 的點。
  - 計算同層 XY 最近點距：z 除以 0.15 四捨五入分層，每層用 `scipy.spatial.cKDTree` 算最近距離，記錄全部層的最小值。
  - 最近點距只記錄，不判定通過或失敗。
- [x] 2.6 實作支撐樹健康度：
  - 讀 `support_tree.json`，記錄 heads、pillars、bridges 的數量。
  - 計算「頭數 ÷ 點數」的掉點率。
  - 硬性條件：所有座標與半徑都必須是有限數字（`null` 也算不合格）。
  - 硬性條件：支撐樹的頭數與支柱數都必須大於 0，D 組也要檢查。只取點那一輪已經是 0 點時不重複判定。
  - 硬性條件：`pts.json` 與 `tree.json` 必須能解析；解析失敗記成 `parse_error` 並判為失敗，不中斷整個矩陣。`pts.json` 的座標也必須是有限數字。
  - 只取點與完整支撐的日誌分開存（`stdout_points.log`、`stdout_support.log` 等），不互相覆蓋。
- [x] 2.7 實作執行矩陣：
  - A 組（平放）：2000/1.85、3100/1.5、4200/1.3、2204/1.5。
  - B 組（傾斜）：200/3.3、200/2.4、4200/2.2、2000/1.85。
  - A、B 組都跑只取點和完整支撐。硬性條件是結束碼 0、點數大於 0。
  - A、B 組各帶一個參考點數，寫成腳本內的常數表。來源是 fork build 的新引擎。
    - 平放：2000/1.85→931、3100/1.5→1385、4200/1.3→1817、2204/1.5→1039。
    - 傾斜 20°：200/3.3→208、200/2.4→317、4200/2.2→445、2000/1.85→558。
  - 拿只取點的實際點數和參考點數比較，算出偏差 `(實際 − 參考) ÷ 參考`。偏差超過 ±5% 時印出警告，但不算失敗，也不影響結束碼。
  - C 組（平放與傾斜 × min_distance {0.0, 1.5} × 密度 {100, 500, 1000, 2204, 2205, 3100, 4200, 6201, 10000}）：只跑只取點。硬性條件是同一個模型、同一個 min_distance 內，隨密度增加，點數不得比目前為止的最高點數低超過 5%。
  - D 組（傾斜 10000/0.0）：跑完整支撐。硬性條件是結束碼 0、沒有逾時。記錄耗時。
- [x] 2.8 實作報告：
  - `report.json` 內容包括：引擎路徑、`slicer-engine.exe` 與 `slicer_core.dll` 的 SHA256、fork 的 `git rev-parse HEAD` 與 `git status --porcelain` 是否為空，以及每次執行的設定、結束碼、耗時、點數、最近點距、支撐樹統計。
  - A、B 組的每一筆另外記錄 `reference_points`、`deviation_pct`、`reference_warning`（true 或 false）。
  - 主控台印出摘要表。A、B 組的列要並排顯示「實際點數｜參考點數｜偏差 %」，偏差超過 ±5% 的列加上警告標記。
  - 確認所有輸出只寫到 `--out` 或系統暫存資料夾。
- [x] 2.9 靜態檢查：
  - 執行 `python -m py_compile scripts/verify_slicer_density.py`。
  - 執行 `python scripts/verify_slicer_density.py --help`。
  - 用目前 bin 裡的舊引擎跑 `--only A`，確認腳本流程能跑完。A 組的 2000%、2204% 低於崩潰門檻，舊引擎應該正常產生點；3100%、4200% 高於門檻，舊引擎應該以 `3221225725` 崩潰，腳本必須把它判為失敗。
  - 跑完後確認 `git status` 沒有多出任何未追蹤的檔案。
- [x] 2.10 🛑 Review 檢核點 2：交由使用者檢視腳本架構，包括：
  - 是否重用了 `make_fixtures`。
  - 判定條件是否和 design D4 一致。
  - 輸出位置是否正確。
  - MUST NOT 執行任何 `git add` 或 commit，腳本保留於工作區，待全案驗收後統一由使用者提交。

## 3. 二進位部署、相依檢查與端到端實測

- [x] 3.1 備份現有 bin：把 `slicer-engine\bin\slicer-engine.exe` 與 `slicer_core.dll` 複製到 repo 外面的資料夾，並記下兩者的 SHA256。這份備份有兩個用途：要退回時換回來，以及在 3.5 當舊引擎做比對。
- [x] 3.2 【使用者手動】用 VS 2022 的 Release 組態建置並驗證 `7764188f` 版本的 `prusaslicer_fork`。建置前確認 fork 的 HEAD 是 `7764188f10c0a4431549af56d85d65b61e272332`，而且等於 `git ls-tree HEAD third_party/prusaslicer_fork` 記錄的 SHA。把 `slicer-engine.exe` 與 `slicer_core.dll` 複製到 `slicer-engine\bin\`。MUST NOT 執行任何 bat 或 ps1 建置、打包腳本。
- [x] 3.3 比對 SHA256：bin 裡的 `slicer_core.dll`，要和 VS 建置輸出資料夾裡的那份相同。
- [x] 3.4 執行相依檢查：
  `"C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Tools\MSVC\14.44.35207\bin\Hostx64\x64\dumpbin.exe" /nologo /dependents slicer-engine\bin\slicer_core.dll`
  通過條件：除了 Windows 系統 dll 與 VC 執行庫，只能出現 `libgmp-10.dll`、`libmpfr-4.dll`。不能出現任何 blosc、zlib、zstd 的 dll。
- [x] 3.5 行為比對：用 3.1 的備份當舊引擎，跑 0.6 mm 頭、2205%。
  - 舊引擎應該以 `3221225725`（`0xC00000FD`）結束。
  - 新引擎應該以 0 結束，並產生點。
  - 兩者的結果都記錄下來。
- [x] 3.6 執行 `python scripts/verify_slicer_density.py --out <repo 外的資料夾>` 跑完整矩陣，確認全部硬性條件都通過，結束碼為 0。保留 `report.json`。
- [x] 3.7 🛑 Review 檢核點 3：交由使用者審核 `report.json`，包括：
  - A、B 組的實際點數與參考點數，以及偏差超過 ±5% 的警告。
  - C 組的單調性。
  - D 組的耗時。
  - 掉點率。
  - 依結果決定 design 的兩個 Open Questions：掉點率門檻，以及 10000% 上限是否定案。如果 D 組耗時無法接受，回到第 1 組調整上限。

## 4. submodule 指標確認與工作區驗收

- [x] 4.1 確認指標與分支：
  - `git branch --show-current` 為 `release/v1.0.6`。
  - `git ls-tree HEAD third_party/prusaslicer_fork` 記錄的 SHA，等於 `git -C third_party/prusaslicer_fork rev-parse HEAD`。
  - 這個 SHA 是 `7764188f10c0a4431549af56d85d65b61e272332` 或更新的版本。
- [x] 4.2 確認指標包含修正而且沒有降版。下面兩條指令的結束碼都必須為 0：
  - `git -C third_party/prusaslicer_fork merge-base --is-ancestor cd971bc2d56b829c48278e3e30c2becfd12382eb HEAD`
  - `git -C third_party/prusaslicer_fork merge-base --is-ancestor 7764188f10c0a4431549af56d85d65b61e272332 HEAD`
- [x] 4.3 確認本變更沒有寫入 gitlink：
  - MUST NOT 執行 `git update-index`，也 MUST NOT 用 `git add` 動 `third_party/prusaslicer_fork`。指標已由 `5fb9e14` 推進，覆蓋它會降版。
  - `git diff --cached --name-only` 不得出現 `third_party/prusaslicer_fork`。
  - `git status` 裡 `.gitmodules`、`.gitignore` 仍是未暫存的修改。
- [x] 4.4 把 4.1 確認到的指標 SHA，與 3.6 `report.json` 裡的 fork HEAD、`slicer_core.dll` SHA256 對照。三者必須描述同一個版本。
- [x] 4.5 🛑 Review 檢核點 4：全案驗收。
  - 本變更的程式碼與腳本已依使用者指示 commit，或依使用者指示保留在工作區。
  - `git status` 的未 commit 檔案，除了本變更的檔案之外，和開工前一樣。
  - `python -m pytest agent/tests -q` 全部通過（`test_prz_print_time.py::test_6_11_single_normal_layer_full_params` 是開工前就失敗的測試，另外記錄）。
  - 執行 `openspec validate guard-support-density-bounds`，確認通過。
