> **執行規則**：四個階段嚴格依序進行。每個階段的「驗證」全部通過、且使用者完成「Code Review 查核點」的審查後，才可以進入下一個階段。任何驗證失敗都必須在該階段內修正，不得帶著失敗進入下一階段。
>
> **路徑慣例**：`<bench>` = `scripts/raster_bench`；`<work>` = `scripts/raster_bench/work`（git 忽略）；`<py>` = `.venv\Scripts\python.exe`；`<vs_build>` = `third_party\prusaslicer_fork\build`（VS2022 編譯目錄，`SLIC3R_GUI=ON`、`SLIC3R_BUILD_TESTS=ON`、`SLIC3R_STATIC=ON`）；`<engine_bin>` = `slicer-engine\bin`；`<tests>` = `<vs_build>\tests\sla_print\Release\sla_print_tests.exe`（1.1 已確認：專案 `sla_print_tests`，Release|x64 輸出於此）。
>
> **建置規則**：引擎與測試一律**由使用者在 VS2022 手動建置**，Claude 不執行任何編譯指令。方案檔為 `<vs_build>\PrusaSlicer.sln`，組態為 `Release | x64`。引擎產物（`<vs_build>\src\Release\` 的 `slicer-engine.exe`、`slicer_core.dll`、`OCCTWrapper.dll`）由使用者覆蓋部署至 `<engine_bin>`。所有「改動前」與「改動後」的引擎都必須出自同一個 `<vs_build>` 目錄與同一組態。
>
> **提交規則**：所有 commit 在提交前都必須取得使用者同意。fork 內既有、未提交的建置調整（`CMakeLists.txt` 的 `encoding_check`、Blosc 連結、`.gitignore`）在改動前與改動後的建置中都保留，但 MUST NOT 被納入本變更的任何 commit。

## 0. 階段 0：基準工具鏈、凍結支撐與 Golden Baseline

### 準備基準引擎

- [x] 0.1 記錄 fork 目前狀態：`git -C third_party/prusaslicer_fork rev-parse HEAD` 與 `git -C third_party/prusaslicer_fork status --short` 的輸出，寫入 `<work>/engines/base-<短commit>/build_info.json`
- [x] 0.2 在根目錄 `.gitignore` 新增 `scripts/raster_bench/work/` 規則（測試改在 `<vs_build>` 建置，不需要另外的測試編譯目錄）
- [x] 0.3 【使用者手動】在**不修改任何 fork 程式碼**的狀態下，以 VS2022 開啟 `<vs_build>\PrusaSlicer.sln`，組態 `Release | x64`，建置 `PrusaSlicer_app_console` 與 `OCCTWrapper` 兩個專案，再將 `<vs_build>\src\Release\` 的 `slicer-engine.exe`、`slicer_core.dll`、`OCCTWrapper.dll` 覆蓋部署至 `<engine_bin>`；完成後回報
- [x] 0.4 將 `<engine_bin>` 的 `slicer-engine.exe`、`slicer_core.dll`、`OCCTWrapper.dll`、`libgmp-10.dll`、`libmpfr-4.dll` 與 `resources\` 複製到（`WebView2Loader.dll` 經 0.5 驗證非 CLI 執行所需，不歸檔） `<work>/engines/base-<短commit>/`，並在 `build_info.json` 補上：
  - 每個複製檔案的 SHA-256
  - `<engine_bin>` 與 `<vs_build>\src\Release\` 的 `slicer-engine.exe`、`slicer_core.dll`、`OCCTWrapper.dll` 指紋是否一致（確認部署的就是這次建置的產物）
  - `<vs_build>\CMakeCache.txt` 的關鍵設定（產生器、`SLIC3R_GUI`、`SLIC3R_STATIC`、`SLIC3R_BUILD_TESTS`、`CMAKE_CXX_FLAGS_RELEASE`、`CMAKE_PREFIX_PATH`）
  - `<engine_bin>\engine_build_id.txt` 的內容照錄，但標註為「手動建置不會更新，不作為引擎身分依據」
  - 複製當下 fork 的原始碼樹指紋（`git rev-parse HEAD^{tree}`）與未提交差異指紋，須與 0.1 紀錄相同；commit 編號可能因切換分支而不同，**不作為判準**
- [x] 0.5 確認基準引擎可以獨立執行：`<work>/engines/base-<短commit>/slicer-engine.exe --help` 成功結束，並以 `--export-sla` 對任一小模型成功產出 `.sl1`

### 建立工具

- [x] 0.6 建立 `<bench>/manifest.json`：四個案例（主基準 16K 8 顆 4×2、次基準 8K 3 顆 3×1、極小 16K 單顆牙冠、滿版 16K 200×110×2 mm 平板）的機型、幅面、平台尺寸、共用光柵化參數、每顆的平移量、來源模型檔名與 SHA-256、執行緒數 `[1, 2, 8]` 與重複次數 `3`；支撐雜湊欄位先留空
- [x] 0.7 實作 `<bench>/make_fixtures.py` 的模型產生：模型目錄只從 `--models` 或 `RASTER_BENCH_MODELS` 取得，未指定即以非零結束碼結束；先驗證來源雜湊；決定性地產生四個案例的 STL；各案例的 `config.ini` 以 `agent.models.SLAConfig` 與 `agent.sla_operations.generate_config_ini` 產生，不另外撰寫 INI 格式
- [x] 0.8 實作 `make_fixtures.py --freeze-support --engine <基準引擎目錄>`：比照 `agent/jobs.py` 的 `run_support_generation` 參數，以 `--export-support-stl` 為主基準與次基準各產生一份 `support.stl`，並把 SHA-256 寫回 `manifest.json`；支撐檔已存在時拒絕覆寫
- [x] 0.9 實作指紋計算模組：以 `zipfile` 讀出 `.sl1` 與預覽 zip 中各項目**解壓後**的位元組計算 SHA-256；只納入層檔與預覽影像，排除 `config.ini`、`prusaslicer.ini` 等中繼資料；依名稱排序，每行 `<名稱>  <sha256>`
- [x] 0.10 實作 `<bench>/run_bench.py`：
  - 執行前驗證模型與支撐雜湊，不符或缺少即拒絕，且不自動重新產生
  - 以 `SLA_LAYER_RLE=1`、`--load config.ini`、`--import-support-stl`、`--export-preview-pngs <preview_scale_for()>`、`--threads N` 執行引擎，可選擇透傳 `SLA_RASTER_*` 環境變數
  - 記錄總牆鐘時間；以 stdout `NN% => <階段>` 行的時間戳推算光柵化階段牆鐘時間；若 stderr 有 `[raster-timing]` 行則一併解析
  - 以 `ctypes` 呼叫 `GetProcessMemoryInfo` 讀取 `PeakWorkingSetSize`（不新增 psutil 依賴）
  - 輸出 `layers.sha256`、`preview.sha256`、`timing.json`、`meta.json` 到 `<work>/runs/<platform>-<build>-<case>-t<threads>-r<n>/`
- [x] 0.11 實作 `<bench>/compare_fingerprints.py`：全部相符結束碼 0、任一不符 1；輸出兩邊項目數、第一個不同項目、差異總數；平台標籤不同時預設拒絕，`--allow-cross-platform` 只輸出報告
- [x] 0.12 撰寫 `<bench>/tests/`（pytest）：指紋排除中繼資料、zip 時間戳不同但指紋相同、單層不符、層數不同、跨平台預設拒絕、排版決定性（同一輸入產出 SHA 相同）、未指定模型目錄即失敗、支撐雜湊不符即拒絕、滿版平板不依賴模型目錄
- [x] 0.13 撰寫 `<bench>/README.md`：模型取得方式（內部共享位置待團隊指定，先留欄位）、產生案例、凍結支撐、執行矩陣與比對步驟

### 產生 Golden Baseline

- [x] 0.14 以本機模型目錄產生四個案例的 STL，再以基準引擎凍結主基準與次基準的支撐
- [x] 0.15 以基準引擎對四個案例各跑 `--threads 1` × 1 次，以及預設執行緒數 × 3 次；預設執行緒數的第 1 次輸出即為該案例的 Golden
- [x] 0.16 以基準引擎另外建立兩份特殊對照：極小案例不設 `SLA_LAYER_RLE`（PNG 層檔模式）× 1 次；極小案例 `blur = 1` × 1 次
- [x] 0.17 從 0.15 的 3 次預設執行緒結果計算光柵化時間與峰值 RSS 的中位數、最大值、最小值；任一組最大與最小差同時超過中位數 5% 且絕對差值大於 0.5 秒時整組重跑（重跑條件只適用於耗時）
- [x] 0.18 將主基準與次基準的實際層數、點亮比例回填 `design.md` 的 Open Questions

### 驗證

- [x] 0.19 執行 `<py> -m pytest scripts/raster_bench/tests -q`，全部通過
- [x] 0.20 對每個案例執行 `<py> scripts/raster_bench/compare_fingerprints.py <t1 結果> <預設執行緒 r1/r2/r3 結果>`，所有比對結束碼皆為 0（基準自我一致性）；**任一不符即停止，不得進入階段 1**
- [x] 0.21 執行 `git status` 與 `git diff --stat`：`<work>/` 下的檔案不出現；變更只包含 `.gitignore` 與 `scripts/raster_bench/`，且不含任何 `.stl`、`.sl1`、`.zip`

### Code Review 查核點

- [x] 0.22 對本階段 diff 執行 `/code-review`，並逐項確認：
  - 沒有硬寫任何本機路徑
  - 來源模型或支撐雜湊不符時確實拒絕執行，且不會自動重新產生
  - 指紋以解壓後內容計算，且排除中繼資料
  - `config.ini` 由 agent 既有函式產生
  - 峰值 RSS 讀的是引擎程序本身，不是 Python 程序
  - 沒有提交任何病患資料或二進位產物
- [x] 0.23 使用者審查通過後，提交階段 0（`.gitignore`、`scripts/raster_bench/`、填入支撐雜湊的 `manifest.json`）

## 1. 階段 1：各階段計時、編碼器同色跳過與單元測試

### 測試建置環境

- [x] 1.1 【使用者手動】在**尚未修改程式碼**時，以 VS2022 於 `<vs_build>\PrusaSlicer.sln`（`Release | x64`）建置 `sla_print_tests` 專案；完成後回報，由 Claude 確認 `<tests>` 實際路徑並回填路徑慣例
- [x] 1.2 在**尚未修改程式碼**時執行 `<tests>`，記錄既有測試的通過數，作為後續「沒有退步」的依據（2026-09-15 基準：51 個測試案例、10843 項斷言全部通過，0 失敗，結束碼 0，約 16 秒；fork tree `561f61f02`）。註：斷言數因多執行緒/排程微幅浮動（約 10,841~10,846）屬正常現象，後續無迴歸判定以「51 案例全過、0 失敗」為唯一準則

### 實作

- [x] 1.3 D9 計時：新增 `SLA_RASTER_TIMING` 開關；以 `tbb::enumerable_thread_specific` 累加 `steady_clock` 耗時；在 `SLAArchiveWriter.hpp` 的 `draw_layers()` 量測 `reset`（`acquire()` 前後）、`encode_layer`、`encode_preview`，在 `SLAPrintSteps.cpp` 的 `lvlfn` 量測 `draw_model`、`postprocess`、`draw_support`；光柵化結束時寫出恰好一行 `[raster-timing] {"layers","threads","wall_s","thread_s":{…}}` 到 stderr
- [x] 1.4 D8 參考實作與開關：把現行逐位元組 RLE 迴圈與區塊優先的預覽累加抽成具名的參考函式，邏輯不做任何修改；新增讀取 `SLA_RASTER_FASTPATH` 的單一函式，程序內只讀一次
- [x] 1.5 D2 RLE 同色跳過：新增 `load_u64`（以 `memcpy` 載入）與 `ctz64`（`__builtin_ctzll`／`_BitScanForward64`）輔助函式，並以編譯期判斷限定小端序；在 `RLERasterEncoder` 實作 8 位元組字組比對，迴圈條件為 `p + 8 <= n`，尾端逐位元組；`num_components != 1`、大端序或 `SLA_RASTER_FASTPATH=0` 時呼叫參考函式
- [x] 1.6 D3 預覽列優先累加：在 `preview_box_downscale_integer` 改為沿來源列走訪、全零字組整段跳過、以長度 `new_w` 的 `sums` 暫存；只讀 `[0, new_w × n) × [0, new_h × n)`；`num_components != 1` 或 `SLA_RASTER_FASTPATH=0` 時呼叫參考函式；通用路徑 `preview_box_downscale` 不修改

### 單元測試

- [x] 1.7 新增 `tests/sla_print/sla_raster_scan_tests.cpp` 並加入 `tests/sla_print/CMakeLists.txt`，測試標籤統一為 `[raster-scan]`
- [x] 1.8 RLE 差分測試（對照參考函式，逐位元組比對）：全黑、全白、只有 (0,0) 或 (W−1,H−1) 單點、灰階雜訊、跨列的長同色段、段長 15／16／4095／4096／1048575／1048576、緩衝長度不是 8 的倍數（例如 7 × 3）、`num_components = 3` 退回參考路徑
- [x] 1.9 預覽差分測試（對照參考函式）：N = 4、5、8、10；含 AA 灰邊的來源；不整除的幅面 7536 × 3240（N = 5）；固定亂數種子的隨機緩衝

### 驗證

- [x] 1.10 【使用者手動】以 VS2022 重建 `sla_print_tests` 後回報；執行 `<tests> "[raster-scan]"` 全部通過，再執行完整的 `<tests>`，通過數不少於 1.2 的紀錄
- [x] 1.11 【使用者手動】依 0.3 相同的方案檔與組態，以 VS2022 重建 `PrusaSlicer_app_console` 與 `OCCTWrapper`，覆蓋部署至 `<engine_bin>` 後回報；再依 0.4 的方式複製並記錄指紋到 `<work>/engines/step1-<短commit>/`
- [x] 1.12 以 step1 引擎對主基準與極小案例，在 `--threads 1`、`2`、`8` 各跑 1 次；每次以 `compare_fingerprints.py` 對 Golden 比對，結束碼皆為 0
- [x] 1.13 以 `SLA_RASTER_FASTPATH=0` 對主基準跑 1 次，指紋等於 Golden
- [x] 1.14 以 `SLA_RASTER_TIMING=1` 對主基準跑 1 次：stderr 恰好一行 `[raster-timing]`，JSON 含六個階段鍵，`layers` 等於實際層數；stdout 的進度行內容與未設定時相同
- [x] 1.15 執行 `<py> -m pytest agent/tests/test_slice_progress_string_contract.py agent/tests/test_slice_progress_parse.py -q`，全部通過
- [x] 1.16 以 step1 引擎在預設執行緒數下對主基準跑 3 次（設定 `SLA_RASTER_TIMING=1`），記錄各階段 `thread_s`，作為階段 2 的比較基礎；確認光柵化時間中位數不高於 Golden 的中位數

### Code Review 查核點

- [x] 1.17 對本階段 fork diff 執行 `/code-review`，並逐項確認：（F1 經顧問審查通過，判定接受現狀無須更動程式碼）
  - 沒有以指標轉型讀取多位元組
  - 所有字組讀取的迴圈條件都保證不越界
  - `ctz` 推論只在小端序啟用
  - 參考函式與修改前的原始迴圈逐行等價
  - 計時不在逐像素或逐多邊形迴圈中取鎖，也不寫 stdout
  - 環境變數在程序內只讀一次
  - `agent/` 沒有任何修改
- [x] 1.18 使用者審查通過後，在 fork 內將階段 1 提交為**單一 commit**（經使用者核准，延後至全案完成統一提交；階段 1 尚未提交）

## 2. 階段 2：Dirty-tile 格子表、像素轉接器與稀疏消費端

### 實作

- [x] 2.1 D4 格子表：新增 `TileMap`（`T = 80` 編譯期常數，以 `static_assert` 檢查 `T % 8 == 0` 與 `T % 40 == 0`；`tiles_x = ceil(W/T)`、`tiles_y = ceil(H/T)`；`std::vector<uint8_t>` 的格子表與格子列摘要）；作為 `AGGRaster` 成員；`RasterBase` 新增 `written_tiles()`，預設回傳 `nullptr`
- [x] 2.2 D7 範圍換算：新增唯一的範圍換算輔助函式（`x1 = min((tx+1)×T, W)`、`y1 = min((ty+1)×T, H)`），並提供依格子列列舉「連續已寫入區段」的函式；後續所有消費端與 `reset()` 只能透過它取得像素範圍
- [x] 2.3 D5 轉接器：新增 `TileTrackingPixfmt<PixFmt>`，只提供 `width`、`height`、`blend_solid_hspan`、`blend_hline`、`copy_hline` 與必要的型別別名，寫入前先標記格子再轉呼叫；`AGGRaster` 的 `renderer_base` 改接轉接器
- [x] 2.4 D6 ① 重置：`reset()` 依已寫入區段直接以背景值寫入 `m_buf`（不經轉接器），再把格子表歸零並重設 gamma；建構子整張清除後把格子表歸零；更新 `reset()` 與 `draw_binary()` 的註解，說明格子表如何滿足「消費端對清除區域一致認知」與執行緒綁定前提
- [x] 2.5 D6 ② 後處理旗標：新增 `RasterPostProcess { fn, zero_preserving_pixel_local = false }`；`create_raster_grayscale_aa()` 新增預設為 false 的參數；`apply_postprocess()` 在旗標為是時只對已寫入區段逐列呼叫 `fn`，為否時整張呼叫一次後把所有格子標為已寫入；`SL1Archive::create_raster()` 僅在 `blur == 0` 時設為是
- [x] 2.6 D6 ③ 稀疏 RLE：實作使用格子表的 RLE 編碼器（整個格子列乾淨時併入 `W` 個背景值、乾淨區段以裁切後長度併入、已寫入區段套用 1.5 的字組比對；同色段換列不重設）；`SLAArchiveWriter` 新增 `get_sparse_encoder()`，預設回傳空；`SL1Archive` 在 `SLA_LAYER_RLE` 開啟時回傳稀疏版；`draw_layers()` 在稀疏編碼器存在且 `written_tiles()` 非空時使用稀疏版
- [x] 2.7 D6 ④ 稀疏預覽：整數倍快路徑在 `T % n == 0` 且有格子表時，對未寫入格子對應的目標像素直接保留背景值，已寫入格子套用 1.6 的列優先累加；目標範圍以 `new_w`、`new_h` 裁切；條件不符時退回 1.6
- [x] 2.8 D8 開關與驗證模式：`SLA_RASTER_FASTPATH=0` 時停用格子表的所有用途（整張清除、整張後處理、參考編碼器）；`SLA_RASTER_VERIFY=1` 時每層編碼後檢查每個未寫入格子皆為背景值，違反時在 stderr 寫出層號與格子座標，並以例外中止光柵化，使 CLI 以非零結束碼結束

### 單元測試

- [x] 2.9 格子登記：模型軌與支撐軌都被登記；AA 邊緣落在相鄰格子時該格被登記；直式方向加 X 鏡像時登記涵蓋所有實際寫入像素；一半在幅面外的多邊形不會登記越界的格子索引
- [x] 2.10 不完整格子：15120 × 6230 的第 77 列格子範圍為 `[6160, 6230)`；7536 × 3240 只寫入 (7535, 3239) 時格子 (94, 40) 被登記且層檔等於參考結果；6230 × 15120（直式對調）格子數為 78 × 189，且只寫入 (6229, 0) 時清除與編碼正確；全空層的同色段長度總和等於 `W × H`
- [x] 2.11 重置：只寫入兩個角落格子後重置，緩衝全為背景且格子表全為未寫入；重置後已寫入格子數為 0；同一個 raster 依序處理「滿版 → 空層 → 右下角單點 → 大面積」，每層都與新建 raster 的結果逐位元組相同
- [x] 2.12 後處理旗標：`blur = 0`（AA level 1、gray level 1）時稀疏套用與整張套用結果相同；`blur = 1` 時整張執行、所有格子被標記，且結果等於參考實作；未提供旗標時預設為否
- [x] 2.13 稀疏 RLE：格子 (0,0) 多標但全黑、格子列 0 其餘與格子列 1 乾淨、第 160 列第一個像素為白時，第一個同色段長度為 2,419,200；已寫入格子右側 30 個黑像素與相鄰乾淨格子合併為同一段
- [x] 2.14 稀疏預覽：16K、N = 10 只有格子 (0,0) 寫入時，目標 `[0,8) × [0,8)` 依來源計算、其餘為 0；8K、N = 5 只有格子 (94,0) 寫入且第 7535 欄為白時，目標欄範圍為 `[1504, 1507)` 且第 7535 欄不影響結果；`T % n != 0` 時退回且不讀格子表
- [x] 2.15 不讀格子表的使用端：PNG 層檔編碼器與 `read_pixel` 的結果與未啟用格子表時相同
- [x] 2.16 驗證模式：透過僅供測試使用的存取介面，在不登記的情況下直接改寫一個像素，確認 `SLA_RASTER_VERIFY=1` 能偵測並回報層號與格子座標
- [x] 2.17 亂數差分：固定亂數種子產生多邊形集合，在 15120 × 6230、7536 × 3240、6230 × 15120 三種幅面下比對稀疏版與參考實作的層檔與預覽

### 驗證

- [x] 2.18 【使用者手動】以 VS2022 重建 `sla_print_tests` 後回報；執行 `<tests> "[raster-scan]"` 全部通過，完整 `<tests>` 的通過數不少於 1.2 的紀錄
- [x] 2.19 【使用者手動】依 0.3 相同的方案檔與組態，以 VS2022 重建引擎並覆蓋部署至 `<engine_bin>` 後回報；依 0.4 的方式複製並記錄指紋到 `<work>/engines/step2-<短commit>/`；在 `SLA_RASTER_VERIFY=1` 下對四個案例各以 `--threads 1` 與 `--threads 8` 跑 1 次，指紋全部等於 Golden，且 stderr 沒有任何違反紀錄
- [x] 2.20 以 `SLA_RASTER_FASTPATH=0` 對主基準跑 1 次，指紋等於 Golden
- [x] 2.21 極小案例 `blur = 1` 跑 1 次，指紋等於 0.16 的 blur 對照
- [x] 2.22 極小案例不設 `SLA_LAYER_RLE` 跑 1 次，指紋等於 0.16 的 PNG 模式對照
- [x] 2.23 決定格子邊長：由 Claude 修改 `T` 後，【使用者手動】依 0.3 以 VS2022 分別建置 `T = 40`、`80`、`160` 三版引擎並逐一部署至 `<engine_bin>` 回報，每版依 0.4 複製到 `<work>/engines/step2-T<值>-<短commit>/`；在預設執行緒數下對主基準與滿版案例各跑 3 次，比較光柵化時間中位數；選定 T 後回填 `design.md` 的 Open Questions，並以選定的 T 重建 step2 引擎、重跑 2.19

### Code Review 查核點

- [x] 2.24 對本階段 fork diff 執行 `/code-review`，並逐項確認：
  - 轉接器沒有提供目前用不到的寫入方法
  - `reset()` 的寫入沒有經過轉接器
  - 所有像素範圍都只由 2.2 的輔助函式換算，沒有任何消費端自行計算邊界
  - 後處理旗標預設為 false，且 SL1 只在 `blur == 0` 時設為 true
  - `AnycubicSLA`、`SL1_SVG`、GUI 字型工作與 `RasterToPolygons` 都不需修改，行為不變
  - 未設定 `SLA_RASTER_VERIFY` 時不做任何全幅面檢查
  - `reset()` 與 `draw_binary()` 的註解已更新
  - 沒有新增跨執行緒共享的可變狀態
- [x] 2.25 使用者審查通過後，在 fork 內將階段 2 提交為**單一 commit**

## 3. 階段 3：驗收矩陣、邊際驗證、效能門檻與 evidence 歸檔

### 正確性驗收矩陣

- [ ] 3.1 【使用者手動】以階段 2 commit 的原始碼，依 0.3 相同的方案檔與組態以 VS2022 建置最終引擎，覆蓋部署至 `<engine_bin>` 後回報；依 0.4 的方式複製並記錄指紋到 `<work>/engines/final-<短commit>/`
- [ ] 3.2 設定 `SLA_RASTER_VERIFY=1`，對四個案例各以 `--threads 1`、`2`、`8` 跑 3 次（每個案例 9 次，共 36 次）
- [ ] 3.3 以 `compare_fingerprints.py` 將 36 次的層檔與預覽指紋逐一對 Golden 比對；**任一次不符即判定不通過**，回到階段 2 修正後重跑整個 3.2，不得只重跑失敗的那一次

### 邊際驗證

- [ ] 3.4 極小案例：確認指紋一致，並以 `SLA_RASTER_TIMING=1` 記錄各階段 `thread_s`，說明與主基準相比哪些階段下降最多
- [ ] 3.5 滿版案例：確認指紋一致，並比較 step1 與 final 的各階段 `thread_s`，找出格子表與轉接器帶來的額外成本落在哪個階段

### 效能門檻驗收

- [ ] 3.6 在驗收機（i7-11370H、4 核 8 緒、16 GB、Windows 11，插電並在每輪之間冷卻）上，**不設** `SLA_RASTER_VERIFY` 與 `SLA_RASTER_TIMING`，以預設執行緒數對四個案例各跑 3 次；任一組最大與最小差同時超過中位數 5% 且絕對差值大於 0.5 秒時整組重跑
- [ ] 3.7 依中位數判定門檻：主基準光柵化時間 ≤ Golden 的 50%，且峰值 RSS ≤ Golden；次基準光柵化時間 ≤ Golden；滿版案例光柵化時間 ≤ Golden 的 103%；未達標時回到階段 2，**不得自行放寬門檻**

### 端到端與回歸

- [ ] 3.8 分別以 `SLICER_ENGINE_BIN` 指向基準引擎與最終引擎啟動 agent，對主基準走完 `POST /api/v2/slices → upload → upload-support → execute → download.prz`；兩份 PRZ 逐位元組相同
- [ ] 3.9 執行 `<py> -m pytest agent/tests -q`，全部通過
- [ ] 3.10 （依 `design.md` Open Questions 的決定）若要求 macOS 驗證：在 macOS 上以同一套編譯設定建置基準與最終引擎，對主基準比對一次指紋；時間只記錄、不採計

### 歸檔

- [ ] 3.11 建立 `openspec/changes/optimize-raster-canvas-scan/evidence/windows-<timestamp>/`，放入：Golden 與最終引擎的指紋清單、驗收矩陣 36 次的比對摘要、效能表（中位數、最大、最小）、峰值 RSS、各階段 `thread_s`、三支引擎的 `build_info.json`
- [ ] 3.12 回填 `design.md` 的 Open Questions（格子邊長、實際層數與點亮比例、macOS 決定），以及 `proposal.md` 中推算數字的實測值
- [ ] 3.13 經使用者同意後，在父 repo 更新 `third_party/prusaslicer_fork` 的 submodule 指標為**單獨一個 commit**，並提交 evidence 與文件回填

### 驗證

- [ ] 3.14 執行 `openspec validate optimize-raster-canvas-scan --strict`，結果為 valid
- [ ] 3.15 確認 evidence 目錄只含 `.sha256`、`.json`、`.md`；執行 `git status` 確認沒有任何 `.stl`、`.sl1`、`.zip`、`.png`、`.rle` 被加入

### Code Review 查核點

- [ ] 3.16 審查 evidence 與原始輸出的一致性：從 `<work>/runs/` 隨機抽 3 次執行，確認歸檔的指紋與時間數字和原始檔相同
- [ ] 3.17 審查門檻判定：確認使用的是中位數、離散同時超過 5% 且絕對差值大於 0.5 秒的組別確實重跑過、所有門檻都沒有被放寬
- [ ] 3.18 審查 commit 切分：階段 1 與階段 2 於 fork 端統一為單一 commit (10fcc6d96)、父 repo 的 submodule 指標更新為獨立 commit，且都沒有夾帶既有的建置調整
- [ ] 3.19 使用者最終審查通過
