# raster-performance-baseline Specification

## Purpose
TBD - created by archiving change optimize-raster-canvas-scan. Update Purpose after archive.
## Requirements
### Requirement: 基準案例須以固定組成定義且可重現

光柵化效能改動的基準案例 SHALL 由入庫的案例清單（`scripts/raster_bench/manifest.json`）完整定義，任何人以相同的來源模型與相同的引擎，SHALL 能產出位元組相同的測試模型。

案例清單 SHALL 至少包含以下四個案例：

| 案例 | 機型與幅面 | 組成 | 用途 |
| --- | --- | --- | --- |
| 主基準 | Sonic Mighty Revo 16K，15120 × 6230，平台 211.68 × 118.37 mm | `fixture-surgical-guide-18-19.stl` 8 顆，4 × 2 排列 | 正確性與效能門檻 |
| 次基準 | Sonic Mini 8K S，7536 × 3240，平台 165.792 × 71.28 mm | 同一導板 3 顆，3 × 1 排列 | 正確性與中型機台不退步 |
| 極小案例 | 16K | `fixture-crown-cad.stl` 1 顆 | 稀疏邊際正確性 |
| 滿版案例 | 16K | 程式產生的 200 × 110 × 2 mm 平板 | 最壞情況的額外成本 |

所有案例 SHALL 使用同一組光柵化相關參數：`layer_height = 0.05`、`anti_aliasing = 1`、`anti_aliasing_level = 1`、`gray_level = 1`、`blur = 0`、`gamma_correction = 1.0`，引擎環境變數 `SLA_LAYER_RLE=1`，預覽縮放比取自 `preview_scale_for()`。

案例清單對來源模型 SHALL 只記錄檔名與 SHA-256，MUST NOT 記錄絕對路徑。模型目錄 SHALL 由命令列參數 `--models` 或環境變數 `RASTER_BENCH_MODELS` 指定，工具 MUST NOT 硬寫任何本機路徑。

排版 SHALL 以每顆的平移量描述，且 SHALL 為決定性的：相同輸入產生的排版 STL SHALL 逐位元組相同。

#### Scenario: 主基準的組成

- **GIVEN** 模型目錄內有 SHA-256 與清單相符的 `fixture-surgical-guide-18-19.stl`
- **WHEN** 產生主基準測試模型
- **THEN** 產出 SHALL 為 8 顆導板、4 × 2 排列，且全部落在 211.68 × 118.37 mm 平台內
- **AND** 使用的參數 SHALL 為本 requirement 列出的光柵化參數組

#### Scenario: 排版結果可重現

- **GIVEN** 兩台機器持有相同的來源模型
- **WHEN** 兩台機器各自產生主基準測試模型
- **THEN** 兩份排版 STL 的 SHA-256 SHALL 相等

#### Scenario: 來源模型雜湊不符時拒絕產生

- **GIVEN** 模型目錄內的 `fixture-surgical-guide-18-19.stl` 雜湊與清單記錄不同
- **WHEN** 執行產生測試模型的工具
- **THEN** 工具 SHALL 以非零結束碼結束，並指出不相符的檔名
- **AND** MUST NOT 產生任何測試模型

#### Scenario: 滿版案例不依賴外部檔案

- **WHEN** 在沒有模型目錄的機器上產生滿版案例
- **THEN** 工具 SHALL 以程式產生 200 × 110 × 2 mm 平板
- **AND** 兩次產生的 STL SHA-256 SHALL 相等

#### Scenario: 未指定模型目錄時不猜測路徑

- **GIVEN** 未提供 `--models` 參數且未設定 `RASTER_BENCH_MODELS`
- **WHEN** 產生需要來源模型的案例
- **THEN** 工具 SHALL 以非零結束碼結束，並提示如何指定模型目錄
- **AND** MUST NOT 自行搜尋任何預設路徑

### Requirement: 支撐網格須凍結且只產生一次

需要支撐的案例 SHALL 使用一份預先產生並凍結的 `support.stl`，每次切片皆以 `--import-support-stl` 匯入，MUST NOT 在每次量測時重新產生支撐。

凍結 SHALL 只在建立基準時執行一次，且 SHALL 使用「改動前」的引擎；產出檔案的 SHA-256 SHALL 寫入案例清單並隨之入庫。

量測工具在執行前 SHALL 驗證支撐檔的雜湊。支撐檔缺少或雜湊不符時，工具 SHALL 拒絕執行，MUST NOT 自動重新產生——自動重新產生會在不知情的情況下更換比較基礎。

#### Scenario: 量測使用凍結的支撐

- **GIVEN** 主基準的 `support.stl` 雜湊與清單相符
- **WHEN** 執行主基準量測
- **THEN** 引擎命令列 SHALL 包含 `--import-support-stl` 並指向該檔案
- **AND** 引擎命令列 MUST NOT 包含 `--export-support-stl`

#### Scenario: 支撐檔遺失時拒絕量測

- **GIVEN** 主基準的 `support.stl` 不存在
- **WHEN** 執行主基準量測
- **THEN** 工具 SHALL 以非零結束碼結束，並指出缺少的檔案
- **AND** MUST NOT 執行引擎，也 MUST NOT 產生新的支撐檔

#### Scenario: 支撐檔被替換時拒絕量測

- **GIVEN** 主基準的 `support.stl` 存在，但雜湊與清單記錄不同
- **WHEN** 執行主基準量測
- **THEN** 工具 SHALL 以非零結束碼結束，並同時列出清單記錄的雜湊與實際雜湊

### Requirement: 病患相關資料不得入庫

來源 STL、排版後的測試模型與凍結的支撐檔 MUST NOT 提交進 git。它們 SHALL 放在 git 忽略的工作目錄（`scripts/raster_bench/work/`）或內部共享位置。

由這些模型切出的產物（`.sl1`、預覽 zip、層檔、端到端驗收下載的 `.prz`）同樣 MUST NOT 提交進 git，且 SHALL 只存放於 `scripts/raster_bench/work/` 內。

入庫的驗收紀錄（`openspec/changes/<change>/evidence/`）SHALL 只包含文字：指紋清單、時間表與中繼資料。MUST NOT 包含任何 STL、`.sl1`、`.prz`、預覽 zip 或影像檔。

#### Scenario: 工作目錄被 git 忽略

- **GIVEN** 已在 `scripts/raster_bench/work/` 產生測試模型與量測輸出
- **WHEN** 執行 `git status`
- **THEN** 該目錄下的任何檔案 MUST NOT 出現在未追蹤或已修改的清單中

#### Scenario: 驗收紀錄只含文字

- **WHEN** 將一次驗收結果歸檔至 evidence 目錄
- **THEN** 歸檔的檔案 SHALL 僅為 `.sha256`、`.json` 或 `.md`
- **AND** MUST NOT 含有 `.stl`、`.sl1`、`.prz`、`.zip`、`.png` 或 `.rle` 檔案

#### Scenario: 端到端驗收下載的 PRZ 不離開工作目錄

- **GIVEN** 端到端驗收已下載改動前與最終引擎各一份主基準 PRZ
- **WHEN** 執行 `git status`
- **THEN** 兩份 PRZ SHALL 位於 `scripts/raster_bench/work/` 內
- **AND** MUST NOT 出現在未追蹤或已修改的清單中

### Requirement: 指紋須以解壓後的項目計算

層檔與預覽圖的指紋 SHALL 以 `.sl1` 與預覽 zip 內每個項目**解壓後**的位元組計算 SHA-256。MUST NOT 以 zip 檔本身的雜湊或檔案大小作為一致性判準，因為 zip 標頭含時間戳記，且壓縮結果會隨建置設定改變。

指紋檔 SHALL 分為層檔（`layers.sha256`）與預覽圖（`preview.sha256`）兩份，每行格式為 `<項目名稱>  <sha256 小寫十六進位>`，並依項目名稱排序。只納入層檔與預覽影像項目；`.sl1` 內的 `config.ini`、`prusaslicer.ini` 等中繼資料項目 MUST NOT 納入。

每次執行 SHALL 同時寫出 `meta.json`，至少記錄：平台標籤、引擎身分、fork commit、實際生效的執行緒數、重複序號與參數雜湊。

- **引擎身分** SHALL 為引擎目錄內 `slicer-engine.exe` 與 `slicer_core.dll` 各自的 SHA-256。引擎自報的 build id（`engine_build_id.txt`）只作參考，MUST NOT 作為身分依據，因為不同原始碼建出的引擎可能回報相同的 build id。
- **實際生效的執行緒數** MUST NOT 為 null。有給 `--threads N` 時 SHALL 記錄 `min(硬體執行緒數, N)`；沒給時 SHALL 記錄硬體執行緒數。這與引擎決定執行緒數的規則一致。

#### Scenario: zip 時間戳記不同不影響指紋

- **GIVEN** 兩份 `.sl1` 的層檔內容逐位元組相同，但 zip 標頭的時間戳記不同
- **WHEN** 分別計算兩者的層檔指紋
- **THEN** 兩份 `layers.sha256` SHALL 逐行相等

#### Scenario: 預覽圖納入指紋

- **GIVEN** 一次產出 590 層與 590 張預覽圖的切片
- **WHEN** 計算指紋
- **THEN** `layers.sha256` SHALL 有 590 行
- **AND** `preview.sha256` SHALL 有 590 行

#### Scenario: 中繼資料項目不納入

- **WHEN** 計算一份含 `config.ini` 的 `.sl1` 的層檔指紋
- **THEN** `layers.sha256` MUST NOT 含有 `config.ini` 的行

#### Scenario: 預設執行緒數仍記錄實際值

- **GIVEN** 驗收機有 8 個硬體執行緒
- **WHEN** 不給 `--threads` 執行一次量測
- **THEN** `meta.json` 的執行緒數 SHALL 為 8
- **AND** MUST NOT 為 null

#### Scenario: build id 相同但二進位不同

- **GIVEN** 兩個引擎目錄的 `engine_build_id.txt` 內容相同，但 `slicer_core.dll` 的內容不同
- **WHEN** 分別以兩者執行量測
- **THEN** 兩次執行的 `meta.json` SHALL 記錄不同的引擎身分

### Requirement: 指紋比對規則

比對工具 SHALL 逐行比較兩組指紋，並以結束碼表示結果：全部相符為 0，任一不符為 1。

不符時工具 SHALL 輸出：兩邊的項目數、第一個不同的項目名稱、不同項目的總數。項目數不同本身即 SHALL 視為不符。

兩組指紋的平台標籤不同時，工具 SHALL 預設拒絕比對並以非零結束碼結束。加上 `--allow-cross-platform` 時工具 SHALL 只輸出差異報告，且該結果 MUST NOT 被採計為驗收通過的依據。

#### Scenario: 完全相符

- **GIVEN** 兩組同平台的指紋逐行相等
- **WHEN** 執行比對
- **THEN** 結束碼 SHALL 為 0

#### Scenario: 單層不符

- **GIVEN** 兩組同平台的指紋只有第 316 層不同
- **WHEN** 執行比對
- **THEN** 結束碼 SHALL 為 1
- **AND** 輸出 SHALL 指出第一個不同的項目為第 316 層，不同項目總數為 1

#### Scenario: 層數不同

- **GIVEN** 基準有 590 層、待測有 589 層
- **WHEN** 執行比對
- **THEN** 結束碼 SHALL 為 1
- **AND** 輸出 SHALL 列出兩邊的項目數

#### Scenario: 跨平台預設拒絕

- **GIVEN** 基準的平台標籤為 Windows、待測為 macOS
- **WHEN** 未加 `--allow-cross-platform` 執行比對
- **THEN** 工具 SHALL 以非零結束碼結束，並說明平台不同

### Requirement: 驗收執行矩陣

正確性驗收 SHALL 依下列順序執行，任一步失敗即 SHALL 中止並判定不通過：

1. **基準自我一致性。** 以改動前的引擎，對每個案例分別以 `--threads 1` 與預設執行緒數各執行一次。兩者的層檔與預覽指紋 SHALL 相等；不相等代表基準本身不具決定性，MUST NOT 作為比對依據。
2. **改動後的一致性。** 以改動後的引擎，對每個案例在 `--threads 1`、`--threads 2`、`--threads 8` 下各執行 3 次，共 9 次。每一次的層檔與預覽指紋 SHALL 等於第 1 步的基準。
3. **驗證模式。** 第 2 步的每次執行 SHALL 同時設定 `SLA_RASTER_VERIFY=1`，且全程 MUST NOT 回報任何違反。

改動前與改動後的引擎 SHALL 在同一台機器、以同一套編譯設定建置。MUST NOT 以打包發行版引擎作為改動前的基準，因為其建置來源無法逐位元組確認。

最終驗收的「改動後引擎」SHALL 只有一支：由最終提交的 fork commit 建置，建置完成當下即寫出 `build_info.json`，記錄 commit、原始碼樹雜湊、未提交建置調整的 diff SHA-256，以及 `slicer-engine.exe` 與 `slicer_core.dll` 的 SHA-256。最終驗收的每一次執行（正確性矩陣、效能門檻、擴展性曲線、端到端比對）其 `meta.json` 記錄的引擎身分 SHALL 等於該 `build_info.json`；不相等的執行 SHALL 作廢，MUST NOT 採計。

#### Scenario: 執行使用了非最終引擎

- **GIVEN** 最終引擎的 `build_info.json` 記錄的 `slicer_core.dll` SHA-256 為 X
- **WHEN** 某次驗收執行的 `meta.json` 記錄的 `slicer_core.dll` SHA-256 為 Y，且 Y 不等於 X
- **THEN** 該次執行 SHALL 作廢
- **AND** 驗收判定 MUST NOT 採計該次執行的指紋、時間或記憶體

#### Scenario: 基準在不同執行緒數下不一致

- **GIVEN** 改動前的引擎以 `--threads 1` 與預設執行緒數產出的主基準指紋不同
- **WHEN** 執行驗收矩陣
- **THEN** 驗收 SHALL 在第 1 步中止
- **AND** MUST NOT 進行第 2 步

#### Scenario: 改動後九次執行全部相符

- **GIVEN** 主基準的基準指紋已通過第 1 步
- **WHEN** 改動後的引擎以三種執行緒數各執行 3 次
- **THEN** 9 份層檔指紋與 9 份預覽指紋 SHALL 全部等於基準

#### Scenario: 只有某一次重複執行不符

- **GIVEN** 改動後的引擎在 `--threads 8` 的第 2 次執行中有 1 層指紋與基準不同，其餘 8 次皆相符
- **WHEN** 判定驗收結果
- **THEN** 驗收 SHALL 判定為不通過
- **AND** MUST NOT 以「多數相符」或「重跑後相符」取代該次結果

### Requirement: 效能量測與門檻

每次執行 SHALL 記錄：切片總牆鐘時間、光柵化階段牆鐘時間、`[raster-timing]` 各階段的執行緒累計秒數（有設定 `SLA_RASTER_TIMING=1` 時），以及引擎程序的**峰值承諾記憶體**（Windows 為 `PeakPagefileUsage`）與**峰值常駐記憶體**（RSS，Windows 為 `PeakWorkingSetSize`）。

**改動前的比較基準** SHALL 為最終驗收同一個工作階段內，以改動前引擎重新執行 3 次的中位數。MUST NOT 以先前建立 Golden 時的時間或記憶體數字作為門檻比較基準，因為兩者相隔數日，機器溫度與系統狀態不同。指紋比對不受此限，仍 SHALL 以凍結的 Golden 為準；改動前引擎重跑的每一次，其指紋也 SHALL 等於 Golden，不相等時整輪 SHALL 作廢。

**交替執行**：同一案例的改動前與改動後引擎 SHALL 交替執行（改動前第 1 次、改動後第 1 次、改動前第 2 次、改動後第 2 次、改動前第 3 次、改動後第 3 次），讓熱效應與排程負載平均分攤到兩邊。

效能比較 SHALL 只使用預設執行緒數下 3 次執行的中位數，並同時記錄最大值與最小值。任一組 3 次耗時的最大值與最小值相差**同時**超過中位數的 5% **且**絕對差值大於 0.5 秒時，即觸發重跑。只滿足其中一個條件時不需重跑：短案例（例如數秒內完成的案例）的秒級差異主要來自系統排程與記憶體配置的雜訊，0.5 秒的絕對下限避免它們無止盡地重跑。

**重跑規則**：

- 同一案例中改動前或改動後任一組觸發重跑時，該案例的**兩組 SHALL 一起**重新交替執行一整輪，MUST NOT 只重跑觸發的那一組，也 MUST NOT 只替換離群的單次。
- 每一輪以 `a1`、`a2`、`a3` 標記，`a1` 為第一輪；判定 SHALL 只採用該案例最新一輪，先前的輪次保留原始紀錄並標記為已被取代（superseded）。
- 同一案例最多 3 輪。`a3` 仍觸發重跑時，該案例 SHALL 標記為 UNSTABLE，MUST NOT 判定為通過或不通過；排除環境干擾後該案例 SHALL 從 `a1` 整個重來，MUST NOT 放寬重跑條件。
- 每一輪的執行 SHALL 使用帶輪次的 build 標籤（例如 `p3-base-a1`、`p3-final-a1`），MUST NOT 與既有執行的目錄撞名。

效能門檻如下，且 SHALL 只在 Windows 驗收機（i7-11370H、4 核 8 緒、16 GB）上認定。表中「基準」皆指同一工作階段內改動前引擎的中位數：

| 案例 | 門檻 |
| --- | --- |
| 主基準 | 光柵化階段耗時 SHALL 不高於基準的 50% |
| 主基準 | 峰值承諾記憶體 SHALL 不高於基準（主門檻） |
| 主基準 | 峰值 RSS SHALL 不高於基準的 103%（護欄） |
| 次基準 | 光柵化階段耗時 SHALL 不高於基準 |
| 滿版案例 | 光柵化階段耗時 SHALL 不高於基準的 103% |

記憶體以承諾記憶體為主門檻，是因為峰值 RSS 受作業系統工作集調整影響，同一支引擎 3 次之間可相差數十 MB，嚴格的「不高於基準」會由雜訊決定成敗；RSS 保留 3% 容許值作為護欄，與滿版案例的時間容許值一致。極小案例沒有效能門檻，只記錄。

#### Scenario: 主基準達標

- **GIVEN** 同一工作階段內，主基準改動前的光柵化中位數為 30.0 秒、峰值承諾記憶體中位數為 8000 MB、峰值 RSS 中位數為 1500 MB
- **WHEN** 改動後的中位數為 14.8 秒、峰值承諾記憶體為 2200 MB、峰值 RSS 為 1540 MB
- **THEN** 主基準的效能門檻 SHALL 判定為通過

#### Scenario: 承諾記憶體超過基準

- **GIVEN** 主基準改動前的峰值承諾記憶體中位數為 8000 MB
- **WHEN** 改動後的峰值承諾記憶體中位數為 8010 MB，其餘門檻皆達標
- **THEN** 主基準的效能門檻 SHALL 判定為不通過

#### Scenario: RSS 超過護欄

- **GIVEN** 主基準改動前的峰值 RSS 中位數為 1500 MB
- **WHEN** 改動後的峰值 RSS 中位數為 1560 MB（高於 1545 MB），其餘門檻皆達標
- **THEN** 主基準的效能門檻 SHALL 判定為不通過

#### Scenario: 不得以 Golden 建立時的數字判定

- **GIVEN** Golden 建立時主基準改動前的光柵化中位數為 22.58 秒，最終驗收同一工作階段內改動前引擎重跑的中位數為 21.00 秒
- **WHEN** 改動後的中位數為 10.80 秒
- **THEN** 門檻 SHALL 以 21.00 秒為基準計算，判定為不通過
- **AND** MUST NOT 改以 22.58 秒計算而判定為通過

#### Scenario: 主基準速度未達標

- **GIVEN** 主基準改動前的光柵化中位數為 30.0 秒
- **WHEN** 改動後的中位數為 15.5 秒
- **THEN** 主基準的效能門檻 SHALL 判定為不通過

#### Scenario: 滿版案例退步超過容許值

- **GIVEN** 滿版案例改動前的光柵化中位數為 40.0 秒
- **WHEN** 改動後的中位數為 41.5 秒
- **THEN** 滿版案例的效能門檻 SHALL 判定為不通過

#### Scenario: 量測離散過大需整組重跑

- **GIVEN** 某組 3 次光柵化耗時為 14.0、14.5、15.4 秒
- **WHEN** 計算該組結果
- **THEN** 因最大值與最小值相差 1.4 秒，超過中位數 14.5 秒的 5%，且大於 0.5 秒，該組 SHALL 觸發重跑

#### Scenario: 只有一邊離散過大仍須成對重跑

- **GIVEN** 主基準第 `a1` 輪改動前 3 次為 22.0、22.4、23.6 秒（觸發重跑），改動後 3 次為 4.3、4.4、4.5 秒（未觸發）
- **WHEN** 計算該案例結果
- **THEN** 改動前與改動後兩組 SHALL 一起以 `a2` 重新交替執行一整輪
- **AND** `a1` 的兩組 SHALL 標記為已被取代，MUST NOT 用於判定

#### Scenario: 第 3 輪仍不收斂

- **GIVEN** 某案例 `a1`、`a2`、`a3` 三輪都有一組觸發重跑
- **WHEN** 計算該案例結果
- **THEN** 該案例 SHALL 標記為 UNSTABLE
- **AND** MUST NOT 判定為通過或不通過
- **AND** MUST NOT 自動執行第 4 輪

#### Scenario: 短案例相對離散超過 5% 但絕對差值很小

- **GIVEN** 某組 3 次光柵化耗時為 2.08、2.18、2.20 秒
- **WHEN** 計算該組結果
- **THEN** 最大值與最小值相差 0.12 秒，雖然超過中位數 2.18 秒的 5%，但未大於 0.5 秒，該組 SHALL NOT 需要重跑
- **AND** 該組的中位數 SHALL 照常作為比較依據

#### Scenario: 非驗收機的時間不採計

- **WHEN** 在 macOS 或其他機器上完成量測
- **THEN** 其時間數據 SHALL 僅供參考
- **AND** MUST NOT 被採計為效能門檻通過的依據

### Requirement: 多執行緒擴展性曲線只記錄不判定

最終驗收 SHALL 以主基準產出一份多執行緒擴展性曲線：改動前引擎與最終引擎各以 `--threads 1`、`2`、`4`、`8` 執行，每種執行緒數 3 次，不設定 `SLA_RASTER_VERIFY` 與 `SLA_RASTER_TIMING`。每個點 SHALL 記錄光柵化階段耗時、峰值承諾記憶體與峰值 RSS 的中位數、最大值與最小值。

曲線 MUST NOT 設效能門檻，也 MUST NOT 套用重跑規則；但曲線中每一次執行的層檔與預覽指紋 SHALL 等於 Golden，任一次不符即判定驗收不通過。

8 緒的點 SHALL 直接採用效能門檻驗收中主基準最新一輪的預設執行緒數執行，不另外重跑；前提是這些執行的 `meta.json` 記錄的實際執行緒數為 8，否則 SHALL 另外以 `--threads 8` 執行。

#### Scenario: 曲線數字不影響通過與否

- **GIVEN** 最終引擎在 `--threads 1` 的光柵化中位數高於改動前引擎的 50%
- **WHEN** 判定驗收結果
- **THEN** 驗收 MUST NOT 因此判定為不通過
- **AND** 該數字 SHALL 如實記錄於曲線中

#### Scenario: 曲線中的指紋不符

- **GIVEN** 最終引擎在 `--threads 2` 的第 3 次執行有 1 張預覽圖指紋與 Golden 不同
- **WHEN** 判定驗收結果
- **THEN** 驗收 SHALL 判定為不通過

### Requirement: 門檻判定由工具產出結構化結果

效能門檻、重跑規則、引擎身分、擴展性曲線與端到端比對的判定 SHALL 由 `scripts/raster_bench/acceptance_report.py` 計算，MUST NOT 由人工讀表判定。負責排程與呼叫引擎的腳本 MUST NOT 計算任何門檻。

`acceptance_report.py` SHALL 只讀取 `scripts/raster_bench/work/` 內既有的執行紀錄，MUST NOT 呼叫引擎。它 SHALL 產出：

- `summary.json`：驗收的單一事實來源，至少包含每次執行的目錄名稱、引擎身分、實際執行緒數、指紋是否等於 Golden、是否已被取代；每組的中位數、最大值、最小值與是否觸發重跑；每個門檻的輸入數字、規則、結果（PASS、FAIL 或 UNSTABLE）；擴展性曲線；端到端比對結果。
- `report.md`：完全由 `summary.json` 轉出，MUST NOT 另外計算任何數字。

任一門檻為 FAIL 或 UNSTABLE、任一指紋不符、任一執行的引擎身分不符，或端到端比對不通過時，工具 SHALL 以非零結束碼結束。判定邏輯 SHALL 有 pytest 單元測試，至少涵蓋本規格各 Scenario 的數字。

#### Scenario: 全部達標

- **GIVEN** 所有案例的最新一輪皆未觸發重跑、所有門檻皆達標、所有指紋相符、引擎身分全部一致、端到端比對通過
- **WHEN** 執行 `acceptance_report.py`
- **THEN** 結束碼 SHALL 為 0
- **AND** `summary.json` 的每個門檻結果 SHALL 為 PASS

#### Scenario: 報表與結構化結果不一致

- **GIVEN** 一份 `summary.json`
- **WHEN** 由它產出 `report.md`
- **THEN** `report.md` 中的每個數字 SHALL 能在 `summary.json` 找到相同的值

### Requirement: 端到端 PRZ 以遮罩位元組比對

以改動前引擎與最終引擎分別經 agent 走完主基準的完整切片流程後，兩份下載的 PRZ SHALL 依下列規則比對。PRZ 檔頭的 File Time 欄位由 agent 寫入產生當下的時間，兩次切片必然不同，因此該欄位予以遮罩；除此之外 MUST NOT 有任何遮罩。

1. 兩份 PRZ 的總長度 SHALL 相同。
2. 遮罩範圍 SHALL 僅為以 0 起算的位元組區間 `[68, 92)`，共 24 位元組。
3. 兩份各自的遮罩區 SHALL 通過格式檢查：前 19 位元組依 `%Y-%m-%d %H:%M:%S` 解析成功，其後 5 位元組皆為 NUL。
4. 遮罩區以外的每一個位元組 SHALL 相同。

任一條不成立即 SHALL 判定不通過。遮罩區以外出現差異時 MUST NOT 以擴大或新增遮罩範圍的方式使其通過。

#### Scenario: 只有產生時間不同

- **GIVEN** 兩份 PRZ 長度相同，只有 `[68, 92)` 內的時間字串不同，且兩者格式皆合法
- **WHEN** 執行比對
- **THEN** 比對 SHALL 判定為通過

#### Scenario: 遮罩區外有一個位元組不同

- **GIVEN** 兩份 PRZ 長度相同，除時間欄位外，偏移 195,500 的位元組不同
- **WHEN** 執行比對
- **THEN** 比對 SHALL 判定為不通過，並指出第一個不同的偏移為 195,500

#### Scenario: 時間欄位格式不合法

- **GIVEN** 其中一份 PRZ 的 `[68, 92)` 前 19 位元組為 `2026-13-45 10:00:00`
- **WHEN** 執行比對
- **THEN** 比對 SHALL 判定為不通過

#### Scenario: 長度不同

- **GIVEN** 兩份 PRZ 長度相差 1 位元組
- **WHEN** 執行比對
- **THEN** 比對 SHALL 判定為不通過

### Requirement: 本變更的驗收平台範圍

本變更的正確性與效能驗收 SHALL 只在 Windows x64 驗收機上執行與認定。macOS arm64 的建置相容性、單元測試、位元組序判斷、macOS 專屬 Golden 與指紋驗證 SHALL 由後續獨立的 macOS 變更負責。

在該 macOS 變更驗收通過之前，含本變更 fork 指標的版本 MUST NOT 部署至 macOS 正式環境。

#### Scenario: 尚未完成 macOS 驗收時部署

- **GIVEN** 本變更已在 Windows 驗收通過並更新父 repo 的 submodule 指標，但 macOS 變更尚未驗收通過
- **WHEN** 準備部署至 macOS 正式環境
- **THEN** 該部署 MUST NOT 包含本變更的 fork 指標

