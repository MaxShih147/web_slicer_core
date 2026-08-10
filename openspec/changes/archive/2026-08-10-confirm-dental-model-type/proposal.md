## Why

現有完整分類 API 執行全部幾何特徵提取與條件式導孔偵測後，回傳一個 `model_type` 字串。然而前端在部分工作流程中只需要知道「此模型是否為某特定類型」，例如「是否為 crown」，不需要知道若非 crown 時模型實際屬於哪一類。

完整分類流程最主要的效能瓶頸是導孔偵測演算法（移植自 C++ `auto_orient_surg_guide.cpp`）。對於 crown、dental model、u_shaped_dental_model、intraoral scan 等能在導孔偵測之前即可確認結果的類型，新的確認 API 可提前回傳布林值，跳過不必要的導孔相關運算。

## What Changes

- 在 `agent/model_classifier.py` 新增 `confirm_dental_model_type(mesh, target) -> bool` 函式：沿用現有分類決策樹，在能確定目標類型成立或不成立時提前回傳，否則執行完整分類並與 target 比較。
- 在 `agent/api_v2.py` 新增 `POST /api/v2/confirm-model-type` 端點：接受 STL 上傳及 `target_type` 字串欄位，回傳 `data.confirmed` 布林值。

## Capabilities

### New Capabilities

- `dental-model-type-confirm`：給定 STL 模型與目標類型，回傳該模型是否屬於目標類型（bool）。對能在導孔偵測前即可確認的類型（crown、dental_model、u_shaped_dental_model、intraoral_scan）提供 early return，避免執行完整導孔偵測流程。

### Modified Capabilities

- `dental-model-classification`：新增 `confirm_dental_model_type()` 作為 `classify_dental_model()` 的補充。`classify_dental_model()` 的介面與行為完全不變。

## Impact

- **修改檔案**：`agent/model_classifier.py`（新增 `confirm_dental_model_type()`）
- **修改檔案**：`agent/api_v2.py`（新增 `POST /api/v2/confirm-model-type` 端點）
- **不影響**：現有 `POST /api/v2/classify-model` 端點與 `classify_dental_model()` 函式的介面及行為完全不變
- **相依**：`trimesh`、`numpy`、`scipy`（現有依賴，無新增）
