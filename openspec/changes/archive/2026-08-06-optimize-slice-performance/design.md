## Context

Agent 以打包桌面程式的形態執行在使用者自己的電腦上（`BUNDLE_JOBS_DIR` / localhost TLS / CORS 白名單指向 DS-Online），一次處理一個 job。因此本變更的約束不是伺服器吞吐量，而是**單機的時間與記憶體**，且硬體規格不可控。

現行 SLA 光柵化的核心形狀（[SLAPrintSteps.cpp:1592](../../../third_party/prusaslicer_fork/src/libslic3r/SLAPrintSteps.cpp#L1592) `rasterize()` → [SLAArchiveWriter.hpp:39](../../../third_party/prusaslicer_fork/src/libslic3r/Format/SLAArchiveWriter.hpp#L39) `draw_layers()`）是：對每一層新建一張完整幅面的 raster，畫上模型與支撐，跑後處理，編碼兩次（RLE + 預覽 PNG）。以 15120×6230 計，單張畫布 94.2 MB；TBB 併發度在四核機器上為 8，`m_layers` 與 `m_preview_layers` 又把全部編碼結果留在 RAM 直到最後才寫檔。

`b1d3a041` 的量測基準與三項缺陷的證據見 [proposal.md](proposal.md)。本文件只處理「怎麼做」。

一個貫穿全篇的關鍵事實：**畫布有九成以上是全黑的**（第 316 層點亮 8.49%，第 60 層 0.90%），但現行實作有數道全幅面掃描是無條件執行的。這決定了哪些優化有效、哪些沒有——例如零件散佈在整個平台上（七個導板的 bbox 總和佔平台 64%、全域 bbox 佔 81%），任何 **bbox 級**的裁切最多只能省兩三成，只有 tile／run 級的稀疏化才拿得到那九成。這也是本變更**不**納入 bbox 裁切的原因。

## Goals / Non-Goals

**Goals:**

- 移除三項可證實的無用功（blur 開關失效、支撐網格 5× 重複、預覽過度取樣），且不犧牲任何既有功能或輸出品質。
- 讓 blur 這條「使用者可主動啟用」的路徑不再是效能地雷——啟用時的成本應與其視覺效果相稱。
- 降低峰值記憶體，因為記憶體壓力會直接轉化為 `download.prz` 這類後續步驟的失敗率。
- 為所有純效能改動建立一條可機械驗證的驗收線，讓「沒有改變輸出」不是靠人眼判斷。

**Non-Goals:**

- **不做 bbox 級畫布裁切**（收益上限僅 19–36%，見 Context）。
- **不做 dirty-tile 稀疏化**。它是唯一能吃到那九成空白的手段，但在前述項目完成後剩餘 headroom 已不多，且複雜度顯著。列為後續變更的候選。
- **不拆分 `model.stl`**。已評估並否決，理由與數據見 [proposal.md](proposal.md)。
- **不處理 DS-Online 前端的程式碼**。前端三項（stencil pass 過濾、WASM fallback 移除、`unzipPreviewFrames` 移除）需在該 repo 另開變更；本文件只定義兩者之間的落地順序閘門。
- **不下架 `Mechado_wasm`**。前端移除 PRZ fallback 後該模組可能整包無用，但那是前端 repo 的判斷。

## Decisions

### D1：blur 開關在後端對映層閘控，採三態語意

`Advanced."Image Blur"` 的閘控放在 [agent/api_v2.py](../../../agent/api_v2.py) 的兩個對映點（`_extract_sla_from_mechado()` 與 `_convert_v2_config_to_sla()`），語意為三態：

| `Advanced."Image Blur"` | `blur` 取值 | 理由 |
|---|---|---|
| `false` | `0` | 使用者已關閉，不得執行 |
| `true` | 複製 `Image Blur Pixel` | 現行行為 |
| 缺失 | 複製 `Image Blur Pixel` | 向後相容：舊 config 不含此鍵，行為必須不變 |

**替代案（否決）：在 fork 端新增 `blur_enable` config 欄位。** 這會擴大 CLI 與 INI 的契約面，而問題的根源本來就在後端對映層漏讀一個既有欄位——修在漏讀處才是最小改動。

**替代案（保留為選項，非本次主線）：保留 blur 但加 deadband**（`≤T → 0`、`≥255−T → 255`，T 取 8–16）。實測顯示 blur 產生的灰階有 40.8% 落在 `≤16` 或 `≥239`，在 PWM 255／曝光 8.8 秒下對固化無可分辨作用，卻佔掉約三分之一的 `.sl1` 體積。這在 blur **啟用**時是純賺，但它改變輸出像素，需產品端另行決策，故不綁進本次修復。

既有 spec 的「AA Level 與 Image Blur Pixel 直接複製、不得二次刻度轉換」約束**維持不變**——開關閘控與刻度轉換是正交的兩件事，這一點必須在 spec delta 中寫清楚，避免日後被誤讀為推翻原約束。

### D2：支撐去重採「精確位元比對」，第一版置於 repair 之後

**判定基準：頂點三元組的精確位元相等，不做任何容差合併。** 我們要處理的型態是「完全相同的面被寫了五次」，精確比對足以涵蓋且零誤判風險；容差合併則可能誤刪合法的共面幾何（相鄰支撐柱貼合、底筏與柱腳交界），代價不對稱。

**置放位置的取捨**——這是本變更最關鍵的一個取捨，因為 [TriangleMesh.cpp:218](../../../third_party/prusaslicer_fork/src/libslic3r/TriangleMesh.cpp#L218) `ReadSTLFile()` 的 `repair` 預設為 `true`：

```
作法 A（採用）：ReadSTLFile(repair=true) → 對 indexed_triangle_set 去重
    ✓ 省下 slice_supports（交線段 31.3 M → 6.3 M）
    ✓ 省下 merge_slices 的 diff_ex（每層每柱 5 → 1 個多邊形）
    ✗ 省不到 admesh repair —— 它已在去重前跑完
    ✓ 風險最低：repair 對未知來源網格的保護完整保留

作法 B（暫不採用）：ReadSTLFile(repair=false) → 去重 → 視需要 repair
    ✓ 三項全省
    ⚠ 需確認 stl_generate_shared_vertices() 在 repair=false 下的流程完整性
    ⚠ 失去對其他來源髒網格的保護
```

先做 A。5× 重複會讓每條邊被 10 個面共用，把網格判為非流形，進而觸發 `stl_check_facets_nearby()`（對 486 萬條邊排序，最多兩輪）與 `stl_fix_normal_directions()` 的整圖 BFS——但這部分的實際佔比未經量測。**升級到 B 的條件是量測顯示 repair 佔比顯著**（`trianglemesh_repair_on_import()` 在 `SLIC3R_LOGLEVEL=4` 下有起訖 debug log，加時間戳即可取得）。

**可觀測性是這項改動的一半價值。** 去重必須輸出一行含去重前後面數與倍率的 log，讓未來任何來源的髒網格都留下痕跡，而不是靜靜地讓切片慢五倍。

### D3：去重的「輸出不變」以三條既有機制論證，而非以測試發現

去重不改變任何切片輸出，理由不依賴實驗而是既有程式碼的結構：

- **光柵化輸出**：五個完全重疊的多邊形在 [SLAPrintSteps.cpp](../../../third_party/prusaslicer_fork/src/libslic3r/SLAPrintSteps.cpp) `merge_slices_and_eval_stats()` 的 `union_ex()` / `diff_ex()` 後收斂為一個，光柵化看到的幾何本就相同。
- **樹脂體積**：`resin_volume_ml` 來自聯集後多邊形的 `area()`，非網格體積，現在就是對的。
- **支撐分類**：`has_support_mesh` 與 `supportOutcome` 走 stdout marker（[agent/support_classifier.py](../../../agent/support_classifier.py)），與面數無關。

儘管如此，驗收仍以 D6 的 SHA-256 逐層比對為準——論證決定我們預期什麼，比對決定我們相信什麼。

### D4：preview scale 定為 0.10，濾波維持 box-mean

**縮放比從顯示需求反推**，而非憑感覺：預覽對話框寬度上限 `max-w-[560px]`，扣掉 padding 後 `<img>` 實際渲染約 520 CSS px，DPR 2 需要約 1040 device px。

| scale | 像素寬 | 相對 DPR2 需求 |
|---|---|---|
| 0.25（現況） | 3,780 | 3.6× |
| 0.15 | 2,268 | 2.2× |
| **0.10（採用）** | **1,512** | **1.45×** |
| 0.07 | 1,058 | 1.02×（無餘裕） |

0.15 只把浪費從 3.6× 降到 2.2×，省得不夠多；0.07 沒有餘裕應付未來放大對話框或 4K 螢幕。0.10 留 45% 餘裕。

**濾波維持 box-mean**，依據是把 `.sl1` 的層解回點陣圖後的實測降取樣：

```
第 60 層（支撐區，點亮 0.898%）
  scale 0.25  box-mean 可見(>32)  57,537 px  →  佔預覽面積 0.98%
  scale 0.10  box-mean 可見(>32)  10,535 px  →  佔預覽面積 1.12%   ← 不減反增
  scale 0.10  max      可見(>32)  11,946 px  →  僅比 box 多 11.8%
```

若細特徵會被平均掉，點亮**比例**應該下降；它反而略升，代表細特徵被攤平成整個預覽像素而存活。尺度換算佐證：印表機像素 14 µm，`support_head_front_diameter = 0.4 mm` 在 0.10 下仍有 2.9 個預覽像素、`support_pillar_diameter = 1.0 mm` 有 7.1 個。

**替代案（備案，非本次採用）：改用 max 降取樣。** 它多保留 11.8% 的特徵像素，而且**比 mean 更快**（省掉每個目標像素的一次除法）。但它會讓細部看起來比實際粗，對「目視判斷壁厚」是誤導。維持 box-mean；若日後真有支撐尖端可見度的回饋，這是最便宜的一刀。

### D5：preview 的三項改動是一組，不可只做降 scale

看 [RasterBase.cpp:44](../../../third_party/prusaslicer_fork/src/libslic3r/SLA/RasterBase.cpp#L44) `PNGPreviewEncoder` 的 box filter，成本結構是不對稱的：

```
每個目標像素都要讀完它對應的來源區塊
  → 來源側永遠讀滿 94.2 M 像素          ← 不隨 scale 下降
目標側才會縮小
  → 除法次數      5.88 M → 0.94 M       ← 隨 scale 下降
  → PNG deflate   5.88 MB → 0.94 MB     ← 隨 scale 下降
```

因此**只降 scale 大約只能拿到一半的收益**。三項必須成組：

1. scale 0.25 → 0.10（縮小目標側）
2. miniz 壓縮等級 6 → 1（改用 `tdefl_write_image_to_png_file_in_memory_ex`；近全黑影像本就好壓，體積代價小、速度差數倍）
3. 整數倍（1/N）快路徑（消掉每個目標像素重算 `sx0/sx1/sy0/sy1` 與一次除法）

### D6：raster 重用受三個不變式約束，第一版清整張緩衝

[AGGRaster.hpp:182](../../../third_party/prusaslicer_fork/src/libslic3r/SLA/AGGRaster.hpp#L182) `draw_binary()` 的既有註解寫著「Per-layer raster instances make this race-free」——**重用會直接打破這句話所依賴的前提**。因此：

- **不變式一（執行緒綁定）**：一個 raster 必須綁定一個執行緒（`tbb::enumerable_thread_specific` 或 thread_local）。**不可**使用會被 work-stealing 跨執行緒取用的共享 pool，否則 `draw_binary()` 暫時抽換 gamma LUT 的那段會 race。此約束必須同步更新到該處註解，否則下一個讀者會被誤導。
- **不變式二（第一版清整張）**：`apply_postprocess()` 的 8-byte 快速跳過會掃過整個緩衝，任何未清除的上層殘留像素都是錯誤輸出。第一版清整張即可——這已消除 632 次 94 MB 的 VirtualAlloc 與兩遍歸零中的一遍（`std::vector` 值初始化 + `renderer_base::clear()`），是大部分收益且零正確性風險。dirty-region 部分清除留給後續。
- **不變式三（驗收）**：見下。

**所有純效能改動的驗收標準：`.sl1` 內每一層 `.rle` 的 SHA-256 與改動前完全一致。** 這條線適用於 D2 去重、D6 raster 重用、D5 的整數倍快路徑（對預覽 PNG 而言是 scale 不變時的等價性）。任何一個 bit 不同都代表有 bug，不接受「看起來一樣」。

### D7：blur 重寫優先做「分帶垂直 pass」而非「3×3 特化」

`agg::stack_blur_gray8()` 的垂直 pass 是 column-major（`for x { for y { img.pixel(x,y) } }`），在 stride 15120 的畫布上每個像素一次 cache miss，單層垂直 pass 約 6 GB DRAM 流量。

數學上，`blur=1` 的整套運算（stack blur radius 1 + α 混合 k=154）等價於單一固定 3×3 卷積：

```
stack_blur r=1：div=3, wsum=(1+1)²=4 → 每軸 [1,2,1]/4 → 可分離為 3×3 [[1,2,1],[2,4,2],[1,2,1]]/16
α 混合 k=154：out = (orig×102 + blurred×154) / 256

合併等效 kernel        ┌ 0.0376  0.0752  0.0376 ┐
                       │ 0.0752  0.5488  0.0752 │   總和 = 1.0000
                       └ 0.0376  0.0752  0.0376 ┘
```

儘管 3×3 特化更快（單一 pass、三條 row 指標、工作集 45 KB 常駐 L1、可 SIMD），**優先做分帶垂直 pass**：

| | 分帶垂直 pass（優先） | 3×3 特化（後續） |
|---|---|---|
| 作法 | 一次處理 64 個 column 的整條帶，工作集 64×6230 ≈ 400 KB 常駐 L2 | 重新推導的固定卷積 |
| 效益 | DRAM 流量降約 32× | 再快一個量級 |
| 位元一致性 | **可做到 bit-exact**（同演算法同順序，只改分塊） | 捨入路徑不同，需接受 ±1 差異 |
| 適用範圍 | 所有 radius | 僅 `blur=1`（`blur=2` 需另做 5×5，`blur≥3` 仍需分帶） |

分帶版能落在 D6 的 SHA-256 驗收線內，3×3 特化不能——這個差別決定了順序。3×3 特化若要做，必須另行定義容差驗收（逐像素差 ≤1）並取得產品端同意。

### D8：跨 repo 落地順序有一道硬閘門

前端（DS-Online）的三項不屬本變更，但其中一項與本變更**有順序相依**：

```
DS-Online：移除 WASM PRZ fallback
      │   （現行：downloadPrz 失敗 → 拿 1/4 尺寸預覽圖上採樣 4× 生成列印檔，
      │     且僅有一行 logger.warn）
      ▼
   ═══ 閘門：未完成前，本變更的 preview scale 必須維持 0.25 ═══
      │     （降到 0.10 會讓上採樣倍率由 4× 惡化為 10×）
      ▼
本 repo：preview scale 0.25 → 0.10
```

其餘兩項無順序相依，但需在文件中對齊認知：

- **前端 `exportSupportOnlySTL()` 缺少子節點過濾才是 5× 的根因**（`clippingStencil.buildPasses()` 把 4 個共用同一份 geometry 的 stencil pass 掛在支撐 mesh 底下，而 STLExporter 的 `scene.traverse()` 只看 `object.isMesh`，不看 `visible` 也不看 `userData`）。本變更的後端去重是**防禦網，不是治本**——若日後 stencil pass 改用位移過的 geometry，精確去重就抓不到，錯誤幾何照樣進切片。這個限制必須寫進 log 訊息與 spec，避免被誤認為已解決根因。
- 前端移除 `unzipPreviewFrames()` 後，`preview.zip` 下載失敗只會讓預覽退到 `parsePrz`，切片不受影響——這反而讓本變更的 D9「預覽產出失敗不得使切片失敗」更容易成立。

fork 為 submodule，需獨立 commit 並更新父 repo 的指標；後端 Python 的改動（D1、preview scale 字串）與 fork 的改動要能分別回滾。

### D9：預覽產出失敗不得使切片失敗

現行 `export_preview_zip()` 在 [SLAArchiveWriter.cpp:30](../../../third_party/prusaslicer_fork/src/libslic3r/Format/SLAArchiveWriter.cpp#L30) 會在寫檔失敗時 rethrow。預覽是輔助產物，其失敗不應讓一趟已完成的切片作廢——尤其在降低 scale 後，`model_preview.zip` 缺席時 DS-Online 的 `SlicePreviewDialog` 本就有後端 `parsePrz` 這條退路。此行為納入 `slice-preview-export` 能力的契約。

### D10：量測先行，且不需要改任何程式碼

本變更所有成本拆解皆為靜態分析，尚未端到端實測。實作的第一步是零程式碼改動的 A/B：以現成 binary 對同一份 job 跑 `blur=1` 與 `blur=0`，記錄總秒數、`.sl1` 大小、`_preview.zip` 大小、峰值 RSS。各階段耗時分佈則可對 CLI stdout 的 `NN% => 階段` 進度行加時間戳取得——[agent/jobs.py](../../../agent/jobs.py) 的 `parse_progress_event()` 已在解析這些行，只是沒記時間。

量測結果**不會推翻任何一項的方向**（每一項都是「本來就在做無用功」，與佔比多少無關），但會決定 D2 是否升級到作法 B、以及 D7 的優先序。

## Risks / Trade-offs

- **[blur 修復改變既有輸出]** 未勾選 blur 的使用者，其層圖像素與 `.sl1` 內容會改變。→ 以 `prz_decoder.rle_layer_to_png` 把代表性層（底層筏、灰階最重的第 316 層、頂層）轉 PNG 目視比對，並取得產品端書面確認。這是修正而非退化，但必須是被看見的修正。
- **[去重誤刪合法幾何]** → 採精確位元比對、不做容差合併（D2）；輸出去重前後面數的 log，異常倍率立即可見；以 SHA-256 逐層比對驗收。
- **[raster 重用引入資料競爭]** `draw_binary()` 的 gamma LUT 抽換在跨執行緒重用下會 race。→ 不變式一強制執行緒綁定，並同步更新該處誤導性註解；SHA-256 驗收可捕捉大部分症狀，但**競爭條件不保證每次重現**，因此執行緒綁定必須以型別層面保證（`enumerable_thread_specific`），而非靠約定。
- **[preview 0.10 細特徵不可見]** → 已以實測排除（D4）；備案依序為 max 濾波、回退 0.15。
- **[跨 repo 順序顛倒]** 若 preview scale 先於前端 fallback 移除落地，上採樣倍率由 4× 惡化為 10×。→ D8 的硬閘門；建議把 scale 改動排在跨 repo 驗證通過之後的獨立 commit。
- **[fork submodule 版本漂移]** 本變更同時改 Python 與 fork。→ 兩者分開 commit、分開回滾；父 repo 的 submodule 指標更新獨立成一個 commit。
- **[量測結果與估計出入]** 靜態分析可能高估 blur、低估 mesh 端。→ D10 的量測排在最前，且各項改動彼此獨立、可依實測結果重排順序而不需重做設計。
- **[後端去重被誤認為已解決 5× 根因]** → log 訊息與 spec 明確標示其為防禦網；前端修復列為 [proposal.md](proposal.md) 的跨 repo 相依項並追蹤到底。

## Migration Plan

分四階段，每階段可獨立驗證與回滾：

階段編號與 [tasks.md](tasks.md) 完全一致（0～9），量測記錄亦以同一套編號引用。

| 階段 | 內容 | 決策 | 回滾方式 |
|---|---|---|---|
| 0 | A/B 基準量測，無程式碼改動 | D10 | — |
| 1 | 後端 Python：blur 開關閘控 | D1 | 單一 commit revert |
| 2 | fork：匯入支撐網格去重（作法 A） | D2、D3 | submodule 指標回退 |
| 3 | fork：預覽編碼器（壓縮等級 6→1、整數倍快路徑） | D5 之 2、3 | submodule 指標回退 |
| 4 | fork：預覽產出失敗不得使切片失敗 | D9 | submodule 指標回退 |
| 5 | fork：raster 每執行緒重用 | D6 | submodule 指標回退 |
| 6 | 後端 Python：preview scale 0.25 → 0.10 | D4、D5 之 1 | 單一 commit revert；**受 D8 閘門管制** |
| 7 | fork：blur 後處理分帶重寫 | D7 | submodule 指標回退 |
| 8 | 整合驗證與收尾（commit 切分、端到端、量測彙整、跨 repo 移交） | D8 | — |
| 9 | 不在本變更範圍的記錄事項 | — | — |

- **階段 2、3、4、5、7 為純效能／可用性改動**，每一項都必須通過 SHA-256 逐層比對才可合併（D6 的驗收線）。
- **階段 1 與 6 會改變輸出**，改以目視比對與產品端確認為準。
- **階段 3～5、7 同屬 fork，落在同一個 submodule commit 內**，因此指標回退是整組退掉；若要單獨退某一項，需先在 fork 內 revert 該項再更新指標。
- **階段 6 於本變更未執行**：D8 閘門的三項條件全數未達成，已整批移交至下一個變更。`slice-preview-export` 能力的縮放比 requirement 因此以現行值 `0.25` 立約，避免 spec 描述系統沒有的行為。

## Open Questions

- ~~**D2 是否升級為作法 B（repair 前去重）？**~~ **已由階段 0 量測決議：是，但分兩步落地。** 實測 `support.stl` 的 `trianglemesh_repair_on_import()` 耗時 **3.02 秒**，而面數僅為 `model.stl` 1.75 倍的它，repair 卻慢 **10.6 倍**（model.stl 為 0.28 秒）——超線性成長證實 5× 重複確實把網格推進了非流形修補路徑。3.02 秒佔修好 blur 之後 63 秒基準的 **4.8%**，值得回收。落地方式為：先實作作法 A 並通過逐層 SHA-256 驗收（回收 `Slicing supports` 的約 7 秒），再改為作法 B（額外回收約 2.9 秒），因為 B 需先驗證 `repair=false` 下 `stl_generate_shared_vertices()` 的流程完整性。

  > **階段 2 實作後回填（Task 8.6）。** 作法 A 已落地並通過驗收；**作法 B 尚未實作，仍為未結案項**。以同一支 binary 隔離變因的三方對照（見 tasks.md 階段 2 驗證結果）：
  >
  > | | 總耗時 | 啟動＋載入＋repair | Slicing supports | 峰值 RSS |
  > | --- | --- | --- | --- | --- |
  > | 不去重（5× 原檔） | 63.13 s | 5.89 s | 8.62 s | 2584.6 MB |
  > | Python 預先去重（等同作法 B 的上界） | 53.67 s | 2.13 s | 2.67 s | 1465.3 MB |
  > | 作法 A（引擎內、repair 之後） | 55.08 s | 4.30 s | 3.14 s | 1446.5 MB |
  >
  > 原估計「作法 A 回收約 7 秒、作法 B 再多回收約 2.9 秒」**方向正確、量值需修正**：作法 A 實得約 8.1 秒（63.13 → 55.08），作法 B 的**剩餘** headroom 只有約 **1.4 秒**（55.08 → 53.67），而非 2.9 秒。差距全部落在「啟動＋載入＋repair」（4.30 vs 2.13）——作法 A 仍必須對 5× 網格跑完 admesh repair 才去重，這 2.2 秒是它結構上省不到的，但其中約 0.8 秒被其他階段的雜訊吸收。
  >
  > **據此建議：作法 B 不值得在本變更後續追加。** 1.4 秒佔最終 43.49 秒的 3.2%，卻要承擔「`repair=false` 下 `stl_generate_shared_vertices()` 流程完整性」的驗證成本與非流形網格的行為風險。真正的解在上游——前端修好重複匯出後，這 5× 連同 repair 成本一併消失，屆時作法 A 也只是空轉的防禦網。

- **blur 的實際啟用率是多少？** 這決定 D7 的優先序。階段 0 實測顯示 blur 啟用時的代價遠超原估計：總耗時 **287.97 秒 vs 63.07 秒**，光是 blur 一項就佔 **222 秒（總時間的 78%、光柵化時間的 85%）**。換言之，任何一位勾選 blur 的使用者，其切片時間會是未勾選者的 **4.6 倍**。若啟用率非零，D7 應提前；若確認幾乎無人啟用，方可延後。這需要產品端的使用數據，程式碼裡查不到。

  > **階段 7 實作後回填（Task 8.6）。** D7 已實作完成，**優先序問題因此消解**——不必再等啟用率數據才決定要不要做。但啟用率仍有兩項殘餘意義，故此問題**不關閉**：
  >
  > 1. **兩條路徑的差距仍在。** 分帶重寫後，blur=1 為 176.19 秒、blur=0 為 43.49 秒，倍率由 4.6× 收斂到 **4.05×**。勾選 blur 的使用者體感仍差四倍，這是 D1 deadband 或 dirty-tile 才能再往下壓的部分。
  > 2. **它決定 D1 deadband 的價值。** deadband 只在 blur 啟用時有意義；若啟用率趨近零，該選項可直接結案為「不做」。
  >
  > 另外，階段 1 的閘控修好之後，「啟用率」的定義本身已經改變：此前所有使用者都被強制走 blur 路徑（開關被無視），因此任何早於階段 1 的使用數據都**不能**拿來估計真實啟用意願。

- **是否採納 D1 的 deadband 選項？** 它在 blur 啟用時可省下約三分之一的 `.sl1` 體積且對固化無可分辨影響，但改變輸出像素，需產品端決策。**（未決；記錄於 tasks.md 9.3，不在本變更範圍。其價值取決於上一項的啟用率。）**

- **dirty-tile 稀疏化是否值得另開變更？** 它是唯一能吃到九成空白的手段，但本變更完成後的剩餘 headroom 需以階段 0／2 的實測數字重新評估。

  > **本變更完成後回填（Task 8.6）：headroom 仍然可觀，建議另開變更。** 最終 43.49 秒中，**核心光柵化 28.96 秒仍佔 66.6%**，而畫布逾九成為全黑——這 28.96 秒幾乎全花在掃描空白。階段 3 的量測另外給出一個獨立佐證：即使把預覽縮放比降到 0.10 並加上快路徑，預覽成本也只降到約 7.4 秒就觸底，因為**來源側必須讀滿 94.2 M 像素**是不隨 scale 下降的固定成本。換言之，光柵化與預覽兩邊的剩餘成本都由「掃描整張畫布」主導，這正是 dirty-tile 唯一能吃到、而本變更任何一項都吃不到的部分。