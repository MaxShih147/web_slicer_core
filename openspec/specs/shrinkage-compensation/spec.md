## Purpose

Shrinkage compensation allows the slicer to automatically scale printed objects along X/Y/Z axes to counteract material shrinkage during SLA curing. Parameters are declared in `PrintObjectConfig` and applied in `sla_trafo()`.

## Requirements

### Requirement: 收縮補償參數宣告於 PrintObjectConfig

`prusaslicer_fork` 的 `PrintObjectConfig` macro 中 SHALL 宣告 4 個收縮補償參數：`shrinkage_compensation`（bool）、`shrinkage_compensation_x`（float，%）、`shrinkage_compensation_y`（float，%）、`shrinkage_compensation_z`（float，%），預設值皆為 `false` / `100.0`。宣告處 SHALL 附上說明性注解，指出參數置於 `PrintObjectConfig` 以避免修改 SLA state-invalidation switch。

#### Scenario: config.ini 包含收縮補償設定時正確讀取
- **WHEN** `config.ini` 含有 `shrinkage_compensation = 1` 與 `shrinkage_compensation_x = 98`
- **THEN** `SLAPrint::apply()` 的 manual cache 必須讀取到這兩個值，且 `m_shrinkage_compensation = true`、`m_shrinkage_compensation_x = 98.0`

#### Scenario: config.ini 缺少收縮補償 key 時採用安全預設值
- **WHEN** `config.ini` 中不存在任何 `shrinkage_compensation*` key
- **THEN** C++ manual cache 必須保持初始值 `false` / `100.0`，切片行為與未套用任何補償相同

### Requirement: Shrinkage 縮放作用於 sla_trafo()

當 `shrinkage_compensation = true` 時，`sla_trafo()` SHALL 在 `relative_correction()` 的基礎上，對 X/Y/Z 各軸乘以 `shrinkage_compensation_{x,y,z} / 100.0`。除以 `100.0` 的換算 SHALL 只在 C++ 端執行一次，Python 層不得做任何數值轉換。

#### Scenario: 啟用收縮補償並指定 X 軸放大 2%
- **WHEN** `shrinkage_compensation = 1` 且 `shrinkage_compensation_x = 102.0`，其餘軸為 `100.0`
- **THEN** `sla_trafo()` 計算的 trafo 在 X 軸方向乘以 `1.02`，Y/Z 方向乘以 `1.0`

#### Scenario: 收縮補償關閉時不改變 trafo
- **WHEN** `shrinkage_compensation = 0`
- **THEN** `sla_trafo()` 不套用任何額外縮放，輸出 trafo 與未加此功能前相同

### Requirement: Shrinkage 參數變更時正確 invalidate 切片步驟

當 `SLAPrint::apply()` 偵測到任何 shrinkage 參數與 cache 值不同時，SHALL 執行：`invalidate_step(slapsMergeSlicesAndEval)` + 所有 object 的 `invalidate_all_steps()` + `set_trafo()`。

#### Scenario: shrinkage_compensation_x 由 100 改為 98
- **WHEN** 上次 apply 時 `m_shrinkage_compensation_x = 100.0`，本次 config 為 `98.0`
- **THEN** 所有 SLA object 的切片步驟被 invalidate，且 trafo 被重設

### Requirement: Shrinkage 補償觸發時輸出日誌

當 `sla_trafo()` 套用收縮補償縮放時，SHALL 以 `BOOST_LOG_TRIVIAL(info)` 輸出格式為 `[shrinkage] applying x=<val> y=<val> z=<val>` 的日誌。此日誌 SHALL 永久保留（不依賴 debug flag）。

#### Scenario: 收縮補償啟用並切片時日誌可見
- **WHEN** 執行 `prusa-slicer --export-sla --load test_shrinkage.ini <model.stl>`，config 中 `shrinkage_compensation = 1`
- **THEN** 程序的 log output 含有 `[shrinkage] applying` 字串，且 exit code 為 `0`

### Requirement: Python SLAConfig 包含收縮補償欄位

`agent/models.py` 的 `SLAConfig` SHALL 包含以下欄位及預設值：`shrinkage_compensation: bool = False`、`shrinkage_compensation_x: float = 100.0`、`shrinkage_compensation_y: float = 100.0`、`shrinkage_compensation_z: float = 100.0`。

#### Scenario: 未傳入收縮補償參數時使用預設值
- **WHEN** 建立 `SLAConfig()` 時不傳入任何 shrinkage 相關欄位
- **THEN** `shrinkage_compensation` 為 `False`，`shrinkage_compensation_x/y/z` 皆為 `100.0`

### Requirement: DS-Online 收縮補償 key 正確 mapping 至 SLAConfig

`agent/api_v2.py` 的 `_convert_v2_config_to_sla()` SHALL 支援以下 key mapping（`print_config` 段）：`"Shrinkage Compensation"` → `shrinkage_compensation`、`"Shrinkage Compensation X"` → `shrinkage_compensation_x`、`"Shrinkage Compensation Y"` → `shrinkage_compensation_y`、`"Shrinkage Compensation Z"` → `shrinkage_compensation_z`。

#### Scenario: DS-Online 傳入 Shrinkage Compensation X = 98
- **WHEN** API request 含有 `{"Shrinkage Compensation": true, "Shrinkage Compensation X": 98}`
- **THEN** 生成的 `config.ini` 包含 `shrinkage_compensation = 1` 與 `shrinkage_compensation_x = 98.0`，且數值未被乘除任何係數
