## ADDED Requirements

### Requirement: 後端接收並校驗多高度區間參數組合

`POST /api/v2/slices`（及其 config 萃取流程）SHALL 接受一組可選的「高度區間參數組合」陣列，每個區間含 `low_mm`、`high_mm` 與該區間適用的層厚與列印參數。後端 SHALL 對該陣列執行契約校驗：依 `low_mm` 升冪、自 `0` 起、相鄰連續（前一區間 `high_mm` 等於下一區間 `low_mm`）、無重疊、無缺口。校驗以 µm 量化（`int(round(mm * 1000))`）後比較。

當提供的區間數 > 1 時，該 job SHALL 標記為變動層厚流程（下游 slicer 變動層厚切片 + 權威表 mandatory）。未提供區間或僅單一全域層厚時，SHALL 維持既有等高流程，且 API MUST NOT 因新欄位對舊請求回傳 422。

#### Scenario: 合法多區間通過校驗
- **WHEN** 收到區間 `[{low:0, high:10, ...}, {low:10, high:20, ...}]`
- **THEN** 校驗 SHALL 通過
- **AND** 該 job SHALL 標記為變動層厚流程

#### Scenario: Verification Failure — 區間有缺口
- **WHEN** 收到區間 `[{low:0, high:10}, {low:12, high:20}]`（`10 != 12`，缺口）
- **THEN** API SHALL 回傳 `422`（validation error）
- **AND** 錯誤訊息 SHALL 指出缺口位置

#### Scenario: Verification Failure — 區間重疊
- **WHEN** 收到區間 `[{low:0, high:12}, {low:10, high:20}]`（重疊）
- **THEN** API SHALL 回傳 `422`（validation error）

#### Scenario: Verification Failure — 未自 0 起
- **WHEN** 第一個區間 `low_mm != 0`
- **THEN** API SHALL 回傳 `422`（validation error）

#### Scenario: 邊界以 µm 量化比較
- **WHEN** 相鄰區間 `high_mm = 10.0000001`、下一區間 `low_mm = 10.0`
- **THEN** 兩者量化後皆為 `10000µm`，SHALL 視為連續、通過校驗

#### Scenario: 舊請求相容
- **WHEN** 請求未提供任何高度區間欄位
- **THEN** API MUST NOT 回傳 422
- **AND** 該 job SHALL 走既有等高流程