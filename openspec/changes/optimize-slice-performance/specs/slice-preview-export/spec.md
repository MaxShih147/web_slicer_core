## ADDED Requirements

### Requirement: 預覽層圖的縮放比須由消費端顯示需求決定

`--export-preview-pngs` 的縮放比 SHALL 依據預覽消費端的實際顯示尺寸決定，而非任意選定。切片時傳入的縮放比 SHALL 為 `0.10`。

依據：DS-Online 的預覽對話框寬度上限為 560 CSS px，扣除內距後 `<img>` 實際渲染約 520 CSS px，在 DPR 2 的螢幕上需要約 1040 device px。以 15120 px 幅面計，縮放比 `0.10` 產生 1512 px 寬，較所需的 1040 px 保有約 45% 餘裕，足以涵蓋高 DPI 螢幕與日後放大對話框。

#### Scenario: 16K 幅面的預覽尺寸
- **WHEN** 印表機幅面為 15120 × 6230、縮放比為 `0.10`
- **THEN** 每張預覽影像的尺寸 SHALL 為 1512 × 623
- **AND** 該寬度 SHALL 不小於消費端在 DPR 2 下所需的 1040 px

#### Scenario: 縮放比為 0 時不產生預覽
- **WHEN** `--export-preview-pngs` 的值為 `0` 或未提供該選項
- **THEN** 系統 MUST NOT 產生任何預覽影像
- **AND** MUST NOT 產生 `*_preview.zip`

### Requirement: 預覽降取樣採區塊平均，並提供整數倍快路徑

預覽降取樣 SHALL 採用區塊平均（box mean）：每個目標像素的值 SHALL 為其對應來源區塊內所有像素的算術平均。系統 MUST NOT 改用取最大值（max）或其他會使細特徵在視覺上變粗的濾波，以免使用者以預覽目視判斷壁厚時被誤導。

當縮放比為整數分之一（`1/N`，N 為正整數）時，系統 SHALL 走固定 `N × N` 區塊的快路徑，避免對每個目標像素重複計算來源區塊邊界與執行除法。快路徑的輸出 SHALL 與通用路徑**逐位元組相同**。

#### Scenario: 整數倍快路徑與通用路徑輸出一致
- **WHEN** 縮放比為 `0.10`（即 `1/10`），對同一張來源點陣圖分別以快路徑與通用路徑降取樣
- **THEN** 兩者產生的目標點陣圖 SHALL 逐位元組相同

#### Scenario: 非整數倍縮放比仍走通用路徑
- **WHEN** 縮放比為 `0.15`（非 `1/N`）
- **THEN** 系統 SHALL 走通用路徑
- **AND** 輸出 SHALL 與本變更前的通用路徑結果相同

#### Scenario: 細支撐特徵在 0.10 下仍可見
- **WHEN** 以縮放比 `0.10` 降取樣一層含支撐的層圖（點亮像素約佔 0.9%）
- **THEN** 預覽中亮度大於 32 的像素占預覽總面積的比例 SHALL 不低於原始層圖的點亮比例
- **AND** 直徑 0.4 mm 的支撐頭在 14 µm 像素的幅面下 SHALL 至少涵蓋 2 個預覽像素

### Requirement: 預覽 PNG 編碼須採用快速壓縮等級

預覽影像的 PNG 編碼 SHALL 使用低壓縮等級（等級 1），而非編碼器預設的等級 6。預覽層圖絕大部分為純黑，低等級已能取得接近的壓縮率，而編碼耗時顯著較低。

此設定 SHALL 只作用於預覽影像；`.sl1` 內層檔的編碼路徑 MUST NOT 受影響。

#### Scenario: 預覽採用等級 1 編碼
- **WHEN** 產生預覽影像的 PNG
- **THEN** 編碼 SHALL 以壓縮等級 `1` 執行

#### Scenario: 層檔編碼不受影響
- **WHEN** 預覽壓縮等級調整後執行一次完整切片
- **THEN** `.sl1` 內每一層層檔的 SHA-256 SHALL 與調整前完全一致

### Requirement: 預覽產出失敗不得使切片失敗

預覽為輔助產物。當預覽影像編碼或 `*_preview.zip` 寫檔失敗時，系統 SHALL 記錄錯誤並讓切片以成功狀態結束，MUST NOT 讓一趟已完成的切片作廢。

`.sl1` 的產出、`status.json` 的終態與 PRZ 下載能力 SHALL 完全不依賴預覽是否成功。

#### Scenario: 預覽寫檔失敗時切片仍成功
- **WHEN** `.sl1` 已成功寫出，但 `*_preview.zip` 寫檔失敗
- **THEN** 切片程序 SHALL 以成功的結束碼結束
- **AND** `status.json` 的 `status` SHALL 為 `completed`
- **AND** 系統 SHALL 記錄一筆含失敗原因的錯誤訊息

#### Scenario: 預覽缺席時 PRZ 下載仍可用
- **WHEN** job 完成切片但 `model_preview.zip` 不存在
- **THEN** `POST /api/v2/slices/{id}/download.prz` SHALL 正常產生並回傳 PRZ