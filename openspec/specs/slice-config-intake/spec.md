# slice-config-intake Specification

## Purpose

定義切片 job 的 config 接收與萃取流程：`POST /slices` 的請求結構（完整 mechado config + 頂層 center）、後端單一真相萃取器（mechado → SLAConfig，含 Bed Size 索引標準與刻度防呆）、execute 階段的 base/override 合併優先權、以及 `download.prz` 的 optional config/preview fallback。目標是讓前端只送一份 mechado config，後端成為唯一的切片參數萃取真相來源。
## Requirements
### Requirement: 後端從完整 mechado config 萃取 SLAConfig 切片參數

系統 SHALL 提供 `_extract_sla_from_mechado()`，從三段式（`Machine` / `Print` / `Advanced`）的完整 mechado config 萃取出 `SLAConfig` 所需的切片參數。萃取 SHALL 涵蓋 `Machine` 與 `Advanced` 區段（非僅 `Print`）。其中 `display_width` SHALL 取自 `Machine.bed_size[2]`、`display_height` SHALL 取自 `Machine.bed_size[3]`；`display_pixels_x/y` SHALL 取自 `Machine.image_size[0]/[1]`。`Advanced.Anti-aliasing Level` 與 `Advanced.Image Blur Pixel` 在 mechado 中已為後端刻度，萃取時 SHALL 直接複製、MUST NOT 再套任何 UI→backend 刻度轉換。`printer_model` SHALL 取自 `Machine.machine_type`。任一來源欄位缺失時，該欄位 SHALL 留給 `SLAConfig` 預設值且 MUST NOT 拋錯。

`blur` 的取值 SHALL 額外受 `Advanced."Image Blur"` 布林開關閘控，採三態語意：

| `Advanced."Image Blur"` | `blur` 取值 |
| --- | --- |
| `false` | SHALL 為 `0`（覆寫 `Image Blur Pixel`，不論其值為何） |
| `true` | SHALL 直接複製 `Image Blur Pixel` |
| 鍵不存在 | SHALL 直接複製 `Image Blur Pixel`（向後相容） |

> **NOTE（開關閘控與刻度轉換正交）**：`Advanced."Image Blur"` 是**啟用與否**的開關，`Advanced."Image Blur Pixel"` 是**強度刻度**。閘控只決定「要不要套用」，MUST NOT 被解讀為對刻度做任何轉換——「直接複製、不得二次刻度轉換」的原有約束在開關為 `true` 或缺失時完全不變。

> **NOTE（AA Level 顯示值 vs 控制值，本變更範圍邊界）**：此處萃取的 `anti_aliasing_level` 為**切片控制值（Prusa 刻度 0/1/2）**，僅供 `SLAConfig` 與底層 prusa_slicer_fork 使用，**不代表也不負責** PRZ 最終呈現給使用者的顯示內容。DS-online 網頁的使用者選項為顯示刻度 `2/4/8`，且前端在寫入 mechado 時已壓成控制刻度 `0/1/2`。「在 PRZ 顯示原始值 2/4/8」屬未來需求，本變更不處理（見 design.md「Future Works FW1」）。

#### Scenario: 完整 Machine/Advanced 萃取出正確數值
- **WHEN** 收到 mechado config 含 `Machine.bed_size = [0.0, 0.0, 134.0, 75.0]`、`Machine.image_size = [3840, 2160]`、`Machine.machine_type = "sonic_4k_2022"`、`Print.Layer Height = 0.05`、`Advanced.Anti-aliasing Level = 2`、`Advanced.Grey Level = 0`、`Advanced.Image Blur Pixel = 1`（未含 `Advanced."Image Blur"` 鍵）
- **THEN** 萃取結果 SHALL 為 `display_width == 134.0`、`display_height == 75.0`（取 `bed_size[2]`/`[3]`，非 `[0]`/`[1]`）
- **AND** `display_pixels_x == 3840`、`display_pixels_y == 2160`
- **AND** `layer_height == 0.05`、`printer_model == "sonic_4k_2022"`
- **AND** `anti_aliasing_level == 2`（直接複製後端刻度，未被轉成 8 或其他值）
- **AND** `gray_level == 0`、`blur == 1`（開關鍵缺失 → 直接複製，向後相容）

#### Scenario: AA Level 不得二次轉換
- **WHEN** mechado `Advanced.Anti-aliasing Level == 1`（後端刻度）
- **THEN** 萃取出的 `anti_aliasing_level` SHALL 等於 `1`
- **AND** 該值 MUST NOT 被 `antiAliasingLevelUiToBackend` 或任何刻度轉換改動（不得變成 4 或 0）

#### Scenario: mechado 缺欄位退回預設且不報錯
- **WHEN** mechado config 缺少 `Advanced` 整個區段
- **THEN** 萃取 SHALL 成功（不拋錯）
- **AND** `anti_aliasing_level`、`gray_level`、`blur` SHALL 等於 `SLAConfig` 對應欄位的預設值

#### Scenario: Image Blur 開關為 false 時 blur 歸零
- **WHEN** mechado config 含 `Advanced."Image Blur" = false` 且 `Advanced."Image Blur Pixel" = 1`
- **THEN** 萃取出的 `blur` SHALL 等於 `0`
- **AND** `generate_config_ini()` 寫出的 INI SHALL 含 `blur = 0` 一行
- **AND** `anti_aliasing`、`anti_aliasing_level`、`gray_level` MUST NOT 受此開關影響

#### Scenario: Image Blur 開關為 false 時忽略任何非零強度
- **WHEN** mechado config 含 `Advanced."Image Blur" = false` 且 `Advanced."Image Blur Pixel" = 3`
- **THEN** 萃取出的 `blur` SHALL 等於 `0`（開關優先於強度，MUST NOT 取 `3`）

#### Scenario: Image Blur 開關為 true 時維持直接複製
- **WHEN** mechado config 含 `Advanced."Image Blur" = true` 且 `Advanced."Image Blur Pixel" = 2`
- **THEN** 萃取出的 `blur` SHALL 等於 `2`（直接複製，MUST NOT 套用任何刻度轉換）

### Requirement: center 位移換算保證「UI 擺放 = 圖檔位置」

`POST /api/v2/slices` SHALL 接受獨立頂層欄位 `center: Optional[List[float]]`（per-job 幾何位移）。萃取時若提供 `center = [x, y]`，最終 `SLAConfig.center_x` SHALL 等於 `center[0] + display_width / 2`、`center_y` SHALL 等於 `center[1] + display_height / 2`，其中 `display_width`/`display_height` 來自同一份 mechado 的 `bed_size[2]`/`[3]`。`center` MUST NOT 被寫入 mechado config 內部（保持 profile 純淨）。

#### Scenario: center 換算為絕對座標
- **WHEN** `center = [10.0, -5.0]` 且 mechado `bed_size = [0.0, 0.0, 134.0, 75.0]`
- **THEN** `SLAConfig.center_x` SHALL 等於 `77.0`（`10 + 134/2`）
- **AND** `SLAConfig.center_y` SHALL 等於 `32.5`（`-5 + 75/2`）

#### Scenario: 未提供 center 時不覆寫預設
- **WHEN** `POST /slices` 未提供 `center` 欄位
- **THEN** 萃取結果 MUST NOT 含 `center_x` / `center_y`
- **AND** `SLAConfig` 的 `center_x` / `center_y` SHALL 使用其預設值（顯示中心）

### Requirement: execute 以 mechado 萃取為 base、snake config 欄位級覆蓋

`execute_slice_job` SHALL 以 `_extract_sla_from_mechado(prz_config, center)` 結果為 base，再以 `PUT /config` 傳入的 snake-case config 進行**欄位級覆蓋**（last-write-wins），組裝最終 `SLAConfig`。只送 mechado 的新流程 SHALL 得到純萃取結果；缺 mechado 而僅有 snake config 的舊流程 SHALL 與變更前 `_convert_v2_config_to_sla(snake)` 行為一致。

#### Scenario: 新流程只送 mechado
- **WHEN** job 僅有 `prz_config`（mechado）與 `center`、無 `PUT /config` 的 snake config
- **THEN** 最終 `SLAConfig` SHALL 完全來自 mechado 萃取結果
- **AND** 切片 SHALL 正常啟動

#### Scenario: PUT snake config 欄位級覆蓋 mechado 萃取
- **WHEN** mechado 萃取得 `layer_height == 0.05`，且其後 `PUT /config` 送入 `{"layer_height": 0.10}`
- **THEN** 最終 `SLAConfig.layer_height` SHALL 等於 `0.10`（PUT 覆蓋 POST 萃取）
- **AND** 其餘未被 snake config 提供的欄位 SHALL 維持 mechado 萃取值

#### Scenario: 舊前端流程相容
- **WHEN** 舊前端流程為 `POST`（空 config、無 mechado）→ `PUT`（snake config）→ `execute`
- **THEN** 最終 `SLAConfig` SHALL 與變更前由 `_convert_v2_config_to_sla(snake)` 產生的結果一致
- **AND** API MUST NOT 因新增 `center` 欄位而對舊請求回傳 422 或其他錯誤

### Requirement: download.prz 的 config 與 preview 改為 optional 並支援降級

`POST /api/v2/slices/{id}/download.prz` SHALL 接受空的或省略的 config body 與 preview。當 body 未提供 config 時，系統 SHALL 從該 job 已持久化的 `prz_config.json` 讀取 mechado config 來生成 PRZ。當 body 顯式提供 config 時，SHALL 以 body 為優先。preview 圖片未提供時 SHALL 沿用既有預設行為而不致失敗。

#### Scenario: body 為空時從 prz_config.json 降級生成
- **WHEN** job 已完成切片且存在 `prz_config.json`，而 `download.prz` 的 request body 為空（未提供 config）
- **THEN** 系統 SHALL 從 `prz_config.json` 讀取 mechado config
- **AND** SHALL 成功生成並回傳 PRZ 檔案
- **AND** PRZ 的 print-time 與位置參數 SHALL 與該 mechado 一致

#### Scenario: body 顯式提供 config 時以 body 為優先
- **WHEN** `download.prz` 的 request body 顯式提供完整 mechado config
- **THEN** 系統 SHALL 以 body 的 config 生成 PRZ（不使用 `prz_config.json`）

#### Scenario: 缺 preview 不致失敗
- **WHEN** `download.prz` 未提供 `preview_small` / `preview_large`
- **THEN** PRZ 生成 SHALL 成功完成（沿用既有預設 preview 行為）

### Requirement: 舊版扁平 config 轉換亦須尊重 Image Blur 開關

`_convert_v2_config_to_sla()`（舊前端流程使用的扁平 DS-Online config 轉換器）SHALL 與 `_extract_sla_from_mechado()` 採用**相同的三態閘控語意**處理 `blur`：頂層鍵 `"Image Blur"` 為 `false` 時 `blur` SHALL 為 `0`；為 `true` 或鍵不存在時 SHALL 直接複製 `"Image Blur Pixel"`。

兩個轉換器對同一組輸入語意 MUST NOT 產生不一致的 `blur` 值——否則 `execute_slice_job` 的「base(mechado) ← override(snake)」合併會依請求順序產生不可預期的結果。

#### Scenario: 扁平 config 的開關為 false
- **WHEN** 扁平 config 含 `{"Image Blur": false, "Image Blur Pixel": 1}`
- **THEN** 轉換出的 `SLAConfig.blur` SHALL 等於 `0`

#### Scenario: 扁平 config 未帶開關鍵時行為不變
- **WHEN** 扁平 config 含 `{"Image Blur Pixel": 1}` 而未含 `"Image Blur"` 鍵
- **THEN** 轉換出的 `SLAConfig.blur` SHALL 等於 `1`（與本變更前行為一致）

#### Scenario: 兩個轉換器對同一語意產生相同結果
- **WHEN** 以語意等價的輸入分別餵給 `_extract_sla_from_mechado()`（`Advanced."Image Blur" = false`、`Advanced."Image Blur Pixel" = 1`）與 `_convert_v2_config_to_sla()`（`{"Image Blur": false, "Image Blur Pixel": 1}`）
- **THEN** 兩者輸出的 `blur` SHALL 相等

