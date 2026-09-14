## MODIFIED Requirements

### Requirement: print_time 計算 SHALL 重用 retract 4-case override

`_compute_print_time()` 內部 SHALL 透過 `_resolve_retract_pair()` 取得 retract 與 drop2 值。**SHALL NOT** 用未經 override 的 raw config 值。

#### Scenario: print_time 反映 Case 4 行為（速度 mm/min，需 ÷ 60）
- **WHEN** config 未傳 retract dist 與 drop2（Case 4）
- **AND** `Lifting Distance = 8.0`、`Lifting Second Distance = 0.0`、`Normal Retract Speed = 100 mm/min`（= 1.667 mm/s）
- **THEN** `_compute_print_time()` 中 retract 段時間 = `8.0 / (100/60) = 4.8` 秒（drop2 = 8.0 對應 second-stage 全段）
- **AND** PRZ header 寫入的 retract = 0.0、drop2 = 8.0
- **AND** 兩處（time 計算與 binary 寫入）使用相同的 4-case 結果

#### Scenario: print_time 反映 Case 2 行為（drop2 距離為 0 時不計入 motion_time）
- **WHEN** config 僅傳 `"Print.Retract Distance": 4.0`（Case 2，未傳 `"Print.Retract Second Distance"`）
- **AND** `Lifting Distance = 5.0`、`Lifting Speed = 60`、`Lifting Second Distance = 2.0`、`Lifting Second Speed = 120`、`Normal Retract Speed = 120`、`Normal Retract Second Speed = 60`（單位皆 mm/min）
- **THEN** `_resolve_retract_pair()` 依 Case 2 規則回傳 `(retract=4.0, drop2=0.0)`
- **AND** `_compute_print_time()` 中 drop2 段時間 SHALL 為 `motion_time(0.0, 60/60) = 0.0`（因 distance 為 0，非因 speed 為 0）
- **AND** drop2 段時間 SHALL NOT 沿用被廢棄的舊版 Case 2 公式（`max(0, lift+lift2-dist) = 3.0`）推得的非零秒數
- **AND** 單層總時間 = exposure(3.0) + lift(5/1=5.0) + lift2(2/2=1.0) + retract(4/2=2.0) + drop2(0.0) = `11.0` 秒
