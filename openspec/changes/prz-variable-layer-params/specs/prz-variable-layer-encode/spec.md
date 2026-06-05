## ADDED Requirements

### Requirement: 變動層厚任務以權威表查表照抄 Z（模型 Y）

對宣告多個高度區間（區間數 > 1）的任務，`prz_encoder` SHALL 自 `model.layers.json` 逐層取 `z_end_um`，以 `z_pos = z_end_um / 1000.0`（mm float）寫入 PRZ 的 `PausePositionZ` 與 `LayerPositionZ`。對此類任務，encoder MUST NOT 以 `layer_height * (layer_idx + 1)` 自行推算 Z。

#### Scenario: Z 來自權威表而非全域層厚
- **WHEN** 多區間任務，`model.layers.json` 第 250 層 `z_end_um == 10000`、第 251 層 `z_end_um == 10100`
- **THEN** PRZ 第 250 層 `z_pos` SHALL 為 `10.0`、第 251 層 SHALL 為 `10.1`
- **AND** encoder MUST NOT 使用 `layer_height * (idx + 1)` 計算這些 Z

### Requirement: 區間→參數比對採 z_end 錨點、µm 量化、半開區間

`prz_encoder` SHALL 為每層挑選曝光／光熄／抬升／回抽／PWM 等參數，判定其所屬高度區間時 SHALL：(a) 以該層 `z_end_um` 為錨點；(b) 將前端區間邊界以 `int(round(mm * 1000))` 量化為 µm 後比較；(c) 採半開區間 `[low_um, high_um)`，使每層恰好被一個區間認領。最末區間上界 SHALL 視為涵蓋模型頂層（`z_end` 等於模型頂仍歸屬末區間）。

此判定規則 SHALL 與 `variable-layer-slicing` 的選層厚規則逐字一致。

#### Scenario: Boundary Alignment — z_end 恰在邊界歸上方區間
- **WHEN** 區間 `A = [0, 10mm)`、`B = [10mm, 20mm)`，某層 `z_end_um == 10000`
- **THEN** 該層參數 SHALL 取自區間 `B`
- **AND** SHALL NOT 取自區間 `A`

#### Scenario: Boundary Alignment — 跨界層厚度與參數同屬一區間
- **WHEN** 某層在 slicer 端因 `z_end` 落入區間 `B` 而選用 `B` 的層厚
- **THEN** encoder 為該層挑參數時 SHALL 同樣判為區間 `B`（相同 `z_end` 錨點與規則）
- **AND** 該層 MUST NOT 出現「厚度屬 A、參數屬 B」的不一致

#### Scenario: Boundary Alignment — 浮點殘差量化後不抖動
- **WHEN** 某層 `z_end` 對應浮點高度為 `10.00000003mm`，權威表存為 `z_end_um == 10000`
- **THEN** encoder SHALL 以整數 `10000µm` 判區間，歸屬與精確 `10mm` 一致

### Requirement: 條件式 mandatory 讀取權威表

是否需要 `model.layers.json` SHALL 由 config 的高度區間數決定：

- 區間數 > 1（變動層厚）：權威表為**必要**。缺檔或校驗失敗 SHALL 使編碼**中止並拋例外**。
- 單一全域層厚：SHALL 沿用既有等高路徑（`z = layer_height * (idx + 1)`）；`model.layers.json` 不存在屬正常，MUST NOT 報錯。

#### Scenario: 多區間缺檔 → 硬中止
- **WHEN** config 宣告 2 個以上區間，但 `model.layers.json` 不存在
- **THEN** encoder SHALL 拋出 `LayerTableMissingError`
- **AND** MUST NOT 退回等高路徑輸出 PRZ

#### Scenario: 單一層厚無權威表屬正常
- **WHEN** config 僅單一全域層厚，且無 `model.layers.json`
- **THEN** encoder SHALL 以既有等高路徑成功輸出 PRZ
- **AND** MUST NOT 因缺檔報錯

### Requirement: 權威表以內容指紋＋層數雙重校驗

對變動層厚任務，encoder SHALL 在使用權威表前進行雙重校驗：(a) 以與 slicer 相同規則重算 `.sl1` 內容指紋，須等於 `source.fingerprint`；(b) `source.layer_count` 須等於 `.sl1` 內 PNG 張數。任一不符 SHALL 中止並拋對應例外。校驗 SHALL NOT 以 Task ID 或 per-job UUID 取代內容指紋。

#### Scenario: Verification Failure — 指紋不符（非同一切片產物）
- **WHEN** 手邊 `.sl1` 與 `model.layers.json.source.fingerprint` 不符（例如重切覆寫導致 `sl1_v1 + table_v2`）
- **THEN** encoder SHALL 拋出 `LayerTableFingerprintMismatch`
- **AND** MUST NOT 產生任何 PRZ 輸出

#### Scenario: Verification Failure — 層數不符
- **WHEN** `source.layer_count` 與 `.sl1` 內 PNG 張數不一致
- **THEN** encoder SHALL 拋出 `LayerTableLayerCountMismatch`

#### Scenario: Verification Failure — 區間缺口或重疊
- **WHEN** 前端區間非自 `0` 起、或相鄰區間 `high_um != next.low_um`（缺口或重疊）
- **THEN** encoder SHALL 拋出 `LayerRangeCoverageError`

### Requirement: 校驗失敗絕不降級輸出

對變動層厚任務，任何缺檔或校驗失敗 SHALL 一律中止；encoder MUST NOT 以等高模式或任何 fallback 產生 PRZ（避免靜默印出廢品）。

#### Scenario: Verification Failure — 不得以等高模式代償
- **WHEN** 變動層厚任務發生缺檔或任一校驗失敗
- **THEN** encoder SHALL 中止並回報錯誤
- **AND** SHALL NOT 輸出任何以 `layer_height * (idx + 1)` 等高推算的 PRZ