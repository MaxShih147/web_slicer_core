## ADDED Requirements

### Requirement: 統一 .sl1 層檔列舉為單一真值來源

系統 SHALL 提供單一 helper `sl1_layer_names(names)` 作為 .sl1 內層檔列舉的唯一真值來源，供層數統計、單層取用與 PRZ 編碼共用，杜絕各處以裸 `endswith` 各自判斷而分歧。該 helper SHALL 以嚴格正則 `^model\d{5}\.(rle|png)$` 匹配層檔名，並在同一 .sl1 內 `.rle` 存在時**優先採用 `.rle`**（否則採用 `.png`），回傳結果 SHALL 以檔名 `sorted()` 排序（零填充 5 位下字典序等於層索引序）。

#### Scenario: 純 RLE 層檔 — 正確列舉並排序
- **GIVEN** 一個 .sl1 內含 `model00000.rle` … `model00199.rle` 與設定檔 `config.ini` / `prusaslicer.ini` / `config.json`
- **WHEN** 呼叫 `sl1_layer_names(zf.namelist())`
- **THEN** 回傳 SHALL 為 200 個 `.rle` 層檔名，且 SHALL 以層索引升冪排序
- **AND** 設定檔（`.ini` / `.json`）SHALL NOT 被納入

#### Scenario: 純 PNG 層檔 — 退回 .png 列舉
- **GIVEN** 一個 .sl1 內僅含 `model#####.png` 層檔（切片器未啟用 `SLA_LAYER_RLE`）
- **WHEN** 呼叫 `sl1_layer_names(zf.namelist())`
- **THEN** 回傳 SHALL 為所有 `model#####.png` 層檔名，並依序排序

#### Scenario: RLE 與 PNG 並存 — .rle 優先
- **GIVEN** 一個 .sl1 同時含 `.rle` 與 `.png` 層檔
- **WHEN** 呼叫 `sl1_layer_names(zf.namelist())`
- **THEN** 回傳 SHALL 僅含 `.rle` 層檔名（`.rle` 優先），SHALL NOT 混入 `.png`

#### Scenario: 縮圖不污染層數統計
- **GIVEN** 一個 .sl1 內含層檔 `model#####.png` 以及子目錄縮圖 `thumbnail/thumbnail400x400.png`
- **WHEN** 呼叫 `sl1_layer_names(zf.namelist())`
- **THEN** `thumbnail/thumbnail400x400.png` SHALL 被排除（不符 `^model\d{5}\.(rle|png)$`）
- **AND** 回傳層數 SHALL NOT 因縮圖而超計

---

### Requirement: 層數統計以實際層檔為準（不論編碼格式）

`parse_sl1_metadata()` 回傳的層數 SHALL 以 `sl1_layer_names()` 計算，使 `.rle`（PRZ 快路徑）與 `.png`（傳統路徑）兩種輸出皆得到正確層數；SHALL NOT 因切片器改以 RLE 輸出而回傳 `0`。`printTime` / `usedMaterial` 等其他 metadata 的解析行為 SHALL 維持不變（`printTime` 仍作為列印時間同步的 fallback 值）。

#### Scenario: RLE 模式層數不再為 0
- **GIVEN** 一個切片成功、內含 `N` 個 `model#####.rle` 層檔的 .sl1
- **WHEN** `parse_sl1_metadata()` 解析該檔
- **THEN** 回傳層數 SHALL 等於 `N`
- **AND** SHALL NOT 為 `0`

#### Scenario: metadata 解析不受影響
- **GIVEN** .sl1 內 `config.ini` 含 `printTime` 與 `usedMaterial`
- **WHEN** `parse_sl1_metadata()` 解析該檔
- **THEN** `printTime` 與 `usedMaterial` 的回傳值 SHALL 與改動前一致

---

### Requirement: 單層取用支援 RLE 即時解碼，失敗回 None

`get_layer_png_from_sl1(job_id, layer_idx)` SHALL 以 `sl1_layer_names()` 定位層檔；當選中的層檔為 `.rle` 時，SHALL 即時解碼為 PNG bytes 回傳（複用既有 `prz_decoder._rle_decode_layer()` 解碼路徑，SHALL NOT 另寫一份解碼）。抽出的單層解碼 helper SHALL 回傳 `Optional[bytes]`：當 .sl1 缺少 `prusaslicer.ini` 或無法解析 `display_pixels_x` / `display_pixels_y` 時 SHALL 回傳 `None`，由上層端點轉為 HTTP 404，維持既有 API 契約。整包 `layers.zip` 轉檔路徑（`_rle_sl1_to_png_zip`）於解析失敗時 SHALL 維持既有 raise 行為（服務語意不同：整包壞一顆即整包無效）。

#### Scenario: RLE 單層即時解碼為 PNG
- **GIVEN** 一個 RLE 模式的 .sl1 且 `prusaslicer.ini` 含有效 `display_pixels_x` / `display_pixels_y`
- **WHEN** 呼叫 `get_layer_png_from_sl1(job_id, idx)`，`idx` 在層數範圍內
- **THEN** 回傳 SHALL 為該層解碼後的 PNG bytes（可被影像庫開啟）

#### Scenario: 解析度資訊缺失 → 回 None（上層 404）
- **GIVEN** 一個 RLE 模式的 .sl1 缺少 `prusaslicer.ini` 或其 `display_pixels` 無法解析
- **WHEN** 呼叫 `get_layer_png_from_sl1(job_id, idx)`
- **THEN** 抽出的單層解碼 helper SHALL 回傳 `None`
- **AND** 上層端點 SHALL 回應 HTTP 404，SHALL NOT 拋出未處理例外

#### Scenario: 索引超出範圍 → 回 None
- **GIVEN** 一個層數為 `N` 的 .sl1
- **WHEN** 呼叫 `get_layer_png_from_sl1(job_id, idx)` 且 `idx < 0` 或 `idx >= N`
- **THEN** 回傳 SHALL 為 `None`

---

### Requirement: PRZ 編碼端共用同一列舉且輸出位元不變

PRZ 編碼路徑（`encode_prz_streaming` 與 `encode_prz`）SHALL 改用同一 `sl1_layer_names()` 列舉層檔，消除與層數統計端的邏輯分歧。在正常 .sl1（層檔皆為 `model#####.{rle,png}`、設定檔為 `.ini`/`.json`）上，`sl1_layer_names()` 選出的層檔集合 SHALL 與改動前的 `endswith` 邏輯完全相同，使 PRZ 二進位輸出 SHALL 保持 byte-identical。

#### Scenario: PRZ 輸出位元不變（回歸保證）
- **GIVEN** 一個切片成功的 .sl1 與其持久化 `prz_config`
- **WHEN** 分別以改動前後的程式碼對同一輸入編碼 PRZ
- **THEN** 兩者產生的 PRZ 二進位 SHALL 完全相同（byte-identical）

#### Scenario: 層數統計與 PRZ 編碼採同一層檔集合
- **GIVEN** 同一個 .sl1
- **WHEN** `parse_sl1_metadata()` 與 PRZ 編碼路徑各自取得層檔
- **THEN** 兩者取得的層檔數量與順序 SHALL 完全一致（同源於 `sl1_layer_names()`）