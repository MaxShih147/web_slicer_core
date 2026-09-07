## ADDED Requirements

### Requirement: 公差補償參數宣告於 PrintObjectConfig

`prusaslicer_fork` 的 `PrintObjectConfig` macro 中 SHALL 宣告 7 個公差補償參數：`tolerance_compensation`（bool）、`tolerance_compensation_a`（float，mm）、`tolerance_compensation_b`（float，mm）、`bottom_tolerance_compensation`（bool）、`bottom_tolerance_compensation_a`（float，mm）、`bottom_tolerance_compensation_b`（float，mm）、`bottom_layer_count`（int，預設 6）。`tolerance_compensation_a/b` 與 `bottom_tolerance_compensation_a/b` 的 `def->min` 限制 SHALL 被移除，以允許負值輸入。

#### Scenario: config.ini 包含公差補償設定時正確讀取
- **WHEN** `config.ini` 含有 `tolerance_compensation = 1` 與 `tolerance_compensation_b = 0.1`
- **THEN** `SLAPrint::apply()` 的 manual cache 必須讀取到 `m_tolerance_compensation = true`、`m_tolerance_compensation_b = 0.1`

#### Scenario: config.ini 缺少公差補償 key 時採用安全預設值
- **WHEN** `config.ini` 中不存在任何 `tolerance_compensation*` key
- **THEN** C++ manual cache 必須初始化為 `tc = false, btc = false`（與 PhrozenOrca 的 `true` 預設不同），切片行為與無補償狀態相同

### Requirement: 公差補償符號語意合約（Raw Offset）

公差參數的符號語意 SHALL 定義如下：`a > 0` 表示實體向孔洞方向擴張（孔縮小）；`b > 0` 表示實體向外擴張（外輪廓變大）。此語意 SHALL 由 C++ 實作直接體現，Python 層與 DS-Online 傳入的數值 SHALL 原封不動寫入 config.ini，不得進行任何正負號翻轉。

#### Scenario: 正 b 值使外輪廓向外擴張
- **WHEN** `tolerance_compensation = 1`、`tolerance_compensation_b = 0.1`（mm）
- **THEN** 每層切片的外輪廓向外偏移 0.1mm，使外徑增大

#### Scenario: 正 a 值使孔洞縮小
- **WHEN** `tolerance_compensation = 1`、`tolerance_compensation_a = 0.05`（mm）
- **THEN** 每層切片的孔洞向內縮小 0.05mm，使孔徑減小

### Requirement: Tolerance 輪廓偏移演算法作用於 apply_printer_corrections()

當 `tolerance_compensation = true` 時，`apply_printer_corrections()` SHALL 對非底層的每個 `ExPolygon` 執行以下操作（在 absolute_correction 之後、elephant_foot 之前）：外輪廓以 `cb` 偏移；每個孔洞先 reverse（CW→CCW），再以 `-ca` 偏移；最後以 `diff_ex(new_contour, hole_solids)` 合併結果。底層（`layer_index < bottom_layer_count`）SHALL 使用 `bottom_tolerance_compensation_a/b` 並在 `bottom_tolerance_compensation = true` 時執行相同邏輯。

#### Scenario: 一般層套用外輪廓偏移
- **WHEN** `tolerance_compensation = true`、`tolerance_compensation_b = 0.2`、`bottom_layer_count = 6`，處理第 10 層
- **THEN** 第 10 層的每個 ExPolygon 外輪廓向外偏移 0.2mm

#### Scenario: 底層套用獨立的底層公差補償
- **WHEN** `bottom_tolerance_compensation = true`、`bottom_tolerance_compensation_b = 0.15`、`bottom_layer_count = 6`，處理第 3 層
- **THEN** 第 3 層使用 `bottom_tolerance_compensation_b = 0.15` 執行偏移，而非一般層的 `tolerance_compensation_b`

#### Scenario: ca 與 cb 皆為 0 時跳過計算
- **WHEN** `tolerance_compensation = true`、`tolerance_compensation_a = 0.0`、`tolerance_compensation_b = 0.0`
- **THEN** `apply_tc_layer` lambda 提前返回，不執行任何 offset 計算

### Requirement: Tolerance 參數變更時正確 invalidate 切片步驟

當 `SLAPrint::apply()` 偵測到任何 tolerance 參數與 cache 值不同時，SHALL 執行：`invalidate_step(slapsMergeSlicesAndEval)` + 所有 object 的 `invalidate_step(slaposObjectSlice)`。

#### Scenario: tolerance_compensation_b 值改變時觸發重切片
- **WHEN** 上次 apply 時 `m_tolerance_compensation_b = 0.0`，本次 config 為 `0.1`
- **THEN** 所有 SLA object 的 `slaposObjectSlice` 步驟被 invalidate

### Requirement: Tolerance 補償觸發時輸出日誌

當 `apply_printer_corrections()` 進入公差補償分支時，SHALL 以 `BOOST_LOG_TRIVIAL(info)` 輸出日誌。一般層格式：`[tolerance] applying tc a=<val> b=<val> layers=<n>..<m>`；底層格式：`[tolerance] applying btc a=<val> b=<val> layers=0..<n>`。此日誌 SHALL 永久保留（不依賴 debug flag）。

#### Scenario: 公差補償啟用並切片時日誌可見
- **WHEN** 執行 `prusa-slicer --export-sla --load test_tolerance.ini <model.stl>`，config 中 `tolerance_compensation = 1`、`tolerance_compensation_b = 0.1`
- **THEN** 程序的 log output 含有 `[tolerance] applying tc` 字串，且 exit code 為 `0`

### Requirement: Python SLAConfig 包含公差補償欄位

`agent/models.py` 的 `SLAConfig` SHALL 包含以下欄位及預設值：`tolerance_compensation: bool = False`、`tolerance_compensation_a: float = 0.0`、`tolerance_compensation_b: float = 0.0`、`bottom_tolerance_compensation: bool = False`、`bottom_tolerance_compensation_a: float = 0.0`、`bottom_tolerance_compensation_b: float = 0.0`、`bottom_layer_count: int = 6`。

#### Scenario: 未傳入公差補償參數時使用預設值
- **WHEN** 建立 `SLAConfig()` 時不傳入任何 tolerance 相關欄位
- **THEN** 所有 `tolerance_compensation*` 及 `bottom_tolerance_compensation*` bool 欄位為 `False`，float 欄位為 `0.0`，`bottom_layer_count` 為 `6`

### Requirement: DS-Online 公差補償 key 正確 mapping 至 SLAConfig

`agent/api_v2.py` 的 `_convert_v2_config_to_sla()` SHALL 支援以下 key mapping（`print_config` 段）：`"Tolerance Compensation"` → `tolerance_compensation`、`"Tolerance Compensation A"` → `tolerance_compensation_a`、`"Tolerance Compensation B"` → `tolerance_compensation_b`、`"Bottom Tolerance Compensation"` → `bottom_tolerance_compensation`、`"Bottom Tolerance Compensation A"` → `bottom_tolerance_compensation_a`、`"Bottom Tolerance Compensation B"` → `bottom_tolerance_compensation_b`、`"Bottom Layer Count"` → `bottom_layer_count`。`"Bottom Layer Count"` 的 mapping 為新增行為（一魚兩吃），`prz_encoder.py` 的既有消費不受影響。

#### Scenario: DS-Online 傳入公差補償設定時正確寫入 config.ini
- **WHEN** API request 含有 `{"Tolerance Compensation": true, "Tolerance Compensation B": 0.1, "Bottom Layer Count": 4}`
- **THEN** 生成的 `config.ini` 包含 `tolerance_compensation = 1`、`tolerance_compensation_b = 0.1`、`bottom_layer_count = 4`

#### Scenario: Bottom Layer Count 不影響 PRZ 底層曝光邏輯
- **WHEN** API request 含有 `{"Bottom Layer Count": 4}`
- **THEN** `prz_encoder.py` 仍正常讀取 `"Print.Bottom Layer Count"` 寫入 `.prz`，行為與加入此功能前完全相同
