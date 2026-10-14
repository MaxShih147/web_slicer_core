## Why

`third_party/prusaslicer_fork` 已在 commit `cd971bc2d` 修好一個崩潰：`support_points_density_relative` 過高時（0.6 mm 頭 ≥ 2205%），`SampleConfigFactory::verify()` 會無限遞迴，導致 Stack Overflow。修好後密度可以超過 2204%，平面支撐點會持續加密。這個修正已經隨本 repo 的 commit `5fb9e14`（2026-10-13）進來：submodule 指標現在指向 fork 的 `7764188f`。它包含 `cd971bc2d`，另外多了兩個 commit，其中 `02f19db4e` 調整了支柱連接的行為。所以本變更不再推進指標，只要部署並驗證 `7764188f` 的引擎。

引擎不再崩潰後，Python 層缺少輸入護欄的問題就浮出來了：

- 負的密度會讓斜面路徑（`SupportPointGenerator.cpp` 的 `calc_influence_radius()` 與 `set_radius()`）對負數開根號，得到 NaN。
- 舊引擎遇到極端密度會很快崩潰，新引擎則會一直算下去。目前 `run_prusa_cli()` 沒有逾時，`engine_job_queue` 一次只跑一個工作，所以一個極端請求可能長時間佔住整條佇列。
- `support_points_min_distance` 沒有上限，也沒擋 NaN。超過約 1073 mm 時，引擎的 int32 計算會溢位，屬於未定義行為。

## What Changes

- `agent/models.py` 的 `SLAConfig` 新增兩個 `field_validator`，寫法沿用 `pad_wall_slope`：
  - `support_points_density_relative`：只接受 `0 <= v <= 10000`。0 保留給「密度 0 加手動點」這條合法路徑，由 `param_rules` 的 R5 處理。負數與大於 10000 的值直接拒絕。
  - `support_points_min_distance`：只接受 `0.0 <= v <= 100.0`。判斷 MUST 寫成 `not (0.0 <= v <= 100.0)`，NaN 才會被擋下。
  - 兩者都只拒絕，不夾限，不偷偷改值。
- `agent/tests/` 新增單元測試。涵蓋上下界、負數、大於 10000、超過 100 mm、NaN，以及密度 0 必須通過。另外確認各入口都回 422，不回 500。
- 新增驗證腳本 `scripts/verify_slicer_density.py`，沿用 `scripts/raster_bench/make_fixtures.py` 的匯入方式與 STL 工具函式。腳本內容：
  - 自建 50×50×10 mm 平放方塊，以及繞 Y 軸傾斜 20 度的方塊。
  - 跑 8 組來自 fork build 新引擎的參考基準案例，只驗證結束碼為 0 且點數大於 0，實際點數記錄下來當基準。
  - 在固定 `min_distance` 的掃描組內，檢查點數不會隨密度增加而比目前為止的最高點數低超過 5%。
  - 對傾斜方塊跑 10000%、`min_distance` 0 的壓力測試，記錄耗時。
  - 讀取 `support_tree.json`，計算頭數與點數的比率（檢查掉點），並檢查座標裡沒有 NaN 或 inf（檢查幾何退化）。
  - 同層 XY 最近點距只計算並記錄，不當成通過條件。
- 確認 `third_party/prusaslicer_fork` 的 gitlink 已包含 `cd971bc2d`，而且指向 `7764188f10c0a4431549af56d85d65b61e272332` 或更新的版本。指標已由 `5fb9e14` 推進，本變更 MUST NOT 用 `git update-index` 或其他方式覆蓋它，否則會降版。也不碰 `.gitmodules`。
- 新版 `slicer-engine.exe` 與 `slicer_core.dll` 由使用者在本機用 Release 建置後手動複製到 `slicer-engine\bin\`。本變更不執行 `build_prusaslicer_fork_windows.bat`，也不執行 `package_slicer_engine_windows.ps1`。

## Capabilities

### New Capabilities

（無）

### Modified Capabilities

- `support-param-validation`：在「參數錯誤須回 422 而非 500」這條要求下，新增 `support_points_density_relative` 與 `support_points_min_distance` 的範圍規則：超出範圍或傳入 NaN 時回 422，密度 0 必須通過。

## Impact

- **程式碼**：
  - `agent/models.py`：`SLAConfig` 新增兩個驗證器。
  - `agent/api_v2.py`：`/generate-hollow` 補上 `except ValidationError` 分支，參數錯誤回 422，不再落入 500。
  - `agent/tests/`：新增測試。
  - `scripts/verify_slicer_density.py`：新增。
  - `third_party/prusaslicer_fork`：gitlink 已由 `5fb9e14` 指向 `7764188f`，本變更不修改。
- **API**：所有建立 `SLAConfig` 的入口都會擋下違規值，但回應方式不同。v2 端點（PUT `/slices/{job_id}/config`、`/execute`、`/generate-supports`、`/export-support-points`、`/generate-hollow`）回 HTTP 422 `CONFIG_VALIDATION_ERROR`，`retryable: false`，訊息含欄位名。v1 上傳端點 `POST /api/jobs` 維持既有行為，回 HTTP 400 `Invalid config: ...`。`POST /support-params/validate` 不拋錯，回 HTTP 200，在 `problems[]` 回報 `CONFIG_VALIDATION_ERROR`。
- **已存資料**：後端沒有資料庫，`config.json` 只寫不讀，`prz_config.json` 沒有這兩個欄位，所以後端沒有已存資料受影響。前端專案若存了超出範圍的值，送出時會收到 422。
- **部署**：`slicer-engine\bin\` 要換的是 `slicer-engine.exe` 與 `slicer_core.dll`。修正在 `slicer_core.dll` 裡，只換 exe 無效。Blosc 是靜態連結，不需要額外的 dll。
- **工作區**：`.gitmodules`、`.gitignore`、`scripts/build_prusaslicer_fork_macos.sh` 現有的未 commit 修改 MUST NOT 被修改、還原或 commit。fork 內本機的 CMake 修改也不 commit。

### 已知限制

- **不做逾時**：本變更不加子行程逾時，也不強制結束程序，之後另開變更處理。10000% 上限能不能真的避免佔住佇列，要看驗證腳本量到的耗時。
- **不對齊演算法**：DS-slicer 與 DS-Online 的斜面、平面密度算法不同（斜面主要看 `min_distance`，平面主要看密度）。這屬於引擎架構，本次不做幾何對齊。
- **溢位仍存在**：頭徑 ≥ 4 mm 搭配 10% 密度，還是會發生 int32 溢位。這是 fork 變更明列的 Non-Goal，密度上下限擋不到。
- **`min_distance` 不保證點距**：它只會讓點變稀，不保證任兩點的距離（見 fork commit `0ed4ec3ce`）。所以腳本只記錄最近點距，不判斷通過或失敗。
- **二進位檔沒有可追溯的指紋**：bin 是本機 Release 建置後手動複製的，fork 也有沒 commit 的 CMake 修改，所以這份二進位檔不能由指標的 commit 重建。`engine_build_id.txt` 與 `engine-artifact-manifest.json` 已經過期，不會自動更新。驗證腳本記錄的 `slicer_core.dll` SHA256，是這次部署唯一可信的身分證明。
