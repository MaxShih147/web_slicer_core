## 1. 共用 helper：_p_base_decide()

- [x] 1.1 在 `agent/model_classifier.py` 新增私有函式 `_p_base_decide(sig: _ClassificationSignals) -> DentalModelType`：封裝 P_base 分支的 dental_model / u_shaped_dental_model 分流邏輯（`u_shaped_model_score > dental_model_score` 嚴格大於判斷），回傳 `DentalModelType.U_SHAPED_DENTAL_MODEL` 或 `DentalModelType.DENTAL_MODEL`
- [x] 1.2 將 `_decide_model_type_with_details()` 中 P_base 與 P5.2A 的分流判斷重構為呼叫 `_p_base_decide(sig)`，確保行為與重構前完全相同（確認現有測試全數通過）

## 2. confirm_dental_model_type() 函式

- [x] 2.1 在 `agent/model_classifier.py` 新增公開函式 `confirm_dental_model_type(mesh: trimesh.Trimesh, target: DentalModelType) -> bool`
- [x] 2.2 實作 P0 early return：`features.axis_l1_mm is None` 時直接回傳 `target == DentalModelType.OTHER`，不執行後續運算
- [x] 2.3 實作 P_base early return：skip reason 為「單側大平面且符合基座尺寸」時，若 target 為 `dental_model` 或 `u_shaped_dental_model` 則呼叫共用 `_p_base_decide(sig)` 並比較；其餘 target 直接回傳 false
- [x] 2.4 實作 P2 early return：skip reason 為「明確牙冠尺寸」或「小尺寸交界且比例偏向牙冠」時，回傳 `target == DentalModelType.CROWN`
- [x] 2.5 實作 P3 early return：skip reason 為「大型開放邊界」時，回傳 `target == DentalModelType.INTRAORAL_SCAN`
- [x] 2.6 實作 needs_drill=True 時的分流：
  - target 為 `dental_model`、`u_shaped_dental_model`、`intraoral_scan`、`other` → 直接回傳 false，不執行導孔偵測（代碼分析確認這四種類型無法出現在 P5；`other` 僅由 P0 產生）
  - target 為 `crown`、`bridge`、`splint`、`surgical_guide` → 執行步驟 2.7
- [x] 2.7 實作 P5 fallback（沿用已計算的 features）：
  - 呼叫 `detect_drill_holes(mesh)` 並填入 `features.drill_*` 欄位（`drill_detection_ran=True`、`drill_detection_skip_reason=None`）
  - 呼叫 `_decide_model_type_with_details(features)` 取得 `final_type`
  - 回傳 `final_type == target`
  - **不呼叫** `classify_dental_model(mesh)`（避免重複特徵提取）

## 3. API 端點

- [x] 3.1 在 `agent/api_v2.py` 新增 `POST /api/v2/confirm-model-type` 路由，接受 `multipart/form-data`（`file` 欄位 + `target_type` 字串欄位）
- [x] 3.2 實作 `target_type` 驗證：欄位缺失 → `MISSING_BODY` 400；值不在 `DentalModelType` 枚舉 → `VALIDATION_ERROR` 400
- [x] 3.3 複用既有 STL 輸入驗證邏輯（無檔案 → `MISSING_BODY` 400；非 `.stl` → `VALIDATION_ERROR` 400；空白檔案 → `MISSING_BODY` 400；STL 解析失敗或空 mesh → `INVALID_MODEL` 422；未預期例外 → `INTERNAL_ERROR` 500）
- [x] 3.4 以 `asyncio.to_thread()` 執行 `confirm_dental_model_type()`，避免阻塞事件循環
- [x] 3.5 成功時回傳 `V2Response(success=True, data={"confirmed": confirmed})`，其中 `confirmed` 為 bool
- [x] 3.6 確認回應 body 不包含 `model_type` 或任何揭露實際類型的欄位

## 4. 一致性驗證

- [x] 4.1 補充測試：對同一個 STL，先取得 `classify_dental_model()` 的結果，再對全部八種 DentalModelType 分別呼叫 `confirm_dental_model_type()`；驗證恰好有一個 target 回傳 true，且等於完整分類結果，其餘七個 target 全部回傳 false（無例外排除）
- [x] 4.2 確認此測試涵蓋 early-return 路徑（P0 / P_base / P2 / P3）與 P5 路徑（含導孔偵測）各至少一個測試案例
- [x] 4.3 確認現有 `classify_dental_model()` 測試全數通過，確認重構 `_p_base_decide()` 未改變行為
