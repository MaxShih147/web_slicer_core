## Why

以 job `b1d3a041`（Sonic Mighty Revo 16K、15120×6230、632 層）為基準，一趟切片耗時 **172 秒**、峰值 RSS 推估約 2.2 GB、產出 `.sl1` 91.6 MB + `model_preview.zip` 33.6 MB。靜態分析與檔案級量測顯示，這些成本有**相當比例不是切片工作本身，而是三個可證實的缺陷**：

1. **使用者已關閉的 blur 仍在全速執行。** 前端 mechado config 明確帶 `Advanced."Image Blur" = false`，但後端萃取器只複製 `Image Blur Pixel`（=1）、完全未讀該開關，於是 `config.ini` 寫出 `blur = 1`。實測第 316 層有 **229 個不同灰階值**，而 AA 量化在數學上只可能產生 `{32, 88, 144, 198}` 四個值——換言之 **298,897 個灰階像素中約 98% 是 blur 產物**，它們佔掉該層 **81% 的 RLE 位元組**，其中四成落在 `≤16` 或 `≥239`（對曝光無意義的「視覺全黑／全白」）。
2. **匯入的支撐網格每個三角形都存在五份。** `input/support.stl` 1,621,320 面 → 去重後 324,264 面，倍率**恰好 5.00×**，四份不同 job 無一例外。去重後 F ≈ 2V，是乾淨的封閉流形。這讓支撐的切片交線段從 6.3 M 膨脹到 **31.3 M**（模型本身只有 3.8 M），並把網格拖進 admesh 的非流形修補路徑。
3. **預覽圖以七倍於顯示需求的解析度產出，且被下載後立刻重複解壓一次。** 預覽對話框寬度上限為 560 px，實際渲染約 520 CSS px；而 `--export-preview-pngs 0.25` 產出的是 3780 px 寬。同時每次切片都在關鍵路徑上把 632 張 PNG 解壓一次，而其唯一消費者是一條幾乎不會被觸發的降級路徑。

這些都是「本來就在做無用功」，與各自佔比多少無關——修掉它們不需要犧牲任何既有功能或輸出品質。現在處理的理由是：Agent 執行在**使用者不可控的個人電腦上**（`BUNDLE_JOBS_DIR` / localhost TLS 的打包桌面部署），16K 機型的畫布是每層 94.2 MB，記憶體壓力會直接轉化為失敗率。

## What Changes

- **修復 blur 設定傳遞缺陷**：後端萃取 SLAConfig 時 SHALL 尊重 `Advanced."Image Blur"` 開關；未勾選時 `blur` 為 `0`。開關缺失時維持現行行為（向後相容）。
  **BREAKING（輸出面）**：既有前端在未勾選 blur 時，切片輸出的層圖像素與 `.sl1` 內容**會改變**（回到使用者實際設定的樣子）。這是修正而非退化，但需納入驗收比對。
- **匯入支撐網格的防禦性清理**：`--import-support-stl` 讀入後 SHALL 去除完全重複的面，並記錄去重前後面數與倍率，讓任何來源的髒網格都留下可觀測痕跡。
- **預覽圖產出調整**：`--export-preview-pngs` 的 scale 由 `0.25` 降為 `0.10`；PNG 壓縮等級由 miniz 預設 6 降為 1；降取樣加入整數倍（1/N）快路徑。降取樣濾波維持 box-mean（已實測驗證 0.10 下支撐特徵不會消失）。
- **光柵化資源重用**：`draw_layers()` 的 raster 由「每層新建」改為「每執行緒重用」，消除每趟 632 次 94 MB 配置與其中一遍歸零。此項為**純效能改動，輸出必須逐位元組不變**。
- **blur 啟用路徑的實作重寫**（第二階段）：現行 `agg::stack_blur_gray8` 的垂直 pass 為 column-major，在 stride 15120 的畫布上每像素一次 cache miss。`blur=1` 在數學上等價於單一固定 3×3 卷積；一般情況則改為分帶（strip）垂直 pass。此項不改變 blur 的視覺結果，只改變取得結果的方式。
- **不做的事（已評估並否決）**：將 `model.stl` 拆成多物件或多 job 分別切片再合併。實測該檔含 8 個連通元件、7 個導板全部起自 `z = 7.00`，拆分後總層數由 632 膨脹至 3,810（**6.03×**），且 `initialize_printer_input()` 本就把所有物件併入同一張畫布、`attach_imported_support()` 寫死綁定單一物件——負收益且有架構硬阻擋。

## Capabilities

### New Capabilities

- `imported-support-sanitization`: 定義 `--import-support-stl` 匯入網格在進入切片管線前的清理契約——重複面去除的判定基準、清理必須在何時發生、可觀測性（log 格式），以及「清理 MUST NOT 改變任何切片輸出」的不變式（重疊多邊形本就會被 `union_ex` / `diff_ex` 吸收，樹脂體積來自聯集後面積而非網格體積）。
- `slice-preview-export`: 定義預覽層圖封存（`model_preview.zip`）的產出契約——縮放比例與消費端顯示需求的對應關係、編碼格式與壓縮等級、降取樣濾波語意，以及「預覽產出失敗 MUST NOT 使切片失敗」的降級行為。此能力目前完全沒有 spec，scale 是 agent 端硬寫的字串。
- `sla-raster-performance`: 定義光柵化階段的效能不變式與正確性契約——raster 生命週期與執行緒綁定的約束（`draw_binary()` 暫時抽換 gamma LUT 的 race-free 前提在重用後如何維持）、部分清除與 `apply_postprocess()` 全緩衝掃描的相容條件，以及所有效能改動的驗收標準：`.sl1` 內每一層 `.rle` 的 SHA-256 必須與改動前完全一致。

### Modified Capabilities

- `slice-config-intake`: 「後端從完整 mechado config 萃取 SLAConfig 切片參數」這條 requirement 目前明文規定 `Advanced.Image Blur Pixel` **直接複製**，並在場景中斷言 `blur == 1`。需新增 `Advanced."Image Blur"` 開關的閘控語意：開關為 `false` 時 `blur` SHALL 為 `0`；開關缺失時維持直接複製（向後相容）。原有的「不得二次刻度轉換」約束不變——開關閘控與刻度轉換是正交的兩件事。

## Impact

**本 repo（web_slicer_core）**

- `agent/api_v2.py`：`_extract_sla_from_mechado()` 的 blur 對映；`_convert_v2_config_to_sla()` 的同源 `"Image Blur Pixel": "blur"` 對映。
- `agent/jobs.py`：`run_slicing()` 中硬寫的 `--export-preview-pngs 0.25`。
- `third_party/prusaslicer_fork`（submodule，需獨立 commit 與版本更新）：
  - `src/CLI/ProcessActions.cpp`：匯入支撐後的去重與 log。
  - `src/libslic3r/SLA/RasterBase.cpp`：`PNGPreviewEncoder` 的壓縮等級與整數倍快路徑。
  - `src/libslic3r/Format/SLAArchiveWriter.hpp`：`draw_layers()` 的 raster 重用。
  - `src/libslic3r/Format/SL1.cpp`：blur 後處理的實作重寫（第二階段）。
- 測試：`agent/tests/test_slice_config_merge.py`、`test_extract_sla_from_mechado.py`。
- 規格：`openspec/specs/slice-config-intake/spec.md` 的既有場景斷言需同步。

**跨 repo 相依（DS-Online 前端，需在該 repo 另開變更，不屬本變更範圍）**

- `MeshManager.exportSupportOnlySTL()`：缺少子節點過濾，把 `clippingStencil.buildPasses()` 掛在支撐 mesh 底下、共用同一份 geometry 的 4 個 stencil pass 一併寫入 STL——這是 5× 的**根因**。本變更的後端去重只是防禦網，治不了根。
- `slicingService.js` 的 WASM PRZ fallback：`downloadPrz` 失敗時改以 1/4 尺寸預覽圖上採樣 4 倍生成列印檔，且僅有一行 `logger.warn`。已決議移除、改為明確拋錯（既有的 `toast.errorKey` 與 `retrySlice` 基礎設施已完備，無需新增 UI）。**此項必須先於 preview scale 降至 0.10 落地**，否則上採樣倍率會由 4× 惡化為 10×。
- `runBackendPipeline()` 的 `unzipPreviewFrames()`：其唯一活消費者即上述 fallback，移除後每次切片可省下主執行緒上 632 次 PNG 解壓（`SlicePreviewDialog` 開啟時本就會自行解壓一次）。

**尚未驗證的前提**

本提案的成本拆解（blur 60–110 s、preview 25–40 s 等）全部來自靜態分析與檔案級量測，**尚未進行任何端到端效能實測**。實作的第一步應為不改動任何程式碼的 A/B 量測（`blur=1` vs `blur=0`，記錄總秒數、`.sl1` 大小、`_preview.zip` 大小、峰值 RSS），據以校準各項的優先序。