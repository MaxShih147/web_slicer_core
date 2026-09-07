## Why

目前切片送印流程中，config 被傳了**三次、兩種型態**（`POST /slices` 傳空 config + mechado、`PUT /config` 又傳 snake config + mechado、`download.prz` 再傳一次 mechado）。前端從同一份 `uiParams` 跑出兩條獨立衍生路徑（snake 與 mechado），冗餘且容易漂移；又因後端既有萃取器只讀 `Print` 區段，若直接餵完整 mechado，`Machine` / `Advanced` 區段的切片參數會被**靜默丟棄退回預設值**。本變更要把流程收斂為「前端只送一份 mechado config，後端成為唯一萃取真相來源（方案 B：單一真相）」。

## What Changes

- **方案 B（單一真相）**：新增後端萃取器 `_extract_sla_from_mechado()`，由後端從完整 mechado config 萃取 `SLAConfig` 切片參數；前端正常流程不再自行計算並傳送 snake-case 切片 config。
- **`POST /api/v2/slices`**：以完整 mechado config 作主要輸入；**新增獨立頂層欄位 `center: Optional[List[float]]`**（per-job 幾何值，不污染 mechado profile）。`printer_model` 不再另傳，改由後端從 `Machine.machine_type` 萃取。
- **`Bed Size` 索引標準釘定**：`display_width = bed_size[2]`、`display_height = bed_size[3]`；`image_size` 取 `[0][1]`。修正既有 `_convert_v2_config_to_sla` 取 `[0][1]` 的錯誤（新萃取器不沿用）。
- **刻度防呆**：`Anti-aliasing Level`、`Image Blur Pixel` 在 mechado 中已是後端刻度，後端**直接複製、禁止二次轉換**。
- **萃取時機與優先權**：萃取延後至 execute；`extract_from_mechado(mechado)` 為 base，`PUT /config` 送入的 snake config 採**欄位級覆蓋**（last-write-wins）。
- **`POST /api/v2/slices/{id}/download.prz`**：config body 與 preview 圖片改為 **optional**；缺 config 時 fallback 讀取 job 已持久化的 `prz_config.json`。
- **`PUT /api/v2/slices/{id}/config`**：保留供特例使用，正常流程不再需要（非 **BREAKING**，舊前端流程仍有效）。

## Capabilities

### New Capabilities
- `slice-config-intake`: 切片 job 的 config 接收與萃取流程——`POST /slices` 的請求結構（mechado + 頂層 center）、後端單一真相萃取器（mechado → SLAConfig，含 Bed Size 索引標準與刻度防呆）、execute 階段的 base/override 合併優先權、以及 `download.prz` 的 optional config/preview fallback。

### Modified Capabilities
<!-- 無：SLAConfig 本身的欄位行為與 sla-slice-config 既有需求不變，本變更僅改變「config 如何進入系統與如何被萃取」，不改變 SLAConfig 欄位語意。 -->

## Impact

- **後端 web_slicer_core**：
  - [agent/api_v2.py](agent/api_v2.py)：`V2SliceCreateRequest` 新增 `center` 欄位；新增 `_extract_sla_from_mechado()`；execute 合併邏輯；`download.prz` 改 optional + fallback。
  - [agent/jobs.py](agent/jobs.py)：execute 階段 SLAConfig 最終組裝與既有 `prz_config.json` 持久化的銜接。
  - 既有 `_convert_v2_config_to_sla()` 維持不動（保舊前端 snake 直讀路徑）。
- **前端 DS-online**：`slicingService.js` 改為 `POST /slices` 帶 `prz_config=mechado` + `center`，移除正常流程的 `PUT /config` snake config 呼叫；`download.prz` 不再強制帶 config。`uiToBackendSlicingConfig` 可留作過渡。
- **相容性承諾**：舊前端流程（`POST` 空 config → `PUT` snake config → `execute`）SHALL 100% 維持有效，切片結果與變更前一致；本變更非破壞性。