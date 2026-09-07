## Why

`POST /api/v2/boolean` 在輸入 mesh 修補後仍無法轉換為有效 Manifold 時，前一個變更（`fix-boolean-non-manifold-tolerance`）使其以 `"mesh_a/b repair failed: still invalid after repair"` 回傳，但 API 端點對所有 boolean 失敗一律回傳 `BOOLEAN_FAILED`。前端無法區分「幾何問題無法修復」與「運算結果為空」或「未預期例外」等不同性質的失敗，無法對使用者提供可行動的提示（例如「請重新匯出或調整模型」與「請確認兩物件有重疊區域」是截然不同的建議）。

本變更為 `fix-boolean-non-manifold-tolerance` 的後續，在不修改任何修補演算法的前提下，為「幾何問題無法修復」的特定失敗路徑增加可辨識的 error code，讓前端可依 code 給使用者對應訊息。

## What Changes

- **`boolean_operation()` 回傳型別擴充**：從 `(bool, Optional[str])` 改為 `(bool, Optional[str], Optional[str])`，第三元素為 `error_code`。成功路徑回傳 `(True, None, None)`；11 個失敗出口中，4 個設 `error_code="BOOLEAN_INVALID_MESH"`，其餘設 `None`。
- **`OperationResult` 新增 `error_code` 欄位**：`Optional[str]`，預設 `None`；由 `perform_boolean()` 從 3-tuple 解包後傳入。
- **新增 `boolean_invalid_mesh()` error factory**：沿用 geometry 失敗家族的 HTTP 422 / `retryable=False` 慣例；message 為穩定的一般使用者訊息，不包含 mesh label、Manifold status 或修補步驟等內部細節。
- **端點 dispatch 依 `error_code` 分派**：`result.error_code == "BOOLEAN_INVALID_MESH"` 時 raise `boolean_invalid_mesh()`，其他失敗維持既有 `boolean_failed(result.error)` 行為；不解析 error message 字串。

## Capabilities

### New Capabilities

無。

### Modified Capabilities

- `boolean-non-manifold-tolerance`：`boolean_operation()` 的回傳型別由 `(bool, Optional[str])` 更新為 `(bool, Optional[str], Optional[str])`。「修補後仍無效」（retry 後 mesh_a/mesh_b 仍 invalid）與「防禦性核查失敗」四個出口現在回傳 `error_code="BOOLEAN_INVALID_MESH"` 作為第三元素；其餘失敗出口與成功出口的第三元素為 `None`。

## Impact

- **後端程式**：
  - [agent/sla_operations.py](../../../agent/sla_operations.py) — `boolean_operation()` 回傳型別與 11 個 return 語句；`OperationResult` dataclass 新增 `error_code` 欄位；`perform_boolean()` 解包 3-tuple 並傳入 `error_code`。
  - [agent/errors.py](../../../agent/errors.py) — 新增 `boolean_invalid_mesh()` factory。
  - [agent/api_v2.py](../../../agent/api_v2.py) — 新增 `boolean_invalid_mesh` import；`_boolean_operation_impl()` 加入 `error_code` dispatch。
- **API 契約（對前端）**：成功 response 不變；失敗時新增 `code="BOOLEAN_INVALID_MESH"` 路徑（HTTP 422，為新增 code，不移除 `BOOLEAN_FAILED`）。前端無需立即更新，但可依新 code 顯示更具體的錯誤訊息。
- **不在範圍**：前端顯示與語系檔；mesh repair 演算法、條件與順序；其他 boolean 失敗分類（空結果、載入失敗、匯出失敗）。
