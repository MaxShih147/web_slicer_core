## MODIFIED Requirements

### Requirement: `boolean_operation()` 回傳型別

`boolean_operation()` 的回傳型別 SHALL 由 `tuple[bool, Optional[str]]` 更新為 `tuple[bool, Optional[str], Optional[str]]`，格式為 `(success, error_message, error_code)`。

#### Scenario: 成功時回傳三元素 tuple
- **WHEN** 布林運算完成並成功匯出結果 STL
- **THEN** `boolean_operation()` SHALL 回傳 `(True, None, None)`

#### Scenario: 幾何問題無法修復時回傳 BOOLEAN_INVALID_MESH
- **WHEN** 修補序列後 mesh 仍無效，或防禦性核查發現無效 Manifold
- **THEN** 回傳的第三元素 `error_code` SHALL 為 `"BOOLEAN_INVALID_MESH"`

#### Scenario: 其他失敗路徑的 error_code 為 None
- **WHEN** 失敗原因為 trimesh 未安裝、退化面清理後無 faces、未知 operation、布林結果為空或未預期例外
- **THEN** 回傳的第三元素 `error_code` SHALL 為 `None`

### Requirement: 修補後必須驗證 Manifold 有效性再進行布林運算

本 Requirement 的敘述不變；以下 Scenarios 更新其回傳格式，加入 `error_code` 第三元素。

#### Scenario: mesh_a 修補後仍無效時提前失敗（更新）
- **WHEN** 修補序列完成後 `_is_valid_manifold(man_a)` 為 False
- **THEN** 系統 SHALL 回傳 `(False, "mesh_a repair failed: still invalid after repair", "BOOLEAN_INVALID_MESH")`

#### Scenario: mesh_b 修補後仍無效時提前失敗（更新）
- **WHEN** 修補序列完成後 `_is_valid_manifold(man_b)` 為 False
- **THEN** 系統 SHALL 回傳 `(False, "mesh_b repair failed: still invalid after repair", "BOOLEAN_INVALID_MESH")`

#### Scenario: 布林運算前的防禦性核查（更新）
- **WHEN** 任何路徑的 Manifold 在進入布林運算前被偵測為無效
- **THEN** 系統 SHALL 提前回傳失敗，MUST NOT 執行布林運算
- **AND** 回傳的 `error_code` SHALL 為 `"BOOLEAN_INVALID_MESH"`

#### Scenario: `error_code` 為 None 的其他失敗出口不受影響
- **WHEN** 失敗原因為以下任一：trimesh 未安裝、退化面清理後無 faces、未知 operation、布林結果為空、未預期例外
- **THEN** 回傳的第三元素 `error_code` SHALL 為 `None`
- **AND** 這些路徑不觸發 `BOOLEAN_INVALID_MESH`，由上層繼續走 `BOOLEAN_FAILED`
