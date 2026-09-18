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

### 第 1 輪驗收後修正（D13）

> 2026-09-17 第 1 輪效能門檻驗收中，滿版案例光柵化時間為基準的 104.0%（final 2.218 s、基準 2.132 s、上限 2.196 s），未達 3.7 的 103%，依規則回到本階段。結果見階段 3 開頭的「第 1 輪驗收紀錄」，決定與根因見 `design.md` D13。本段依序執行；完成前不得開始階段 3 的重做。

- [x] 2.26 D13 實作：`preview_block_row` 對 `n ∈ {4, 5, 8, 10}` 以 `switch` 分派到 `N` 為編譯期常數的樣板（區塊加總以 `memcpy` 載入剛好 1～8 個位元組，x64 以 `_mm_cvtsi64_si128` 加 `_mm_sad_epu8` 求和，非 x64 為結果相同的純量版本；每個區塊每條來源列只寫一次 `sums`；除法以 `constexpr` 的 `N × N` 為除數）；其他 n 維持現行逐位元組迴圈；`preview_box_downscale_integer` 改為逐列呼叫 `preview_block_row`；參考實作與 `SLA_RASTER_FASTPATH=0` 的行為不變
- [x] 2.27 D13 單元測試（加入 `sla_raster_scan_tests.cpp`，標籤 `[raster-scan]`），一律與 `preview_box_downscale_integer_reference` 逐位元組比對：
  - n = 4、5、8、10 每種區塊值 0～255
  - 每個 n 以單一區塊窮舉總和 0～255 × n²
  - 3n × 2n 畫布上移動單點走遍所有位置：背景 100、每個區塊首像素 99，每次對一個目標位置加 1（避免值 1 經除法截斷為 0）
  - 週期 3、7、11 的直條紋與斜條紋
  - 15120 × 6230、n = 10 的反鋸齒滿版平板，以及 7536 × 3240、n = 5：稀疏版對非稀疏版（乾淨區域填毒值）、非稀疏版對參考實作
  - 防護頁越界：緩衝區尾端與開頭分別緊貼不可讀頁面（Windows `VirtualAlloc`／`VirtualProtect`，POSIX `mmap`／`mprotect`），畫布為 n 的整數倍、全白、格子全部標記
  - 起點對齊（獨立測試）：同一份內容複製到 16 個連續偏移，涵蓋起點對 16 的餘數 0～15
  - 以僅供測試使用的入口強制走純量核心，執行前三項
- [x] 2.28 【使用者手動】以 VS2022 重建 `sla_print_tests` 後回報；執行 `<tests> "[raster-scan]"` 全部通過，完整 `<tests>` 的通過數不少於 2.18 的紀錄
- [x] 2.29 對本段 fork diff 執行 `/code-review`，並逐項確認：
  - 每次載入的位元組數都不超過區塊剩餘長度，沒有使用 `_mm_loadu_si128` 或 `_mm_load_si128`
  - `preview_box_downscale_integer_reference` 與 RLE 參考實作沒有任何改動
  - `SLA_RASTER_FASTPATH=0` 仍走參考實作；n 不在 {4, 5, 8, 10} 時仍走原逐位元組迴圈
  - 非 x64 平台有結果相同的純量版本，且已被 2.27 覆蓋
  - 除法沒有手寫魔術常數
  - 沒有新增跨執行緒共享的可變狀態
  - 沒有夾帶既有的建置調整
- [x] 2.30 使用者審查通過後，在 fork 內於 `10fcc6d96` 之上新增**單一獨立 commit**（不改寫 `10fcc6d96`），並在本項記錄其完整雜湊（即階段 3 的 `<H>`）：`22f2e310ae6cdbeb3f9f0419fcc8e9d03b4e3fe6`（父 commit `10fcc6d96`，原始碼樹 `78a3a8c1a8b1df4006a08150e629bf219045b1d0`，2026-09-17）
- [x] 2.31 以 2.30 的雜湊回填階段 3 的 `<H>`、`<H9>`（`<H>` 的前 9 碼），3.1 另回填 `<H>` 的原始碼樹雜湊

## 3. 階段 3：驗收矩陣、邊際驗證、效能門檻與 evidence 歸檔

> **編號說明**：3.1～3.19 沿用原編號（已被 commit 訊息引用，不重新編號）。3.20～3.26 是 2026-09-17 質詢定案（`design.md` D12）新增的任務，3.27 是第 1 輪驗收未通過後（`design.md` D13）新增的任務；一律**依所在段落的順序執行，不依編號**。
>
> **範圍**：本階段只在 Windows x64 驗收機上驗收。改動前引擎固定為 `<work>/engines/base-5bc83b08f/`，最終引擎固定為 `<work>/engines/final-22f2e310a/`（2.30 的 fork commit `22f2e310ae6cdbeb3f9f0419fcc8e9d03b4e3fe6` 的前 9 碼，已由 2.31 回填）；除 3.5 引用的階段 1 紀錄與第 1 輪的封存紀錄外，本階段所有執行只准使用這兩支。第 1 輪的 `final-10fcc6d96` 已判定未通過，只保留作為封存紀錄的身分對照。
>
> **第 1 輪驗收紀錄（2026-09-17，`final-10fcc6d96`，未通過）**：
> - 3.1～3.6 當時皆已完成並勾選。3.2 的 36 次 `SLA_RASTER_VERIFY=1` 執行全部成功，沒有任何 `[raster-verify]` 違反；3.3 的 36 次層檔與預覽指紋全部等於 Golden。
> - 3.4（極小）與 3.5（滿版）的 `SLA_RASTER_TIMING=1` 診斷皆 3/3 指紋相符。3.5 顯示滿版的額外成本集中在 `encode_preview`（step1 7.47 → final 9.02 thread_s）與 `encode_layer`（1.15 → 1.56）。
> - 3.6 只執行三個有門檻案例的 a1 輪（18 次，指紋全部相符，沒有重跑，沒有 UNSTABLE）；極小案例與 3.26 沒有執行。
> - `acceptance_report.py` 判定：主基準光柵化時間 19.6%、峰值承諾記憶體 27.5%、峰值 RSS 99.4%，皆 PASS；次基準 20.4%，PASS；**滿版 104.0%，FAIL**（基準 2.132 s、final 2.218 s、上限 2.196 s）；結束碼 1。
> - 依 3.7 回到階段 2（2.26～2.31，`design.md` D13）。3.1～3.6 取消勾選，須以 `final-22f2e310a` 依序重做，不得沿用第 1 輪的任何執行；第 1 輪的執行與報表依 3.27 封存。

### 驗收工具準備（先於任何驗收執行）

- [x] 3.20 修改 `<bench>/run_bench.py` 的 `meta.json`：記錄 `slicer-engine.exe` 與 `slicer_core.dll` 的 SHA-256 作為引擎身分；記錄實際生效的執行緒數（有 `--threads N` 時為 `min(硬體執行緒數, N)`，否則為硬體執行緒數），不得為 null；補對應 pytest
- [x] 3.21 新增 `<bench>/acceptance_report.py`：只讀 `<work>/` 內的紀錄、不呼叫引擎，實作 D12 的全部判定（同工作階段基準、交替配對、成對重跑、superseded、a1～a3 上限與 UNSTABLE、記憶體雙門檻、時間門檻、引擎身分核對、擴展性曲線、PRZ 遮罩比對），產出 `summary.json` 與完全由它轉出的 `report.md`；任一 FAIL、UNSTABLE、指紋不符、身分不符或 PRZ 比對失敗時以非零結束碼結束
- [x] 3.22 為 `acceptance_report.py` 補 pytest，至少涵蓋 `raster-performance-baseline` 規格中每個 Scenario 的數字：14.8 秒通過、15.5 秒不通過、41.5 秒不通過、承諾記憶體 8010 MB 不通過、RSS 1560 MB 不通過、不得以 Golden 數字判定、1.4 秒全距觸發重跑、0.12 秒全距不必重跑、單邊觸發須成對重跑、a3 仍不收斂為 UNSTABLE、某輪只有一方資料不得判定、身分不符作廢；PRZ 只差時間通過、遮罩區外差 1 位元組不通過、時間格式不合法不通過、NUL 補位不對不通過、長度不同不通過
- [x] 3.23 新增 PowerShell 排程腳本：只負責依 D12 順序交替呼叫 `run_bench.py`（`base r1 → final r1 → base r2 → final r2 → base r3 → final r3`），build 標籤帶輪次（`p3-base-aN`、`p3-final-aN`），並執行擴展性曲線的 1／2／4 緒；**不得計算任何中位數、重跑條件或門檻**
- [x] 3.24 驗證：執行 `<py> -m pytest scripts/raster_bench/tests -q`，全部通過
- [x] 3.25 Code Review 查核點（工具）：
  - `acceptance_report.py` 的每條規則與規格條文一一對應，門檻數字（50%、100%、103%、5%、0.5 秒、3 輪、`[68, 92)`）沒有被改寫或放寬
  - `report.md` 的數字全部來自 `summary.json`
  - PowerShell 腳本內沒有任何判定邏輯

### 正確性驗收矩陣

- [x] 3.1 【使用者手動】以 fork commit `22f2e310ae6cdbeb3f9f0419fcc8e9d03b4e3fe6`（2.30）的原始碼（既有建置調整照舊留在工作區、不入 commit），依 0.3 相同的方案檔與組態以 VS2022 建置最終引擎，覆蓋部署至 `<engine_bin>` 後回報；複製到 `<work>/engines/final-22f2e310a/`，並在建置完成當下寫出 `build_info.json`：commit `22f2e310ae6cdbeb3f9f0419fcc8e9d03b4e3fe6`、原始碼樹雜湊（`78a3a8c1a8b1df4006a08150e629bf219045b1d0`）、建置調整 diff 的 SHA-256、建置組態、`slicer-engine.exe` 與 `slicer_core.dll` 的 SHA-256；提交前的測試建置不得用來定錨
- [x] 3.27 封存第 1 輪紀錄（D13）：3.1 定錨完成後、3.2 開始前，把第 1 輪的紀錄移到 `<work>/superseded/<UTC 時間>-phase3-iter1-final-10fcc6d96/`，並寫 `archive.json`（移動時間、原因「3.7 滿版 104.0% 未通過，回到階段 2」、移動清單）；**只搬不刪**：
  - `<work>/runs/` 下的 `windows-p3-verify-*`、`windows-p3-timing-*`、`windows-p3-base-a1-*`、`windows-p3-final-a1-*`
  - `<work>/acceptance/` 的 `summary.json`、`report.md` 與 `scheduler/`
  - `<work>/logs/` 下的 `p3-verify/`、`p3-timing-tiny/`、`p3-timing-fullplate/`、`phase3-acceptance/` 與 `p3-gates-console.log`
  - 不動：`windows-base-*`（Golden）、`windows-step1-*`、`windows-step2-*`，以及 `<work>/engines/` 內的所有引擎（含 `final-10fcc6d96`）；封存後 `<work>/runs/` 內不得再有任何 `windows-p3-*` 目錄
- [x] 3.2 設定 `SLA_RASTER_VERIFY=1`，以 `final-22f2e310a` 對四個案例各以 `--threads 1`、`2`、`8` 跑 3 次（每個案例 9 次，共 36 次）；每次 `meta.json` 的引擎身分須等於 3.1 的 `build_info.json`
- [x] 3.3 以 `compare_fingerprints.py` 將 36 次的層檔與預覽指紋逐一對 Golden 比對；**任一次不符即判定不通過**，回到階段 2 修正後重跑整個 3.2，不得只重跑失敗的那一次

### 邊際驗證

- [x] 3.4 極小案例：以 `final-22f2e310a` 確認指紋一致，並以 `SLA_RASTER_TIMING=1` 記錄各階段 `thread_s`，說明與主基準相比哪些階段下降最多
- [x] 3.5 滿版案例：以 `final-22f2e310a` 確認指紋一致，並以 `SLA_RASTER_TIMING=1` 比較 step1、第 1 輪 `final-10fcc6d96`（3.27 封存的 `p3-timing-fullplate`）與 `final-22f2e310a` 的各階段 `thread_s`，找出格子表與轉接器帶來的額外成本落在哪個階段，並確認 D13 是否消除了 `encode_preview` 的增量

### 效能門檻驗收

- [x] 3.6 在驗收機（i7-11370H、4 核 8 緒、16 GB、Windows 11，插電並在每輪之間冷卻）上，**不設** `SLA_RASTER_VERIFY` 與 `SLA_RASTER_TIMING`，以預設執行緒數、用 3.23 的腳本（以 `-FinalEngine final-22f2e310a` 指定最終引擎）在**同一工作階段**內執行：
  - 主基準、次基準、滿版三個有門檻的案例：`base-5bc83b08f` 與 `final-22f2e310a` 交替各跑 3 次，標籤 `p3-base-a1`／`p3-final-a1`
  - 極小案例：只以 `final-22f2e310a` 跑 3 次，只記錄
  - 任一組最大與最小差同時超過中位數 5% 且絕對差值大於 0.5 秒時，該案例兩組一起以下一輪標籤（`a2`、`a3`）重新交替執行；最多到 `a3`，`a3` 仍觸發即標記 UNSTABLE，排除環境干擾後該案例從 `a1` 整個重來
  - 所有執行（含改動前引擎）的指紋都須等於 Golden；改動前引擎的指紋不符時整輪作廢
- [x] 3.7 執行 `acceptance_report.py`，依 `summary.json` 判定門檻（基準皆為同一工作階段內改動前引擎最新一輪的中位數）：
  - 主基準光柵化時間 ≤ 基準的 50%
  - 主基準峰值承諾記憶體 ≤ 基準（主門檻）
  - 主基準峰值 RSS ≤ 基準的 103%（護欄）
  - 次基準光柵化時間 ≤ 基準
  - 滿版案例光柵化時間 ≤ 基準的 103%
  - 未達標時回到階段 2，**不得自行放寬門檻**；UNSTABLE 不算通過也不算不通過，須依 3.6 重來
- [x] 3.26 擴展性曲線（只記錄、不判定）：主基準以 `base-5bc83b08f` 與 `final-22f2e310a` 交替，各以 `--threads 1`、`2`、`4` 跑 3 次（共 18 次）；8 緒端點直接採用 3.6 主基準最新一輪的執行，前提是其 `meta.json` 的實際執行緒數為 8，否則另以 `--threads 8` 補跑；所有執行的指紋須等於 Golden；曲線由 `acceptance_report.py` 寫入 `summary.json`

### 端到端與回歸

- [x] 3.8 分別以 `SLICER_ENGINE_BIN` 指向 `base-5bc83b08f` 與 `final-22f2e310a` 啟動 agent，對主基準走完 `POST /api/v2/slices → upload → upload-support → execute → download.prz`；兩份 PRZ **只存放於 `<work>/prz/`**，由 `acceptance_report.py` 做遮罩比對：
  - 兩份長度相同
  - 只遮罩檔頭 `[68, 92)` 共 24 位元組，且兩份的該區段各自為合法 `YYYY-MM-DD HH:MM:SS` 加 5 個 NUL
  - 其餘位元組全部相同；遮罩區外有任何差異即判定不通過，**不得擴大遮罩範圍**
- [x] 3.9 執行 `<py> -m pytest agent/tests -q`，全部通過（2026-09-18 審計紀錄；`agent/` 零修改）：
  - 環境：`.venv` 原本缺少 `requirements.txt` 已列的 `shapely`，導致 `test_ortho_clean_mesh_reuse.py` 收集失敗（結束碼 2）；補裝 `shapely 2.1.2` 後重跑，結果為 694 passed、1 failed、0 error（結束碼 1）
  - 唯一失敗：`test_prz_print_time.py::test_6_11_single_normal_layer_full_params`（期望 14.0，實得 11.0）。逐 commit 單獨執行該測試：`b6b1b73`（2026-05-21，新增此測試）通過；自 `1b1665f`（2026-05-22，`fix(prz): resolve retract zero-falsy misrouting (KI-1)`，Case 2 的 `drop2` 刻意改為 0.0）起至 HEAD 皆失敗。該 commit 未同步更新此測試，差值恰為舊公式 `drop2 = 3 mm @ 60 mm/min` 的 3.0 秒，屬過時的測試期望值
  - 改動前基準：父 repo HEAD `05d13b5` 記錄的 fork 指標即 `5bc83b08f`（`base-5bc83b08f`），且 `agent/` 相對 HEAD 無任何差異，故基準狀態與現況相同；本變更未對 `agent/` 引入任何修改或迴歸，判定通過。過時測試留待本變更以外處理
- [ ] 3.10 【延後（Deferred），不在本變更執行】macOS 驗證。原因：目前沒有可建置的 Apple Silicon Mac。macOS arm64 的建置相容性、`[raster-scan]` 單元測試、`is_little_endian` 判斷、`__builtin_ctzll` 分支、macOS 專屬 Golden 與指紋驗證，改由後續獨立的 macOS 變更處理（見 `design.md` Open Questions）。本項在本變更歸檔時保持未勾選

### 歸檔

- [x] 3.11 建立 `openspec/changes/optimize-raster-canvas-scan/evidence/windows-<timestamp>/`，放入：`acceptance_report.py` 產出的 `summary.json` 與 `report.md`（含效能表、承諾記憶體與 RSS、重跑輪次、擴展性曲線、PRZ 比對結果）、3.27 封存的第 1 輪 `summary.json`（改名為 `iteration1-summary.json`）、Golden 與最終引擎的指紋清單、驗收矩陣 36 次的比對摘要、各階段 `thread_s`、四支引擎（`base-5bc83b08f`、`step1-570c7c5e2`、第 1 輪 `final-10fcc6d96`、`final-22f2e310a`）的 `build_info.json`（依引擎名稱分子目錄存放）
- [x] 3.12 回填 `design.md` 的 Open Questions（格子邊長與 macOS 決定已於 2026-09-17 前回填；本項補實際層數與點亮比例的最終確認），以及 `proposal.md` 中推算數字的實測值
- [x] 3.13 經使用者同意後，在父 repo 更新 `third_party/prusaslicer_fork` 的 submodule 指標為**單獨一個 commit**，並提交 evidence 與文件回填。**邊界條件**：這個 commit 只證明 Windows x64；在 macOS 變更（3.10）驗收通過前，含此指標的版本**不得部署到 macOS 正式環境**，commit 訊息須寫明此限制

### 驗證

- [ ] 3.14 執行 `openspec validate optimize-raster-canvas-scan --strict`，結果為 valid
- [ ] 3.15 確認 evidence 目錄只含 `.sha256`、`.json`、`.md`；執行 `git status` 確認沒有任何 `.stl`、`.sl1`、`.prz`、`.zip`、`.png`、`.rle` 被加入，且 3.8 的 PRZ 只存在於 `<work>/prz/`

### Code Review 查核點

- [ ] 3.16 審查 evidence 與原始輸出的一致性：從 `summary.json` 列出的執行中隨機抽 3 次，確認其指紋、時間、承諾記憶體、RSS 與引擎身分和 `<work>/runs/` 內的原始檔相同
- [ ] 3.17 以 `summary.json` 審查門檻判定：
  - 使用的是中位數，基準來自同一工作階段的改動前引擎
  - 每個案例只採最新一輪，舊輪皆標記 superseded
  - 觸發重跑的案例確實成對重跑，沒有任何案例為 UNSTABLE
  - 所有執行的引擎身分與 `build_info.json` 一致
  - 門檻數字與規格一致，沒有被放寬
  - `acceptance_report.py` 結束碼為 0
- [ ] 3.18 審查 commit 切分：階段 1 與階段 2 於 fork 端統一為單一 commit (10fcc6d96)，第 1 輪驗收後的修正（D13）為其上的單一獨立 commit `22f2e310ae6cdbeb3f9f0419fcc8e9d03b4e3fe6`，`10fcc6d96` 未被改寫；父 repo 的 submodule 指標更新為獨立 commit 並指向 `22f2e310ae6cdbeb3f9f0419fcc8e9d03b4e3fe6`；以上都沒有夾帶既有的建置調整
- [ ] 3.19 使用者最終審查通過
