## Context

fork commit `cd971bc2d` 修好了極端密度下 `SampleConfigFactory::verify()` 無限遞迴的崩潰（細節見 fork 的 `openspec/changes/archive/2026-10-13-fix-sla-island-extreme-density`）。本 repo 的 commit `5fb9e14`（2026-10-13）已經把 submodule 指標推進到 fork 的 `7764188f`。它包含 `cd971bc2d`，另外多了 `02f19db4e`（支柱連接行為調整）與一個合併 commit。所以本 repo 要做兩件事：部署並驗證 `7764188f` 的新引擎，以及在 Python 層補上輸入護欄。

現況（皆已讀過原始碼確認）：

- `SLAConfig.support_points_density_relative` 是 `int`，`support_points_min_distance` 是 `float`，兩者都沒有任何驗證器。
- `param_rules.py` 只攔「密度 == 0 且沒有手動點」（R5）。負數會直接通過。
- Python 層沒有任何密度夾限，也沒有任何閃避舊引擎崩潰的邏輯。範圍限制只出現在開發用前端：`dev-interface` 是 0～500，`web` 是 50～200。
- 引擎內部有兩條路徑，處理密度的方式不同：
  - island 路徑（平面）：密度低於 10% 會被當成 10%。高密度時會飽和，0.6 mm 頭的內部間距約在 18988% 停在 0.6 mm。
  - slope 路徑（斜面）：`calc_influence_radius()` 與 `set_radius()` 直接除以密度，沒有下限。密度是負數時會開根號得到 NaN。實測在此幾何體（傾斜 20° 的 50×50×10 mm 方塊、0.6 mm 頭、`min_distance` 0）上，斜面點在約 2204% 亦達到飽和，後續僅有約 1% 之離散化數值抖動（矩陣內 6201% → 10000% 為 1522 → 1506；額外重測 5000% 時比 4200% 低 2.3%，每次重跑結果都相同）。
- `run_prusa_cli()` 呼叫 `communicate()` 時沒有逾時。`engine_job_queue` 是全程序共用的 FIFO，一次只跑一個工作。
- `slicer-engine.exe` 只是外殼，演算法在 `slicer_core.dll`。引擎沒有 `--version`。`engine_build_id.txt` 與 `engine-artifact-manifest.json` 是 2026-09-04 打包時產生的，現在 bin 裡檔案的 SHA256 已經對不上。

限制：

- 二進位檔由使用者在本機用 Release 建置，再手動複製。本變更不執行任何 bat 或 ps1 建置、打包腳本。
- 工作區既有的未 commit 修改 MUST NOT 被動到，包括 `.gitmodules`、`.gitignore`、`scripts/build_prusaslicer_fork_macos.sh`，以及 fork 內本機的 CMake 修改。

## Goals / Non-Goals

**Goals:**

- 所有會建立 `SLAConfig` 的入口，都拒絕負密度、大於 10000 的密度，以及不在 `[0, 100]` 範圍內（含 NaN、inf）的 `min_distance`。
- 密度 0 維持合法，讓 R5 與「純手動放點」的路徑不變。
- 用一支可以重跑的腳本，證明部署到 `slicer-engine\bin\` 的引擎已經包含這次修正，並把高密度下的點數、耗時、支撐樹健康度記錄成基準。
- 確認 gitlink 已包含 `cd971bc2d`，而且指向 `7764188f` 或更新的版本。不覆蓋、不降版，也不改動工作區其他任何檔案。

**Non-Goals:**

- 引擎子行程逾時與強制結束：另開變更處理。
- 修改 fork 原始碼，或處理頭徑 ≥ 4 mm 時的 int32 溢位。
- 對齊 DS-slicer 與 DS-Online 的斜面、平面密度演算法。
- 修改 `param_rules.py` 的規則表，或改變 v1 `POST /api/jobs` 的錯誤格式。
- 更新 `engine-artifact-manifest.json`、`engine_build_id.txt`、SBOM。

## Decisions

### D1：防線放在 `models.py` 的 `field_validator`

**決定**：兩條範圍規則都寫成 `SLAConfig` 上的 `field_validator`。

**理由**：`SLAConfig(**...)` 是所有入口都會經過的地方：

```
v2 PUT  /slices/{id}/config      → _run_param_validation      → SLAConfig(**merged)
v2 POST /execute                 → _build_sla_config          → SLAConfig(**merged)
v2 POST /generate-supports       ┐
v2 POST /export-support-points   ┤
v2 POST /generate-hollow         ┘→ _convert_v2_config_to_sla → SLAConfig(**sla_dict)
v2 POST /support-params/validate → _run_param_validation      → SLAConfig(**merged)
v1 POST /api/jobs (main.py)      → SLAConfig(**config_data)
```

（v2 路徑皆省略前綴 `/api/v2`。）

**替代方案**：

- **放在 `param_rules.py`**：否決。理由有三：
  - 它只在 PUT /config 和 /validate 執行。`/execute`、`/generate-supports`、`/export-support-points` 會重新建立一次設定，v1 `POST /api/jobs` 根本不呼叫它，所以都能繞過。
  - 它的定位是「預先模擬引擎 `validate()` 的判斷」，外加 D9「引擎會默默處理錯」的規則。輸入值的型別或範圍邊界不屬於這兩類。
  - `test_param_rules_contract.py` 會把每條規則釘到 fork 原始碼的公式，而這兩條規則在引擎裡找不到對應公式。
- **放在 API route**：否決。每個入口都要各寫一份，違反 `slice-config-intake` 規格的「MUST NOT 另寫一套判斷」。
- **用 `Field(ge=, le=)`**：否決。`models.py` 現有的範圍檢查都是 `field_validator` 搭配自訂訊息（例如 `pad_wall_slope`）。D3 也要求訊息裡一定要有欄位名。

**符合既有原則**：`models.py` 對 `pad_wall_slope` 的註解寫明，只有「這個值會讓公式出錯」時才加範圍檢查。負密度會在斜面路徑產生 NaN，`min_distance` 過大會讓 int32 溢位，都符合這個條件。密度上限 10000 則是資源政策，不是公式出錯。這點列入 Risks，由驗證腳本量到的耗時來支撐。

### D2：邊界語法

**密度：`0 <= v <= 10000`**

- 下界取 0，不取 10：
  - 密度 0 加手動點是 R5 明確允許的路徑（`param_rules.py:197`）。
  - `test_param_rules.py` 的 R5 測試會先讓參數經過 `SLAConfig` 驗證，用的值是 0、0、1。下界設 10 會讓這三個測試失敗。
  - 會產生 NaN 的只有負數。密度 0 在斜面路徑會變成無限大半徑，結果是沒有點，不會變成 NaN。
- 密度 1～9 照樣接受。island 路徑會把它當成 10%，slope 路徑照實際值計算。結果是定義好的，不會出錯。
- 這個欄位是 `int`，NaN 進不來。驗證器在 pydantic 完成整數轉換後才執行。

**min_distance：MUST 寫成 `if not (0.0 <= v <= 100.0): raise`**

- FastAPI 用 `json.loads` 讀 JSON，它接受 `NaN` 與 `Infinity` 這種寫法。pydantic v2 的 `float` 預設也會放 NaN 與 inf 通過。
- 依 IEEE 754 規則，NaN 跟任何數字比較都是 False。所以 `v < 0 or v > 100` 會讓 NaN 通過，`not (0.0 <= v <= 100.0)` 才會擋下。inf 也會被擋下。
- 上界取 100 mm，遠低於 int32 溢位的門檻（約 1073 mm）。
- 下界取 0。負值在引擎裡會被 `min_distance > 0` 判斷忽略，不會出錯；擋下它是為了讓輸入的意思清楚。

**訊息格式**：`"<欄位名> must be between <下界> and <上界>, got <v>"`。欄位名 MUST 寫在訊息字串裡，理由見 D3。

### D3：只拒絕，不夾限；兩種錯誤回傳路徑

**決定**：值超出範圍就拒絕，MUST NOT 自動改成邊界值。

**理由**：

- 如果偷偷夾限，`config.json`、前端存的專案和實際切片用的值會對不上。使用者看到的是 20000%，實際跑的是 10000%。
- 本 repo 一貫的做法是把值原樣交給引擎（見 `support_base_safety_distance` 的註解）。少數真的會被改值的欄位，都要透過 `compute_clamps()` 對外回報。
- 值不對，重試也不會變對，所以 `retryable` 為 false。

**拋錯路徑**（pydantic 的 `ValidationError` 由端點自己接住，再轉成 `APIError`。這不是 FastAPI 的 `RequestValidationError`，因為請求本體本身是合法的 JSON 與格式）：

- **`PUT /slices/{id}/config`**：
  - `_run_param_validation` 接住錯誤，產生 `problems[0].code = CONFIG_VALIDATION_ERROR`，`suggestion` 取自 `err["msg"]`。
  - 接著 `_raise_for_first_problem` 回 HTTP 422，設定不會被存下。
  - 這裡的訊息只有 `err["msg"]`，不帶欄位位置，所以欄位名必須寫在驗證器自己的訊息裡。
- **`/execute`、`/generate-supports`、`/export-support-points`、`/generate-hollow`**：
  - `/execute` 呼叫 `_build_sla_config`；其餘三個呼叫 `_convert_v2_config_to_sla`。兩個函式最後都會建立 `SLAConfig`。
  - 拋出 `ValidationError` 後，四個端點都在自己的 `except ValidationError` 分支呼叫 `config_validation_error(_config_validation_message(exc))`，回 HTTP 422 `CONFIG_VALIDATION_ERROR`，`retryable: false`。訊息格式是 `欄位: 訊息`。
  - 正常情況下，PUT /config 已經先擋過一次。這一層是給直接呼叫、或用舊的待處理設定執行時的保險。

**檢驗路徑**：

- **`POST /support-params/validate`** 不拋錯，回 HTTP 200，內容是 `ok: false`，`problems[]` 裡有 `{code: CONFIG_VALIDATION_ERROR, fields: [欄位名], suggestion}`。
- 錯誤發生在 `SLAConfig` 建立階段，所以這時不會執行 `param_rules.evaluate()`。這是現有行為，不變。

**v1 入口的回應**：v1 `POST /api/jobs`（`main.py:619`）把所有例外都包成 HTTP 400 `"Invalid config: ..."`，不是 422。這是既有的舊行為，本變更不改，只是新規則也會在這裡生效。現有的 422 一致性測試（`test_config_validation_422.py`）涵蓋 v2 的 `/execute`、`/generate-supports`、`/export-support-points`；`/generate-hollow` 原本沒有 `except ValidationError` 分支，會回 500，本變更補上，並列入同一組測試。

### D4：驗證腳本 `scripts/verify_slicer_density.py`

**匯入方式**：照 `scripts/raster_bench/run_bench.py` 的做法：

1. 把 `REPO_ROOT` 與 `scripts/raster_bench` 加進 `sys.path`。
2. `import make_fixtures`，取用 `slab_geometry()`、`write_binary_stl()`、`sha256_file()`。
3. 從 `agent.models` 匯入 `SLAConfig`。
4. 從 `agent.sla_operations` 匯入 `generate_config_ini`、`SUPPORT_DETECTION_LAYER_HEIGHT`、`_english_locale_env`。
5. 引擎路徑預設取 `agent.config.SLICER_ENGINE_CLI`，也可以用 `--engine` 指定。實際用到的路徑一定要印出來，因為 `SLICER_ENGINE_BIN` 環境變數會改掉它，bin 裡沒有 exe 時也會改用別的路徑。

**幾何**（在暫存資料夾產生，不讀桌面的檔案）：

- 平放方塊：`slab_geometry([50, 50, 10])`。
- 傾斜方塊：
  1. 拿同一組頂點，乘上繞 Y 軸 20 度的旋轉矩陣。
  2. 用頂點的外積重新計算每個三角形的法向量，不旋轉原本的法向量，這樣法向量方向一定和頂點繞向一致。
  3. 把整塊平移，讓最低點落在 z = 0。
  4. 全程用 float32，寫出 binary STL。
- 腳本有一個選用參數 `--reference-box <path>`，只用來比對外框大小，確認自建的方塊和 DS-slicer 用的輸入一致。

**每次執行的設定**：

- `SLAConfig(supports_enable=True, support_head_front_diameter=0.6, support_pillar_diameter=1.0, support_points_density_relative=d, support_points_min_distance=m)`。
- 再用 `model_copy` 把 `layer_height` 與 `initial_layer_height` 換成 `SUPPORT_DETECTION_LAYER_HEIGHT`（0.15）。
- 其他欄位全部用 `SLAConfig` 的預設值。
- 最後交給 `generate_config_ini()` 寫出 ini。這樣測到的就是 agent 實際會送給引擎的設定。

**兩種引擎指令**：

- **只取點**（快速路徑，和 `export_support_points` 相同）：
  - `slicer-engine.exe --export-support-points <pts.json> --load <ini> <stl>`
- **完整支撐**（和 `generate_supports` 相同，只保留需要的輸出）：
  - `slicer-engine.exe --export-support-stl --output <x.sl1> --load <ini> --export-support-tree <tree.json> <stl>`
- 兩種都用 `subprocess.run`，帶 `_english_locale_env()`，用 `time.perf_counter()` 計時。
- 腳本自己設一個單次執行的逾時（預設 600 秒，可以用參數調整）。超時就結束程序，並記成 `TIMEOUT`。這是驗證工具自己的保護，和 agent 沒有逾時這件事無關。

**執行矩陣**：

| 組別 | 模型 | 密度／min_distance | 指令 | 判定 |
|---|---|---|---|---|
| A 對照基準 | 平放 | 2000/1.85、3100/1.5、4200/1.3、2204/1.5 | 只取點＋完整支撐 | 硬性：結束碼 0、點數 > 0；記錄點數 |
| B 對照基準 | 傾斜 | 200/3.3、200/2.4、4200/2.2、2000/1.85 | 只取點＋完整支撐 | 同 A |
| C 單調性掃描 | 平放、傾斜 | min_distance ∈ {0.0, 1.5} × 密度 ∈ {100, 500, 1000, 2204, 2205, 3100, 4200, 6201, 10000} | 只取點 | 硬性：結束碼 0、點數 > 0；同一個模型、同一個 min_distance 內，隨密度增加，點數不得比目前為止的最高點數低超過 5%（容許飽和後的離散化抖動） |
| D 壓力測試 | 傾斜 | 10000/0.0 | 完整支撐 | 硬性：結束碼 0、沒有逾時、`tree.json` 能解析、座標有限、`heads` 與 `pillars` 都大於 0；記錄耗時 |

- C 組納入 2205%，因為那是舊引擎崩潰的門檻。拿舊引擎跑同一組，可以順便證明 bin 已經換成新版（見 D5）。
- 6201% 是 0.6 mm 頭的 `thick_outline` 開始碰到下限的地方。

**每次執行的度量**：

- **點數**：讀 `pts.json` 的 `points[]`，依 `type` 分開數 island 與 slope。
- **同層 XY 最近點距**：
  1. 把點的 z 值除以 0.15 後四捨五入，分到各層。
  2. 每一層用 `scipy.spatial.cKDTree` 算 XY 平面上的最近鄰距離。
  3. 記錄全部層裡的最小值。
  - 只記錄，不判定通過或失敗。理由：fork commit `0ed4ec3ce` 自己量過，設 12 mm 時最近的兩點只有 7.52 mm。原文是 "moves the spacing, it does not fence it"。island 取樣器本來就會在角落與外框放比較近的點，如果當成硬性條件，平放組一定失敗。
- **支撐樹健康度**（只有完整支撐的執行才有）：
  - 讀 `tree.json`，記錄 `heads`、`pillars`、`bridges` 的數量。
  - 計算 `頭數 / 同一設定下只取點的點數`，記錄這個掉點率。只記錄，不設硬性百分比門檻（見 Open Questions）。
  - 硬性：`heads`、`pillars`、`junctions`、`pedestals`、`bridges` 裡所有座標與半徑，都 MUST 是有限數字（不能是 NaN 或 inf）。引擎把 NaN 寫成 `null`，所以 `null` 也算。
  - 硬性：支撐樹的 `heads` 與 `pillars` 都 MUST 大於 0。D 組沒有只取點的那一輪，同樣要檢查。只取點那一輪已經是 0 點時，這一輪不重複判定（0 點已在只取點那一輪判為失敗）。
- **檔案完整性**（兩種指令都適用）：
  - 硬性：`pts.json` 與 `tree.json` MUST 能解析。檔案被截斷（例如逾時中斷、寫到一半崩潰）時，記成 `parse_error`，判這一筆失敗，矩陣其餘部分照常跑完並寫出 `report.json`。
  - 硬性：`pts.json` 裡所有點的數值都 MUST 是有限數字（`null` 也算不合格）。座標不合格的點不參與最近點距計算。
  - 只取點與完整支撐共用同一個執行資料夾，日誌分開寫成 `stdout_points.log`／`stderr_points.log` 與 `stdout_support.log`／`stderr_support.log`，不會互相覆蓋。

**輸出**：

- 預設寫到系統暫存資料夾，也可以用 `--out` 指定位置。
- 不寫進 repo 的任何資料夾。原因是 `.gitignore` 不能改，而預設寫進 repo 會產生未追蹤的檔案。
- 產生一份 `report.json`，內容包括：
  - 引擎路徑。
  - `slicer-engine.exe` 與 `slicer_core.dll` 的 SHA256。
  - fork 的 `git rev-parse HEAD` 與是否有未 commit 的修改。
  - 每一次執行的設定、結束碼、耗時、點數、最近點距、支撐樹統計。
  - A、B 組每一筆的參考點數、偏差百分比，以及是否超過 ±5%。
- 主控台會印出摘要表。A、B 組的列會並排顯示實際點數、參考點數、偏差。
- **A、B 組的參考點數**（來源：fork build 的新引擎）：
  - 平放：2000/1.85→931、3100/1.5→1385、4200/1.3→1817、2204/1.5→1039。
  - 傾斜 20°：200/3.3→208、200/2.4→317、4200/2.2→445、2000/1.85→558。
  - 偏差超過 ±5% 時只印警告，不算失敗。理由是腳本走的是 agent 的設定（`SLAConfig` 的預設值，加上 0.15 mm 層高），產生參考點數時用的參數不一定完全相同。
- 腳本的結束碼：全部硬性條件都通過時回 0，任何一條失敗時回 1，參數錯誤時回 2（和 `make_fixtures.py` 相同）。

### D5：submodule 指標確認與部署的隔離

**gitlink 只確認，不推進**：

原本的計畫是用 `git update-index --cacheinfo` 把指標從 `a114d13` 推進到 `cd971bc2d`。後來 `5fb9e14` 已經把指標推進到 `7764188f`。如果再照原計畫執行，指標會被拉回 `cd971bc2d`，等於丟掉 `02f19db4e`。所以本變更改成只確認，MUST NOT 寫入 gitlink：

```
git ls-tree HEAD third_party/prusaslicer_fork                    # 記下 HEAD 記錄的指標
git -C third_party/prusaslicer_fork rev-parse HEAD               # 必須等於上一行的 SHA
git -C third_party/prusaslicer_fork merge-base --is-ancestor cd971bc2d56b829c48278e3e30c2becfd12382eb HEAD
git -C third_party/prusaslicer_fork merge-base --is-ancestor 7764188f10c0a4431549af56d85d65b61e272332 HEAD
git diff --cached --name-only                                    # 不得出現 third_party/prusaslicer_fork
```

- 兩個 `--is-ancestor` 都要成功，也就是結束碼為 0。這代表指標包含修正，而且不比 `7764188f` 舊。
- 已確認 `7764188f` 存在於 fork 的 `origin/release/v1.0.6`，別人拉得到。
- fork 內沒 commit 的修改，本來就不會進入上層 repo 的 gitlink。
- 以後如果真的要手動移動指標，仍然要用 `--cacheinfo` 寫死目標 SHA，不要用 `git add`。原因是 `git add` 記下的是「submodule 當下的 HEAD」，而且習慣性打出 `git add .` 或 `git commit -a` 時，`.gitmodules` 會被一起帶進去。

**二進位完整性**：

1. **覆蓋前先備份**：把 `slicer-engine\bin\` 裡現有的 `slicer-engine.exe` 與 `slicer_core.dll` 複製到 repo 外面。這份是退回用的版本，也是 C 組比對 2205% 時的舊引擎。
2. **相依檢查**（手動）：
   ```
   "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Tools\MSVC\14.44.35207\bin\Hostx64\x64\dumpbin.exe" /nologo /dependents slicer-engine\bin\slicer_core.dll
   ```
   通過條件：除了 Windows 系統 dll 與 VC 執行庫，只能出現 `libgmp-10.dll`、`libmpfr-4.dll`。Blosc 是靜態連結（deps 裡只有 `libblosc.lib`），不應該出現。`OCCTWrapper.dll` 是執行時才載入的，不會出現，這是正常的。
3. **複製是否完整**：bin 裡的 `slicer_core.dll` SHA256，要和 VS 建置輸出資料夾裡的那份相同。這一步只證明「複製對了」。
4. **行為證明**：在 C 組裡，0.6 mm 頭、2205% 必須以結束碼 0 完成並產生點。舊引擎在同樣設定下會以 `3221225725`（`0xC00000FD`，Stack Overflow）結束。這一步證明「修正有進去」。
5. **身分記錄**：`report.json` 裡的 dll SHA256 與 fork 狀態，是這次部署唯一可信的身分紀錄。

## 資料流程與錯誤分支

```
前端 / 呼叫端
   │
   ├─ PUT /slices/{id}/config ──► _run_param_validation("slice", merged)
   │                                 │
   │                                 ├─ SLAConfig(**merged) ✗ ValidationError
   │                                 │     └─► problems[CONFIG_VALIDATION_ERROR]
   │                                 │           └─► _raise_for_first_problem ──► 422（不存設定）
   │                                 │
   │                                 └─ ✓ param_rules.evaluate()
   │                                       ├─ 有 problem（例如 R5）──► 422 + 對應 code
   │                                       └─ 沒問題 ──► 存進 pending["config"]
   │
   ├─ POST /support-params/validate ──► 同上的 _run_param_validation
   │                                       └─► 一律 200 { ok, problems[], clamped[], unknown[] }
   │
   ├─ POST /execute ──────────────────────────► _build_sla_config(mechado 基底 + snake 覆寫)
   ├─ POST /generate-supports | /export-support-points | /generate-hollow ──► _convert_v2_config_to_sla(snake config)
   │        └─► 兩者都建立 SLAConfig
   │              ├─ ✗ ValidationError ──► 422 CONFIG_VALIDATION_ERROR（欄位: 訊息）
   │              └─ ✓ BackgroundTasks ──► engine_job_queue（FIFO，一次一個）
   │                                          └─► generate_config_ini ──► config.ini
   │                                                └─► slicer-engine.exe → slicer_core.dll
   │                                                      ├─ 正常 ──► classifier ──► COMPLETED
   │                                                      ├─ 引擎回報錯誤（PHZ_ERROR）──► FAILED + error_code
   │                                                      └─ 跑很久 ──► 沒有逾時，佇列被佔住（Non-Goal）
   │
   └─ v1 POST /api/jobs（main.py）──► SLAConfig(**config)
                                    └─ ✗ 任何例外 ──► 400 "Invalid config: ..."（既有行為，不改）
```

範圍規則只在 `SLAConfig` 建立時執行。所以 `generate_config_ini()` 寫出的 ini 裡，這兩個欄位一定在範圍內，引擎不會再收到負密度或 NaN。

## Risks / Trade-offs

- **[沒有逾時，10000% 仍可能佔住佇列]** → 驗證腳本 D 組會量出傾斜方塊在 10000%、`min_distance` 0 時的耗時。如果耗時明顯超出可接受範圍，就回頭調低上限，或提高逾時變更的優先順序。實測 D 組約 1～2 秒（各次執行略有波動），額外補測平放方塊 10000%／0 的完整支撐 6.2 秒，整個矩陣最慢 15.0 秒（A 組平放 4200%／1.3），10000% 上限已定案。只測過 50 mm 方塊，更大的模型耗時沒有量過。
- **[上限 10000 砍掉 0.6 mm 頭在 10000%～18988% 之間仍然有效的範圍]** → 接受。這段範圍沒有實際列印需求，換來的是點數的上限有保障。
- **[頭徑 ≥ 4 mm 搭配低密度仍會 int32 溢位]** → 這是 fork 變更明列的 Non-Goal。溢位時引擎會在 21 輪後拋出 `SUPPORT_POINT_SAMPLING_FAILED`，但附帶的建議是「調整模型角度」，這個建議不對。記錄為已知限制，之後如果要處理，應該在頭徑或柱徑加上限，不是在密度。
- **[小頭徑（< 0.2 mm）在高密度下點數很多]** → island 內部間距最小停在 0.1 mm，50 mm 方塊約 25 萬點，可能很慢。密度上限擋不到這種情況。記錄為已知限制。
- **[斜面與平面的密度演算法和 DS-slicer 不同]** → 不做幾何對齊。A、B 組的點數只記錄，不和 DS-slicer 的點數做斷言。
- **[二進位檔不能由指標重建]** → fork 有沒 commit 的 CMake 修改（Blosc 連結、`encoding_check`），所以 `package_slicer_engine_windows.ps1` 會拒絕打包。manifest 與 `engine_build_id.txt` 已經過期。這次只用 `report.json` 的 SHA256 當身分。正式出貨前，必須讓 fork 變乾淨並走打包流程（見 Migration Plan 的「出貨門禁注意事項」）。
- **[手動複製會略過打包時的去識別化檢查]** → 匯出表檢查、PE 圖示檢查、consumer harness 檢查都不會執行。這份 bin 只能當開發與驗證用，MUST NOT 當成可簽署的 release。
- **[前端存的專案裡有超出範圍的值]** → 送出時會收到 422，訊息含欄位名，使用者改了就能繼續。後端沒有需要遷移的已存資料。
- **[掉點率沒有硬性門檻]** → 定案為只記錄。保留的防線是「支撐樹的頭數與支柱數 MUST > 0」（含 D 組）。A、B、D 組的比率都是 1.00；補測平放 10000%／0 時是 0.925（6099 點、5643 頭），因為最近點距只有 0.077 mm，遠小於 0.6 mm 頭寬（見 Open Questions）。
- **[`7764188f` 比 `cd971bc2d` 多了支柱連接的調整（`02f19db4e`）]** → 這只影響支撐樹，不影響取點，所以 A、B 組的點數比對不受影響。但支撐樹的統計（pillars、bridges）可能和用 `cd971bc2d` 量到的不同。參考點數要確認是用哪個版本量的；如果是 `cd971bc2d`，點數仍然可以比，支撐樹的統計則只當作新基準。

## Migration Plan

1. 實作 `models.py` 的兩個驗證器並補上測試。執行 `pytest agent/tests`，確認 R5 的三個測試與 422 一致性測試都通過。這一步自成一個 commit。
2. 實作 `scripts/verify_slicer_density.py`。這一步自成一個 commit。
3. 使用者備份現有 bin，然後用 VS 2022 的 Release 建置 `7764188f`（也就是目前 gitlink 記錄的版本），再複製 `slicer-engine.exe` 與 `slicer_core.dll`。
4. 執行 dumpbin 相依檢查，再跑驗證腳本。全部硬性條件都通過後，保留 `report.json`。
5. 用 D5 的步驟確認 gitlink 包含 `cd971bc2d` 且不舊於 `7764188f`。這一步不寫入 gitlink，也不產生 commit。
6. 全部 commit 都在 `release/v1.0.6` 分支上。commit 的時機由使用者決定。

**退回方式**：

- 程式碼的 commit 用 `git revert` 退回。
- bin 用第 3 步的備份覆蓋回去。
- 本變更不寫入 gitlink，所以沒有指標要退回。指標的變動屬於 `5fb9e14`，不在本變更的範圍內。

兩者可以各自獨立退回。

### 出貨門禁注意事項

以下是正式出貨前的門禁，不在本變更的實作範圍內，所以不列進 tasks.md。它由使用者在 v1.0.6 的出貨流程中另外處理，本變更執行 `/opsx:apply` 時不做。

1. **先讓 fork 變乾淨**：`git -C third_party/prusaslicer_fork status --porcelain` MUST 為空。fork 內本機的 CMake 修改（Blosc 連結、`encoding_check`）要先 commit 進 fork 或丟棄，否則 `package_slicer_engine_windows.ps1` 會拒絕打包。
2. **正式打包**：用 `scripts/package_slicer_engine_windows.ps1` 打包，由打包流程產生 `slicer-engine.exe` 與 `slicer_core.dll`，同時跑完去識別化檢查（匯出表、PE 圖示、consumer harness）。
3. **更新身分紀錄**：打包時一併更新 `engine_build_id.txt`、`engine-artifact-manifest.json`，以及相關的 SBOM 與 source-chain，讓它們對得上實際出貨的二進位檔。
4. **手動複製的 bin 不得出貨**：本變更手動複製到 `slicer-engine\bin\` 的二進位檔（`slicer_core.dll` SHA256 `cb2d676928dc071ead0d37917b99d5a49cf1069ed1113dec90cee4e42955fbd3`），只能當開發與驗證用，MUST NOT 隨 v1.0.6 出貨，也 MUST NOT 當成可簽署的 release。
5. **出貨版本仍要包含修正**：正式打包所用的 fork 版本 MUST 包含 `cd971bc2d`，而且不舊於 `7764188f`（檢查方式同 D5 的兩條 `--is-ancestor`）。打包後建議用正式產物再跑一次 `scripts/verify_slicer_density.py`，確認全部硬性條件通過。

## Open Questions

- **（已解決）掉點率的門檻**：維持只記錄，不設硬性百分比門檻。只保留「支撐樹的頭數與支柱數 MUST > 0」（最終審查時由「點數 > 0 時頭數 MUST > 0」擴大，納入支柱與 D 組）。
- **（已解決）D 組可接受的耗時**：實測 D 組約 1～2 秒，補測平放 10000%／0 為 6.2 秒，10000% 上限定案。
- **（已解決）C 組單調性的寫法**：第一次完整執行時，傾斜方塊 `min_distance` 0 在 6201% → 10000% 從 1522 點降到 1506 點，被嚴格單調檢查判為失敗。重跑確認這是飽和後的固定抖動，不是掉點。改為「比目前為止的最高點數低超過 5% 才失敗」。
- **（已解決）proposal 的 Impact 段落**：已更正為 v1 回 400、v2 回 422、驗證端點回 200 加 `problems[]`。
