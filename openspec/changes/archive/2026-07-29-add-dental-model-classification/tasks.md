## 1. 幾何特徵提取

- [x] 1.1 實作 `convex_hull_area_weighted_pca_detail()`：以凸包三角面面積加權 PCA，計算三個主軸長度（L1/L2/L3）及對應的 PCA 軸向量
- [x] 1.2 實作 `open_boundary_stats()`：統計 open edge 數量、邊界 loop 數量（含迴路偵測）、最大 loop 周長、全體開放邊長度總和
- [x] 1.3 實作 `large_outer_flat_plane_stats()`：以法向量與偏移量量化找出最大外側平面，計算面積比例、單側性（`flat_plane_one_side`）及對側面積比
- [x] 1.4 實作 `projection_shape_gap_stats()`：將 mesh 沿 PCA 最小軸投影至平面，以柵格化計算缺口面積、最大缺口中心偏移、與凸包邊界的接觸長度，及中型/大型投影孔洞數量
- [x] 1.5 實作 `extract_model_features()`：依序呼叫上述四個函式，填入 `ModelFeatures` dataclass（含衍生比例欄位 `elongation_ratio`、`flatness_ratio`、`relative_thickness`、`largest_open_ratio`、`total_open_ratio`）

## 2. Soft-score 信號計算

- [x] 2.1 定義 `_ClassificationSignals` dataclass（19 個信號欄位）
- [x] 2.2 實作分段線性 soft threshold 輔助函式：`_soft_less_than()`、`_soft_greater_than()`、`_soft_between()`、`_soft_max_with_falloff()`、`_soft_range_with_falloff()`
- [x] 2.3 實作 `_crown_bridge_length_scores()` 與 `_crown_bridge_ratio_scores()`：分別以 L1 長度與 L1/L2 比例輸出牙冠/牙橋雙分數
- [x] 2.4 實作 `_compute_signals()`：依 `ModelFeatures` 計算全部 19 個信號，PCA 失效時各相關信號回傳 0.0

## 3. 條件式導孔偵測規劃

- [x] 3.1 實作 `_is_one_sided_base_candidate()`：判斷基座模型尺寸與單側大平面是否同時達到門檻
- [x] 3.2 實作 `_get_drill_detection_plan()`：依優先順序（基座 → 明確牙冠 → 大型開放邊界）決定是否跳過導孔偵測，回傳 `(needs_drill, skip_reason)`

## 4. 導孔偵測演算法

- [x] 4.1 移植 C++ `auto_orient_surg_guide.cpp` 導孔偵測邏輯為 Python `detect_drill_holes()`
- [x] 4.2 實作頂點合併（1e-4mm 網格）、邊界鄰接圖成長、PCA 長寬比過濾（最大 1.5）
- [x] 4.3 實作掃描線孔洞偵測（空白 ≥ 2.4mm、實心 ≥ 0.6mm）
- [x] 4.4 實作連接邊鏈累積轉角偵測（≥ 220°）及 bbox 過濾（3–35mm）
- [x] 4.5 回傳 `{"valid": bool, "found": bool, "candidate_count": int}`；環形直徑有效範圍 5.5–14.0mm

## 5. 分類決策

- [x] 5.1 實作 `_decide_model_type_with_details()`：依 P0 → P_base → P2 → P3 → P5 優先順序輸出 `ClassificationDecision`（含 `model_type`、`confidence`、`primary_reasons`）
- [x] 5.2 實作 P5 分支（導孔已執行）的所有子分支：5.1 找到導孔、5.2A–E 無孔分流、5.3 導孔失敗 fallback
- [x] 5.3 實作 `decide_model_type()`：公開介面包裝，僅回傳 `DentalModelType`，不暴露 confidence/reasons
- [x] 5.4 定義校準常數區塊（`CANDIDATE_GROUP_MIN`、`STRONG_SIGNAL_MIN`、`LOW_FEATURE_MAX` 等），並標注為初版待校準值

## 6. 公開進入點

- [x] 6.1 實作 `classify_dental_model(mesh: trimesh.Trimesh) -> DentalModelType`：協調特徵提取 → 信號計算 → 導孔規劃 → 條件式導孔偵測 → 分類決策，僅回傳 `DentalModelType`

## 7. API 端點

- [x] 7.1 在 `agent/api_v2.py` 新增 `POST /api/v2/classify-model` 路由，接受 `multipart/form-data`（`file` 欄位），副檔名限制 `.stl`
- [x] 7.2 以 `asyncio.to_thread()` 執行 `classify_dental_model()`，避免阻塞事件循環
- [x] 7.3 加入輸入驗證：無檔案 → `MISSING_BODY` 400；非 `.stl` → `VALIDATION_ERROR` 400；空白檔案 → `MISSING_BODY` 400；STL 解析失敗或空 mesh → `INVALID_MODEL` 422；未預期例外 → `INTERNAL_ERROR` 500
- [x] 7.4 成功時回傳 `V2Response(success=True, data={"model_type": model_type.value})`
