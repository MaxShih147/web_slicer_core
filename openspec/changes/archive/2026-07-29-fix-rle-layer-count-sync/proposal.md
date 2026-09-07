## Why

自 `[layer-rle]`（commit `f9bccb9`）起，切片器以 `SLA_LAYER_RLE=1` 將層輸出為 `model#####.rle` 而非 `.png`，但 `parse_sl1_metadata()` 仍只統計 `.png`，導致層數恆為 `0`。這使 `print-time-sync`（commit `8501569`）的守衛 `if not total_layers: return fallback` 恆為真——列印時間同步**靜默失效**，`estimatedPrintTime` 永遠退回 fork SL1 估值；因 fork 估值與 PRZ 物理公式結構不同（前者吃每層投影面積），多物件切片時落差被放大而被使用者察覺。同一根因也使 `layerCount` API 一律回 `0`，且單層端點 `/layers/{idx}.png` 在 RLE 模式恆回 `None`。

## What Changes

- 新增單一真值來源 helper `sl1_layer_names()`：以嚴格正則 `^model\d{5}\.(rle|png)$` 列舉 .sl1 層檔（`.rle` 優先，否則 `.png`），排除 `thumbnail/` 子目錄縮圖污染層數。
- `parse_sl1_metadata()` 改用 `sl1_layer_names()` 計層數，使 RLE 模式下層數正確、`print-time-sync` 得以正常啟動。
- `get_layer_png_from_sl1()` 支援 `.rle` 單層即時解碼；抽出共用的單層解碼 helper，失敗（缺 `prusaslicer.ini` / `display_pixels` 解析失敗）時回 `None`，維持既有「上層轉 404」契約。
- PRZ 編碼端（`encode_prz_streaming` / `encode_prz`）改用同一 `sl1_layer_names()`，消除層檔列舉邏輯分歧；正常 .sl1 上選出集合不變，PRZ 輸出保持 byte-identical。
- 時間精度採**選項 A**：`status.json` 維持 float，接受與 PRZ header（`int()` 截斷）`0 ≤ 差 < 1s` 的落差（前端格式化後無感），不新增轉型邏輯。

## Capabilities

### New Capabilities
- `sl1-layer-access`: .sl1 層檔的統一列舉與單層取用能力——嚴格檔名過濾、`.rle`/`.png` 一致的層數統計、單層 PNG 即時解碼（RLE 解碼 + 失敗回 `None`），作為 print-time 同步與 `layerCount`／`/layers/{idx}.png` API 的共同來源。

### Modified Capabilities
- `print-time-sync`: `total_layers` 來源明確為「實際層數（不論 RLE 或 PNG）」；新增回歸保證——RLE 模式下同步仍正確啟動，API 值等於公式值而非 fork 估值。

## Impact

- 程式碼：[agent/prz_encoder.py](../../../agent/prz_encoder.py)（新增 `sl1_layer_names()`、抽出單層解碼 helper、兩個 encode 路徑改用）、[agent/jobs.py](../../../agent/jobs.py)（`parse_sl1_metadata` / `get_layer_png_from_sl1`）、[agent/api_v2.py](../../../agent/api_v2.py)（`_rle_sl1_to_png_zip` 可選共用）。
- API 行為：`GET /api/v2/slices/{id}` 的 `estimatedPrintTime` 與 `layerCount` 由「恆退回 / 恆 0」修正為真實值；`/layers/{idx}.png` 在 RLE 模式可正確回圖。無 API 介面破壞。
- 相容性：切片器仍輸出 `.png` 的部署行為不變（helper 退回 `.png`）；PRZ 二進位輸出 byte-identical。
- 測試：擴充 [agent/tests/test_jobs_sync.py](../../../agent/tests/test_jobs_sync.py) 與層檔列舉／縮圖污染／單層解碼失敗案例。
- 前綴耦合注意：正則 `model` 前綴綁定固定輸出 `output/model.sl1`（[agent/jobs.py](../../../agent/jobs.py)）；日後改輸出名須同步更新。