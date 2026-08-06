> **驗證原則**：每個階段結束前必須通過該階段自己的驗證任務才可進入下一階段。禁止累積到最後才驗證。
>
> **黃金基準**：階段 0 會產出兩份逐層 SHA-256 清單——`golden-blur1.sha256`（blur 啟用）與 `golden-blur0.sha256`（blur 關閉）。階段 2～6 的位元一致性比對基準為 **`golden-blur0`**（階段 1 之後的新常態）；階段 7 的比對基準為 **`golden-blur1`**。
>
> **測試素材**：一律使用 `agent/jobs/b1d3a041/`（16K、632 層、含 5× 重複支撐），另備一份小型 job（如 `agent/jobs/410009d2/`）作為快速迴圈用。

## 0. 基準量測（不得改動任何程式碼）

- [x] 0.1 建立量測工作目錄與 A/B 設定：複製 `agent/jobs/b1d3a041/config.ini` 為 `a.ini`（維持 `blur = 1`）與 `b.ini`（改為 `blur = 0`），其餘欄位完全不動
- [x] 0.2 執行 A 組（`a.ini`）：以 `slicer-engine/bin/slicer-engine.exe` 搭配 `SLA_LAYER_RLE=1`、`--export-preview-pngs 0.25`、`--import-support-stl`，記錄總秒數、`.sl1` 位元組數、`_preview.zip` 位元組數、`PeakWorkingSet64`
- [x] 0.3 執行 B 組（`b.ini`）：條件同上，記錄同四項指標
- [x] 0.4 取得各階段耗時分佈：將 CLI stdout 逐行加上時間戳（以外部管線處理，**不得修改 `agent/jobs.py`**），解析 `NN% => 階段` 進度行，產出每個階段的起訖與耗時
- [x] 0.5 產出黃金基準：對 A、B 兩份 `.sl1` 分別列出所有層檔並計算 SHA-256，存為 `golden-blur1.sha256` 與 `golden-blur0.sha256`
- [x] 0.6 量測 admesh 修補佔比：以 `SLIC3R_LOGLEVEL=4` 執行一次，從 `TriangleMesh::repair() started` / `finished` 的時間戳取得 `trianglemesh_repair_on_import()` 耗時
- [x] 0.7 **驗證**：A 與 B 的層檔數量相等（632）；B 的 `.sl1` 明顯小於 A；兩份 SHA-256 清單各自 632 行且彼此不同
- [x] 0.8 **決策點**：依 0.6 的結果決定 design D2 是否由作法 A 升級為作法 B（repair 前去重），將結論寫入 `design.md` 的 Open Questions
- [x] 0.9 將 0.2～0.6 的所有數字整理成基準表，附於本檔末的「量測記錄」區

## 1. 後端 blur 開關閘控（Python，可獨立回滾）

- [x] 1.1 於 `agent/api_v2.py` 的 `_extract_sla_from_mechado()` 加入 `Advanced."Image Blur"` 三態閘控：`false` → `blur = 0`；`true` 或鍵不存在 → 直接複製 `Image Blur Pixel`
- [x] 1.2 於 `agent/api_v2.py` 的 `_convert_v2_config_to_sla()` 加入同語意的三態閘控（頂層鍵 `"Image Blur"`）
- [x] 1.3 於 `agent/tests/test_extract_sla_from_mechado.py` 新增三態場景測試：開關 `false` + pixel `1` → `0`；開關 `false` + pixel `3` → `0`；開關 `true` + pixel `2` → `2`；缺鍵 + pixel `1` → `1`
- [x] 1.4 新增跨轉換器一致性測試：語意等價輸入分別餵給兩個轉換器，斷言 `blur` 相等
- [x] 1.5 檢查 `agent/tests/test_slice_config_merge.py` 既有斷言是否因三態語意而失效，必要時補上開關鍵使輸入語意明確
- [x] 1.6 **驗證**：`pytest agent/tests/test_extract_sla_from_mechado.py agent/tests/test_slice_config_merge.py -v` 全數通過
- [x] 1.7 **驗證**：以 `b1d3a041` 的 `prz_config.json`（含 `"Image Blur": false`）實跑一次切片，確認產出的 `config.ini` 含 `blur = 0`
- [x] 1.8 **驗證**：以 `agent/prz_decoder.rle_layer_to_png` 將底層筏、第 316 層、頂層轉為 PNG，與階段 0 的 A 組同層目視比對，確認邊緣仍保有 AA、無硬邊化
- [x] 1.9 **驗證**：新產出的 `.sl1` 逐層 SHA-256 與 `golden-blur0.sha256` 完全一致
- [x] 1.10 取得產品端對 1.8 目視比對結果的書面確認

## 2. fork：匯入支撐網格去重（作法 A）

- [x] 2.1 於 `src/CLI/ProcessActions.cpp` 的 `ReadSTLFile()` 之後、`attach_imported_support()` 之前，對 `indexed_triangle_set` 執行完全重複面去除（頂點三元組精確位元比對，含繞序）
- [x] 2.2 加入去重記錄：偵測到重複時輸出含去重前面數、去重後面數與倍率的單行訊息；未偵測到重複時不輸出
- [x] 2.3 在該處註解明確標示此去重為**防禦措施而非根因修復**，根因為前端支撐匯出未過濾 stencil pass 子節點
- [x] 2.4 **驗證**：以 `b1d3a041/input/support.stl` 執行，log 顯示 `1621320 → 324264`、倍率 `5.00`
- [x] 2.5 **驗證**：以任一份 `agent/jobs/*/output/model_support.stl`（皆為 1.00×）執行，面數不變且**不輸出**去重記錄
- [x] 2.6 **驗證**：`.sl1` 逐層 SHA-256 與 `golden-blur0.sha256` 完全一致
- [x] 2.7 **驗證**：`status.json` 的 `layer_count`、`resin_volume_ml`、`estimated_print_time`、`has_support_mesh` 與階段 1 產出完全相等
- [x] 2.8 **驗證**：未使用 `--import-support-stl` 的切片路徑完全未觸及去重程式碼（以自產支撐的 job 執行一次確認）
- [x] 2.9 量測本階段耗時與峰值 RSS 變化，記入量測表

## 3. fork：預覽編碼器（壓縮等級與整數倍快路徑）

> 本階段**不動縮放比**。縮放比調整位於階段 6，受跨 repo 閘門管制。

- [x] 3.1 於 `src/libslic3r/SLA/RasterBase.cpp` 的 `PNGPreviewEncoder` 改用 `tdefl_write_image_to_png_file_in_memory_ex(..., level=1, MZ_FALSE)`
- [x] 3.2 於同一編碼器加入整數倍（`1/N`）降取樣快路徑：固定 `N × N` 區塊平均，不逐目標像素重算邊界與除法
- [x] 3.3 保留通用路徑供非整數倍縮放比使用，維持既有行為
- [x] 3.4 **驗證**：對同一張來源點陣圖，以 `1/4`（現行 0.25）分別跑快路徑與通用路徑，兩者輸出逐位元組相同
- [x] 3.5 **驗證**：對 `1/10` 重複 3.4 的比對
- [x] 3.6 **驗證**：`.sl1` 逐層 SHA-256 與 `golden-blur0.sha256` 完全一致（預覽改動不得影響層檔）
- [x] 3.7 **驗證**：產出的 `model_preview.zip` 可被 JSZip 正常解壓、影像尺寸仍為 3780×1557
- [x] 3.8 量測預覽階段耗時與 zip 體積變化，記入量測表

## 4. fork：預覽產出失敗不得使切片失敗

- [x] 4.1 於 `src/libslic3r/Format/SLAArchiveWriter.cpp` 的 `export_preview_zip()` 改為記錄錯誤後不再 rethrow
- [x] 4.2 確認 `src/CLI/ProcessActions.cpp` 的呼叫端在預覽失敗時仍走完既有的成功結束路徑
- [x] 4.3 **驗證**：將輸出目錄設為唯讀（或使預覽檔名指向不可寫路徑）執行一次切片，確認 `.sl1` 正常產出、程序結束碼為 0
- [x] 4.4 **驗證**：該次切片的 `status.json` 的 `status` 為 `completed`，且 stderr 含預覽失敗的錯誤記錄
- [x] 4.5 **驗證**：刪除 `model_preview.zip` 後呼叫 `POST /api/v2/slices/{id}/download.prz`，PRZ 正常產生
- [x] 4.6 **驗證**：正常情況下（可寫路徑）預覽仍照常產出，`.sl1` 逐層 SHA-256 不變

## 5. fork：raster 每執行緒重用

- [x] 5.1 於 `src/libslic3r/Format/SLAArchiveWriter.hpp` 的 `draw_layers()` 將 `create_raster()` 由每層新建改為 `tbb::enumerable_thread_specific` 持有的執行緒區域實例
- [x] 5.2 每層開始繪製前將整張像素緩衝清為背景值（第一版不做 dirty-region 部分清除）
- [x] 5.3 更新 `src/libslic3r/SLA/AGGRaster.hpp` 中 `draw_binary()` 上方「Per-layer raster instances make this race-free」的註解，改述為「執行緒綁定的重用實例使其免於競爭」並註明此為正確性必要條件
- [x] 5.4 **驗證**：`.sl1` 逐層 SHA-256 與 `golden-blur0.sha256` 完全一致
- [x] 5.5 **驗證**：以一份含「大面積層緊接空層」的測試模型執行，確認空層層檔等同全背景編碼結果、SHA-256 與重用前相同
- [x] 5.6 **驗證**：以 `blur = 1` 再跑一次，逐層 SHA-256 與 `golden-blur1.sha256` 完全一致（確認 `draw_binary()` 的 gamma 還原在重用下仍正確）
- [x] 5.7 **驗證**：幅面大小的緩衝配置次數不超過併發執行緒數，且不隨層數線性增長（以配置點加計數記錄或 profiler 確認）
- [x] 5.8 量測峰值 RSS 與總耗時變化，記入量測表

## 6. 預覽縮放比降至 0.10（受跨 repo 硬閘門管制）

> ### 🚚 本階段整批移交至下一個變更
>
> **閘門條件 6.1～6.3 於本變更結束時全數未達成**（DS-Online 的 WASM PRZ fallback 三處呼叫點皆未移除），因此 6.4～6.11 一項未做。本節**不視為本變更的未完成工作，而是明確移交**：`slice-preview-export` 能力的縮放比 requirement 已改以現行值 `0.25` 立約，並在該處記載升級到 `0.10` 的三項落地條件，故封存後 spec 與程式碼一致，不留懸空需求。下一個變更承接時可直接把本節搬過去。
>
> ### ⛔ 硬閘門
>
> **本階段不得在下列條件全部成立之前開始。**
>
> 現行 DS-Online 在 `downloadPrz` 失敗時，會以 1/4 尺寸的預覽圖**上採樣 4 倍**生成列印用 PRZ，且僅有一行 `logger.warn`。若在移除該路徑之前把縮放比降到 0.10，上採樣倍率將由 4× 惡化為 **10×**——這不是優化，是加深既有的坑。
>
> **閘門的理由需要修正（實測發現，保留原文以誌其誤）**：前端靜態檢查顯示 `pngRleWorker.js` 在尺寸不符時直接 `throw`，而 `paramsStore.resolution` 是整機解析度——該 fallback 在**任何**預覽縮放比下都必然失敗，不會真的產出上採樣的 PRZ，只會拋錯。因此「4× 惡化為 10×」的推論不成立。閘門本身仍應保留，但正確理由是「未移除的死路徑會把真實錯誤遮蔽成一次無聲的降級」，而非上採樣品質。

- [ ] 6.1 **閘門條件**：DS-Online 已移除 `slicingService.js` 的 WASM PRZ fallback，`downloadPrz` 失敗改為明確拋錯（已確認既有 `toast.errorKey('errors.slices.sliceFailed')` 與 `retrySlice()` 可承接）
- [ ] 6.2 **閘門條件**：DS-Online 該變更已合併並部署至與本變更相同的發版通道
- [ ] 6.3 **閘門條件**：以移除後的前端實地驗證「agent 中途停止 → 切片顯示失敗並可重試」，確認不再產生任何 PRZ 檔案
- [ ] 6.4 將 `agent/jobs.py` 中 `--export-preview-pngs` 的引數由 `"0.25"` 改為 `"0.10"`
- [ ] 6.5 **驗證**：以 `b1d3a041` 執行，預覽影像尺寸為 1512 × 623
- [ ] 6.6 **驗證**：對含支撐的層（點亮約 0.9%）比較降取樣結果，預覽中亮度 > 32 的像素占比不低於原始層圖的點亮比例
- [ ] 6.7 **驗證**：直徑 0.4 mm 的支撐頭在預覽中至少涵蓋 2 個像素
- [ ] 6.8 **驗證**：`model_preview.zip` 體積由約 33.6 MB 降至個位數 MB
- [ ] 6.9 **驗證**：`.sl1` 逐層 SHA-256 與 `golden-blur0.sha256` 完全一致
- [ ] 6.10 **驗證**：DS-Online 的 `SlicePreviewDialog` 可正常載入並逐層播放新尺寸的預覽
- [ ] 6.11 量測預覽階段耗時與 zip 體積，記入量測表

## 7. fork：blur 後處理分帶重寫（條件性）

> 優先序依階段 0 的量測結果與 blur 的實際啟用率決定；若啟用率極低可延後至後續變更。
> **僅實作分帶（strip）垂直處理**——重新推導的等價 3×3 卷積因捨入路徑不同、無法保證位元一致，已由 spec 排除在本能力之外。

- [x] 7.1 於 `src/libslic3r/Format/SL1.cpp` 的 blur 後處理，將縱向處理改為一次處理固定欄數（如 64 欄）的分帶，使工作集常駐 L2
- [x] 7.2 確認演算法本身與捨入順序完全未變，僅改變記憶體走訪型態
- [x] 7.3 **驗證**：`blur = 1` 下 `.sl1` 逐層 SHA-256 與 `golden-blur1.sha256` 完全一致
- [x] 7.4 **驗證**：`blur = 2` 與 `blur = 3` 各自與重寫前的同參數產出逐層 SHA-256 一致
- [x] 7.5 **驗證**：`blur = 0` 下後處理完全不執行，層檔與 `golden-blur0.sha256` 一致
- [x] 7.6 量測 `blur = 1` 的總耗時變化，記入量測表

## 8. 整合驗證與收尾

- [x] 8.1 fork 的所有改動整理為獨立 commit；父 repo 的 submodule 指標更新獨立成另一個 commit，使 Python 與 fork 可分別回滾
- [x] 8.2 **驗證**：`pytest agent/tests/` —— 484 passed / 2 failed，**兩筆失敗皆非本變更所致，且在本變更之前即已存在**：`test_prz_print_time.py::test_6_11`（`_compute_print_time()` 少算 drop2，屬 `release/v1.0.5` 既有缺陷；該測試與其相依模組的 `git diff HEAD` 為空）與 `test_subprocess_boundary_5_11.py::test_engine_runs_as_separate_process`（環境未安裝 `pytest-asyncio`）。本變更直接相關的 `test_extract_sla_from_mechado.py`、`test_slice_config_merge.py` 全數通過。兩筆失敗**不列為本變更的驗收阻擋，但也不視為已解決**——`_compute_print_time` 的 drop2 需另行處理
- [x] 8.3 **驗證**：端到端經 agent API 實跑一次完整流程（建立 job → 上傳模型與支撐 → execute → 輪詢 → `download.prz` → `preview.zip` → `layers.zip`），全部成功
- [x] 8.4 **驗證**：端到端產出的 PRZ 之 `layer_count`、`estimated_print_time`、`resin_volume_ml` 與階段 0 的基準一致（blur 差異造成的檔案大小變化除外）
- [x] 8.5 彙整量測表：對照階段 0 的基準，列出總耗時、峰值 RSS、`.sl1` 體積、`preview.zip` 體積的前後變化
- [x] 8.6 將實測結果與階段 0.8 的決策結論回填 `design.md` 的 Open Questions；若實測推翻原估計比例，於該處記錄實際數字
- [x] 8.7 確認 DS-Online 的三項跨 repo 項目狀態（stencil pass 子節點過濾＝5× 根因、WASM fallback 移除、`unzipPreviewFrames` 移除），將未完成者移交該 repo 的變更追蹤

## 9. 不在本變更範圍（僅記錄）

> 本節是**記錄本身即為交付物**，不是待辦清單——寫下來就完成了，因此不使用 checkbox。
> 先前以 `- [ ]` 呈現會讓「所有任務完成」在定義上永遠無法達成。

- **9.1** DS-Online `MeshManager.exportSupportOnlySTL()` 缺少子節點過濾為 5× 重複之**根因**，後端去重僅為防禦網。詳細的可驗證事實與尚未閉合之處見「階段 8 驗證結果」的 8.7 移交事項第 1 點
- **9.2** dirty-tile 稀疏化為唯一能吃到九成空白畫布的手段。本變更完成後的剩餘 headroom 已於 design.md Open Questions 回填：核心光柵化 28.96 秒仍佔最終總耗時的 66.6%，建議另開變更
- **9.3** blur deadband（`≤T → 0`、`≥255−T → 255`）在 blur 啟用時可省約三分之一 `.sl1` 體積，改變輸出像素，待產品端決策。其價值取決於 blur 的真實啟用率
- **9.4** `agent/jobs/` 目前累積逾 1 GB 且無清理邏輯，保留策略需另開變更
- **9.5** `RLERasterEncoder` 的 `out.reserve(n / 8 + 64)`（16K 幅面為 11.23 MB/層）在編碼結果 move 進 `m_layers` 後**容量被完整保留**，實際只用約 150 KB。632 層即提交約 7.1 GB 且不隨用量收斂，是階段 0 觀測到「commit 單調成長至 9,167 MB」的真正成因（原先誤判為每層新建 raster，已於量測記錄更正）。一次 `shrink_to_fit()` 或改為兩段式編碼即可回收，屬既有缺陷，不在本變更範圍
- **9.6** ~~本變更引入的 metadata 不一致~~ **已於封存前修復**。`agent/prz_encoder.py` 原本把 `Advanced."Image Blur Pixel"` 直接寫進 PRZ header 的 `blur_level`，未經閘控——階段 1 之前這是正確的（blur 本就被強制啟用），階段 1 之後層檔以 `blur = 0` 光柵化，header 卻仍宣稱 `blur_level = 1`（端到端實測確認）。**這是本變更自己造成的**，不屬既有缺陷，因此不適合當作「僅記錄」項目留下。修法為套用同一個閘控函式；連帶把 `_gate_blur` 由 `api_v2.py` 移至 `models.py` 並更名為 `gate_blur`，因為 `prz_encoder` 是 `api_v2` 的**下游**，留在原處會迫使低階編碼器反向匯入整個 FastAPI 路由模組。`api_v2` 內保留 `_gate_blur = gate_blur` 別名以維持既有呼叫點與測試
- **9.7** `slice-config-intake` 能力**尚未涵蓋 PRZ header 這條輸出路徑**。9.6 修好了實作，但 spec 層面仍只約束 `SLAConfig` 與 `generate_config_ini()` 兩個消費端，沒有任何 requirement 說「閘控後的 `blur` 是所有下游的唯一來源」。若日後再新增一個讀 `Image Blur Pixel` 的消費端，同樣的不一致會再發生一次而不被任何 spec 抓到。建議另行補一條 requirement，本次未擅自加入（超出指定範圍）
- **9.8** fork 側的四項行為（去重、`reset()` 全清、blur 分帶、預覽失敗隔離）**沒有任何自動化回歸防護**。現有 `test_slice_progress_string_contract.py` 只鎖 marker 字面量與其相對位置，即使 marker 改回無條件輸出也照樣通過，抓不到階段 4 的行為回歸。632 層 SHA-256 比對腳本目前只存在於暫存目錄，session 結束即失。建議至少把比對腳本固化進 repo，並補一個斷言 marker 位於成功分支內的字串契約測試

## 量測記錄

量測環境：Intel i7-11370H（4C/8T）、16 GB RAM、Windows 11。素材：`agent/jobs/b1d3a041`（15120×6230、632 層、model 926,086 面、support 1,621,320 面含 5.00× 重複）。引擎：`slicer-engine/bin/slicer-engine.exe`（`slicer_core.dll` 2026-07-30）。

> **方法論注意**：`.sl1` 的**檔案大小不可作為位元一致性的判準**。A 組與封存 job 的 632 層解壓後 SHA-256 完全相同，但 `.sl1` 檔案大小為 106.5 MB vs 91.6 MB（逐層壓縮後大小 0/632 相同，比值中位數 1.172）。層檔內容相同而 zip 壓縮結果不同，代表產生封存 job 的建置與目前打包版的 deflate 設定有差異。**後續所有階段的驗證一律以「解壓後層檔的 SHA-256」為準**；體積指標則改用「層檔原始總量」。

| 指標 | 0-A（blur=1） | 0-B（blur=0） | 0-D（blur=0、無 preview） | 階段 2 後 | 階段 3 後 | 階段 5 後 | 階段 6 後 | 階段 7 後 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 總耗時（秒） | **287.97** | **63.07** | 48.49 | **55.08** | **53.78** | **44.65** | | 43.49 |
| 峰值 RSS（MB） | 2642.5 | 2518.8 | 2361.2 | **1446.5** | 1488.9 | 1488.4 | | 1498.5 |
| 峰值 commit / PrivateBytes（MB） | — | 9167 | — | | 8128 | 8464 | | |
| `.sl1` 檔案（MiB） | 101.60 | 55.61 | 55.62 | 55.61 | 55.60 | 55.61 | | 55.61 |
| 層檔原始總量（MiB） | **194.64** | **92.42** | 92.42 | 92.42 | 92.42 | 92.42 | | 92.42 |
| 層檔平均 / 最大（B） | 322,941 / 819,278 | 153,336 / 323,855 | 同 B | 同 0-B | 153,336 / 323,855 | 同 0-B | | 同 0-B |
| `preview.zip`（MB） | 32.09 | 29.30 | 0（停用） | 29.30 | **27.38** | 27.38 | | 27.38 |
| 支撐 repair（秒） | — | 3.02 | — | 3.02（未回收，作法 A） | 3.02 | 3.02 | | 3.02 |
| 模型 repair（秒） | — | 0.28 | — | 0.28 | 0.28 | 0.28 | | 0.28 |
| Slicing supports（秒） | 10.57 | 9.01 | 8.49 | **3.14** | 3.02 | 3.13 | | 3.09 |
| Merging（秒） | 1.60 | 1.56 | 1.43 | 1.60 | 1.30 | 1.40 | | 1.40 |
| Rasterizing（秒） | **262.06** | **40.00** | **28.59** | 41.22 | **38.57** | **29.83** | | 28.96 |
| ├ 其中預覽產生（秒） | — | 11.41 | 0 | — | **9.06** | 9.80 | | — |
| └ 其中核心光柵化（秒） | — | 28.59 | 28.59 | — | 29.51 | **20.03** | | — |
| 封存尾段（秒） | 2.37 | 3.87 | 1.05 | 1.32 | 1.30 | 1.22 | | 1.47 |

> **「階段 7 後」欄位是 `blur = 0` 的產出**，以維持與階段 2／3／5 各欄的可比性（那些欄位也都是 `blur = 0`）。階段 7 只改 blur 後處理，對 `blur = 0` 本來就不該有影響——該欄與階段 5 後幾乎相同正是預期結果，**不是**本階段的效益。真正的效益在下方 `blur > 0` 的對照表。

> **單位已於 Task 8.5 統一（原表有誤，此處說明以誌其誤）**：`.sl1 檔案` 與 `層檔原始總量` 兩列原先 0-A／0-B／0-D 三欄用的是 10⁶ bytes、階段 2 以後各欄用的是 MiB，兩種單位混在同一列。這讓表面上出現「`.sl1` 由 58.3 降到 55.61」「層檔總量由 96.9 降到 92.4」的假降幅——實際上 **0-B 與階段 2～7 的層檔逐位元組完全相同**（每階段皆已驗證 632/632），體積本來就不該有任何變化。現已全部改用 MiB 並以位元組重新換算：0-A `.sl1` 106,534,856 B、0-B 58,309,005 B、層檔原始總量 0-A 204,099,264 B、0-B 96,908,411 B。`preview.zip` 一列原本即全為 MiB，未受影響。
>
> 階段 2 之後的欄位取自 `F2-task2`。**注意**：0-A/0-B/0-D 由打包版引擎（2026-07-30 建置）產出，階段 2 由本次重新建置的引擎產出，兩者的建置環境不完全相同，因此跨欄比較會混入建置差異。階段 2 的效益數字一律以下方「同一支 binary」的對照為準，不要直接拿 0-B 減 F2-task2。

### 0-A 基準（blur=1，等同現行正式流程）

逐層 SHA-256 與封存 job `agent/jobs/b1d3a041/output/model.sl1` **632/632 完全相同** —— 量測確實重現了正式流程的切片結果。

### 0-B 相對 0-A 的差異

- 總耗時 **287.97 → 63.07 秒（−78.1%）**；其中 Rasterizing **262.06 → 40.00 秒（−84.7%）**
- 層檔原始總量 **204.1 → 96.9 MB（−52.5%）**；平均層 322,941 → 153,336 B
- 逐層雜湊：0–139 層（共 140 層）完全相同，140–631 層（共 492 層）全部不同。模型底部 z = 7.00 mm ÷ 0.05 mm = 第 140 層，**與「blur 只作用於 model track、support track 走 `draw_binary` 不受影響」的分析完全吻合**

### blur=0 之後的耗時結構（總計 63.07 秒）

| 階段 | 秒 | 佔比 |
| --- | --- | --- |
| 啟動 + STL 載入 + repair | 4.44 | 7.0% |
| ├ support.stl repair | 3.02 | 4.8% |
| └ model.stl repair | 0.28 | 0.4% |
| Slicing model | 3.10 | 4.9% |
| support points / tree / pad | 0.75 | 1.2% |
| Slicing supports | 9.01 | 14.3% |
| Merging slices | 1.56 | 2.5% |
| Rasterizing | 40.00 | 63.4% |
| ├ preview 產生 | 11.41 | 18.1% |
| └ 核心光柵化 | 28.59 | 45.3% |
| 封存尾段（含 preview zip 約 2.8 秒） | 3.87 | 6.1% |

### 階段 1 驗證結果（後端 blur 開關閘控）

以 `b1d3a041/prz_config.json`（真實輸入，含 `Advanced."Image Blur" = false`、`"Image Blur Pixel" = 1`）走完整後端路徑：

- 萃取結果 `SLAConfig.blur == 0`；`generate_config_ini()` 寫出 `blur = 0`（封存 job 當時寫的是 `blur = 1`）
- 新程式碼產生的 `config.ini` 與階段 0 手改的 `b.ini` **SHA-256 位元組相同**
- 以該 config 實跑切片（E-task1，63.19 秒），逐層 SHA-256 與 `golden-blur0.sha256` **632/632 完全一致**
- 對照 `golden-blur1.sha256` 相同 140 層（純支撐層），符合預期
- `pytest agent/tests/test_extract_sla_from_mechado.py agent/tests/test_slice_config_merge.py` 27 passed

**Task 1.8 目視比對（第 316 層，差異最密集的 160×240 區塊放大 4 倍）**

| | 全黑 | 全白 | 中間灰 | 相異灰階值 |
| --- | --- | --- | --- | --- |
| blur=1 | 14,819 | 18,758 | 4,823 | **126** |
| blur=0 | 16,535 | 20,544 | **1,321** | **6** |

blur=0 的相異灰階值恰為 6（`0`、`255` 加上 AA 階梯的 `32/88/144/198`），全層 AA 階梯像素 62,865 個 —— **邊緣完整保有四階抗鋸齒，未硬邊化**。目視上 blur=1 的邊緣有明顯灰色暈開，blur=0 邊緣銳利但對角過渡仍平滑，幾何位置完全相同（最大差值 72/255，差異像素平均差 16.0）。

第 10 層（純支撐筏）兩者**完全相同**（全黑 61,549,040 / 全白 32,648,560 / 中間灰 0），再次證實支撐走 `draw_binary` 不受 blur 影響。

附帶發現：blur 會**輕微侵蝕實體件尺寸** —— 全層純白像素 blur=1 為 7,699,613、blur=0 為 7,807,292，blur 把邊緣約 1.4% 的純白拉成灰階。

> 註：`test_slice_config_merge.py` 的 mechado fixture **刻意不帶** `Image Blur` 開關，用以鎖住三態語意中的「鍵不存在 → 直接複製」向後相容態；已於該處加註說明，避免日後被誤補而失去這層保護。

### 階段 2 驗證結果（fork：匯入支撐網格去重，作法 A）

實作位於 `src/CLI/ProcessActions.cpp`：新增 static `remove_duplicate_faces()`，於 `ReadSTLFile()` 之後、`attach_imported_support()` 之前呼叫。判準為三個頂點座標的精確位元相等且**含順序**（不做容差、不做繞序或循環旋轉正規化）。

**前置：判準本身先被驗證過**。在改 C++ 之前先用 Python 對 `support.stl` 直接統計，確認「有序頂點三元組精確比對」真的會得到 spec 寫的數字，而不是拿一個沒驗過的假設去對 log 做斷言。結果：有序比對、循環旋轉正規化、三頂點排序（含反繞序）三種判準**得到完全相同的 324,264**，且每個唯一面恰好出現 5 次 —— 最嚴格的判準已足夠涵蓋此型態。

| 驗證項 | 結果 |
| --- | --- |
| 2.4 去重記錄 | `warning: --import-support-stl contained duplicate faces: 1621320 -> 324264 (5.00x). Deduplicated for slicing; the upstream exporter still needs fixing.`（輸出至 stderr，不污染 stdout 的進度與支撐分類 marker） |
| 2.5 乾淨網格 | `9dbfec0e/output/model_support.stl`（24,792 面、1.0000×）→ exit 0、**stderr 完全為空**；且逐層 SHA-256 與舊引擎跑同一組輸入 **155/155 相同** |
| 2.6 逐層 SHA-256 | 與 `golden-blur0.sha256` **632/632 完全一致** |
| 2.7 統計值 | `layer_count` 632、`resin_volume_ml` 47.238572、`estimated_print_time` 16393.8 —— 與未去重產出**完全相等**（以 `parse_sl1_metadata()` + `resolve_estimated_print_time()`，即 agent 產生 `status.json` 的同一條路徑取得）。`has_support_mesh` 由 `support_stl_file.exists()` 決定，與面數無關 |
| 2.8 未匯入支撐 | 以 `9dbfec0e` 自產支撐路徑執行（不帶 `--import-support-stl`）→ exit 0、stderr 為空，逐層 SHA-256 與舊引擎 **155/155 相同** |

**2.9 效益量測（隔離變因）**：階段 2 的引擎是本次重新建置的，與打包版並非同一次建置，直接和 0-B 相比會把建置差異算進去。因此另外用**同一支舊引擎**跑一份「已在 Python 端預先去重（324,264 面）」的支撐，讓兩次之間唯一的變因就是網格本身。

| 階段（秒） | 舊引擎 / 5× 原檔 | 舊引擎 / 已預先去重 | 新引擎 / 內建去重 |
| --- | --- | --- | --- |
| 啟動 + STL 載入 + repair | 5.89 | 2.13 | 4.30 |
| hollow / drill | 0.13 | 0.27 | 0.14 |
| Slicing model | 3.46 | 4.51 | 3.21 |
| support points / tree / pad | 0.73 | 0.17 | 0.15 |
| **Slicing supports** | **8.62** | **2.67** | **3.14** |
| Merging slices | 1.25 | 1.27 | 1.60 |
| Rasterizing | 41.64 | 41.11 | 41.22 |
| 封存尾段 | 1.41 | 1.55 | 1.32 |
| **總計** | **63.13** | **53.67** | **55.08** |
| **峰值 RSS（MB）** | **2584.6** | **1465.3** | **1446.5** |

三者的逐層 SHA-256 皆與 `golden-blur0.sha256` **632/632 一致** —— 引擎內去重、Python 預先去重、完全不去重，三條路徑產出位元相同的層檔。

- 同一支 binary 的去重效益：**63.13 → 53.67 秒（−15.0%）**，峰值 RSS **2584.6 → 1465.3 MB（−43.3%）**
- 主要來源是 `Slicing supports` **8.62 → 2.67 秒（−69%）**；`Rasterizing` 如預期完全不受影響（41.64 vs 41.11）
- 作法 A 實測落在 55.08 秒，比「預先去重」的 53.67 秒多約 1.4 秒。差距幾乎全在「啟動 + 載入 + repair」（4.30 vs 2.13）—— **作法 A 仍要對 5× 網格跑完 admesh repair 才去重，這 2.2 秒是作法 A 結構上省不到的**，與 design D2 的預測一致，也再次支持階段 0.8「後續升級為作法 B」的決議

> **量測工具的一個坑（已修正，記錄以免再犯）**：量測腳本以 LF 換行、無 BOM 存檔，而 Windows PowerShell 5.1 對無 BOM 檔案以 CP950 解讀，中文註解結尾的多位元組字元會把後面的換行吃掉，導致**下一行程式碼被併入註解而靜默失效**。這一度讓 `--import-support-stl` 整個沒被傳進去，跑出 492 層（少掉 140 層純支撐層）卻仍然 exit 0。症狀是「基準組突然快了 20 秒、輸出小了一半」。腳本改存 CRLF 後恢復正常，並在腳本內加上實際命令列的落檔以便日後比對。

### 階段 3 驗證結果（fork：預覽編碼器）

實作位於 `src/libslic3r/SLA/RasterBase.cpp` 的 `PNGPreviewEncoder`：原本的降取樣迴圈原封不動抽成 `preview_box_downscale()`（通用路徑），新增 `preview_box_downscale_integer()`（固定 `N×N` 區塊）；PNG 改用 `tdefl_write_image_to_png_file_in_memory_ex(..., level=1, MZ_FALSE)`。`PNGRasterEncoder` 與 `RLERasterEncoder` 完全未動。

**3.4 / 3.5 的比對怎麼做**：快路徑與通用路徑無法在同一支 binary 內同時取用（進入條件由 scale 決定），因此以**改動前的引擎當通用路徑、改動後的引擎當快路徑**——改動前的那段程式碼就是原封不動被抽成 `preview_box_downscale()` 的那份，比的正是同一份通用實作 vs 新的固定區塊實作。PNG 位元組本身必然不同（等級 6 vs 1），所以比的是**解碼後的點陣圖**；壓縮等級只影響容器，不影響降取樣產物。

| 驗證項 | 結果 |
| --- | --- |
| 3.4 `1/4`（scale 0.25） | 632 / 632 影格解碼後**逐位元組完全相同**，尺寸皆 3780 × 1557 |
| 3.5 `1/10`（scale 0.10） | 632 / 632 影格解碼後**逐位元組完全相同**，尺寸皆 1512 × 623 |
| 3.6 層檔 SHA-256 | 0.25 與 0.10 兩次產出**皆 632 / 632 與 `golden-blur0.sha256` 一致** |
| 3.7 `preview.zip` 結構 | 632 個檔、`testzip()` 無誤、壓縮方法僅 `deflate`（JSZip 支援）、PNG magic 正確、尺寸 3780 × 1557 |

> 3.5 只是為了驗證快路徑而以 `--export-preview-pngs 0.10` 跑引擎，**未更動 `agent/jobs.py` 的縮放比**。正式落地仍歸階段 6，受跨 repo 硬閘門管制。

**3.8 預覽階段耗時與體積**（預覽成本 = 同一支 binary 的「有預覽」減「停用預覽」）

| | 舊引擎 @0.25 | 新引擎 @0.25 | 舊引擎 @0.10 | 新引擎 @0.10 |
| --- | --- | --- | --- | --- |
| 預覽產生（光柵化內，秒） | 12.07 | **9.06** | 8.98 | 7.58 |
| 封存尾段增量（zip 寫出，秒） | 0.23 | −0.05 | 0.05 | −0.19 |
| **預覽合計（秒）** | **12.30** | **9.02** | **9.02** | **7.39** |
| `preview.zip`（MB） | 29.30 | **27.38** | 12.42 | **11.91** |
| 核心光柵化（停用預覽，秒） | 29.57 | 29.51 | 29.57 | 29.51 |
| 總耗時（秒） | 63.13 | 53.78 | 59.53 | 50.85 |

- 在**現行縮放比 0.25** 下，本階段的兩項改動使預覽成本 **12.30 → 9.02 秒（−26.7%）**，`preview.zip` **29.30 → 27.38 MB（−6.6%）**
- 核心光柵化 29.57 vs 29.51 秒——**改動確實只作用於預覽路徑**，這也和 3.6 的層檔逐層一致互相印證
- **D5「只降 scale 大約只能拿到一半收益」得到實測支持**：單獨降 scale 到 0.10（舊引擎）是 12.30 → 9.02 秒；單獨做編碼器兩項改動（新引擎 @0.25）同樣是 12.30 → 9.02 秒；兩者合起來也只到 7.39 秒。剩下那約 7.4 秒是來源側必須讀滿 94.2 M 像素的固定成本，不隨 scale 下降——要再往下砍只能靠 dirty-tile 稀疏化（已列於 9.2）

### 階段 4 驗證結果（fork：預覽產出失敗不得使切片失敗）

實作：`SLAArchiveWriter::export_preview_zip()` 由 `void` 改回傳 `bool`，catch 內記錄錯誤後 `return false` 取代 `throw`；`SLAArchiveWriter.hpp` 與 `SLAPrint.hpp` 的宣告同步；`ProcessActions.cpp` 的呼叫端依回傳值分流，失敗時不 `return 1`。

**為何改成回傳 `bool` 而非單純吞掉例外**：`agent/jobs.py:139` 把 `"Preview ZIP exported to "` 當作 `ARCHIVE_DONE_MARKER`，且 `test_slice_progress_string_contract.py` 直接對 fork 原始碼鎖定該字面量。若只吞例外、讓呼叫端照印那行，log 會出現「已匯出到 X」但 X 不存在的假陳述。因此成功才印原字面量（一字未動，契約測試 98 passed），失敗改印一行到 stderr。

**已知取捨**：預覽失敗時進度會停在 `STAGE_FINALIZING` 而非 `STAGE_ARCHIVED`。`run_slicing` 的終態判定只看 `returncode == 0` 與 `output_file.exists()`，marker 純為進度子狀態且進入終態時會被清除，故不影響 4.4。

**測試怎麼製造預覽失敗**：把 `*_preview.zip` 這個路徑**預先建成目錄**，使 `Zipper` 開檔必失敗，而同目錄下的 `.sl1` 仍正常寫出。照 tasks.md 字面把整個輸出目錄設唯讀行不通——那樣 `export_print()` 會先失敗，根本走不到待測的程式碼。

| 驗證項 | 結果 |
| --- | --- |
| 4.3 預覽寫檔失敗 | **exit code 0**、`model.sl1` 58,307,736 bytes 正常寫出、stderr 含 `warning: preview ZIP could not be written to ...`、stdout **未**輸出 archive marker |
| 4.3 對照（改動前引擎） | **exit code 1** —— `.sl1` 其實已完整寫在磁碟上仍被判為失敗，正是本需求要修的缺陷 |
| 4.4 `status.json` | `status=completed`、`layer_count=632`、`resin_volume_ml=47.238572`、`estimated_print_time=16393.8`、`error=None`；`stderr.log` 完整保留預覽失敗記錄 |
| 4.5 `download.prz` | `model_preview.zip` 不存在（該路徑是目錄）下 **HTTP 200、97,149,403 bytes**；以 `agent.prz_decoder.parse_prz()` 解析成功：632 層、15120×6230、內嵌預覽圖 116×116 與 290×290 皆在；抽驗第 0/10/316/500/631 層，PRZ 與 `.sl1` 解碼後點陣圖 **5/5 完全相同** |
| 4.6 層檔不變 | 正常路徑、`.sl1` 逐層 SHA-256 與 `golden-blur0.sha256` **632/632**；預覽失敗的兩次（CLI 直跑與 agent API 端到端）亦皆 **632/632** |

> 4.4 / 4.5 是以 `SLICER_ENGINE_BIN` 指向 build tree 的引擎、另起 uvicorn 於 127.0.0.1:5279 實跑 agent API 完成的（建立 job → 上傳 model 與 support → execute → 輪詢 → `download.prz`），未覆蓋 `slicer-engine/bin` 的打包成果物。

### 階段 5 驗證結果（fork：raster 每執行緒重用）

實作：`draw_layers()` 改由 `ThreadBoundRasters` 提供執行緒綁定的重用實例；`RasterBase` 新增純虛擬 `reset()`；`AGGRaster::reset()` 清整張緩衝並重設 gamma；`SVGRaster::reset()` 截斷回 SVG header。

> **建置期插曲（已修，記錄以免再犯）**：第一版把 `<tbb/enumerable_thread_specific.h>` 直接寫進 `SLAArchiveWriter.hpp`。查證後確認，在此檔原本就需要的 TBB 標頭裡（`spin_mutex` / `parallel_for` / `parallel_reduce` / `task_arena` / `task` / `profiling`）**只有它會 `#include <windows.h>`**。該標頭經 `SLAPrint.hpp` 被大量 TU 引入，於是 GDI 的 `::Polygon` 與 `Slic3r::Polygon` 在 `using namespace Slic3r;` 的測試檔中相撞（C2872）。改以 pimpl 把 TBB 容器關進 `SLAArchiveWriter.cpp` 解決；不採用「在衝突處改寫成 `Slic3r::Polygon`」，那是替污染打補丁而非移除污染。

| 驗證項 | 結果 |
| --- | --- |
| 5.4 `blur = 0` | 逐層 SHA-256 與 `golden-blur0.sha256` **632 / 632** |
| 5.5 大面積層緊接空層 | 見下 |
| 5.6 `blur = 1` | 逐層 SHA-256 與 `golden-blur1.sha256` **632 / 632** —— `draw_binary()` 的 gamma 還原與 blur 後處理在重用下皆正確 |
| 5.7 配置次數 | 見下 |

**5.5 的測試模型是特地造的**：兩片 180 × 95 mm 平板，中間留 z = 1.0 ~ 2.0 的空隙（層高 0.05 → 上下板各 20 層、空隙 20 層）。第 19 層點亮 **64,302,858** 像素（佔畫布 68%），緊接的第 20 層必須是空的。

- 20 個空層的 `.rle` 位元組**全部等於 `55 30 59 d5 76 2b`**，也就是我依 RLE 編碼規則獨立推導出的全背景標準編碼（header + 一段 BLACK run 94,197,600 + 補數檢查碼），**不是抄引擎輸出來比對自己**
- 新舊引擎逐層 SHA-256 **60 / 60 相同**

**5.7 的量測方式必須先排除一個干擾**：`peak commit` 無法用來驗這一項，因為它被 `RLERasterEncoder` 每層 11.23 MB 的過度保留主導（詳見上方對階段 0 觀察的更正）。因此改用 **PNG 編碼路徑（不過度保留）＋停用預覽＋同一份模型與畫布、只改層高**來隔離幅面緩衝：

| | 層數 | 舊引擎（每層新建） | 新引擎（執行緒重用） |
| --- | --- | --- | --- |
| 層高 0.20 | 158 | 15.17 s / commit 1819.9 MB | 13.31 s / commit 1791.8 MB |
| 層高 0.05 | 632 | 54.41 s / commit 2106.6 MB | 48.57 s / commit 2143.7 MB |

- 新引擎由 158 層增至 632 層，commit 只增加 **351.9 MB**。若每層各配置一張幅面緩衝並累積，多出的 474 層應增加 474 × 94.2 MB = **44,651 MB**。實際增量約每層 0.74 MB，量級與「474 張已編碼 PNG 存入 `m_layers`」相符 → **幅面緩衝不隨層數線性增長**
- 省下的時間隨層數成長：158 層省 1.86 s、632 層省 5.84 s（每層 11.77 ms 與 9.24 ms），與「每層一次幅面配置＋一遍歸零」被移除的量級相符
- **「配置次數不超過併發執行緒數」是由程式結構保證而非計數量到的**：`ThreadBoundRasters::acquire()` 只在該執行緒的 ETS 槽位為空時呼叫 `create_raster()`，而 ETS 每條執行緒至多一個槽位，故建構次數 ≤ 實際執行 body 的執行緒數 ≤ `max_concurrency`。tasks.md 原本允許「配置點加計數記錄或 profiler」，我兩者都沒做——加計數需要改 C++ 並重新建置（本階段建置由人工進行），故以結構論證加上上述兩項間接量測替代，此處據實標明。

**5.8 效益**（與階段 3/4 的建置在同一台機器、同一組輸入與 config 比較）

| 階段（秒） | 階段 3/4 後 | 階段 5 後 |
| --- | --- | --- |
| 啟動 + 載入 + repair | 4.64 | 5.11 |
| Slicing model | 3.49 | 3.60 |
| Slicing supports | 2.88 | 3.13 |
| Merging | 1.49 | 1.40 |
| **Rasterizing** | **39.18** | **29.83** |
| ├ 預覽產生 | 9.06 | 9.80 |
| └ **核心光柵化** | **29.51** | **20.03** |
| 封存尾段 | 1.33 | 1.22 |
| **總計** | **53.32** | **44.65** |
| 峰值 RSS（MB） | 1452.5 | 1488.4 |

- **核心光柵化 29.51 → 20.03 秒（−32.1%）**，總耗時 53.32 → 44.65 秒（−16.3%）。其餘階段皆在雜訊範圍內，效益乾淨地落在光柵化
- **峰值 RSS 沒有下降（1452.5 → 1488.4 MB）**，這與原先的預期不同但事後想是合理的：無論每層新建或執行緒重用，同時存活的 raster 數量都是併發執行緒數，峰值本就相同。重用省的是**配置與歸零的時間**，不是峰值記憶體。design D6 的用詞「省掉數千萬次 page fault」指的正是時間面；階段 0 那條「為 D6 提供記憶體面實測依據」的推論是錯的，已於上方更正

### 階段 7 驗證結果（fork：blur 後處理分帶重寫）

實作位於 `src/libslic3r/Format/SL1.cpp`：新增 `stack_blur_gray8_vertical_strips()`，以 64 欄為一帶處理垂直 pass；原本的 `agg::stack_blur_gray8(pixf, radius, radius)` 改為 `agg::stack_blur_gray8(pixf, radius, 0)`（水平 pass 一行未改）＋ 分帶垂直 pass。兩個分支（`k >= 256` 就地模糊、`k < 256` temp buffer + alpha blend）都改。

**位元一致性為何能成立**：`agg_blur.h` 的垂直 pass 中，column x 只讀寫 column x，彼此完全獨立，因此走訪順序不影響任何輸出位元組；且 `stack_ptr` 與 `yp` 對所有 column 演進完全相同，可提到外層當純量。算術（`unsigned` 累加器、stack 更新順序、`(sum + whalf) / wsum` 截斷除法、邊界夾取）逐行照抄未改。這正是 spec 允許分帶、卻排除「重新推導等價 3×3 卷積」的原因——後者捨入路徑不同，無法保證一致。

實作時特別處理的兩點：**(a)** 最後一列 `yp` 被夾到 `hm` 時等於 `y`，AGG 原版會讀到自己剛寫入的位元組，因此內層迴圈維持「先寫 `out_row[j]`、後讀 `in_row[j]`」的次序；**(b)** AGG 在 y 迴圈前那次 `pix = img.pixel(x, yp)` 是死碼（迴圈內每次都在使用前重新指派），已省略並於該處註明。

| 驗證項 | 結果 |
| --- | --- |
| 7.5 `blur = 0` | 與 `golden-blur0.sha256` **632 / 632**（後處理未執行） |
| 7.3 `blur = 1` | 與 `golden-blur1.sha256` **632 / 632** |
| 7.4 `blur = 2`（temp buffer + alpha blend 分支） | 與重寫前產出 **632 / 632** |
| 7.4 `blur = 3`（`k >= 256` 就地模糊分支） | 與重寫前產出 **632 / 632** |

> `blur = 2` / `blur = 3` 沒有階段 0 留下的黃金基準，以打包版引擎（2026-07-30，重寫前）各跑一次建立。該版雖也不含階段 2～5 的改動，但那些階段都已各自驗證不改變層檔（每次皆 632/632），對 blur 輸出而言是合法的參照。
>
> **交叉檢查**：四種強度兩兩比對，相同層數皆為 140 / 632——恰為 z = 7.00 mm 以下的純支撐層（走 `draw_binary()` 不受 blur 影響）。四者確實互不相同，「全部一致」不是因為都走了同一條路徑。

**7.6 效益量測**

`blur = 1` 是乾淨對照：兩者都是本機建置，唯一差別就是本階段的重寫。

| 階段（秒） | 階段 5 後 | 階段 7 後 |
| --- | --- | --- |
| 啟動 + 載入 + repair | 4.33 | 4.75 |
| Slicing model | 3.19 | 3.65 |
| Slicing supports | 2.95 | 3.07 |
| Merging | 1.23 | 1.32 |
| **Rasterizing** | **258.63** | **161.08** |
| 封存尾段 | 2.38 | 1.96 |
| **總計** | **273.07** | **176.19** |
| 峰值 RSS（MB） | 2242.9 | 2280.1 |

各強度的光柵化耗時：

| | 重寫前 | 重寫後 | 變化 |
| --- | --- | --- | --- |
| `blur = 1` | 258.63 | **161.08** | **−37.7%** |
| `blur = 2` | 232.32 | 152.77 | −34.2% |
| `blur = 3` | 203.27 | 143.13 | −29.6% |
| `blur = 0`（參考） | — | 28.96 | 不適用 |

- **`blur = 1` 總耗時 273.07 → 176.19 秒（−35.5%）**，效益全部落在光柵化，其餘階段在雜訊範圍內
- 扣掉 `blur = 0` 的光柵化基準 28.96 秒，blur 後處理本身由約 229.7 秒降至 132.1 秒（**−42.5%**）
- **`blur = 2` / `blur = 3` 的「重寫前」欄取自打包版引擎，該版同時缺少階段 2／3／5 的改動，因此那兩列的時間差被高估**，不可視為本階段單獨的效益；乾淨的數字只有 `blur = 1` 那一組
- 峰值 RSS 幾乎不變（2242.9 → 2280.1 MB）：分帶只改變走訪順序，額外配置僅 `div × 64` 位元組的 stack 與三個 64 元素的累加器陣列

### 階段 8 驗證結果（整合驗證與收尾）

**8.1 commit 切分**。三個 commit，Python 與 fork 可分別回滾：

| Repo | Commit | 內容 |
| --- | --- | --- |
| fork | `f8eb1e9cb` | 階段 2／3／4／5／7 的 C++ 改動（9 個檔） |
| 父 repo | `d05aa67` | 階段 1 的 Python blur 閘控 + 測試 |
| 父 repo | `08ee0ee` | submodule 指標 `24587c6 → f8eb1e9` |

三項刻意不納入的東西，以免污染回滾邊界：

- fork 內的 `.gitignore`、`src/libslic3r/CMakeLists.txt`（停用 `encoding_check`、補 `find_package(Blosc)`）、`src/slic3r/CMakeLists.txt` 是**本機建置環境的權宜改動**，與本變更無關，留在工作區未提交。把它們混進效能 commit 會讓別人 revert 時連帶改掉建置設定。
- 父 repo 的 `agent/support_classifier.py`、`agent/tests/test_support_e2e.py`、`scripts/*`、`.gitignore`、`.gitmodules` 屬另一個變更（`fix-empty-pad-slicing-error`）的在途工作，同樣未動。
- **submodule 指標 commit 的回滾邊界不乾淨，已在 commit message 標明**：`24587c6 → f8eb1e9` 之間除了本次的 `f8eb1e9cb`，還夾帶父 repo 先前未跟進的 `9dee8f6be`（PE icon）與 `40f3b2561`（零支撐柱 pad 降級）。revert 該指標 commit 會一併退掉那兩筆；只想退效能改動時應在 fork 內 revert `f8eb1e9cb` 後重新更新指標。

**8.2 `pytest agent/tests/`**：**484 passed, 2 failed**——未達 100%，但**兩筆皆與本變更無關**，且在本變更之前就已存在：

| 失敗項 | 原因 | 判定依據 |
| --- | --- | --- |
| `test_prz_print_time.py::test_6_11_single_normal_layer_full_params` | `_compute_print_time()` 少算 drop2 那一段（得 11.0、期望 14.0） | 該測試與它 import 的 `prz_encoder` / `prz_decoder` / `models` **`git diff HEAD` 皆為空**，即工作區內容與 HEAD 完全相同，本變更一行未碰 |
| `test_subprocess_boundary_5_11.py::test_engine_runs_as_separate_process` | async 測試，環境未安裝 `pytest-asyncio`（已確認 `find_spec` 為 None） | 環境缺件，非程式碼缺陷 |

階段 1 直接相關的 `test_extract_sla_from_mechado.py` 與 `test_slice_config_merge.py` 全數通過。**這兩筆失敗不應算在本變更頭上，但也不該被當作「已通過」帶過**——`_compute_print_time` 的 drop2 是真的算錯，屬 `release/v1.0.5` 上的既有缺陷，需另行處理。

**8.3／8.4 端到端**（job `53b18019`，經 agent API 全程實跑，`SLICER_ENGINE_BIN` 指向本次建置的引擎）：

| 步驟 | 結果 |
| --- | --- |
| `POST /slices` → `upload` → `upload-support` → `execute` | 全部 200；輪詢 44.3 秒完成，進度依序經 `STAGE_SLICING` → `STAGE_SLICING_SUPPORTS` → `STAGE_RASTERIZING` → `STAGE_FINALIZING` |
| `config.ini` | `blur = 0` —— 階段 1 的閘控在完整後端路徑上生效 |
| `status.json` | `layer_count` **632**、`resin_volume_ml` **47.238572**、`estimated_print_time` **16393.8**、`has_support_mesh` **False**、`error` None —— 四項**與封存 job `b1d3a041/status.json` 完全相等** |
| `.sl1` 逐層 SHA-256 | 與 `golden-blur0.sha256` **632 / 632** |
| `POST /download.prz` | HTTP 200、97,149,403 bytes、0.9 秒；`parse_prz()` 解析出 `total_layers` **632**、15120 × 6230、內嵌預覽 116×116 與 290×290 皆在；抽驗第 0/10/316/500/631 層，PRZ 與 `.sl1` 解碼後點陣圖 **5 / 5 完全相同** |
| `GET /preview.zip` | HTTP 200、28,707,446 bytes（27.38 MiB）、0.4 秒；632 影格、`testzip()` 無誤、尺寸 3780 × 1557 |
| `GET /layers.zip` | HTTP 200、145,708,892 bytes（138.96 MiB）、**378.3 秒**；632 層、`testzip()` 無誤、尺寸 15120 × 6230 |

> **`has_support_mesh = False` 是正確值，不是回歸。** 該欄位由 `jobs.py:525` 的 `(output/model_support.stl).exists()` 決定，語意是「引擎**自產**了支撐」。本 job 的支撐由前端上傳、走 `--import-support-stl`，引擎不會產出 `model_support.stl`，封存基準 `b1d3a041/status.json` 記的同樣是 `False`。（撰寫驗證腳本時我一開始把基準寫成 `True`，是憑印象填的，已依封存 job 的實際值更正。）
>
> **`layers.zip` 的 378 秒值得記一筆。** 這條路徑在 RLE 模式下要把 632 層 15120×6230 逐層解碼再重新編成 PNG（`_rle_sl1_to_png_zip`），耗時是整趟切片的 8.5 倍。它只是前端 `preview.zip` 失敗時的 fallback（`slicingService.js:878`），happy path 不會碰到，但一旦碰到就是六分鐘的同步阻塞。不在本變更範圍，列此備查。
>
> **本次端到端發現一項本變更引入的 metadata 不一致**：PRZ header 的 `blur_level` 仍為 **1**，而層檔是以 `blur = 0` 光柵化的。詳見第 9 節 9.6。

**8.5 最終量測彙整**（對照階段 0-A，即改動前的正式流程）

階段 0-A 是「使用者在 UI 關掉 blur、後端卻仍以 blur=1 切片」的實際狀態，因此下表的 blur=0 欄才是**同一位使用者在同一組設定下**改動前後的真實對照。

| 指標 | 0-A（改動前） | 完成後（blur=0，未勾選） | 完成後（blur=1，已勾選） |
| --- | --- | --- | --- |
| 總耗時（秒） | 287.97 | **43.49（−84.9%）** | **176.19（−38.8%）** |
| 峰值 RSS（MB） | 2642.5 | **1498.5（−43.3%）** | 2280.1（−13.7%） |
| `.sl1` 檔案（MiB） | 101.60 | **55.61（−45.3%）** | 101.60（不變） |
| 層檔原始總量（MiB） | 194.64 | **92.42（−52.5%）** | 194.64（不變） |
| `preview.zip`（MiB） | 32.09 | **27.38（−14.7%）** | 未單獨量測 |

各階段對「blur=0 路徑」總耗時的貢獻（每一列都是同一支 binary 的對照，已排除建置差異）：

| 階段 | 對照 | 省下 |
| --- | --- | --- |
| 1 blur 閘控 | 287.97 → 63.07 | **−224.9 s** |
| 2 支撐去重 | 63.13 → 55.08 | −8.1 s |
| 3 預覽編碼器 | 預覽成本 12.30 → 9.02 | −3.3 s |
| 5 raster 執行緒重用 | 53.32 → 44.65 | −8.7 s |
| 7 blur 分帶 | 僅作用於 blur>0：273.07 → 176.19 | −96.9 s（blur=0 時 0） |

- **九成以上的效益來自階段 1 這個一行閘控的缺陷修復**，而不是任何一項光柵化優化。這點值得在結論裡誠實標明：後面五個階段合計約 20 秒，量級與那個設定傳遞 bug 差了一個數量級。
- 階段 4（預覽失敗不中止切片）不產生效能數字，是可用性修復。
- 階段 6 未執行（跨 repo 閘門未解除），其預估效益不計入本表。

**8.7 跨 repo 項目狀態**（DS-Online，`release/v1.0.5` @ `45f8216`，靜態檢查）

| 項目 | 位置 | 狀態 |
| --- | --- | --- |
| 支撐匯出子節點過濾（5× 根因） | `src/three/managers/MeshManager.js:2251` | **未修復** |
| WASM PRZ fallback 移除 | `src/services/slicingService.js` **三處**：747–754（前景 `downloadPrz` 失敗）、758–765（無 backendJobId）、1174–1181（背景切片 `downloadPrz` 失敗） | **未移除** |
| `unzipPreviewFrames` 自 happy path 移除 | `slicingService.js:436` 定義、`:868` happy path 使用 | **未移除** |

移交事項（三項皆須在 DS-Online 開變更追蹤）：

1. **5× 根因**。可驗證的事實：`support.stl` 為精確 **5.0000×**（1,621,320 → 324,264，連法線在內逐位元組相同），而同一次匯出的 `model.stl` 是 **1.0000×**（926,086 面全部唯一）。靜態面：`exportSupportOnlySTL()` 只在挑選 `model.children` 時套 `isSlicableChild`，接著把每個支撐**連同整棵子樹**交給原生 three.js `STLExporter.parse()`，而它是無條件 `traverse()` 匯出所有後代 Mesh；`clippingStencil.buildPasses()` 又會在每個 slicable host 底下掛上 **4 個** stencil pass Mesh（top/bottom × Back/FrontSide），且全部共用 `host.geometry`——1 + 4 = 5，與量到的倍率吻合。
   **但這個推論尚未閉合，交接時必須說清楚**：`_exportModelsWithChildFilter()`（模型路徑）有完全相同的「只過濾一層」問題，模型卻沒有 5×。這個不對稱我無法從靜態程式碼解釋。**因此修正必須以可重現的實例驗證，不能只依這段算術就認定修好了。**
2. **WASM fallback**。呼叫點是三處而非先前記錄的一處。移除前需確認前景下載路徑（747–765）的 `backendJobId` 為空時要如何處置——那不是 fallback，是**唯一**路徑。另已確認 `downloadPrz` 失敗後由 `useSlicedFilesStore.js:221` 的 `toast.errorKey('errors.slices.sliceFailed')` 與 `:267` 的 `retrySlice()` 承接，改為明確拋錯不會沒有著落。
3. **`unzipPreviewFrames`**。`pngBlobs` 的下游只有 `generatePrzFromBackendLayers`（750／761／1180）。**若 2 完成，3 的 happy path 解壓即成為純浪費**（632 張 WebP 解壓後無人使用），兩者應同一個變更一起處理，順序為先 2 後 3。
4. **階段 6 的硬閘門維持不解除**。閘門條件 6.1～6.3 全數未達成。附帶提醒：先前於前端靜態檢查已確認 `pngRleWorker.js` 在尺寸不符時直接 `throw`，而 `paramsStore.resolution` 是整機解析度——**該 fallback 在任何預覽縮放比下都必然失敗**，所以閘門原文「上採樣 4× 惡化為 10×」的技術理由其實不成立（它根本不會產出上採樣的 PRZ，只會拋錯）。閘門本身仍應保留（未移除的死路徑會遮蔽真實錯誤），但理由需改寫。此處僅記錄，未修改閘門文字。

### 額外觀察（非 checklist 項目）

- **repair 呈超線性**：support.stl 面數為 model.stl 的 1.75 倍，repair 卻慢 **10.6 倍**（3.02 s vs 0.28 s）。與 design D2 的預測一致——5× 重複讓每條邊被 10 個面共用，網格被判為非流形而進入 `stl_check_facets_nearby()` 路徑。
- **commit 在 rasterize 期間單調成長至 9,167 MB**（WorkingSet 僅約 1.9 GB）。引擎自報值由 96% 的 8,083 MB 一路升到 100% 的 9,079 MB，約每 1% 進度增加 250 MB。在 8 GB 記憶體的機器上此提交量是實質風險。

  > **原因判定已於階段 5 被實測推翻，保留原文以誌其誤。** 當時寫的是「這與『每層新建並釋放一張 94.2 MB raster』的配置型態吻合，為 design D6 提供直接的實測依據」——**不成立**。階段 5 以 250 ms 取樣同時量測新舊引擎的 commit 曲線，兩者成長速率幾乎相同（舊 8,128 MB、新 8,464 MB），raster 重用完全沒有改變它。真正的來源是 `RLERasterEncoder` 的 `out.reserve(n / 8 + 64)`：94,197,600 / 8 + 64 = **11,774,764 bytes ≈ 11.23 MB 每層**，而編碼結果以 move 存入 `m_layers` 時**容量原封不動被保留**（實際只用約 150 KB）。632 × 11.23 MB = **7,096.9 MB**，與觀測到的成長量吻合；WorkingSet 不跟著漲，是因為這些頁面已提交但從未被觸碰。當初「per-layer raster」的推論只是與曲線形狀相容，並未被驗證。此項屬既有缺陷、不在本變更範圍，另記於第 9 節。