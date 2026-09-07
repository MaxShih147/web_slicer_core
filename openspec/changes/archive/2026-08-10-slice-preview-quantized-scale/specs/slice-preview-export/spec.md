## MODIFIED Requirements

### Requirement: 預覽層圖的縮放比須由消費端顯示需求決定

`--export-preview-pngs` 的縮放比 SHALL 依據預覽消費端的實際顯示尺寸決定，而非任意選定。**縮放比 SHALL 由印表機幅面長邊經一個量化函式決定，不得為硬寫常數。**

量化函式的契約：

```
輸入   long_side_px = max(display_pixels_x, display_pixels_y)
目標   TARGET_WIDTH_PX = 1400
集合   ALLOWED_N = (4, 5, 8, 10)
規則   N = max{ n ∈ ALLOWED_N : long_side_px / n >= TARGET_WIDTH_PX }
退路   上式無解時 N = 4
輸出   (scale_str, N)，scale_str ∈ {"0.25", "0.2", "0.125", "0.1"}
```

四項約束：

1. **長邊判準。** 輸入 SHALL 為 `max(display_pixels_x, display_pixels_y)`，MUST NOT 直接採用 `display_pixels_x`。理由：引擎在 `display_orientation = portrait` 時會交換像素維度，`max` 對該交換不變、恆等於 raster 長邊。
2. **`N = 4` 為天花板。** 量化函式 MUST NOT 回傳小於 4 的 N。此下限保證任何機台的預覽解析度都不低於本變更前的 `0.25`，即畫質永不退化。
3. **僅限快路徑成員。** `ALLOWED_N` 的每個成員 SHALL 使其 `scale_str` 滿足 `1.0 / float(scale_str)` 位元級等於該整數，以確保引擎的固定區塊快路徑必然啟用。
4. **單一真值來源。** 所有需要決定預覽縮放比的呼叫點 SHALL 取自同一個函式；原始碼中 MUST NOT 出現硬寫的縮放比字面量。

依據：DS-Online 的預覽對話框寬度上限為 560 CSS px，扣除內距後 `<img>` 實際渲染約 520 CSS px，在 DPR 2 的螢幕上需要約 1040 device px。目標值取 1400 而非 1040，是為了在離散量化的落點上保留餘裕。

> **關於 `N = 4` 天花板的已知取捨**：長邊 3840 的機台在天花板保護下停留於 960 px 預覽寬，低於上述 1040 device px 的推導需求。此缺口為**明文接受的取捨**，不視為待辦：要消除它只能將 `1/2`、`1/3` 納入 `ALLOWED_N`，那會使該級機台的 `preview.zip` 膨脹為原本的 4 倍，與本能力降低預覽成本的目的直接衝突。
>
> **關於 `N = 8`**：該成員只在長邊落於 [11200, 14000) 時被選中，目前機隊無此規格機台。它是合法的保留枝，驗證 MUST NOT 以「每個 N 都須有實機命中」作為判準。

#### Scenario: 16K 幅面選中 N=10

- **WHEN** 印表機幅面為 15120 × 6230
- **THEN** 量化函式 SHALL 回傳 `N = 10`、`scale_str = "0.1"`
- **AND** 每張預覽影像的尺寸 SHALL 為 1512 × 623
- **AND** 該寬度 SHALL 不小於消費端在 DPR 2 下所需的 1040 px

#### Scenario: 中幅面機台選中 N=5

> 本場景的期望值由量化規則與引擎快路徑閘門推導而得（`7536 / 5 = 1507.2 → 1507`，`1507 × 5 = 7535 ≤ 7536`；`3240 / 5 = 648`，`648 × 5 = 3240 ≤ 3240`），**尚未經真機實測**。體積與時間的實測數據目前僅涵蓋 15120 幅面。本場景以推導立約，實測補齊前 SHALL 以單元測試驗證尺寸推導，不得以「缺實測」為由放寬。

- **WHEN** 印表機幅面為 7536 × 3240
- **THEN** 量化函式 SHALL 回傳 `N = 5`、`scale_str = "0.2"`
- **AND** 每張預覽影像的尺寸 SHALL 為 1507 × 648

#### Scenario: 小幅面機台受 N=4 天花板保護

- **WHEN** 印表機幅面為 5760 × 3600、3840 × 2400 或 2560 × 1440
- **THEN** 量化函式 SHALL 一律回傳 `N = 4`、`scale_str = "0.25"`
- **AND** 預覽影像尺寸 SHALL 分別為 1440 × 900、960 × 600、640 × 360
- **AND** 該輸出 SHALL 與本變更前的輸出逐位元組相同

#### Scenario: portrait 幅面以長邊為判準

- **WHEN** 組態的 `display_pixels_x` 小於 `display_pixels_y`（例如 6230 × 15120）
- **THEN** 量化函式 SHALL 以 15120 作為輸入
- **AND** 回傳結果 SHALL 與 15120 × 6230 的情形相同

#### Scenario: 無組態時退回天花板值

- **WHEN** 切片作業未提供組態（因而未傳 `--load`，引擎採用內建預設 preset，Python 端無從得知幅面）
- **THEN** 系統 SHALL 以 `N = 4`、`scale_str = "0.25"` 執行
- **AND** MUST NOT 中止切片或回報錯誤

#### Scenario: 允許集合的每個成員都命中快路徑

- **WHEN** 取 `ALLOWED_N` 中任一成員 N 及其對應的 `scale_str`
- **THEN** `1.0 / float(scale_str)` SHALL 位元級等於 `float(N)`
- **AND** 對機隊中任一幅面 `w × h`，`int(w * float(scale_str)) * N` SHALL 不大於 `w`，`int(h * float(scale_str)) * N` SHALL 不大於 `h`

#### Scenario: 縮放比為 0 時不產生預覽

- **WHEN** `--export-preview-pngs` 的值為 `0` 或未提供該選項
- **THEN** 系統 MUST NOT 產生任何預覽影像
- **AND** MUST NOT 產生 `*_preview.zip`

### Requirement: 預覽降取樣採區塊平均，並提供整數倍快路徑

預覽降取樣 SHALL 採用區塊平均（box mean）：每個目標像素的值 SHALL 為其對應來源區塊內所有像素的算術平均。系統 MUST NOT 改用取最大值（max）或其他會使細特徵在視覺上變粗的濾波，以免使用者以預覽目視判斷壁厚時被誤導。

**此濾波語意 SHALL 適用於所有產出預覽層圖的產線**，包含引擎產線與 Python 備援產線。備援產線 MUST NOT 使用三角權重或其他非均勻權重的重取樣濾波。

當縮放比為整數分之一（`1/N`，N 為正整數）時，系統 SHALL 走固定 `N × N` 區塊的快路徑，避免對每個目標像素重複計算來源區塊邊界與執行除法。快路徑的輸出 SHALL 與通用路徑**逐位元組相同**。

#### Scenario: 整數倍快路徑與通用路徑輸出一致

- **WHEN** 縮放比為 `0.10`（即 `1/10`），對同一張來源點陣圖分別以快路徑與通用路徑降取樣
- **THEN** 兩者產生的目標點陣圖 SHALL 逐位元組相同

#### Scenario: 非整數倍縮放比仍走通用路徑

- **WHEN** 縮放比為 `0.15`（非 `1/N`）
- **THEN** 系統 SHALL 走通用路徑
- **AND** 輸出 SHALL 與本變更前的通用路徑結果相同

#### Scenario: 細支撐特徵在 0.10 下仍可見

> 判準由 `optimize-slice-performance` design D4 的實測支持（第 60 層：0.10 box-mean 可見像素占預覽面積 1.12%，高於原始層圖的 0.898%；`support_head_front_diameter = 0.4 mm` 在 14 µm 像素下涵蓋 2.9 個預覽像素）。**`0.10` 現為 15120 幅面機台的實際組態**，因此本場景已由「未來的驗收線」轉為對現行行為的約束。

- **WHEN** 以縮放比 `0.10` 降取樣一層含支撐的層圖（點亮像素約佔 0.9%）
- **THEN** 預覽中亮度大於 32 的像素占預覽總面積的比例 SHALL 不低於原始層圖的點亮比例
- **AND** 直徑 0.4 mm 的支撐頭在 14 µm 像素的幅面下 SHALL 至少涵蓋 2 個預覽像素

#### Scenario: 備援產線採用與引擎相同的濾波語意

- **WHEN** Python 備援產線以縮放比 `1/N` 產出預覽層圖
- **THEN** 其降取樣 SHALL 為均勻區塊平均
- **AND** MUST NOT 使用雙線性、雙三次或其他非均勻權重濾波

## ADDED Requirements

### Requirement: 預覽備援產線須在任何層檔編碼下產出非空封存

`GET /api/v2/slices/{job_id}/preview.zip` 在引擎產出的 `model_preview.zip` 缺席時 SHALL 由 Python 備援產線即時產生預覽封存。該產線 SHALL 支援 `.sl1` 內的**所有**層檔編碼形式，包含 PNG 與 RLE，並 SHALL 以既有的層檔列舉真值來源決定層檔清單，MUST NOT 自行以副檔名硬篩。

備援產線 MUST NOT 將空的預覽封存寫入快取位置。當來源 `.sl1` 含有層檔卻產出零筆預覽時，系統 SHALL 視為錯誤並回報，MUST NOT 留下一個會被後續請求永久重用的空檔。

#### Scenario: RLE 模式下備援產線產出完整預覽

- **WHEN** `.sl1` 以 RLE 編碼寫出層檔（`SLA_LAYER_RLE=1`），且 `model_preview.zip` 不存在
- **THEN** 備援產線產出的預覽封存 SHALL 包含與層數相同筆數的預覽影像
- **AND** MUST NOT 為空

#### Scenario: 空預覽不得被快取

- **WHEN** 備援產線因任何原因產出零筆預覽影像
- **THEN** 系統 MUST NOT 在快取位置留下該封存檔
- **AND** 後續請求 SHALL 重新嘗試產生，而非直接回傳空檔

### Requirement: 兩條預覽產線的已知差異須明文立約

引擎產線與 Python 備援產線的輸出經同一端點、同一檔名送出，但在 ZIP 內項目命名與影像編碼格式上**刻意不統一**。此差異 SHALL 記載為契約的一部分，而非缺陷。

| 項目 | 引擎產線 | 備援產線 |
| --- | --- | --- |
| ZIP 項目命名 | `model_preview00000.png` 起始的零填充序號（前綴取自預覽封存檔名的 stem） | `0.webp` 起始的序號 |
| 影像編碼 | PNG | WebP |

預覽封存的消費端 SHALL 以 ZIP 內實際的項目名稱與副檔名決定解碼方式，MUST NOT 假設固定的命名規則或編碼格式。

> **義務對象的歸屬**：上一段的 SHALL / MUST NOT **約束的是消費端（DS-Online 前端 repo），不是本 repo**。本能力無法驗證也無法強制前端的解碼流程；它在此立約，是為了讓「兩條產線刻意不統一」這個決定連同其對消費端的前提一起被記錄下來，避免日後被讀成「後端已保證消費端行為」。
>
> 本 repo 實際能保證、且已由測試釘住的，是上表**兩欄的產出側**：引擎產線的 `model_preview00000.png` / PNG 由實跑切片驗證，備援產線的 `0.webp` / WebP 由 `test_preview_service_fallback.py` 的命名與編碼斷言鎖定。任一側漂移都會使上表失真，因此兩側都不得靜默改動。
>
> 前端側的對應義務已於 change `remove-wasm-prz-fallback` 的連動回覆中知會 DS-Online。

#### Scenario: 消費端不得假設固定命名

- **WHEN** 消費端取得 `preview.zip`
- **THEN** 其解碼流程 SHALL 依 ZIP 內實際項目名稱與副檔名運作
- **AND** 對兩條產線的任一輸出 SHALL 皆能正確解碼

### Requirement: 縮放比調整須經最大幅面機台目視驗收

任何改變預覽縮放比落點的變更 SHALL 在**輸出實際發生改變的機台**上完成目視畫質驗收後，方可視為完成。驗收 MUST NOT 在輸出逐位元組未變的機台上執行——在該類機台上驗收必然通過，不具驗證力。

以本次量化機制而言，唯一輸出改變且有實機的規格為 15120 × 6230，因此目視驗收 SHALL 於該機台執行。

#### Scenario: 目視驗收於 15120 幅面機台執行

- **WHEN** 量化機制上線後進行畫質驗收
- **THEN** 驗收 SHALL 在 15120 × 6230 機台上，透過消費端的預覽對話框播放層預覽完成
- **AND** 驗收 MUST NOT 僅在長邊 ≤ 5760 的機台上執行

#### Scenario: 未改變輸出的機台不作為驗收依據

- **WHEN** 某機台在變更前後的預覽輸出逐位元組相同
- **THEN** 該機台的目視結果 MUST NOT 被採計為畫質驗收通過的依據
