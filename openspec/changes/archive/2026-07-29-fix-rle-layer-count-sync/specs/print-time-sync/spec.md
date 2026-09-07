## MODIFIED Requirements

### Requirement: Web API 列印時間以 PRZ 物理公式為單一真值來源

切片完成後，`status.json["estimated_print_time"]`（Web API `estimatedPrintTime` 的資料來源）SHALL 等於 `_compute_print_time(prz_config, total_layers, timing)` 的回傳值，其中 `prz_config` 為持久化的前端 config、`total_layers` 為 `parse_sl1_metadata()` 取得的**實際層數（不論切片器輸出為 `.rle` 或 `.png`，皆由 `sl1_layer_names()` 統計，SHALL NOT 因 RLE 輸出而恆為 0）**、`timing` 為 `_extract_prz_timing_config(prz_config)` 的萃取結果。此值 SHALL 與 PRZ 下載端使用**同一公式與同一份 config**，確保 Web API 顯示值與 PRZ binary 內列印時間一致。`estimated_print_time` SHALL NOT 直接沿用 fork SL1 估值作為正常情況下的回傳值。`status.json` 保存 float 原值；與 PRZ binary（其 `print_time` 額外經 `int()` 截斷）之間允許 `0 ≤ 差 < 1` 秒的落差，SHALL NOT 因此差額被視為不一致。

#### Scenario: 正常同步 — API 數值等於公式計算值
- **GIVEN** 一個切片成功的 job，其 `jobs/{id}/prz_config.json` 存在且含有效 timing / lift / retract 參數
- **AND** `parse_sl1_metadata()` 回傳層數 `N`
- **WHEN** `run_slicing()` 完成並寫入 `status.json`
- **THEN** `status.json["estimated_print_time"]` SHALL 等於 `_compute_print_time(prz_config, N, _extract_prz_timing_config(prz_config))` 的回傳值
- **AND** 該值 SHALL NOT 等於 `parse_sl1_metadata()` 解出的 fork SL1 估值（兩者公式不同）

#### Scenario: RLE 模式下同步正確啟動（回歸保證）
- **GIVEN** 一個切片成功的 job，其 .sl1 以 `SLA_LAYER_RLE` 輸出 `N` 個 `model#####.rle` 層檔（`N > 0`）
- **AND** `jobs/{id}/prz_config.json` 存在且有效
- **WHEN** `run_slicing()` 完成時間同步
- **THEN** `parse_sl1_metadata()` 回傳的 `total_layers` SHALL 等於 `N`（SHALL NOT 為 0）
- **AND** `status.json["estimated_print_time"]` SHALL 等於 `_compute_print_time(prz_config, N, timing)`，而非退回 fork 估值

#### Scenario: 與 PRZ binary 列印時間同源一致
- **GIVEN** 同一個 job 的 `prz_config.json` 與層數 `N`
- **WHEN** 透過 PRZ 下載端產生 PRZ binary
- **THEN** PRZ binary 的 `print_time` 欄位 SHALL 由相同的 `_compute_print_time(prz_config, N, timing)` 推導（PRZ binary 端額外的 `int()` 截斷除外）
- **AND** Web API 回傳的時間與 PRZ 列印時間 SHALL 來自單一真值來源，不再各自獨立計算
- **AND** 兩者差額 SHALL 僅來自 `int()` 截斷，即 `0 ≤ |API 值 − PRZ 值| < 1` 秒