## 1. `boolean_operation()` 回傳型別擴充

- [x] 1.1 將 `boolean_operation()` 的 return 型別標注由 `tuple[bool, Optional[str]]` 改為 `tuple[bool, Optional[str], Optional[str]]`（[sla_operations.py:827](../../../agent/sla_operations.py#L827)）。
  - **驗證**：`python -m py_compile agent/sla_operations.py` 通過。✅
- [x] 1.2 更新 11 個 return 語句為 3-tuple：4 個 BOOLEAN_INVALID_MESH 出口（retry 後 mesh_a/b 仍無效 × 2、defensive pre-check × 2）設 `"BOOLEAN_INVALID_MESH"`；其餘 7 個（ImportError、無 faces × 2、unknown op、空結果、success、generic exception）設 `None`。
  - **驗證**：`grep "BOOLEAN_INVALID_MESH" agent/sla_operations.py` 命中 4 行，均為正確出口。✅

## 2. `OperationResult` 新增 `error_code` 欄位

- [x] 2.1 在 `OperationResult` dataclass 新增 `error_code: Optional[str] = None`（[sla_operations.py:126](../../../agent/sla_operations.py#L126)）。
  - **驗證**：`python -m py_compile agent/sla_operations.py` 通過。✅
- [x] 2.2 更新 `perform_boolean()` 的 executor 解包由 `success, error = ...` 改為 `success, error, error_code = ...`，並在失敗路徑的 `OperationResult(...)` 中傳入 `error_code=error_code`（[sla_operations.py:2417](../../../agent/sla_operations.py#L2417)）。
  - **驗證**：`python -m py_compile agent/sla_operations.py` 通過。✅

## 3. `boolean_invalid_mesh()` factory

- [x] 3.1 於 `agent/errors.py` 的 `boolean_failed()` 定義之後新增 `boolean_invalid_mesh()`：`code="BOOLEAN_INVALID_MESH"`、HTTP 422、`retryable=False`、message 為穩定使用者訊息（[errors.py:111](../../../agent/errors.py#L111)）。
  - **驗證**：`python -m py_compile agent/errors.py` 通過。✅

## 4. API endpoint dispatch

- [x] 4.1 在 `agent/api_v2.py` 的 errors import 中新增 `boolean_invalid_mesh`（[api_v2.py:28](../../../agent/api_v2.py#L28)）。
  - **驗證**：`python -m py_compile agent/api_v2.py` 通過。✅
- [x] 4.2 在 `_boolean_operation_impl()` 的失敗 dispatch 區塊加入 `error_code` 分派：`result.error_code == "BOOLEAN_INVALID_MESH"` → `raise boolean_invalid_mesh()`，其他 → 既有 `raise boolean_failed(result.error)`（[api_v2.py:931](../../../agent/api_v2.py#L931)）。
  - **驗證**：`python -m py_compile agent/api_v2.py` 通過。✅

## 5. 驗證

- [x] 5.1 全語法檢查：`python -m py_compile agent/sla_operations.py agent/errors.py agent/api_v2.py` 無錯誤。✅
- [x] 5.2 dispatch 邏輯單元驗證（inline mock）：
  - `error_code="BOOLEAN_INVALID_MESH"` → `APIError.code == "BOOLEAN_INVALID_MESH"`、status 422、retryable False、message 不含 `mesh_a`/`repair`/`Manifold`。✅
  - `error_code=None` → `APIError.code == "BOOLEAN_FAILED"`、status 422。✅
- [x] 5.3 確認所有 `boolean_operation()` return 出口均為 3-tuple（無遺漏的 2-tuple return），且唯一 call site（`perform_boolean()`）以 3-tuple 解包。✅
- [x] 5.4 執行 `openspec validate boolean-non-manifold-tolerance` 通過。✅
