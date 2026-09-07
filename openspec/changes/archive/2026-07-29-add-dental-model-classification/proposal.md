## Why

牙科 3D 列印工作流程依模型種類各有不同處理需求：基座模型需自動定向、手術導板需識別導孔方向、牙冠與牙橋體積小需不同支撐策略、口腔內掃描通常不需列印。目前前端無法自動得知上傳模型的種類，導致使用者需手動選擇正確的處理模式，有誤操作風險。

提供後端自動分類能力，可作為前端後續自動選擇 auto-orient 模式、切片參數及工作流程的依據，降低使用者操作門檻。

## What Changes

- 新增 `agent/model_classifier.py`：實作幾何啟發式牙科模型分類器，包含四類特徵提取、19 個 soft-score 信號計算、條件式導孔偵測及分類決策。
- 在 `agent/api_v2.py` 新增 `POST /api/v2/classify-model` 端點：接受 STL 上傳，回傳 `data.model_type` 字串。

## Capabilities

### New Capabilities

- `dental-model-classification`：從 STL mesh 提取幾何特徵，以啟發式規則判斷牙科模型種類，回傳八種類型之一（`dental_model`、`u_shaped_dental_model`、`crown`、`bridge`、`splint`、`surgical_guide`、`intraoral_scan`、`other`）。

### Modified Capabilities

（無現有 spec 需修改）

## Impact

- **新增檔案**：`agent/model_classifier.py`
- **修改檔案**：`agent/api_v2.py`（新增 `POST /api/v2/classify-model` 端點）
- **相依**：`trimesh`、`numpy`、`scipy`（現有依賴）
- **與現有程式碼關係**：導孔偵測演算法與 `agent/auto_orient_surg_guide.py` 中的手術導板 auto-orient 導孔邏輯來自同一 C++ 原始碼（`auto_orient_surg_guide.cpp`），移植為獨立的 Python 實作，不共用程式碼。
