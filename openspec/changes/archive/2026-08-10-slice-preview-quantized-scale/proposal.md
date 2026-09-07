## Why

切片預覽的縮放比目前是一個與消費端無關的硬寫常數 `--export-preview-pngs 0.25`，散落在兩個呼叫點加一個 Python 函式預設值。它在機隊的兩端同時出錯：

**超大型機台過度取樣。** DS-Online 的 `SlicePreviewDialog` 寬度上限 560 CSS px，扣除內距後 `<img>` 實際渲染約 520 CSS px，DPR 2 下需要約 1040 device px。16K 機台（15120 × 6230）在 `0.25` 下產出 3780 px 寬——需求的 3.6 倍。前一個變更 `optimize-slice-performance` 已在同一支引擎上實測過降到 `0.10` 的收益：`preview.zip` **27.38 → 11.91 MB（−56%）**、預覽處理 **9.02 → 7.39 秒（−18%）**。這是每一趟 16K 切片都在白付的傳輸與運算開銷。

**但一律硬改 `0.10` 會讓中小幅面畫質崩塌。** 同一個 `0.10` 套到 5760 幅面只剩 576 px、3840 幅面只剩 384 px，遠低於同一份推導所要求的 1040 device px。`optimize-slice-performance` 的 design D4 之所以能論證 `0.10` 成立，是因為它整張表**只算了 15120 這一種幅面**；判準本身（1040 device px）套到其他機台時，`0.10` 反而是不及格的。

**根因是旋鈕選錯了。** 顯示需求是一個**絕對像素寬**，縮放比卻是一個**比例**。任何單一固定比例都必然在「大機台不浪費」與「小機台不糊掉」之間二選一，涵蓋 2560 ~ 15120 的機隊做不到兩者兼顧。

**時機。** 降低縮放比原受 `optimize-slice-performance` design D8 的跨 repo 硬閘門管制（DS-Online 在 `downloadPrz` 失敗時會拿預覽圖上採樣生成列印用 PRZ，降低縮放比會讓上採樣倍率由 4× 惡化為 10×）。前端 Change B `remove-wasm-prz-fallback` 已於 2026-08-07 封存，該降級路徑徹底移除並補上 2 次指數退避重試，**閘門已解除**。

## What Changes

- **新增 `agent/preview_scale.py`**：`preview_scale_for(long_side_px)` 作為預覽縮放比的**單一真值來源**。以幅面長邊為判準，動態量化吸附至 C++ 引擎快路徑集合 `N ∈ {4, 5, 8, 10}`；規則為「取最大的 N 使 `long_side / N ≥ 1400`」，找不到符合者則退回 `N = 4`。**`N = 4`（`0.25×`）同時是天花板與無 config 時的退路**，確保任何機台的預覽畫質都不會比今日更差。

- **接入兩條引擎產線**：主路徑 `agent/jobs.py` 的 `run_slicing()`（含 `config is None` 的 `N = 4` 退路）與第二路徑 `agent/sla_operations.py` 的 `slice_model()`，兩處硬寫的 `"0.25"` 改由 helper 決定。

- **收斂 `agent/preview_service.py` 備援產線**（三項）：
  - 縮放比改由同一個 helper 決定，移除 `scale: float = 0.25` 預設值；
  - 降取樣濾波由 PIL `BILINEAR`（三角權重）改為 `Image.BOX`（box-mean 的精確對應），使 `slice-preview-export` 的 box-mean 契約對兩條產線同時成立；
  - **修正 RLE 模式下產出空 ZIP 並永久快取的缺陷**——主路徑以 `SLA_LAYER_RLE=1` 執行時 `.sl1` 內只有 `model#####.rle`，而現行實作只挑 `.png`，結果是空 ZIP 被 `if output_path.exists(): return` 永久快取。此缺陷先於本變更即存在。

- **補強單元測試**：量化器表格斷言（全機隊 → 期望 N 與預覽寬、`N ≥ 4`、`N ∈ {4,5,8,10}`）、**浮點倒數精確性防護**（守 `RasterBase.cpp` 的 `inv_scale == (double)n` 閘門，不成立時快路徑會靜默退回通用路徑、不報錯不寫 log 只變慢）、呼叫點原始碼下鎖防止硬編碼回流、RLE 模式備援產線非空斷言。

- **修訂文件**：`openspec/specs/slice-preview-export/spec.md` 的縮放比 requirement 由「固定值 `0.25`」改為動態量化函式；清除 `README.md:548` 的過期 TODO（`generate_config_ini()` 早已全欄位傾印，`display_*` 都有寫進 INI）。

## Capabilities

### New Capabilities

（無）本變更不引入新能力。

### Modified Capabilities

- `slice-preview-export`：縮放比 requirement 由「現行值 SHALL 為 `0.25`」改為「SHALL 由幅面長邊經量化函式決定」。同時處理該 spec 內既有的三項升級落地條件（其中「DS-Online 移除 WASM fallback」已達成），並新增 `N = 4` 天花板、無 config 退路、備援產線 Known Difference 等契約條款。

## Impact

**受影響程式碼**

| 檔案 | 性質 |
| --- | --- |
| `agent/preview_scale.py` | 新增 |
| `agent/jobs.py` | 主引擎路徑接入 |
| `agent/sla_operations.py` | 第二引擎路徑接入 |
| `agent/preview_service.py` | 備援產線三項收斂 |
| `agent/tests/` | 新增量化器、浮點精確性、呼叫點契約、RLE 備援等測試 |
| `openspec/specs/slice-preview-export/spec.md` | requirement 改寫 |
| `README.md` | 清除過期 TODO |

**發版後的全機隊落點**

| 機台 | 長邊 | 今日 | N | 新預覽寬 | 變化 |
| --- | --- | --- | --- | --- | --- |
| 預設組態 | 2560 | 640 | 4 | 640 | 無 |
| sonic_4k_2022 | 3840 | 960 | 4 | 960 | 無 |
| sonic_ls_plus | 3840 | 960 | 4 | 960 | 無 |
| 5760 幅面 | 5760 | 1440 | 4 | **1440** | **無** |
| sonic_cs_plus | 7536 | 1884 | 5 | 1507 | 面積 0.64× |
| 16K (15120×6230) | 15120 | 3780 | 10 | 1512 | 面積 0.16× |

實質只有 7536 與 15120 兩種機台的輸出會改變；3840 級與 5760 機台逐位元組相同。

**對前端 DS-Online 的連動回覆**（Change B `remove-wasm-prz-fallback` Task 5.6）

- **撤銷 5760 機台的品質疑慮警語。** Task 5.6 記載的「5760×3600 單張預覽自 1440×900 降至 576×360，屬可見的 UI 品質變更」在量化機制下**不會發生**——5760 / 4 = 1440 ≥ 1400，N 停在 4，與今日完全相同、畫質零退化。
- **效益數字更正為誠實值。** 正確表述為「`preview.zip` −56%、預覽處理時間 −18%」（基準：16K 機台、新引擎）。**不是**「體積與時間皆省約 60%」——`optimize-slice-performance` design D5 已論證，剩餘約 7.4 秒是來源側必須讀滿 94.2 M 像素的固定成本，不隨縮放比下降。
- **目視畫質驗收 MUST 指定於 16K 機台執行。** 3840 級機台的輸出逐位元組相同，在其上驗收會必然通過但毫無資訊量。

**不受影響**

`_prz_sessions`（PRZ 上傳解析檢視器 session）與 `download.prz` 的 `StreamingResponse` **完全不經過預覽縮放比**——前者讀 `.prz` 內嵌縮圖，後者串 `.sl1` 全解析度層檔。列印檔的位元組輸出不受本變更影響。

**Non-Goals / Known Differences**

- **備援產線的檔名與編碼格式維持現狀，不強制統一。** 引擎產線寫出 `model_preview00000.png`（PNG，miniz level 1），備援產線寫出 `0.webp`（WebP，quality 80），兩者由同一端點以相同 `filename="preview.zip"` 送出。統一會牽動 DS-Online 的解壓邏輯，屬另一次跨 repo 連動，不納入本變更。改以在 spec 明文記載為 Known Difference：消費端 MUST 以 ZIP 內實際 entry 名稱與副檔名為準。
- **不修正 3840 級機台低於 1040 device px 判準這件事。** 明文接受 `N = 4` 為量化下限。要改善只能把 `1/2`、`1/3` 納入集合，那會讓 3840 機台的 `preview.zip` 反向膨脹為今日的 4 倍，與降本目標直接衝突。
- **不動 C++ fork。** 本變更僅使用引擎既有的 `--export-preview-pngs` 介面與既有的 1/N 快路徑，`third_party/prusaslicer_fork` 無需改動或重新編譯。
- **不改進降取樣濾波演算法本身。** box-mean 維持不變（`optimize-slice-performance` design D4 已以實測支持其在 `0.10` 下仍保留支撐特徵）；本變更只是讓備援產線也真正符合這個契約。
