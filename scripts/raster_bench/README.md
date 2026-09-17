# raster_bench — 光柵化基準工具

OpenSpec 變更 `optimize-raster-canvas-scan` 的基準測試工具（規格：`raster-performance-baseline`）。
用途是比對「改動前」與「改動後」的切片引擎：

- 每層、每張預覽圖的輸出是否逐位元組相同。
- 光柵化耗時與峰值記憶體的變化。

所有指令都在 **repo 根目錄**、以 `.venv\Scripts\python.exe` 執行。以下範例為 PowerShell。

## 檔案

| 檔案 | 用途 |
| --- | --- |
| `manifest.json` | 案例定義：機型、光柵化參數、排版位移、來源模型檔名與 SHA-256、`model.stl` 與排版定義的 SHA-256、凍結支撐 SHA-256 及其綁定的模型、執行矩陣 |
| `make_fixtures.py` | 產生排版 STL、合成平板與 `config.ini`；凍結支撐 |
| `run_bench.py` | 執行一次引擎，輸出指紋、時間與中繼資料 |
| `fingerprint.py` | 計算 `.sl1` 與預覽 zip 內每個影像項目解壓後的 SHA-256 |
| `compare_fingerprints.py` | 比對兩次執行的指紋 |
| `tests/` | 上述工具的 pytest 測試（不需要真實模型或引擎） |
| `work/` | 工作目錄，**已被 git 忽略** |

## 資料安全

- 來源 STL、排版後的 `model.stl`、`support.stl`、`.sl1` 與預覽 zip 都含病患相關資料，**一律不得提交進 git**。它們只能放在 `work/` 或內部共享位置。
- 會進 git 的只有：`manifest.json`、工具程式碼，以及 `openspec/changes/optimize-raster-canvas-scan/evidence/` 下的文字檔（`.sha256`、`.json`、`.md`）。
- `meta.json` 裡的命令列已把路徑換成 `<engine>`、`<fixture>`、`<run>` 代號，可以直接歸檔。

## 1. 取得與放置來源模型

**內部共享位置：`（待團隊指定）`**

需要的檔案（以檔名與 SHA-256 為準，見 `manifest.json` 的 `sources`）：

| 代號 | 檔名 | SHA-256 |
| --- | --- | --- |
| `surgical_guide` | `fixture-surgical-guide-18-19.stl` | `2170334b7cdc547bc011bb7a841787c12eaf355b59c696aff46fa7926970df2e` |
| `crown` | `fixture-crown-cad.stl` | `ba7aeb3428f8288ec367faa3b491f7283eac340f11067e3347300297e163fc1e` |

- 把兩個檔案放進任一個本機資料夾，子資料夾也可以。工具會依**完整檔名**搜尋，同名檔案只能有一個。
- 工具**不會猜路徑**。模型資料夾只能用下面兩種方式指定：

```powershell
# 方式一：每次指定
.venv\Scripts\python.exe scripts\raster_bench\make_fixtures.py --models D:\path\to\models

# 方式二：環境變數
$env:RASTER_BENCH_MODELS = "D:\path\to\models"
```

- 檔案的 SHA-256 與 manifest 不符時，工具會拒絕並指出是哪個檔名。
- 滿版案例 `fullplate-16k-slab` 由程式產生，不需要模型資料夾。

## 2. 準備基準引擎

改動前的引擎放在 `work/engines/<名稱>/`，例如 `work/engines/base-5bc83b08f/`。資料夾內需要：

- `slicer-engine.exe`、`slicer_core.dll`、`OCCTWrapper.dll`、`libgmp-10.dll`、`libmpfr-4.dll`
- `resources\`
- 建議附上 `build_info.json`：`run_bench.py` 會讀它的 `fork.commit` 與 `fork.tree` 寫進 `meta.json`

引擎由使用者在 VS2022 手動建置（`third_party\prusaslicer_fork\build\PrusaSlicer.sln`，`Release | x64`），細節見 `tasks.md` 階段 0。
改動前與改動後的引擎必須出自同一個建置目錄與同一組態。

## 3. 產生測試案例

```powershell
# 全部四個案例
.venv\Scripts\python.exe scripts\raster_bench\make_fixtures.py --models D:\path\to\models

# 只做指定案例（可重複 --case）
.venv\Scripts\python.exe scripts\raster_bench\make_fixtures.py --case fullplate-16k-slab
```

每個案例會寫出 `work/fixtures/<案例>/` 底下三個檔案：

- `model.stl`：決定性排版結果。同樣的來源在任何機器上產出的位元組都相同，屬性位元組一律寫成 0。
- `config.ini`：以 `agent.models.SLAConfig` 與 `generate_config_ini` 產生。支撐關閉，因為量測時匯入凍結的支撐。
- `fixture.json`：`model.stl` 的 SHA-256、三角形數、尺寸，以及 `config.ini` 的 SHA-256。

第一次產生時，工具會把兩個指紋寫進 `manifest.json` 的 `model`：

- `sha256`：`model.stl` 本身的指紋。
- `geometry_sha256`：排版定義（`geometry` 加上來源模型 SHA-256）的指紋。

這次改動需要提交進 git。之後每次產生都必須得到相同的兩個指紋，否則拒絕。
如果確定要改排版，請把 `model` 的兩個指紋、以及凍結支撐的 `support.sha256`、`support.model_sha256` 都改回 `null`，刪除舊的案例檔案後再重建，並重新凍結支撐。

重跑是安全的：

- 內容相同時回報 `unchanged`。
- 既有檔案內容不同時**拒絕覆寫**。確定要重建，請先手動刪除。

每行輸出一筆 JSON 結果。結束碼：0 成功、1 拒絕或失敗、2 參數錯誤。

## 4. 凍結支撐（只做一次）

主基準與次基準需要固定的 `support.stl`，每次量測都匯入同一份，不重新產生。

```powershell
.venv\Scripts\python.exe scripts\raster_bench\make_fixtures.py --freeze-support --engine scripts\raster_bench\work\engines\base-5bc83b08f
```

- 必須先完成第 3 步。
- 必須使用**改動前**的引擎。
- 產生方式比照 agent 的支撐生成：開啟支撐、偵測層厚 0.15 mm、`--export-support-stl`。
- 引擎輸出存到 `work/fixtures/<案例>/freeze_support.stdout.log` 與 `.stderr.log`。
- 成功後會把 `support.stl` 的 SHA-256、它所屬模型的 SHA-256（`support.model_sha256`）與引擎指紋（`frozen_with`）寫回 `manifest.json`。**這次改動需要提交進 git**，提交前先取得同意。

以下情況會拒絕執行：

- `support.stl` 已存在。
- manifest 已經記錄過支撐雜湊。
- `model.stl` 與 `fixture.json` 不符。
- `model.stl` 或目前的排版定義與 manifest 的 `model` 紀錄不符。

凍結後，請把 `support.stl` 放到內部共享位置，讓其他機器取得同一份。

## 5. 執行一次量測

```powershell
.venv\Scripts\python.exe scripts\raster_bench\run_bench.py `
    --case primary-16k-guide-x8 `
    --engine scripts\raster_bench\work\engines\base-5bc83b08f `
    --build base --repeat 1 --threads 8
```

| 參數 | 說明 |
| --- | --- |
| `--case ID` | manifest 中的案例 |
| `--engine DIR` | 引擎資料夾 |
| `--build LABEL` | 建置標籤，例如 `base`、`fast`；用於輸出資料夾名稱 |
| `--repeat N` | 第幾次重複，從 1 開始 |
| `--threads N` | 傳給引擎 `--threads N`；省略即為引擎預設執行緒數，資料夾標為 `tdefault` |
| `--raster-env SLA_RASTER_X=V` | 額外傳給引擎的 `SLA_RASTER_*` 環境變數，可重複；例如 `SLA_RASTER_TIMING=1`、`SLA_RASTER_VERIFY=1` |
| `--keep-archives` | 保留 `.sl1` 與預覽 zip。預設會刪掉，因為 16K 每次數百 MB |
| `--disable-rle` | 對照用：不設 `SLA_LAYER_RLE`，引擎輸出 PNG 層檔 |
| `--raster-param KEY=VALUE` | 對照用：覆蓋 manifest 的 `raster_params`，例如 `blur=1`；可重複 |
| `--platform LABEL` | 平台標籤，預設 `windows` 或 `macos` |
| `--work DIR` | 工作目錄，預設 `scripts/raster_bench/work` |

**執行前的檢查。** 不符就拒絕，也不會自動重新產生：

- `model.stl` 與 `fixture.json` 相符，而且 fixture 是用 manifest 目前記錄的來源做出來的。
- `model.stl` 等於 manifest 的 `model.sha256`，而且 manifest 目前的排版定義仍然等於 `model.geometry_sha256`。改了排版卻沒重建時會被擋下。
- `config.ini` 與 manifest 目前的參數重新產生的結果完全相同。
- 需要支撐的案例：manifest 已記錄支撐雜湊，`support.stl` 存在，而且雜湊相符；支撐綁定的模型（`support.model_sha256`）必須就是目前的 `model.stl`。
- 同名的輸出資料夾不存在。

**引擎命令。** 參數順序比照 `agent/jobs.py` 的 `run_slicing`：

- `--export-sla`
- `--export-preview-pngs <preview_scale_for()>`
- `--center`
- `--load config.ini`
- `--import-support-stl`（需要支撐的案例）
- `--threads`

環境變數固定為英文語系加上 `SLA_LAYER_RLE=1`。從目前 shell 繼承來的 `SLA_*` 會先全部清掉，清掉的名稱記錄在 `meta.json`。

**輸出資料夾** `work/runs/<platform>-<build>-<case>[-<variant>]-t<threads>-r<n>/`：

| 檔案 | 內容 |
| --- | --- |
| `layers.sha256` | 每個層檔解壓後的 SHA-256，依名稱排序，每行 `<名稱>  <sha256>`；排除 `config.ini`、`prusaslicer.ini` 等中繼資料 |
| `preview.sha256` | 每張預覽圖的 SHA-256，格式同上 |
| `timing.json` | 見下方說明 |
| `meta.json` | 平台、建置標籤、引擎指紋與 fork commit/tree、輸入雜湊、環境變數、命令列、`params_sha256`、項目數、變體 |
| `stdout.log`、`stderr.log` | 引擎原始輸出 |
| `config.ini` | 只在使用 `--raster-param` 時出現，是實際載入的設定 |

`timing.json` 的內容：

- `total_wall_s`：總牆鐘時間。
- `rasterizing_wall_s`：從第一行 `Rasterizing layers` 到 `Slicing done` 的時間，不含寫檔。
- `raster_timing`：解析後的 `[raster-timing]` 行。
- `peak_working_set_bytes`：峰值實體記憶體，以 `GetProcessMemoryInfo` 讀取。
- `progress`：每一行進度與它的時間戳。

`params_sha256` 涵蓋所有決定輸出像素的參數：光柵化參數、`SLA_LAYER_RLE`、機型、預覽縮放比、中心點、各輸入雜湊。
**不含**執行緒數、重複序號與 `SLA_RASTER_*`，因此應該產出相同指紋的執行會有相同的雜湊。

**失敗處理。**

- 執行過程在 `.partial-*` 資料夾進行，成功才改名為正式資料夾。
- 引擎失敗（結束碼非 0、沒有 `.sl1`、沒有預覽 zip）時保留 `.partial-*` 與 log 供檢查。確認後可以手動刪除。

結束碼：0 成功、1 拒絕或失敗、2 參數錯誤。

峰值記憶體量測只在 Windows 進行。在其他平台（例如 macOS）量測仍會照常完成並產出指紋與時間，`timing.json` 的記憶體欄位記為 `null`，`memory_note` 說明原因，stderr 也會印出一行警告。

## 6. 執行矩陣

所有時間數據只在 Windows 驗收機（i7-11370H、4 核 8 緒、16 GB）上採計。

### Golden Baseline（改動前引擎，tasks 0.15）

每個案例依序執行：

- `--threads 1` 跑 1 次。
- 預設執行緒數跑 3 次。預設執行緒數的第 1 次就是該案例的 Golden。

```powershell
$engine = "scripts\raster_bench\work\engines\base-5bc83b08f"
foreach ($case in "primary-16k-guide-x8", "secondary-8k-guide-x3", "tiny-16k-crown-x1", "fullplate-16k-slab") {
    .venv\Scripts\python.exe scripts\raster_bench\run_bench.py --case $case --engine $engine --build base --repeat 1 --threads 1
    foreach ($n in 1..3) {
        .venv\Scripts\python.exe scripts\raster_bench\run_bench.py --case $case --engine $engine --build base --repeat $n
    }
}
```

基準自我一致性：每個案例的 `t1-r1` 必須與 `tdefault-r1` 比對相符。不相符代表基準本身不具決定性，不能拿來當比較基礎。

### 特殊對照（tasks 0.16）

```powershell
# PNG 層檔模式
.venv\Scripts\python.exe scripts\raster_bench\run_bench.py --case tiny-16k-crown-x1 --engine $engine --build base --repeat 1 --disable-rle
# blur = 1
.venv\Scripts\python.exe scripts\raster_bench\run_bench.py --case tiny-16k-crown-x1 --engine $engine --build base --repeat 1 --raster-param blur=1
```

輸出資料夾分別為 `windows-base-tiny-16k-crown-x1-norle-tdefault-r1` 與 `windows-base-tiny-16k-crown-x1-blur1-tdefault-r1`。

### 改動後驗收

每個案例以 `--threads 1`、`2`、`8` 各跑 3 次，共 9 次，全部加上 `--raster-env SLA_RASTER_VERIFY=1`。
每一次都必須與 Golden 相符。任何一次不符就判定不通過，**不得**以多數相符或重跑後相符取代。

```powershell
$engine = "scripts\raster_bench\work\engines\<改動後引擎>"
foreach ($t in 1, 2, 8) { foreach ($n in 1..3) {
    .venv\Scripts\python.exe scripts\raster_bench\run_bench.py --case primary-16k-guide-x8 --engine $engine `
        --build fast --repeat $n --threads $t --raster-env SLA_RASTER_VERIFY=1
} }
```

### 效能數據

- 只使用預設執行緒數 3 次的**中位數**，同時記錄最大值與最小值。
- 任一組的最大值與最小值相差**同時**超過中位數的 5% **且**絕對差值大於 0.5 秒時，**整組重跑**，不能只替換單次。只滿足其中一個條件時不需重跑。
- 每次執行前讓電腦閒置 60 秒，並關閉 VS2022、瀏覽器等背景程式。
- 門檻：
  - 主基準：光柵化時間 ≤ 基準的 50%，峰值記憶體 ≤ 基準。
  - 次基準：光柵化時間 ≤ 基準。
  - 滿版案例：光柵化時間 ≤ 基準的 103%。

## 7. 比對指紋

```powershell
.venv\Scripts\python.exe scripts\raster_bench\compare_fingerprints.py `
    scripts\raster_bench\work\runs\windows-base-primary-16k-guide-x8-tdefault-r1 `
    scripts\raster_bench\work\runs\windows-fast-primary-16k-guide-x8-t8-r2
```

- 分別比對 `layers.sha256` 與 `preview.sha256`。
- 輸出兩邊的項目數、第一個不同的項目，以及不同項目的總數。某一邊少了項目也算不同。
- 兩邊的 `case` 或 `params_sha256` 不同時會印出警告。

| 結束碼 | 意義 |
| --- | --- |
| 0 | 全部相符 |
| 1 | 有任何不同 |
| 2 | 輸入資料夾不完整或無法讀取 |
| 3 | 平台標籤不同：預設拒絕；加上 `--allow-cross-platform` 會印出報告，但結束碼仍為 3，永遠不算驗收通過 |

只想看單一封存檔的指紋時：

```powershell
.venv\Scripts\python.exe scripts\raster_bench\fingerprint.py layers  path\to\model.sl1
.venv\Scripts\python.exe scripts\raster_bench\fingerprint.py preview path\to\model_preview.zip
```

## 8. 工具測試

```powershell
.venv\Scripts\python.exe -m pytest scripts\raster_bench\tests
```

測試使用合成的四面體與假引擎。不需要來源模型或真實引擎，也不會寫入 `work/` 或改動 `manifest.json`。
其中一項會啟動真實的 Python 子程序，用來驗證峰值記憶體量測，只在 Windows 執行。
