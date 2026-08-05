## Context

`fix-boolean-non-manifold-tolerance`（歸檔於 `2026-08-05-fix-boolean-non-manifold-tolerance`）為 `boolean_operation()` 引入完整的修補序列，並在其 Non-Goals 明確排除「前端錯誤碼傳遞」。修補序列執行後，仍有兩個確定性的失敗出口——retry 後 mesh_a/mesh_b 仍無效——以及兩個防禦性核查出口，這四個出口代表「輸入網格的幾何問題無法透過現有修補序列修復」，是前端可賦予使用者可行動提示的明確情況。

本設計在不觸碰修補演算法的前提下，最小化地擴充 `boolean_operation()` 的回傳介面，讓這四個出口攜帶可辨識的 error code 傳遞至 API 層。

## Goals / Non-Goals

**Goals:**

- 為「幾何問題無法修復」的四個失敗出口設定 `error_code="BOOLEAN_INVALID_MESH"`，且不解析 error message 字串。
- 在 `OperationResult` 新增 `error_code` 欄位，使 error code 可從 `boolean_operation()` 傳遞至 API endpoint。
- 在 `errors.py` 依既有 factory 慣例新增 `boolean_invalid_mesh()`，message 對使用者穩定可理解。
- API endpoint 依 `error_code` 分派，確保 `BOOLEAN_INVALID_MESH` 與其他失敗的回應 code 可被前端區分。

**Non-Goals:**

- 修改 mesh repair 演算法、修補序列的執行條件或順序。
- 新增 `BOOLEAN_RESULT_EMPTY`、`BOOLEAN_MESH_LOAD_FAILED`、`BOOLEAN_EXPORT_FAILED` 等其他 boolean 失敗分類（留待後續需求）。
- 修改前端顯示邏輯或語系檔。
- 設計全站統一錯誤架構。
- 修改成功 response schema。

## Decisions

### D1：`boolean_operation()` 回傳型別擴充為 3-tuple

**決定**：回傳型別由 `tuple[bool, Optional[str]]` 改為 `tuple[bool, Optional[str], Optional[str]]`，第三元素為 `error_code`。

**採用此方式的理由**：
- 避免在呼叫端以字串比對（string parsing）判斷錯誤類型，符合「不要用解析 error message 字串的方式判斷」的要求。
- 型別標注即自我說明，新增 error code 時只需在對應 return 語句加值，不影響其他出口。

**設 `BOOLEAN_INVALID_MESH` 的四個出口**（另 7 個出口設 `None`）：
1. retry 後 `_is_valid_manifold(man_a)` 仍 False（`sla_operations.py:2062`）
2. retry 後 `_is_valid_manifold(man_b)` 仍 False（`sla_operations.py:2068`）
3. defensive pre-check `man_a` 無效（`sla_operations.py:2074`）
4. defensive pre-check `man_b` 無效（`sla_operations.py:2076`）

**設 `None` 的七個出口**（維持既有 `BOOLEAN_FAILED` 行為）：
- trimesh 未安裝（ImportError）
- 退化面清理後 mesh_a/mesh_b 無 faces
- 未知 operation enum
- 布林運算結果為空 mesh
- STL 寫出失敗（包含於 generic exception handler）
- 未預期例外（outer except）

### D2：`OperationResult` 新增 `error_code: Optional[str] = None`

**決定**：在 `sla_operations.py` 的 `OperationResult` dataclass 新增欄位；不修改 `to_dict()` 避免改動 API 回應 schema。

**理由**：`OperationResult` 是 `boolean_operation()` → API endpoint 的傳遞媒介；欄位加在 dataclass 層讓所有操作型別均可擴充，但本次僅 boolean 路徑使用。

### D3：`boolean_invalid_mesh()` factory

**決定**：沿用 `agent/errors.py` 中 geometry 失敗家族（`boolean_failed`、`invalid_model`、`hollow_generation_failed`）的慣例：HTTP 422、`retryable=False`。

**message 設計**：
```
"The model mesh contains geometry errors and could not be processed."
```
- 不包含 `mesh_a`、`mesh_b`、Manifold status、修補步驟等內部細節
- 穩定（不隨修補序列調整而改變）
- 一般使用者可理解，可作為前端 toast/dialog 的 fallback 文字

### D4：Endpoint dispatch 以 `error_code` 欄位分派

**決定**：`_boolean_operation_impl()` 中，`result.error_code == "BOOLEAN_INVALID_MESH"` 時 raise `boolean_invalid_mesh()`，其他情況維持 `boolean_failed(result.error)`。

**理由**：
- 用 `error_code` 欄位而非字串比對，耦合點明確（`==` 比對一個字串常數）。
- 其他失敗路徑（空結果、未預期例外）的 `error` message 仍有除錯價值，保留在 `BOOLEAN_FAILED.message` 中。
- `boolean_failed()` 傳入 `result.error`（內部除錯訊息）；`boolean_invalid_mesh()` 傳入固定使用者訊息，兩者分開呼叫點各自清晰。

## Risks / Trade-offs

- **3-tuple 擴充破壞既有呼叫者假設**：`boolean_operation()` 只有一個呼叫者（`perform_boolean()` 內的 `run_in_executor`），已同步更新為 3-tuple 解包，風險為零。若未來新增呼叫者須留意型別標注。
- **error_code 字串為裸常數**：`"BOOLEAN_INVALID_MESH"` 在 `sla_operations.py` 為裸字串，與 `errors.py` 中的 code 字串僅靠慣例保持一致，無型別繫結。若日後 code 改名需同步修改兩處。可在後續提取為具名常數，但本次以最小化修改為優先。
